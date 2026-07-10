"""rank_transfer_study — ARE WE JUST TESTING WINNERS? (confirmation study, 2026-07-10)

The question: does the masked-TRAIN ranking of whitebox baselines transfer to the held-out
windows, or is the top of the map pure selection (winner's curse)? Design:

  - a structured sample of the map: the ENTIRE Saturday-reversal-buy family (the plateau)
    plus stratified top/middle/bottom slices of everything else
  - for each config-side: the BASELINE's pooled W2:W4 profit factor and W4-only profit
    factor (unconditional — no clustering, no selection; the population as a strategy)
  - outputs: Spearman rank correlation (train vs out-of-sample), the decile transfer table,
    the winner vs the family median out-of-sample, and the empirical winner's-curse curve
    (train minus out-of-sample as a function of train rank)

STATUS OF THIS READ: bulk DIAGNOSTIC on the historical windows, which are certification-
burned for this lineage (recorded 2026-07-10, user-authorized). It calibrates the
instrument; it can NOT alter the pre-registered forward candidate (pinned BEFORE this ran)
and none of these configs may ever cite these windows as certification evidence. The real
exam is W4' (post-2026-06-30 virgin data, self-executing re-anchor).

Usage: python -m registry.rank_transfer_study [--workers 4] [--workdir ~/lightray/research]
"""
from __future__ import annotations

import argparse
import json
import time
from multiprocessing import Pool
from pathlib import Path

from .stage1_sweep import MENU, grid, key_of


def eval_config(cfg: dict) -> dict:
    """One config -> train + OOS baseline stats, both sides. Reads window outcomes (burned)."""
    import pandas as pd
    from .cascade_run import CANONICAL, _mask_cfg
    from .bridges.vbt_runner import WhiteboxSpec, run_population, tierb_train_mask
    from .tools.build_sgl_jobs import load_pc
    t0 = time.time()
    row = {"key": key_of(cfg), **cfg}
    pf = lambda p: float(p[p > 0].sum() / max(1e-9, -p[p <= 0].sum()))
    try:
        spec = WhiteboxSpec(data_path=CANONICAL, exit_resolution="hybrid",
                            trading_days=MENU["trading_days"][cfg["trading_days_name"]],
                            **{k: cfg[k] for k in ("strategy", "sl_atr_mult", "tp_atr_mult",
                                                   "donchian_period", "atr_fast")})
        df = pd.DataFrame(run_population(spec)["rows"])
        mc = _mask_cfg(load_pc())
        for side in ("sell", "buy"):
            s = df[df["side"] == side].reset_index(drop=True)
            if len(s) < 100:
                continue
            try:
                is_train, win_id, counts = tierb_train_mask(s["entry_ts"].tolist(), mc)
            except ValueError:
                continue
            r_tr = s.loc[is_train, "profit"]
            import numpy as np
            wid = np.asarray(win_id)
            oos = s.loc[wid >= 2, "profit"]              # pooled middles+certifier (historical)
            w4 = s.loc[wid == len(mc["windows"]), "profit"]
            row[side] = {"train_pf": round(pf(r_tr), 4), "train_n": int(is_train.sum()),
                         "oos_pf": round(pf(oos), 4) if len(oos) > 30 else None,
                         "oos_n": int(len(oos)),
                         "w4_pf": round(pf(w4), 4) if len(w4) > 30 else None,
                         "w4_n": int(len(w4))}
    except Exception as e:  # noqa: BLE001
        row["error"] = str(e)[-120:]
    row["elapsed_s"] = round(time.time() - t0, 1)
    return row


def sample_configs() -> list[dict]:
    """The whole Saturday-reversal family + stratified slices of the rest of the map."""
    g = grid()
    fam = [c for c in g if c["strategy"] == "reversal_pch" and c["trading_days_name"] == "saturday"]
    rest = [c for c in g if c not in fam]
    step = max(1, len(rest) // 110)
    return fam + rest[::step]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--workdir", default="/home/alex/lightray/research")
    a = ap.parse_args()
    out_path = Path(a.workdir) / "rank_transfer.jsonl"
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["key"])
    todo = [c for c in sample_configs() if key_of(c) not in done]
    print(f"rank-transfer study: {len(todo)} configs ({len(done)} done), {a.workers} workers")
    with Pool(a.workers) as pool, out_path.open("a") as f:
        for i, row in enumerate(pool.imap_unordered(eval_config, todo), 1):
            f.write(json.dumps(row) + "\n")
            f.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(todo)}")
    print(f"study rows -> {out_path}")


if __name__ == "__main__":
    main()
