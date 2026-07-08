"""fetch_binance — build the canonical volume-bearing spot snapshot for the R&D framework.

Pulls **spot BTCUSDT 1-minute klines** from Binance and writes ONE deterministic parquet with
REAL volume + trade count + taker flow — the fresh data contract for all new research
(fam_liquidity / fam_flow need this; the zerovol legacy file cannot serve them).

Source: `data.binance.vision` monthly dumps (≈100 files for 2017-08 → now; no rate limits, no
API keys), plus daily dumps for the current partial month. Falls back to nothing missing — a
gap raises rather than silently truncating.

Gotchas handled: (a) Binance switched the dump timestamp unit from ms → **microseconds** in
2025 — detected per-file by magnitude; (b) newer CSVs carry a header row — detected; (c) the
canonical parquet is sorted by open_time and de-duplicated so its content digest is stable.

Columns (canonical): index `ts` (UTC, bar OPEN) · open high low close · **volume** (base) ·
**quote_volume** · **trades** (tick-count proxy) · **taker_buy_base** · **taker_buy_quote**.

Bridge scope (pandas/pyarrow). Usage:
  python -m registry.tools.fetch_binance --symbol BTCUSDT --interval 1m \
         --start 2017-08 --out /workspace/snapshots/binance_btcusdt_1m/canonical.parquet
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://data.binance.vision/data/spot"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
CANON_COLS = ["open", "high", "low", "close", "volume", "quote_volume",
              "trades", "taker_buy_base", "taker_buy_quote"]


def _months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m = 1; y += 1


def _download(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except Exception:
        return None


def _parse_zip(raw: bytes):
    """Parse ONE monthly/daily dump into a normalized frame with a UTC `ts` column.

    The timestamp unit is detected PER FILE — Binance switched ms → microseconds in early 2025,
    so a global detection corrupts the mixed-era concat (year-58485 bug). Each month is internally
    consistent, so we normalize here, before concat."""
    import pandas as pd
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = zf.namelist()[0]
    with zf.open(name) as f:
        head = f.read(64)
    has_header = head[:9].lower().startswith(b"open_time") or head[:5].lower().startswith(b"open,")
    df = pd.read_csv(io.BytesIO(zf.read(name)),
                     header=0 if has_header else None,
                     names=None if has_header else KLINE_COLS)
    if has_header:
        df.columns = [c.strip().lower() for c in df.columns]
    ot = df["open_time"].astype("int64")
    unit = "us" if int(ot.iloc[0]) > 1_000_000_000_000_000 else "ms"   # per-file
    out = df[["open", "high", "low", "close", "volume", "quote_volume",
              "trades", "taker_buy_base", "taker_buy_quote"]].copy()
    out.insert(0, "ts", pd.to_datetime(ot, unit=unit, utc=True))
    return out


def fetch(symbol: str, interval: str, start: str, out: Path, verbose: bool = True):
    import pandas as pd

    now = datetime.now(timezone.utc)
    end_month = f"{now.year:04d}-{now.month - 1 if now.month > 1 else 12:02d}" \
        if now.day <= 2 else f"{now.year:04d}-{now.month:02d}"
    frames = []
    missing = []
    for mon in _months(start, end_month):
        url = f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{mon}.zip"
        raw = _download(url)
        if raw is None:
            # month not published as a monthly dump yet → try daily dumps for that month
            got_days = _fetch_daily_month(symbol, interval, mon)
            if got_days is None:
                missing.append(mon); continue
            frames.append(got_days)
        else:
            frames.append(_parse_zip(raw))
        if verbose:
            sys.stdout.write(f"\r  fetched {mon}  ({len(frames)} chunks)"); sys.stdout.flush()
    if verbose:
        print()
    if missing:
        raise RuntimeError(f"missing months (no monthly OR daily dump): {missing} — refusing to "
                           "register a snapshot with silent gaps")

    # frames are ALREADY normalized (each carries a UTC `ts` from its own per-file unit)
    out_df = pd.concat(frames, ignore_index=True)
    out_df = (out_df.drop_duplicates(subset="ts")
                    .sort_values("ts")
                    .reset_index(drop=True))
    for c in ("open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_base", "taker_buy_quote"):
        out_df[c] = out_df[c].astype("float64")
    out_df["trades"] = out_df["trades"].astype("int64")

    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_parquet(out, index=False)
    if verbose:
        print(f"  rows={len(out_df):,}  range={out_df['ts'].iloc[0]} → {out_df['ts'].iloc[-1]}  "
              f"→ {out}")
    return out_df


def _fetch_daily_month(symbol: str, interval: str, mon: str):
    """Assemble a partial/recent month from DAILY dumps (published sooner than monthly)."""
    import calendar
    import pandas as pd
    y, m = map(int, mon.split("-"))
    days = calendar.monthrange(y, m)[1]
    parts = []
    for d in range(1, days + 1):
        day = f"{y:04d}-{m:02d}-{d:02d}"
        raw = _download(f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{day}.zip")
        if raw is not None:
            parts.append(_parse_zip(raw))
    return pd.concat(parts, ignore_index=True) if parts else None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1m")
    p.add_argument("--start", default="2017-08")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    fetch(a.symbol, a.interval, a.start, a.out)


if __name__ == "__main__":
    main()
