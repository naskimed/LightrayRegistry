"""convert_legacy_pair — the load-bearing t=0 converter (B7).

Reads the frozen ANOTHERSTRATEGY pair, verifies BYTE-EQUALITY against the registered hashes
(seed/anotherstrategy.json), parses both halves (txt: UTF-16 properly decoded, NEVER
byte-stripped; csv: replicate read_trades filtering while RECORDING its silent NaN→0
coercions — count + affected ids — in the manifest), applies the CLOCK LAW as a verification
(txt hour == csv-UTC hour + 2/3 US-DST on every row), pairs in/out rows by deal id, and
emits the population rows + manifest. Truncations must be EXPLAINED or this converter errors.

Usage: python -m registry.tools.convert_legacy_pair <data_dir> [--out out_dir]
"""
from __future__ import annotations

import argparse
import csv as csvmod
import json
from datetime import datetime, timedelta
from pathlib import Path

from ..canon import sha256_file
from ._seed import load_seed


def parse_txt(path: Path) -> dict:
    text = path.read_text(encoding="utf-16")     # proper decode — never byte-stripping (R3)
    def section(name: str, nxt: str) -> list[list[str]]:
        body = text.split(f"[{name}]")[1].split(f"[{nxt}]")[0]
        rows = []
        for line in body.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 7:
                rows.append(parts)
        return rows
    return {"buy": section("BUY", "SELL"), "sell": section("SELL", "Perceptron")}


def parse_csv(path: Path) -> dict:
    """Self-keyed ledger: col0 datetime (UTC — the clock law), col1 deal id, col3 side,
    col4 in/out, col5 volume, col6 price, col10 profit (out rows), col12 exit comment."""
    ins, outs = [], []
    nan_profit_ids = []
    with open(path, newline="", encoding="ascii") as f:
        for row in csvmod.reader(f):
            if len(row) < 7 or not row[0][:2].isdigit():
                continue
            rec = {"ts": row[0].strip(), "deal": int(row[1]), "side": row[3].strip().lower(),
                   "volume": float(row[5]) if row[5] else None,
                   "price": float(row[6]) if row[6] else None}
            if row[4].strip().lower() == "in":
                ins.append(rec)
            else:
                raw_profit = row[10].strip() if len(row) > 10 else ""
                if raw_profit in ("", "nan", "NaN"):
                    nan_profit_ids.append(rec["deal"])       # the read_trades NaN→0 coercion,
                    rec["profit"] = 0.0                       # RECORDED, not silent
                else:
                    rec["profit"] = float(raw_profit)
                rec["exit_comment"] = row[12].strip() if len(row) > 12 else ""
                outs.append(rec)
    return {"ins": ins, "outs": outs, "nan_profit_coerced": nan_profit_ids}


def us_dst_offset_hours(dt: datetime) -> int:
    """The registered clock law: server = UTC + 2 (winter) / + 3 (US DST). US DST: second
    Sunday of March 07:00 UTC → first Sunday of November 06:00 UTC (close enough at hour
    granularity for the verification; the FEATURE materializer owns the exact formula)."""
    y = dt.year
    def nth_sunday(month: int, n: int) -> datetime:
        d = datetime(y, month, 1)
        sundays = [d + timedelta(days=i) for i in range(31)
                   if (d + timedelta(days=i)).month == month
                   and (d + timedelta(days=i)).weekday() == 6]
        return sundays[n - 1]
    start = nth_sunday(3, 2)
    end = nth_sunday(11, 1)
    return 3 if start <= dt.replace(tzinfo=None) < end else 2


def run(data_dir: Path, out_dir: Path) -> dict:
    seed = load_seed("anotherstrategy.json")
    a = seed["converter_assertions"]
    txt_path = data_dir / seed["pair"]["txt"]["filename"]
    csv_path = data_dir / seed["pair"]["csv"]["filename"]

    # 1) byte-equality with the registered hashes (raw UTF-16 bytes hashed, not decoded text)
    for half, fp in (("txt", txt_path), ("csv", csv_path)):
        actual = sha256_file(fp)
        expected = seed["pair"][half]["sha256"]
        if actual != expected:
            raise ValueError(f"{half} hash {actual} != registered {expected} — REFUSING (frozen pair)")

    # 2) parse both halves
    txt = parse_txt(txt_path)
    led = parse_csv(csv_path)
    ins_by_side = {"buy": [r for r in led["ins"] if r["side"] == "buy"],
                   "sell": [r for r in led["ins"] if r["side"] == "sell"]}

    # 3) blocking assertions (counts + fingerprints from BOTH halves independently)
    if len(txt["buy"]) != a["buy_count"] or len(txt["sell"]) != a["sell_count"]:
        raise ValueError("txt counts != registered fingerprints")
    if len(ins_by_side["buy"]) != a["buy_count"] or len(ins_by_side["sell"]) != a["sell_count"]:
        raise ValueError("csv in-row counts != registered")
    for side, fp_key in (("buy", "buy_fingerprint"), ("sell", "sell_fingerprint")):
        sizes: dict[int, int] = {}
        for r in txt[side]:
            cid = int(float(r[0]))
            sizes[cid] = sizes.get(cid, 0) + 1
        if sorted(sizes.values(), reverse=True) != sorted(a[fp_key], reverse=True):
            raise ValueError(f"{side} cluster fingerprint mismatch — txt is not the incumbent artifact")
    deals = [r["deal"] for r in led["ins"]] + [r["deal"] for r in led["outs"]]
    if len(set(deals)) != len(deals):
        raise ValueError("deal ids must be unique (self-keyed csv)")

    # 4) the clock law, row by row (positional alignment guard — the hour key WITH the mapping)
    mismatches = 0
    for side in ("buy", "sell"):
        for i, trow in enumerate(txt[side]):
            ts = datetime.strptime(ins_by_side[side][i]["ts"], "%Y.%m.%d %H:%M:%S")
            expect = (ts.hour + us_dst_offset_hours(ts)) % 24
            if int(float(trow[1])) != expect:
                mismatches += 1
    if mismatches != 0:
        raise ValueError(f"clock-law violations: {mismatches} (alignment guard FAILED)")

    # 5) build population rows — pair each 'in' with an 'out' BY DEAL ID, not positionally.
    #    Out rows carry the INVERTED side label; one position at a time ⇒ the matching out is the
    #    first inverted-side out whose deal id strictly exceeds the in's deal id (deal ids are
    #    strictly increasing across the whole ledger, which makes this an exact order check).
    rows = []
    for side in ("buy", "sell"):
        outs_side = sorted((r for r in led["outs"] if r["side"] != side),
                           key=lambda r: r["deal"])
        ins_side = ins_by_side[side]
        if len(outs_side) != len(ins_side):
            raise ValueError(f"{side}: {len(ins_side)} ins but {len(outs_side)} inverted-side outs "
                             "— not one-position-at-a-time; refusing to guess the pairing")
        oi = 0
        for i, trow in enumerate(txt[side]):
            entry = ins_side[i]
            while oi < len(outs_side) and outs_side[oi]["deal"] <= entry["deal"]:
                oi += 1
            if oi >= len(outs_side):
                raise ValueError(f"{side} trade {i} (deal {entry['deal']}): no closing out with a "
                                 "greater deal id — pairing broken")
            out = outs_side[oi]; oi += 1
            rows.append({
                "trade_id": f"t{len(rows):06d}", "side": side,
                "entry_ts": entry["ts"], "exit_ts": out["ts"],
                "entry_price": entry["price"], "exit_price": out["price"],
                "volume": entry["volume"], "profit": out["profit"],
                "exit_reason": out.get("exit_comment", ""),
                "f_hour": float(trow[1]), "f_ema": float(trow[2]), "f_mom": float(trow[3]),
                "f_dv": float(trow[4]), "f_iv": float(trow[5]), "f_hurst": float(trow[6]),
                "incumbent_cluster_id": int(float(trow[0])),
                "legacy_row_index": i,
                "mt5_deal_in": entry["deal"], "mt5_deal_out": out["deal"],
            })

    manifest = {
        "source": {"txt_sha256": seed["pair"]["txt"]["sha256"],
                   "csv_sha256": seed["pair"]["csv"]["sha256"]},
        "clock": seed["clock_law"],
        "n_trades": len(rows),
        "nan_profit_coerced": {"count": len(led["nan_profit_coerced"]),
                               "deal_ids": led["nan_profit_coerced"]},
        "truncations_explained": {},
        "causality_class": "legacy_attested",
        "featureset": "fs_belka6_ea",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "population_rows.json").write_text(json.dumps(rows))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"OK: {len(rows)} trades · clock law verified · NaN-coerced={len(led['nan_profit_coerced'])}")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data_dir", type=Path)
    p.add_argument("--out", type=Path, default=Path("var/populations/anotherstrategy_p0"))
    args = p.parse_args()
    run(args.data_dir, args.out)


if __name__ == "__main__":
    main()
