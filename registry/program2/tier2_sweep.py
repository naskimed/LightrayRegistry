"""program2.tier2_sweep — the Tier-2 mass sweep: regime x side-policy x family x era (v3).

Free layer, train-side only, resumable. For every combination: the Tier-2 delta statistic
on the forward-masked (and era-filtered) train rows. Combos that clear the admission bar
(delta>0, p<0.05, n_cond>=POWER_FLOOR) then face the full gauntlet — regime placebo PASS
and twin battery SILENT — before pool admission under their mechanism card.

Usage: python -m registry.program2.tier2_sweep [--families 12] [--workdir .../research_v3]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from ..cascade_run import CANONICAL, Ledger, _mask_cfg, generate_population
from ..regimes.attach import attach_regime
from ..regimes.defs import RegimeSpec
from ..regimes.referee import regime_placebo
from ..tools.build_sgl_jobs import load_pc
from ..twin_check2 import run_battery2
from .masks import forward_train_mask
from .pool import admit
from .stats import tier2_stat

REGIMES = [
    {"name": "trend_sma", "params": {"fast_d": 10, "slow_d": 50}},
    {"name": "trend_sma", "params": {"fast_d": 20, "slow_d": 100}},
    {"name": "trend_sma", "params": {"fast_d": 50, "slow_d": 200}},
    {"name": "vol_tercile", "params": {"window_d": 20}},
    {"name": "vol_tercile", "params": {"window_d": 30}},
]
POLICIES_BY_REGIME = {
    "trend_sma": ["long_up_short_down", "long_up_flat_down",
                  "flat_up_short_down", "long_down_short_up"],
    "vol_tercile": ["long_low_vol", "long_high_vol", "short_high_vol", "both_low_vol"],
}
ERAS = {"full": None, "post2023": "2024-01-01"}
MECHANISM = {"trend_sma": "T2-TREND-SIDE", "vol_tercile": "T2-VOL-SIDE"}
POWER_FLOOR = 100
DAYS = {"saturday": (5,), "all": None, "weekend": (5, 6), "monday": (0,)}


def top_families(stage1_map: Path, n: int) -> list[dict]:
    """Top-n distinct configs by best healthy-side train PF (train-only map)."""
    best: dict[str, tuple[float, dict]] = {}
    for line in stage1_map.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pf = max((row[s]["train_pf"] for s in ("sell", "buy")
                  if isinstance(row.get(s), dict) and row[s].get("healthy")), default=None)
        if pf is None:
            continue
        spec = {"strategy": row["strategy"], "sl_atr_mult": row["sl_atr_mult"],
                "tp_atr_mult": row["tp_atr_mult"], "donchian_period": row["donchian_period"],
                "atr_fast": row["atr_fast"],
                "trading_days": DAYS[row["trading_days_name"]]}
        best[row["key"]] = (pf, spec)
    ranked = sorted(best.values(), key=lambda t: -t[0])[:n]
    return [spec for _pf, spec in ranked]


def _era_filter(df: pd.DataFrame, era: str) -> pd.DataFrame:
    start = ERAS[era]
    if start is None:
        return df
    return df[pd.to_datetime(df["entry_ts"]) >= pd.Timestamp(start)].reset_index(drop=True)


def sweep(workdir: Path, n_families: int) -> None:
    led = Ledger(workdir / "events.jsonl")
    out_path = workdir / "tier2_map.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["combo"] for l in out_path.read_text().splitlines() if l.strip()}
    mc = _mask_cfg(load_pc())
    fams = top_families(Path("/home/alex/lightray/research/stage1_map.jsonl"), n_families)
    print(f"tier2 sweep: {len(fams)} families x {len(REGIMES)} regimes x 4 policies x "
          f"{len(ERAS)} eras ({len(done)} combos done)", flush=True)
    t0 = time.time()
    for fi, fam in enumerate(fams, 1):
        pop_path, pop_sha, ns, nb = generate_population(dict(fam), workdir / "pops")
        for rg in REGIMES:
            spec = RegimeSpec(rg["name"], rg["params"])
            rg_path, rg_key = attach_regime(pop_path, spec, CANONICAL, workdir / "pops")
            df = pd.read_parquet(rg_path)
            is_train, _, _ = forward_train_mask(df["entry_ts"].tolist(), mc)
            train_all = df[is_train].reset_index(drop=True)
            col = f"rg_{rg['name']}"
            for era in ERAS:
                train = _era_filter(train_all, era)
                for policy in POLICIES_BY_REGIME[rg["name"]]:
                    combo = f"{pop_sha[:12]}|{rg_key}|{policy}|{era}"
                    if combo in done:
                        continue
                    s = tier2_stat(train, col, policy)
                    row = {"combo": combo, "family": fam | {"trading_days":
                           list(fam["trading_days"]) if fam["trading_days"] else None},
                           "regime": rg, "policy": policy, "era": era, **s}
                    hit = ("delta_pf" in s and s["delta_pf"] > 0 and s["p_boot"] < 0.05
                           and s["n_cond"] >= POWER_FLOOR)
                    row["admission_bar"] = bool(hit)
                    if hit:
                        pl = regime_placebo(train, col, policy)
                        row["placebo"] = pl["verdict"]
                        if pl["verdict"] == "PASS":
                            def statistic(twin_path, _col=col, _pol=policy, _era=era,
                                          _rg=rg_path):
                                tw = pd.read_parquet(twin_path)
                                tw[_col] = pd.read_parquet(_rg)[_col].to_numpy()
                                m, _, _ = forward_train_mask(tw["entry_ts"].tolist(), mc)
                                t = _era_filter(tw[m].reset_index(drop=True), _era)
                                st = tier2_stat(t, _col, _pol)
                                return bool(st.get("delta_pf", 0) > 0
                                            and st.get("p_boot", 1) < 0.05)
                            tag = f"t2_{rg_key}_{policy}_{era}"
                            rep = run_battery2(rg_path, statistic, tag, workdir)
                            row["twins"] = rep["verdict"]
                            if rep["verdict"] == "SILENT":
                                recipe = {"family": fam | {"trading_days":
                                          list(fam["trading_days"]) if fam["trading_days"]
                                          else None},
                                          "side": None, "regime": rg | {"source": "spot_bars",
                                          "effective_lag": "1d"},
                                          "policy": policy, "era": era,
                                          "mechanism_id": MECHANISM[rg["name"]],
                                          "rule_override": None}
                                row["pool"] = admit(workdir / "pool_E1.jsonl", recipe,
                                                    {"tier2": s, "placebo": pl["verdict"],
                                                     "twins": "SILENT"}, led)
                    with out_path.open("a") as f:
                        f.write(json.dumps(row) + "\n")
        print(f"  family {fi}/{len(fams)} done ({(time.time()-t0)/60:.1f} min)", flush=True)
    led.append("tier2.sweep_done", {"families": len(fams),
                                    "elapsed_min": round((time.time() - t0) / 60, 1)})
    print("tier2 sweep DONE", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", type=int, default=12)
    ap.add_argument("--workdir", default="/home/alex/lightray/research_v3")
    a = ap.parse_args()
    sweep(Path(a.workdir), a.families)


if __name__ == "__main__":
    main()
