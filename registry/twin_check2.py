"""twin_check2 — the placebo twin battery for Program-2 Python statistics (v3).

Reuses twin_check.make_twin VERBATIM (per-side circular profit shift, seed family
771100+i) — the construction is validated; only the evaluated statistic changes. Each twin
runs the candidate's own pass rule; >=4 of 20 twin passes => LEAKY => var/HALT, same
semantics as the SGL-era battery. Report scoped by (pop_sha16, statistic scope tag).

statistic_fn contract: statistic_fn(twin_parquet_path) -> bool (does this twin PASS the
same rule a real candidate must pass — e.g. tier2 delta>0 with p_boot<0.05).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from .cascade_run import _sha
from .twin_check import make_twin


def run_battery2(population: str, statistic_fn: Callable[[str], bool], scope_tag: str,
                 workdir: Path, n_twins: int = 20, leaky_at: int = 4) -> dict:
    tdir = workdir / "twins"
    tdir.mkdir(parents=True, exist_ok=True)
    pop_key = _sha(population)[:16]
    report_path = tdir / f"{pop_key}_{scope_tag}.json"
    if report_path.exists():
        return json.loads(report_path.read_text())
    passes, rows, t0 = 0, [], time.time()
    for i in range(1, n_twins + 1):
        tp = tdir / f"twin2_{pop_key}_{scope_tag}_{i}.parquet"
        make_twin(population, tp, i)
        try:
            hit = bool(statistic_fn(str(tp)))
        except Exception as e:  # noqa: BLE001 — a broken twin is recorded, not counted
            rows.append({"twin": i, "error": str(e)[-120:]})
            tp.unlink(missing_ok=True)
            continue
        passes += hit
        rows.append({"twin": i, "pass": hit})
        tp.unlink(missing_ok=True)
        if passes >= leaky_at:
            break
    verdict = "LEAKY" if passes >= leaky_at else "SILENT"
    report = {"population_sha256": _sha(population), "scope": scope_tag,
              "n_twins_run": len(rows), "n_twins_planned": n_twins,
              "passes": passes, "leaky_at": leaky_at, "verdict": verdict,
              "elapsed_s": round(time.time() - t0, 1), "rows": rows}
    report_path.write_text(json.dumps(report, indent=1))
    if verdict == "LEAKY":
        var = workdir.parent / "var"
        var.mkdir(parents=True, exist_ok=True)
        (var / "HALT").write_text(f"twin2 LEAKY on {pop_key} scope {scope_tag}\n")
    return report
