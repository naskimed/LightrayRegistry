"""NS11 constants documents — single source of truth for every chosen number.

Per-key finality: provisional | final. Amend = NEW VERSION linked to old, never an edit.
Anything on the REG-INV-22 apparatus list is human-only categorically — including the
autonomy-constants object itself (the brake is not editable by the braked) and, per v10.1,
the score function + promotion projection (the ordering authority).
Formulas are DECLARATIVE (named ids + params, NO eval) — MATLAB mirrors the id.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Finality = Literal["provisional", "final"]

# Constants series that are APPARATUS (REG-INV-22): human-only even to *amend*.
APPARATUS_SERIES = frozenset({
    "autonomy_constants",
    "audit_rule_constants",
    "look_budget",            # per-lineage budgets (NS7 objects registered through here)
    "placebo_recipe",
    "score_function",         # v10.1: ordering authority
    "promotion_predicate",    # v10.1
    "novelty_penalty",        # promotion-projection component (TS-2.0 §5.5.4)
    "emission_spec",          # silent_v1 — the registered definition of "emits nothing"
    "card_coarseness",
    "agent_contracts",
})

# NON-apparatus constants series (still human-only via constants.amend barrier law; listed for
# the exporter): pc_* engine constants docs, cascade_unit_costs, cycle_schedule, cost_model,
# dial constants (the human-only shell citing the live DialBudgetRule).


class FormulaRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str                                # e.g. "affine_floor"
    params: dict[str, Any] = Field(default_factory=dict)


class ConstantEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Any = None
    finality: Finality = "provisional"
    formula_ref: Optional[FormulaRef] = None
    unknown: bool = False                    # registered-but-unset ([UNKNOWN] until measured/chosen)
    rationale: Optional[str] = None


class ConstantsRegister(BaseModel):
    """constants.register — a whole versioned document in a series."""
    model_config = ConfigDict(extra="forbid")
    series: str                              # e.g. "pc", "autonomy_constants", "placebo_recipe"
    doc_id: str                              # e.g. "pc_v0.7.0"
    version: int
    entries: list[ConstantEntry]
    provenance: dict = Field(default_factory=dict)


class ConstantsAmend(BaseModel):
    """constants.amend — new version linked to old, never an edit."""
    model_config = ConfigDict(extra="forbid")
    series: str
    old_doc_id: str
    new_doc_id: str
    version: int
    entries: list[ConstantEntry]
    rationale: str
