"""stage1_sweep — the MASS-PARALLEL whitebox map (v3, "run many tests" at machine scale).

Sweeps the ENTIRE bounded whitebox menu (strategy x exits x structure x trading-days), scoring
each config's population MASKED-TRAIN ONLY (free layer — no window outcome is ever read):
per-side train profit factor, expectancy (R-multiples), trade counts, and the certifier-window
TRADE COUNT (target-blind). Output: the complete ranked map of which populations deserve a
geometry search at all — the baseline pre-filter applied to the whole space in one pass.

Parallel across processes (each worker loads the shared bars once and iterates its chunk).
Results stream to stage1_map.jsonl (crash-resumable: done keys are skipped on re-run).

Usage: python -m registry.stage1_sweep [--workers 4] [--workdir ~/lightray/research] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from itertools import product
from multiprocessing import Pool
from pathlib import Path

MENU = {
    "strategy": ["reversal_pch", "breakout_pch", "momentum_pa"],
    "sl_atr_mult": [0.05, 0.08, 0.12],
    "tp_atr_mult": [0.05, 0.08, 0.12, 0.16, 0.24],
    "donchian_period": [20, 36, 50],
    "atr_fast": [7, 14],
    "trading_days": {"saturday": (5,), "all": None, "weekend": (5, 6), "monday": (0,)},
}


def grid() -> list[dict]:
    out = []
    for st, sl, tp, don, atr, days in product(MENU["strategy"], MENU["sl_atr_mult"],
                                              MENU["tp_atr_mult"], MENU["donchian_period"],
                                              MENU["atr_fast"], MENU["trading_days"]):
        out.append({"strategy": st, "sl_atr_mult": sl, "tp_atr_mult": tp,
                    "donchian_period": don, "atr_fast": atr, "trading_days_name": days})
    return out


def key_of(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def score_config(cfg: dict) -> dict:
    """One config -> masked-train scorecard for BOTH sides. Free layer; windows never read."""
    from .cascade_run import CANONICAL, _mask_cfg
    from .bridges.vbt_runner import WhiteboxSpec, run_population, tierb_train_mask
    from .tools.build_sgl_jobs import load_pc
    import pandas as pd
    t0 = time.time()
    row = {"key": key_of(cfg), **cfg}
    try:
        spec = WhiteboxSpec(data_path=CANONICAL, exit_resolution="hybrid",
                            trading_days=MENU["trading_days"][cfg["trading_days_name"]],
                            **{k: cfg[k] for k in ("strategy", "sl_atr_mult", "tp_atr_mult",
                                                   "donchian_period", "atr_fast")})
        rows = run_population(spec)["rows"]
        df = pd.DataFrame(rows)
        mc = _mask_cfg(load_pc())
        for side in ("sell", "buy"):
            s = df[df["side"] == side]
            if len(s) < 100:
                row[side] = {"n": int(len(s)), "healthy": False, "reason": "too few trades"}
                continue
            try:
                is_train, _, counts = tierb_train_mask(s["entry_ts"].tolist(), mc)
            except ValueError as e:
                row[side] = {"n": int(len(s)), "healthy": False, "reason": str(e)[:80]}
                continue
            r = s.loc[is_train, "profit"]
            gl = float(-r[r <= 0].sum())
            pf = float(r[r > 0].sum() / gl) if gl > 0 else float("inf")
            row[side] = {"n": int(len(s)), "train_n": int(is_train.sum()),
                         "train_pf": round(pf, 4), "train_exp": round(float(r.mean()), 5),
                         "w4_count": int(counts[-1]),
                         "healthy": bool(pf >= 1.05 and r.mean() > 0 and counts[-1] >= 30)}
    except Exception as e:  # noqa: BLE001
        row["error"] = str(e)[-150:]
    row["elapsed_s"] = round(time.time() - t0, 1)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--workdir", default="/home/alex/lightray/research")
    ap.add_argument("--limit", type=int, default=0, help="cap configs (0 = the full grid)")
    a = ap.parse_args()
    out_path = Path(a.workdir) / "stage1_map.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["key"])
    todo = [c for c in grid() if key_of(c) not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"stage1 sweep: {len(todo)} configs to score ({len(done)} already done), "
          f"{a.workers} workers")
    t0 = time.time()
    with Pool(a.workers) as pool, out_path.open("a") as f:
        for i, row in enumerate(pool.imap_unordered(score_config, todo), 1):
            f.write(json.dumps(row) + "\n")
            f.flush()
            hs = [s for s in ("sell", "buy") if isinstance(row.get(s), dict) and row[s].get("healthy")]
            print(f"  [{i}/{len(todo)}] {row['strategy']:>13} {row['trading_days_name']:>8} "
                  f"sl{row['sl_atr_mult']} tp{row['tp_atr_mult']} d{row['donchian_period']} "
                  f"-> healthy: {hs or '-'} ({row['elapsed_s']}s)")
    print(f"sweep done in {(time.time()-t0)/60:.1f} min -> {out_path}")


if __name__ == "__main__":
    main()
