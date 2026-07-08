"""NS12 — pre-signed conditionals: the unifying primitive letting the scheduler act with
human authority. The human registers an event body + firing predicate in advance; the
scheduler emits when the predicate goes green; the barrier accepts because the authorization
chain is human.

conditional.arm/disarm are HUMAN-ONLY (REG-INV-22 — an agent-armed conditional would launder
apparatus events through the scheduler). Predicate name + VERSION are pinned at arming;
deployed-version drift ⇒ the conditional is STALE (never fire on drifted semantics; human
re-arm required). Staleness is DERIVED at evaluation time (pinned vs deployed), not an event.

The two operating KINDS (TS-2.0 item 4):
 (i) per-batch readout-firing conditional — armed per handoff bundle, never standing;
     predicate = named batch's REG-INV-23 battery green + budget>0 + emission cap respected.
 (ii) queue_reorder conditional — armable only after the shadow's re-entry qualification;
     fired event applies at the handoff queue only (STAT-INV-13).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ConditionalStatus = Literal["armed", "fired", "disarmed"]  # "stale" is DERIVED, not stored


class PredicateRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str                                # resolved in predicates.PREDICATES — no eval, no DSL
    version: str                             # PINNED AT ARMING
    params: dict = Field(default_factory=dict)


class ConditionalArm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cond_id: str
    kind: Literal[
        "budget_floor_alarm", "extended_suspend_alarm", "windowset_supersession",
        "readout_firing", "queue_reorder", "other",
    ]
    predicate: PredicateRef
    event_body: dict                         # the event to emit, FULLY FORMED at arming
    note: Optional[str] = None


class ConditionalDisarm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cond_id: str
    reason: str
