"""Shadow telemetry, queue reorder, notes, replay verification."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ShadowRanking(BaseModel):
    """agent:claude/shadow's SOLE permitted event — telemetry, zero verdict/ordering weight.
    R23 (Goodhart) rides this metric series."""
    model_config = ConfigDict(extra="forbid")
    epoch_id: str
    handoff_queue_ref: str
    ranking: list[str]                        # candidate ids, shadow's order
    divergence_hypotheses: dict[str, str] = Field(default_factory=dict)
    # {candidate_id: one-line hypothesis} for each disagreement with score order


class QueueReorder(BaseModel):
    """Legal ONLY as a fired conditional citing human arming + the shadow qualification
    evidence (STAT-INV-13). Applies at the HANDOFF QUEUE only — never inter-stage."""
    model_config = ConfigDict(extra="forbid")
    handoff_queue_ref: str
    new_order: list[str]
    qualification_evidence_ref: str


class NoteRecord(BaseModel):
    """Prose findings — LEDGER.md's lab-notebook voice survives as first-class data."""
    model_config = ConfigDict(extra="forbid")
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)


class ReplayVerified(BaseModel):
    """Nightly cold replay result (scheduler-mechanical, REG-INV-25)."""
    model_config = ConfigDict(extra="forbid")
    as_of_seq: int
    live_state_hash: str
    replay_state_hash: str
    ok: bool
