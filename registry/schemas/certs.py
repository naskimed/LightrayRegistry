"""NS10 certification — clause-granular stamps; status is a PROJECTION of stamp state.

`cert.clause_stamp` is the carrying event (loops emit measured_pass/fail from result
ingestion; humans emit pre_authorized entries). `cert.certify`/`cert.displace` are
scheduler-MATERIALIZED on gate-green / REG-INV-09-green — the examinee neither writes nor
grades the exam. `cert.revoke` is human-only; consequence = automatic projection-restore of
the prior incumbent.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ClauseId = Literal["w4_per_blob", "regime_consistency", "degradation", "persistence", "seed_survival"]
StampKind = Literal["measured_pass", "measured_fail", "pre_authorized"]


class CertClauseStamp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str                        # config/blob lineage being examined
    lineage_id: str                          # windowset-family lineage
    clause: ClauseId
    stamp: StampKind
    evidence_ref: Optional[str] = None       # artifact/log the number comes from (no-remembered-literals)


class CertCertify(BaseModel):
    """Scheduler-materialized when the FULL frozen gate (clauses + aggregate band, ONE
    versioned predicate) is green. Imported historical certs carry imported:true and are
    exempt from the scheduled-channel rule (they were discretionary human acts)."""
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    lineage_id: str
    gate_predicate_version: str
    clause_state: dict                       # {clause: stamp} — 5/5 at certify (REG-INV-09)
    k_stamp: Optional[str] = None            # transparency; ZERO verdict weight


class CertDisplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineage_id: str
    new_incumbent: str
    old_incumbent: Optional[str] = None


class CertRevoke(BaseModel):
    """HUMAN-ONLY (REG-INV-22). Carrier for decision 7(c): certifications from contaminated
    lineage are invalid. Consequence: automatic projection-restore of the prior incumbent."""
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    lineage_id: str
    reason: str
