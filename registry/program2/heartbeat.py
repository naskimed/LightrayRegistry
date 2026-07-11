"""program2.heartbeat — the daily runner that keeps the calendar promises (v3, cron).

Owns three obligations, all pre-registered:
  1. the W4' re-anchor check (inherited from v2 whose loop is stopped),
  2. pool freeze on FREEZE_DATE (writes the E1 exam pin from the frozen pool),
  3. the standing-armed E1 exam on/after EXAM_DATE — refreshes the data snapshot, pins its
     sha, and runs the pinned exam with ONE canonical-budget spend. Respects canonical
     var/HALT at exam time (skips + ledgers, retries next day).

Cron: 17 3 * * *  LIGHTMINER_PATH=... python3 -m registry.program2.heartbeat
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..cascade_run import CANONICAL, Ledger, LookBudget, generate_population, _sha
from .exam import pin_exam, run_exam
from .pool import freeze

V3_WD = Path("/home/alex/lightray/research_v3")
CANON_WD = Path("/home/alex/lightray/research")
HALT = Path("/home/alex/lightray/var/HALT")
FREEZE_DATE = "2026-09-15"
EXAM_DATE = "2026-10-01"
EXAM_ID = "E1"
EPOCH = ("2026-07-01", "2026-09-30")
REANCHOR_POP = {"strategy": "reversal_pch", "sl_atr_mult": 0.05, "tp_atr_mult": 0.16,
                "donchian_period": 20, "atr_fast": 7, "trading_days": None}


def check_reanchor(led_canon: Ledger) -> None:
    """Run v2's maybe_reanchor against a high-count all-days population (best virgin
    trade-count proxy). Defensive: reanchor semantics live in the v2 module."""
    try:
        from ..cascade_run import maybe_reanchor
        pop_path, _sha256, _ns, _nb = generate_population(dict(REANCHOR_POP), V3_WD / "pops")
        maybe_reanchor(pop_path, Path(__file__).resolve().parents[1] / "seed", led_canon)
    except Exception as e:  # noqa: BLE001 — heartbeat must never die silently
        led_canon.append("heartbeat.reanchor_error", {"error": str(e)[-160:]})


def refresh_snapshot() -> tuple[str, str]:
    """Fetch the epoch data snapshot (through epoch end) and return (path, sha256)."""
    out = V3_WD / "data" / f"canonical_{EXAM_ID}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "registry.tools.fetch_binance",
                    "--symbol", "BTCUSDT", "--interval", "1m", "--start", "2017-08",
                    "--out", str(out)],
                   cwd=str(Path(__file__).resolve().parents[2]), check=True,
                   capture_output=True, text=True, timeout=7200)
    return str(out), _sha(str(out))


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    led_v3 = Ledger(V3_WD / "events.jsonl")
    led_canon = Ledger(CANON_WD / "events.jsonl")
    check_reanchor(led_canon)

    pin_path = V3_WD / "exams" / f"exam_{EXAM_ID}.pin.json"
    if today >= FREEZE_DATE and not pin_path.exists():
        cands = freeze(V3_WD / "pool_E1.jsonl", led_v3)
        for c in cands:
            c.pop("evidence", None)
        pin_exam(EXAM_ID, EPOCH, cands, {}, V3_WD / "exams", led_canon)
        print(f"pool frozen + {EXAM_ID} pinned: {len(cands)} candidates", flush=True)

    results_path = V3_WD / "exams" / f"exam_{EXAM_ID}.results.json"
    if today >= EXAM_DATE and pin_path.exists() and not results_path.exists():
        if HALT.exists():
            led_canon.append("exam.blocked_by_halt", {"exam_id": EXAM_ID,
                                                      "halt": HALT.read_text()[:120]})
            print("exam blocked by HALT — retrying tomorrow", flush=True)
            return
        snap_path, snap_sha = refresh_snapshot()
        led_canon.append("exam.snapshot_pinned", {"exam_id": EXAM_ID, "path": snap_path,
                                                  "sha256": snap_sha})
        # fresh pop dir so no stale spec-keyed cache serves pre-refresh trades
        import registry.cascade_run as cr
        cr.CANONICAL = snap_path
        out = run_exam(EXAM_ID, V3_WD / "exams", V3_WD / "exams" / f"pops_{EXAM_ID}",
                       snap_path, led_canon, LookBudget(CANON_WD / "budget_btc.json"))
        print(f"{EXAM_ID} DONE: {out['n_survivors']}/{out['n_testable']} survive", flush=True)


if __name__ == "__main__":
    main()
