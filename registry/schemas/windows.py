"""NS3 windowsets · window-interval lineage (`wiv_`) · scopes · spend records.

Spend identity hardening: window-interval lineage is THE single spend key. `wiv_` identity =
(data_contract, start, end) ONLY — anchor_field/clock live at the WINDOWSET level so an
OPEN-16 re-anchor (mask semantics change) carries spends + cumulative k automatically.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

WindowRole = Literal["backward_only", "middle", "forward_certifier"]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wiv_id: str                              # wiv_<hash8> over (data_contract, start, end)
    data_contract: str
    start: str                               # ISO date — interval identity
    end: str
    role: WindowRole                         # roles NEVER change; windows never retire


class Embargo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_days: int
    right_days: int
    right_provisional: bool = False


class WindowsetRegister(BaseModel):
    """NS3 windowset (windowset.register). Masks carry a REGISTERED CLOCK (SP-1.4)."""
    model_config = ConfigDict(extra="forbid")
    windowset_id: str                        # ws_<name>
    data_contract: str
    windows: list[Window]
    exclusions: list[dict] = Field(default_factory=list)   # [{range, rationale}]
    embargo: Embargo
    anchor_field: Literal["entry", "exit"]
    clock: str                               # e.g. "utc" (the pair CSV clock) | "gmt+2_us_dst"
    pooling_exclude_roles: list[WindowRole] = Field(default_factory=lambda: ["backward_only"])
    status: Literal["live", "historical"] = "live"


class WindowsetSupersede(BaseModel):
    """windowset.supersede — REQUIRES the spend-carryover map (REG-INV-15).

    The carryover is a barrier-checked ASSERTION derived from wiv lineage (rejected if
    inconsistent), never a second source of truth. It enumerates BOTH one-shot spends AND
    cumulative look-counts k.
    """
    model_config = ConfigDict(extra="forbid")
    old_windowset_id: str
    new_windowset_id: str
    new_windowset: WindowsetRegister
    carryover: list[dict]                    # [{wiv_id, spends: [...], k_cumulative: int}]
    rationale: str


class ScopeMint(BaseModel):
    """scope.mint — a fresh spend scope is a fresh shot; discretionary + velocity-capped."""
    model_config = ConfigDict(extra="forbid")
    scope_id: str
    windowset_id: str
    purpose: str


class SpendRecord(BaseModel):
    """Derived view row (projection) — kept as schema for the spend ledger export."""
    model_config = ConfigDict(extra="forbid")
    wiv_id: str
    scope_id: str
    readout_ref: str
    one_shot: bool = True
    reopen_of: Optional[str] = None
    purpose: Literal["readout", "postmortem", "rehearsal"] = "readout"
    slot_index: Optional[int] = None         # lineage-budget slot consumed (None for zero-look)
    k_cumulative: Optional[int] = None       # "look k of budget N" — k never resets
    budget_ref: Optional[str] = None         # the lineage-budget object version consumed against
