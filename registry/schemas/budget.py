"""NS7 — the per-lineage look budget (REG-INV-24, FINAL form).

Verdict invariance is the core principle: the certification verdict is identical at look 1
and look 31 — history gates ACCESS to the exam, never the grade. Windows never retire, never
change role. NO earn-back; refill = calendar re-anchor or human amend only (both human-only
under REG-INV-22 — the agent cannot self-refill).

SEEDED VALUES — SINGLE SOURCE (OQ-1 resolved; every other mention cites this object):
initial_budget = 10 · floors in slots-REMAINING · alarm_remaining = 5 · diagnostic_remaining = 1.
Comparator (review-5): a floor FIRES when slots_remaining <= value.
The final slot is a SOFT reserve (user decision 2026-07-07): contract-only — the boundary's
registered contract says don't propose at 1-remaining; the barrier would NOT reject it.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LookBudget(BaseModel):
    """The registered constants object per window-interval lineage."""
    model_config = ConfigDict(extra="forbid")
    lineage_id: str                          # windowset-family lineage key
    generation: int = 1
    initial_budget: int                      # gen-1 seeded value: 10  ← cite, do not restate
    alarm_remaining: int                     # 5  (floor fires when slots_remaining <= value)
    diagnostic_remaining: int                # 1  (diagnostic mode below this — contract-enforced)
    reserve_form: Literal["soft"] = "soft"
    refill_channels: list[str] = Field(
        default_factory=lambda: ["calendar_reanchor", "human_amend"]
    )
    # Counting rule: accepted NON-postmortem readout batches across ALL scopes.
    # postmortem + rehearsal spend nothing; readout.void restores its slot;
    # a placebo-passed readout still consumes its slot (OQ-9) — a look is a look.


class BudgetView(BaseModel):
    """Projection row (state.lineages[*].budget)."""
    model_config = ConfigDict(extra="forbid")
    lineage_id: str
    generation: int
    k_cumulative: int                        # never resets across generations ("look 13 of 12+6")
    consumed_this_generation: int
    remaining: int
    alarm_fired: bool = False
    diagnostic_mode: bool = False
