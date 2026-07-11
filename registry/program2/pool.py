"""program2.pool — the candidate pool between the free layer and the quarterly exam (v3).

Admission requires the full free-layer gauntlet (recorded in `evidence`); the pool is
capped so the exam's FDR keeps its power; a frozen pool admits nothing. Rows are
exam-ready candidate recipes (the exact shape program2.exam consumes).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..canon import sha256_canon
from ..cascade_run import locked

POOL_CAP = 40
FREEZE_MARKER = "__POOL_FROZEN__"


def candidate_id(recipe: dict) -> str:
    return sha256_canon({k: recipe[k] for k in sorted(recipe)
                         if k not in ("pin_ts", "candidate_id", "evidence")})[:16]


def _rows(pool_path: Path) -> list[dict]:
    if not pool_path.exists():
        return []
    return [json.loads(l) for l in pool_path.read_text().splitlines() if l.strip()]


def admit(pool_path: Path, recipe: dict, evidence: dict, ledger) -> str:
    """-> 'admitted' | 'duplicate' | 'pool_full' | 'frozen'."""
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    with locked(pool_path):
        rows = _rows(pool_path)
        if any(r.get("marker") == FREEZE_MARKER for r in rows):
            return "frozen"
        cid = candidate_id(recipe)
        if any(r.get("candidate_id") == cid for r in rows):
            return "duplicate"
        if sum(1 for r in rows if "candidate_id" in r) >= POOL_CAP:
            return "pool_full"
        row = {**recipe, "candidate_id": cid,
               "pin_ts": recipe.get("pin_ts")
               or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "evidence": evidence}
        with pool_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
    ledger.append("pool.admit", {"candidate_id": cid,
                                 "mechanism_id": recipe.get("mechanism_id"),
                                 "era": recipe.get("era"),
                                 "evidence_keys": sorted(evidence)})
    return "admitted"


def freeze(pool_path: Path, ledger) -> list[dict]:
    """Freeze the pool (idempotent) and return the exam-ready candidate list."""
    with locked(pool_path):
        rows = _rows(pool_path)
        if not any(r.get("marker") == FREEZE_MARKER for r in rows):
            with pool_path.open("a") as f:
                f.write(json.dumps({"marker": FREEZE_MARKER,
                                    "ts": datetime.now(timezone.utc).isoformat()}) + "\n")
    cands = [r for r in rows if "candidate_id" in r]
    ledger.append("pool.freeze", {"n_candidates": len(cands)})
    return cands
