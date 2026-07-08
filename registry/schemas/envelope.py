"""The event envelope (TECH_SPEC §3.1) — the one shape everything submits.

Clients submit an EventDraft (no seq / chain hashes). Ingest enriches it (computes physical
hashes into the payload's computed_* fields), the barrier decides on the enriched draft, and
the writer appends the full Event with seq/prev_hash/event_hash.

`event_id` is CLIENT-generated and deterministic — sha256 over canonical
{type, actor, payload, intent} — so the timeout-then-retry path is safe (daemon dedups on it
and fsyncs before ACK).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import REGISTRY_SPEC_VERSION, SCHEMA_VERSION
from ..canon import sha256_canon

# ---- actors (TS-2.0 item 1: proposer RETIRED — historical events only) ----------------------
ACTOR_HUMAN = "human:alexander"
ACTOR_LOOP_POPULATION = "loop:population"
ACTOR_LOOP_GEOMETRY = "loop:geometry"
ACTOR_SCHEDULER = "scheduler:daemon"
ACTOR_BOUNDARY = "agent:claude/boundary"
ACTOR_SHADOW = "agent:claude/shadow"
ACTOR_OPERATOR = "agent:claude/operator"
ACTOR_PROPOSER_RETIRED = "agent:claude/proposer"  # appears only in historical/imported events

ACTORS = {
    ACTOR_HUMAN, ACTOR_LOOP_POPULATION, ACTOR_LOOP_GEOMETRY, ACTOR_SCHEDULER,
    ACTOR_BOUNDARY, ACTOR_SHADOW, ACTOR_OPERATOR, ACTOR_PROPOSER_RETIRED,
}
AGENT_ACTORS = {ACTOR_BOUNDARY, ACTOR_SHADOW, ACTOR_OPERATOR, ACTOR_PROPOSER_RETIRED}
LOOP_ACTORS = {ACTOR_LOOP_POPULATION, ACTOR_LOOP_GEOMETRY}

# ---- event vocabulary (TECH_SPEC §3.2; TS-2.0 additions included) ---------------------------
EVENT_TYPES = frozenset({
    # NS1/NS2/NS4
    "dataset.register",
    "feature.register", "feature.status_change",
    "featureset.freeze",
    "family.register", "family.activate",
    # NS5 blocks
    "block.register", "block.freeze", "block.supersede", "block.kill_axis", "block.close",
    # trials
    "trials.open_batch", "trials.record", "trials.close_batch",
    # NS8 artifacts
    "artifact.register", "artifact.stamp", "artifact.attest_missing", "artifact.integrity_checked",
    # NS9 cards + scorecards (TS-2.0)
    "card.emit", "scorecard.emit",
    # NS3/NS7 windows + spend
    "windowset.register", "windowset.supersede", "scope.mint",
    # readouts
    "readout.request", "readout.record", "readout.void",
    # NS10 certification
    "cert.clause_stamp", "cert.certify", "cert.displace", "cert.revoke",
    # NS11 constants
    "constants.register", "constants.amend",
    # NS12 conditionals
    "conditional.arm", "conditional.disarm",
    # rules channel (P7 probation; STAT-INV-10)
    "rules.propose", "rules.adopt", "rules.revert",
    # cascade cycle machinery (TS-2.0)
    "cycle.open", "cycle.close", "stage.dispatch",
    # agent telemetry + ordering channel
    "shadow_ranking", "queue_reorder",
    # housekeeping
    "replay.verified", "note.record",
})

Provenance = Literal["scheduled", "discretionary"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_event_id(type_: str, actor: str, payload: dict, intent: str) -> str:
    """Deterministic client-side id: dedup key for safe retries."""
    return "evt_" + sha256_canon({"type": type_, "actor": actor, "payload": payload,
                                  "intent": intent})[:24]


class EventDraft(BaseModel):
    """What a client submits (HTTP or inbox). No chain fields yet."""
    model_config = ConfigDict(extra="forbid")

    event_id: str
    ts: Optional[datetime] = None            # daemon clock stamps at append; payload times are DATA
    type: str
    actor: str
    provenance: Provenance
    hypothesis: Optional[str] = None         # ┐
    reasoning: Optional[str] = None          # │ REQUIRED iff discretionary (REG-INV-05)
    expected_outcome: Optional[str] = None   # ┘
    cites: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    registry_spec_version: str = REGISTRY_SPEC_VERSION
    registry_git: Optional[str] = None
    predicate_version: Optional[str] = None
    reducer_version: Optional[str] = None
    agent_prompt_version: Optional[str] = None   # stamped on agent-actor events (R13)
    agent_model_version: Optional[str] = None
    imported: bool = False                   # t=0 converters set True (historical acts import as what they were)
    schema_version: int = SCHEMA_VERSION

    @model_validator(mode="after")
    def _basic(self) -> "EventDraft":
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {self.type}")
        if self.actor not in ACTORS:
            raise ValueError(f"unknown actor: {self.actor}")
        return self


class Event(EventDraft):
    """The appended record: draft + chain fields. Frozen once written."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    ts: datetime                              # daemon-assigned UTC (ordering is seq, never ts)
    prev_hash: str
    event_hash: str

    def chain_body(self) -> dict:
        """The envelope minus event_hash — the bytes the chain hash covers."""
        d = self.model_dump(mode="json")
        d.pop("event_hash")
        return d


def compute_event_hash(envelope_without_hash: dict) -> str:
    return sha256_canon(envelope_without_hash)
