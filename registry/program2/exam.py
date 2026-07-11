"""program2.exam — pinned quarterly epoch exams on virgin data (v3).

Formalizes the proven final-exam pattern (2026-07-10, sha f472954b): pin the candidate
list + rule BEFORE reading any outcome, ONE budget spend for the whole batch, BH-FDR
across it, verdict-only reporting. Candidates are full generative recipes:

  {"candidate_id", "family": <whitebox spec dict>, "side": "buy"|"sell" | null,
   "regime": <RegimeSpec dict> | null, "policy": <POLICIES name> | null,
   "era": "full"|"post2023", "pin_ts": iso, "mechanism_id", "rule_override": {...}|null}

side XOR (regime+policy): a plain candidate pools one side unconditionally; a Tier-2
candidate applies its side policy. rule_override lets a pre-registered standalone pin
(e.g. the weekend-buy candidate) keep its own verdict rule while sharing the batch spend.

V3-SEPARATION ACCOUNTING: free-layer events go to the v3 ledger, but pin/spend/result
append to the CANONICAL ledger and spend from the CANONICAL LookBudget — virgin data is
one shared pool with one accounting point.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..cascade_run import Ledger, LookBudget, generate_population
from ..canon import sha256_canon
from ..regimes.attach import attach_regime
from ..regimes.defs import RegimeSpec
from .stats import conditional_series

DEFAULT_RULE = {"min_n": 30, "fdr_q": 0.10, "bootstrap": 10000,
                "h0": "mean R-multiple <= 0", "seed": 20260711}


def pin_exam(exam_id: str, epoch: tuple[str, str], candidates: list[dict], rule: dict,
             exam_dir: Path, canonical_ledger: Ledger) -> str:
    """Write the pin and ledger it. MUST precede any read of epoch outcomes."""
    exam_dir.mkdir(parents=True, exist_ok=True)
    pin_path = exam_dir / f"exam_{exam_id}.pin.json"
    if pin_path.exists():
        return json.loads(pin_path.read_text())["pin_sha256"]
    pin = {"exam_id": exam_id, "epoch": list(epoch), "rule": {**DEFAULT_RULE, **rule},
           "n_candidates": len(candidates), "candidates": candidates}
    pin["pin_sha256"] = hashlib.sha256(
        json.dumps(pin, sort_keys=True).encode()).hexdigest()
    pin_path.write_text(json.dumps(pin, indent=1))
    canonical_ledger.append("exam.pin", {"exam_id": exam_id, "epoch": list(epoch),
                                         "pin_sha256": pin["pin_sha256"],
                                         "n_candidates": len(candidates),
                                         "program": "v3"})
    return pin["pin_sha256"]


def _candidate_trades(c: dict, epoch: tuple[str, str], pop_dir: Path,
                      bars_path: str) -> np.ndarray:
    """Profit series of candidate c inside [max(epoch_start, pin_ts), epoch_end]."""
    path, _sha, _ns, _nb = generate_population(dict(c["family"]), pop_dir)
    if c.get("regime"):
        path, _key = attach_regime(path, RegimeSpec(**c["regime"]), bars_path, pop_dir)
    df = pd.read_parquet(path)
    if c.get("policy"):
        df = conditional_series(df, f"rg_{c['regime']['name']}", c["policy"])
    else:
        df = df[df["side"] == c["side"]]
    t = pd.to_datetime(df["entry_ts"])
    a = max(pd.Timestamp(epoch[0]), pd.Timestamp(c["pin_ts"]))
    b = pd.Timestamp(epoch[1]) + pd.Timedelta(days=1)
    return df.loc[(t >= a) & (t < b), "profit"].to_numpy()


def run_exam(exam_id: str, exam_dir: Path, pop_dir: Path, bars_path: str,
             canonical_ledger: Ledger, canonical_budget: LookBudget) -> dict:
    """Verify pin, ONE spend, evaluate, BH-FDR, verdict-only ledger record."""
    pin = json.loads((exam_dir / f"exam_{exam_id}.pin.json").read_text())
    body = {k: pin[k] for k in ("exam_id", "epoch", "rule", "n_candidates", "candidates")}
    if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() \
            != pin["pin_sha256"]:
        raise RuntimeError("pin sha mismatch — pin file was modified after pinning")
    mode = canonical_budget.spend(f"exam_{exam_id}", pin["pin_sha256"],
                                  pin["pin_sha256"][:16])
    canonical_ledger.append("exam.spend", {"exam_id": exam_id, "mode": mode,
                                           "pin_sha256": pin["pin_sha256"],
                                           "program": "v3"})
    rule, epoch = pin["rule"], tuple(pin["epoch"])
    rng = np.random.RandomState(rule["seed"])
    results, t0 = [], time.time()
    for c in pin["candidates"]:
        crule = {**rule, **(c.get("rule_override") or {})}
        try:
            r = _candidate_trades(c, epoch, pop_dir, bars_path)
        except Exception as e:  # noqa: BLE001 — one bad recipe must not void the batch
            results.append({"candidate_id": c["candidate_id"], "error": str(e)[-120:]})
            continue
        n = len(r)
        row = {"candidate_id": c["candidate_id"], "mechanism_id": c.get("mechanism_id"),
               "n": n, "standalone": bool(c.get("rule_override"))}
        if n < crule["min_n"]:
            row["verdict"] = "insufficient_n"
        else:
            boots = rng.choice(r, size=(crule["bootstrap"], n), replace=True).mean(axis=1)
            row.update({"exam_pf": round(float(r[r > 0].sum()
                                               / max(1e-9, -r[r <= 0].sum())), 4),
                        "exam_mean_r": round(float(r.mean()), 5),
                        "p": float((boots <= 0).mean())})
        results.append(row)
    # BH-FDR over the shared-rule testable set; standalone pins use their own rule verbatim
    shared = [r for r in results if "p" in r and not r["standalone"]]
    m = len(shared)
    kmax = 0
    for rank, r in enumerate(sorted(shared, key=lambda x: x["p"]), 1):
        if r["p"] <= rank / max(m, 1) * rule["fdr_q"]:
            kmax = rank
    for rank, r in enumerate(sorted(shared, key=lambda x: x["p"]), 1):
        r["pass"] = rank <= kmax
    for r in results:
        if r.get("standalone") and "p" in r:
            crule = next(c.get("rule_override") or {} for c in pin["candidates"]
                         if c["candidate_id"] == r["candidate_id"])
            if "min_pf" in crule:      # a pre-registered PF bar (e.g. the weekend-buy pin)
                r["pass"] = (r["n"] >= crule.get("min_n", rule["min_n"])
                             and r["exam_pf"] >= crule["min_pf"])
            else:
                r["pass"] = r["p"] <= crule.get("alpha", 0.05)
    out = {"exam_id": exam_id, "pin_sha256": pin["pin_sha256"], "epoch": pin["epoch"],
           "n_candidates": len(pin["candidates"]), "n_testable": m,
           "n_survivors": sum(1 for r in results if r.get("pass")),
           "elapsed_s": round(time.time() - t0, 1), "results": results}
    (exam_dir / f"exam_{exam_id}.results.json").write_text(json.dumps(out, indent=1))
    canonical_ledger.append("exam.result", {k: out[k] for k in
                                            ("exam_id", "pin_sha256", "n_candidates",
                                             "n_testable", "n_survivors")}
                            | {"program": "v3"})
    return out
