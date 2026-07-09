"""build_sgl_jobs — the SINGLE-SOURCE job builder for the MATLAB SGL engine.

Every search/readout job.json is generated HERE from registry/seed/pc_v062_constants.json
(extracted field-for-field from the hashed precommit.m). MATLAB builds its mask and fit
constants from the job contract only and echoes them back (pc_echo) — no engine ever reads
precommit() off whatever BelkaSGL tree is on its path. This closes the observed drift class
where the search took windows from the job while the readout silently took them from the tree.

Usage:
  python -m registry.tools.build_sgl_jobs search  --population P.parquet --side sell \
      --selector z --out job.json --result r.json [--progress p.jsonl] \
      [--trials 200 --seed-points 40 --runs-per-k 3] [--k-values 2,3,...,9] [--job-hash H]
  python -m registry.tools.build_sgl_jobs readout --config cfg.json --tag TAG \
      --out job.json --result r.json (--population P.parquet | --legacy-txt T --legacy-csv C)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PC_PATH = Path(__file__).resolve().parents[1] / "seed" / "pc_v062_constants.json"
BELKASGL_DEFAULT = "/home/alex/Documents/Atesting7/BelkaSGL"


def load_pc() -> dict:
    return json.loads(PC_PATH.read_text())


def _mask_block(pc: dict) -> dict:
    return {
        "windows": {k: pc["windows"][k] for k in ("names", "starts", "ends")},
        "exclusions": pc["exclusions"],
        "embargo": pc["embargo"],
        "min_window_side": pc["min_window_side"],
    }


def build_search_job(population: str, side: str, selector: str, result_path: str,
                     progress_path: str | None = None, trials: int | None = None,
                     seed_points: int | None = None, runs_per_k: int | None = None,
                     k_values: list[int] | None = None, rng_seed: int = 42,
                     belkasgl_path: str = BELKASGL_DEFAULT, job_hash: str = "") -> dict:
    pc = load_pc()
    job = {
        "belkasgl_path": belkasgl_path,
        "population_parquet": population,
        "side": side,
        "K_values": k_values or [2, 3, 4, 5, 6, 7, 8, 9],
        **_mask_block(pc),
        "fit": pc["fit"],
        "search": pc["search_space"],
        "budget": {
            "n_trials": trials if trials is not None else pc["budget"]["trials_soft"],
            "n_seed": seed_points if seed_points is not None else pc["budget"]["seed_soft"],
            "runs_per_k": runs_per_k if runs_per_k is not None else pc["budget"]["runs_per_k"],
        },
        "null": pc["null"],
        "selector": selector,                 # PINNED here — the engine applies it, nobody re-ranks
        "rng_seed": rng_seed,
        "result_path": result_path,
        "pc_source_sha256": pc["_provenance"]["source_sha256"],
    }
    if progress_path:
        job["progress_path"] = progress_path
    job["job_hash"] = job_hash or _cheap_hash(job)
    return job


def build_readout_job(config: dict, tag: str, result_path: str, side: str = "sell",
                      population: str | None = None, legacy_txt: str | None = None,
                      legacy_csv: str | None = None,
                      belkasgl_path: str = BELKASGL_DEFAULT) -> dict:
    pc = load_pc()
    if not population and not (legacy_txt and legacy_csv):
        raise SystemExit("readout needs --population OR --legacy-txt + --legacy-csv")
    job = {
        "belkasgl_path": belkasgl_path,
        "side": side, "tag": tag,
        **_mask_block(pc),
        "fit": pc["fit"],
        "select": {k: pc["select"][k] for k in ("sel_pf", "sel_min_tr", "knn_k")},
        "null": pc["null"],
        "config": config,
        "result_path": result_path,
        "pc_source_sha256": pc["_provenance"]["source_sha256"],
    }
    if population:
        job["population_parquet"] = population
    else:
        job["legacy_txt"] = legacy_txt
        job["legacy_csv"] = legacy_csv
    return job


def _cheap_hash(obj: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)

    s = sub.add_parser("search")
    s.add_argument("--population", required=True)
    s.add_argument("--side", default="sell")
    s.add_argument("--selector", required=True, choices=["z", "sep"])
    s.add_argument("--out", required=True)
    s.add_argument("--result", required=True)
    s.add_argument("--progress")
    s.add_argument("--trials", type=int)
    s.add_argument("--seed-points", type=int)
    s.add_argument("--runs-per-k", type=int)
    s.add_argument("--k-values")
    s.add_argument("--rng-seed", type=int, default=42)
    s.add_argument("--belkasgl", default=BELKASGL_DEFAULT)
    s.add_argument("--job-hash", default="")

    r = sub.add_parser("readout")
    r.add_argument("--config", required=True, help="JSON file with K/kernel/sigma/.../w_hurst")
    r.add_argument("--tag", required=True)
    r.add_argument("--side", default="sell")
    r.add_argument("--out", required=True)
    r.add_argument("--result", required=True)
    r.add_argument("--population")
    r.add_argument("--legacy-txt")
    r.add_argument("--legacy-csv")
    r.add_argument("--belkasgl", default=BELKASGL_DEFAULT)

    a = ap.parse_args()
    if a.kind == "search":
        kv = [int(x) for x in a.k_values.split(",")] if a.k_values else None
        job = build_search_job(a.population, a.side, a.selector, a.result, a.progress,
                               a.trials, a.seed_points, a.runs_per_k, kv, a.rng_seed,
                               a.belkasgl, a.job_hash)
    else:
        job = build_readout_job(json.loads(Path(a.config).read_text()), a.tag, a.result,
                                a.side, a.population, a.legacy_txt, a.legacy_csv, a.belkasgl)
    Path(a.out).write_text(json.dumps(job, indent=1))
    print(f"wrote {a.out} ({a.kind}, side={job['side']})")


if __name__ == "__main__":
    main()
