"""descriptor_emit — deterministic, target-blind descriptor-card payloads (descriptor_v1).

DECOUPLING DECISION (user, 2026-07-08): the descriptor emitter is decoupled from TS-MIX
adoption — the compressor contract is satisfied by ANY partition, and the incumbent's own
cluster labels (P0, `incumbent_cluster_id`) are the first partition source. The mixture, if
ever adopted, becomes merely a second partition source through this same emitter.

FROZEN FIELD LIST (user sign-off, 2026-07-08 — "identical to what" decided before code):
per (side, component), per feature: n, median, iqr (p75-p25), p05, p95, bowley_skew
((q3+q1-2*q2)/(q3-q1), 0.0 when iqr==0). Nothing else. TARGET-BLIND AT SCHEMA LEVEL:
only `f_*` columns are readable by construction (allowlist); profit/volume/prices are
unrepresentable in the payload (REG-INV-29 pattern).

DETERMINISM: pure-python stats (no numpy/pandas float-path drift), sorted iteration
everywhere, linear-interpolation quantiles, round(., 9), canonical-JSON bytes for both the
file and the card_id (card_<sha12> over the payload). Re-emit on the same input is
byte-identical — enforced by --selftest and intended as the M-series acceptance fixture.

USAGE (on the machine holding the converted pair):
  python -m registry.tools.descriptor_emit --pop-dir var/populations/anotherstrategy_p0 \
      --out var/cards_pending [--drafts inbox/staging]

  --pop-dir: the convert_legacy_pair output dir (population_rows.json + manifest.json)
  --drafts:  ALSO write card.emit EventDrafts. card.emit is scheduler-mechanical
             (REG-INV-25): in production the daemon emits these on ingest; the drafts
             written here carry actor "scheduler" and are for the daemon/human seed path
             to append — this tool itself never touches the ledger.
  --selftest: synthetic input, two emits, assert byte-equality, exit 0/1.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..canon import canonical_bytes, sha256_canon

FEATURE_ALLOWLIST = ("f_hour", "f_ema", "f_mom", "f_dv", "f_iv", "f_hurst")
PARTITION_COL = "incumbent_cluster_id"
SCHEMA = "descriptor_v1"


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile on a pre-sorted list (numpy 'linear' method)."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _stats(values: list[float]) -> dict:
    sv = sorted(values)
    q1, q2, q3 = (_quantile(sv, 0.25), _quantile(sv, 0.5), _quantile(sv, 0.75))
    iqr = q3 - q1
    skew = 0.0 if iqr == 0 else (q3 + q1 - 2.0 * q2) / iqr
    r = lambda x: round(x, 9)
    return {"n": len(sv), "median": r(q2), "iqr": r(iqr),
            "p05": r(_quantile(sv, 0.05)), "p95": r(_quantile(sv, 0.95)),
            "bowley_skew": r(skew)}


def build_payloads(rows: list[dict], population_ref: str, featureset: str) -> list[dict]:
    """One payload per side; components sorted by id; features in allowlist order."""
    payloads = []
    for side in sorted({r["side"] for r in rows}):
        side_rows = [r for r in rows if r["side"] == side]
        comps = []
        for cid in sorted({r[PARTITION_COL] for r in side_rows}):
            crows = [r for r in side_rows if r[PARTITION_COL] == cid]
            feats = {f: _stats([float(r[f]) for r in crows]) for f in FEATURE_ALLOWLIST}
            comps.append({"component_id": int(cid), "n": len(crows), "features": feats})
        payloads.append({"schema": SCHEMA, "population_ref": population_ref,
                         "featureset": featureset, "partition": PARTITION_COL,
                         "side": side, "n_side": len(side_rows), "components": comps})
    return payloads


def emit(pop_dir: Path, out_dir: Path, drafts_dir: Path | None) -> list[Path]:
    rows = json.loads((pop_dir / "population_rows.json").read_text())
    manifest = json.loads((pop_dir / "manifest.json").read_text())
    population_ref = "pop::anotherstrategy_p0"
    featureset = manifest.get("featureset", "fs_belka6_ea")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for payload in build_payloads(rows, population_ref, featureset):
        card_id = "card_" + sha256_canon(payload)[:12]
        path = out_dir / f"descriptor_{payload['side']}_{card_id}.json"
        path.write_bytes(canonical_bytes(payload))
        written.append(path)
        if drafts_dir is not None:
            # Envelope per schemas.envelope (merge-fix 2026-07-10: actor must be the full
            # actor string and provenance the bare literal — the old draft shape failed
            # EventDraft validation and could never be appended), and the draft is VALIDATED
            # here so a malformed one dies in this tool, not at the daemon.
            from ..schemas.envelope import ACTOR_SCHEDULER, EventDraft
            from ..store import inbox_submit
            draft = {"event_id": f"evt_cardemit_{card_id}",
                     "type": "card.emit", "actor": ACTOR_SCHEDULER,
                     "provenance": "scheduled",
                     "cites": [population_ref],
                     "payload": {"card_id": card_id, "card_type": "descriptor",
                                 "inputs": [population_ref,
                                            manifest["source"]["txt_sha256"],
                                            manifest["source"]["csv_sha256"]],
                                 "payload": payload, "coarseness_applied": False},
                     "schema_version": 1}
            EventDraft.model_validate(draft)          # fail loudly, here
            # Route via the ONLY legal submission path (staging -> atomic rename -> pending),
            # so the daemon poller actually sees it. --drafts may point at the inbox root or
            # its staging/ subdir (the colleague's original usage).
            root = drafts_dir.parent if drafts_dir.name == "staging" else drafts_dir
            inbox_submit(root / "staging", root / "pending", draft["event_id"], draft)
    return written


def selftest() -> int:
    import tempfile
    rows = []
    for side in ("BUY", "SELL"):
        for cid in (0, 1):
            for i in range(7):
                rows.append({"side": side, PARTITION_COL: cid,
                             "f_hour": float((i * 3 + cid) % 24), "f_ema": 1.0 + 0.01 * i,
                             "f_mom": (-1) ** i * 0.5 * i, "f_dv": 1.1 + 0.1 * cid,
                             "f_iv": 0.9 - 0.05 * i, "f_hurst": 0.5 + 0.01 * (i - 3),
                             "profit": 999.0})  # present in input, UNREPRESENTABLE in output
    with tempfile.TemporaryDirectory() as td:
        pop = Path(td) / "pop"; pop.mkdir()
        (pop / "population_rows.json").write_text(json.dumps(rows))
        (pop / "manifest.json").write_text(json.dumps(
            {"featureset": "fs_test", "source": {"txt_sha256": "x", "csv_sha256": "y"}}))
        a = emit(pop, Path(td) / "a", None)
        b = emit(pop, Path(td) / "b", None)
        for pa, pb in zip(a, b):
            ba, bb = pa.read_bytes(), pb.read_bytes()
            assert ba == bb, "NOT byte-identical across emits"
            assert b"profit" not in ba and b"999" not in ba, "target-blindness violated"
        # merge-fix 2026-07-10: exercise the DRAFTS path too — the old selftest never did,
        # which is how structurally un-appendable drafts shipped "green". Every draft must
        # validate as an EventDraft AND land in inbox/pending (the poller's directory).
        from ..schemas.envelope import EventDraft
        inbox = Path(td) / "inbox"
        emit(pop, Path(td) / "c", inbox)
        pending = sorted((inbox / "pending").glob("evt_cardemit_*.json"))
        assert pending, "drafts path produced nothing in inbox/pending"
        for dp in pending:
            EventDraft.model_validate(json.loads(dp.read_text()))
        print(f"selftest OK: {len(a)} payloads byte-identical; payoff unrepresentable; "
              f"{len(pending)} drafts validate as EventDraft and reached pending/")
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pop-dir", type=Path)
    p.add_argument("--out", type=Path, default=Path("var/cards_pending"))
    p.add_argument("--drafts", type=Path, default=None)
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if not a.pop_dir:
        raise SystemExit("--pop-dir required (convert_legacy_pair output)")
    for w in emit(a.pop_dir, a.out, a.drafts):
        print("wrote", w)


if __name__ == "__main__":
    main()
