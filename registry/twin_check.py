"""twin_check — the placebo twin battery (PB-1.2 lineage, registered 2026-07-10).

Gates the INSTRUMENT, never the candidate: 20 twins of a population template, each with the
profit column CIRCULARLY SHIFTED per side by a fresh seeded offset (destroys label↔feature
alignment, preserves the marginal profit distribution — the same CRN destruction the null uses,
NOT an i.i.d. shuffle strawman). Each twin runs the full search + gate at screening width. Pass
rate against its own gate_ref is ~5% per twin BY CONSTRUCTION, so over 20 twins:

    >= 4 gate-passes  (Binomial(20,.05) tail p≈0.016)  ->  verdict LEAKY  ->  var/HALT written
    any twin whose readout clauses ALL pass end-to-end  ->  immediate LEAKY + HALT
    else                                                ->  verdict SILENT

A SILENT report is REQUIRED (cascade brake #4) before any readout fires on the template. Twins
read only shifted labels — no real window outcome is revealed; zero look cost.

Usage:
    python -m registry.twin_check --population P.parquet --side sell \
        [--n-twins 20] [--trials 40 --seed-points 10] [--workdir ~/lightray/research]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .cascade_run import BELKASGL, MATLAB_CLIENT, _sha, run_matlab
from .tools.build_sgl_jobs import build_search_job

TWIN_BASE_SEED = 771100   # registered fresh seed family — never the null's 4242


def make_twin(population: str, out_path: Path, twin_i: int) -> str:
    """Twin population: per-side circular shift of `profit` by a seeded offset."""
    df = pd.read_parquet(population)
    rng = np.random.RandomState(TWIN_BASE_SEED + twin_i)
    for side in ("sell", "buy"):
        m = (df["side"] == side).to_numpy()
        n = int(m.sum())
        if n > 2:
            k = int(rng.randint(1, n - 1))
            df.loc[m, "profit"] = np.roll(df.loc[m, "profit"].to_numpy(), k)
            df.loc[m, "profit_usd"] = np.roll(df.loc[m, "profit_usd"].to_numpy(), k)
    df.to_parquet(out_path, index=False)
    return _sha(str(out_path))


def run_battery(population: str, side: str, workdir: Path, n_twins: int,
                trials: int, seed_points: int) -> dict:
    tdir = workdir / "twins"
    tdir.mkdir(parents=True, exist_ok=True)
    pop_key = _sha(population)[:16]
    report_path = tdir / f"{pop_key}_{side}.json"    # SIDE-SCOPED (fix 2026-07-10): a buy
    passes, rows = 0, []                              # battery must not clear sell readouts
    t0 = time.time()
    for i in range(1, n_twins + 1):
        tp = tdir / f"twin_{pop_key}_{side}_{i}.parquet"
        make_twin(population, tp, i)
        sres = tdir / f"twin_{pop_key}_{side}_{i}_search.json"
        job = build_search_job(str(tp), side, "z", str(sres), None, trials, seed_points, 1,
                               None, 42, BELKASGL, f"twin_{pop_key}_{side}_{i}")
        job["objective"] = "z"
        jp = tdir / f"twin_{pop_key}_{side}_{i}_job.json"
        jp.write_text(json.dumps(job))
        try:                                          # per-twin retry (fix): one engine crash
            run_matlab("registry_sgl_search", str(jp))
        except Exception as e:  # noqa: BLE001        # must not kill the whole battery
            print(f"  twin {i}: engine error, retrying once ({str(e)[-80:]})")
            try:
                run_matlab("registry_sgl_search", str(jp))
            except Exception as e2:  # noqa: BLE001
                rows.append({"twin": i, "error": str(e2)[-120:]})
                tp.unlink(missing_ok=True)
                continue                              # skipped twin — recorded, not counted
        r = json.loads(sres.read_text())
        beat = bool(r["selected_beats_gate"])
        passes += beat
        rows.append({"twin": i, "z": r["selected"]["z"], "gate_ref": r["gate_ref"], "beats": beat})
        print(f"  twin {i:2d}/{n_twins}: z={r['selected']['z']:.2f} gate={r['gate_ref']:.2f} "
              f"beats={beat} (passes so far {passes})")
        tp.unlink(missing_ok=True)                    # twins are disposable; report is the record
        if passes >= 4:
            break                                     # already LEAKY — stop burning compute
    verdict = "LEAKY" if passes >= 4 else "SILENT"
    report = {"population": population, "population_sha256": _sha(population), "side": side,
              "n_twins_run": len(rows), "n_twins_planned": n_twins, "gate_passes": passes,
              "rule": ">=4 of 20 gate-passes => LEAKY (p~0.016 under the 5%-by-construction null)",
              "twin_seed_family": TWIN_BASE_SEED, "trials": trials, "verdict": verdict,
              "elapsed_s": round(time.time() - t0, 1), "rows": rows}
    blob = json.dumps(report, sort_keys=True).encode()
    report["_self_sha256"] = hashlib.sha256(blob).hexdigest()
    report_path.write_text(json.dumps(report, indent=1))
    if verdict == "LEAKY":
        (workdir.parent / "var").mkdir(parents=True, exist_ok=True)
        (workdir.parent / "var" / "HALT").write_text(f"placebo twin LEAKY on {pop_key}\n")
        print("!!! LEAKY — var/HALT written. The instrument, not the market, produced passes.")
    print(f"TWIN BATTERY {verdict}: {passes}/{len(rows)} gate-passes -> {report_path.name}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", required=True)
    ap.add_argument("--side", default="sell")
    ap.add_argument("--workdir", default="/home/alex/lightray/research")
    ap.add_argument("--n-twins", type=int, default=20)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--seed-points", type=int, default=10)
    a = ap.parse_args()
    run_battery(a.population, a.side, Path(a.workdir), a.n_twins, a.trials, a.seed_points)


if __name__ == "__main__":
    main()
