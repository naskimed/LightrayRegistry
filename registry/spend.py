"""The three-layer spend stack (all coexist; composition matters):

 (1) per-scope ONE-SHOT   — forward_certifier windows admit exactly one accepted readout per
                            scope EVER (generalizes TIERB_OPENED.flag);
 (2) RATE                 — readout_velocity + scope.mint velocity + the emission cap
                            (1 batch / lineage / month, resolved provisional);
 (3) LIFETIME             — the per-lineage look budget (REG-INV-24): counts accepted
                            non-postmortem readout batches across ALL scopes, enforced at
                            readout.request — SPEND-TIME, PRE-UNMASK. At zero: barrier-reject.

postmortem + rehearsal spend nothing; readout.void restores its slot; a placebo-passed
readout still consumes its slot (OQ-9). NO earn-back. Windows never retire.

Placebo classification (PB-1.2): L1 = strict > gate_ref ⇒ LOCAL consequence only (readout
cert-ineligible, slot consumed, NO alarm). L2 = exceed the EXTENDED null's maximum
(n_ext=999, readout-batch scale, exact rate 1/1000) OR the at-shot clause subset + aggregate
band ⇒ feeds the extended-SUSPEND alarm. Search-stage twins never reach here.
"""
from __future__ import annotations

from typing import Any, Optional

from .schemas.state import RegistryState

# Rejection codes owned by this module (merged into barrier.CODES)
WINDOWS_SPENT = "WINDOWS_SPENT"
LOOK_BUDGET_ZERO = "LOOK_BUDGET_ZERO"
EMISSION_CAP = "EMISSION_CAP"
VELOCITY_EXCEEDED = "VELOCITY_EXCEEDED"


def _lineage_of(state: RegistryState, windowset_id: str) -> str:
    ws = state.windowsets.get(windowset_id, {})
    return ws.get("lineage_id", windowset_id)


def can_spend(state: RegistryState, readout_payload: dict, month: Optional[str] = None,
              check_only: bool = False) -> tuple[bool, Optional[str], Optional[str]]:
    """The composite spend check for a readout.request payload. Returns (ok, code, why).

    Zero-look classes (purpose in {postmortem, rehearsal}) skip (1) partially and (3)
    entirely: a postmortem may cite spent windows (that is its LEGALITY class) but must
    never be able to spend a fresh one.
    """
    purpose = readout_payload.get("purpose", "readout")
    windowset_id = readout_payload["windowset_id"]
    scope_id = readout_payload["scope_id"]
    lineage = _lineage_of(state, windowset_id)
    lin = state.lineages.get(lineage, {})

    if purpose in ("postmortem", "rehearsal"):
        return True, None, None  # spend nothing; REG-INV-21 identity checks happen in barrier

    # (1) one-shot per (wiv, scope) on forward_certifier windows
    ws = state.windowsets.get(windowset_id, {})
    one_shot_map: dict[str, Any] = lin.get("one_shot_map", {})
    for w in ws.get("windows", []):
        if w.get("role") == "forward_certifier":
            key = f"{w['wiv_id']}::{scope_id}"
            if key in one_shot_map:
                return False, WINDOWS_SPENT, f"one-shot already spent: {key}"

    # (2) rate — emission cap: 1 readout batch per lineage per calendar month (provisional).
    # month is derived from the draft's ts by the barrier (NOT from the payload — the schema
    # forbids extra fields); None (e.g. predicate pre-check) skips the cap here, the barrier
    # re-checks at request time.
    if month and month in set(lin.get("emission_months", [])):
        return False, EMISSION_CAP, f"emission cap: lineage {lineage} already read out in {month}"
    # readout_velocity (autonomy constants) — value cited from the constants doc when registered
    velocity = _constant(state, "autonomy_constants", "readout_velocity")
    if velocity is not None and lin.get("readouts_in_window", 0) >= velocity:
        return False, VELOCITY_EXCEEDED, "readout_velocity cap reached"

    # (3) lifetime — the look budget, pre-unmask
    budget = lin.get("budget")
    if budget is None:
        return False, LOOK_BUDGET_ZERO, f"no look-budget object registered for lineage {lineage}"
    if budget.get("remaining", 0) <= 0:
        return False, LOOK_BUDGET_ZERO, "look budget exhausted (renewal = calendar re-anchor or human amend)"

    return True, None, None


def _constant(state: RegistryState, series: str, key: str):
    doc = state.constants.get(series)
    if not doc:
        return None
    for e in doc.get("entries", []):
        if e.get("key") == key and not e.get("unknown"):
            return e.get("value")
    return None


# ---- placebo classification (readout-batch ONLY — PB-1.2 input scope) ----------------------
def classify_placebo(placebo_result: dict) -> str:
    """none | L1 | L2 from a readout.record's placebo_result. The engine supplies max_z,
    gate_ref, extended_max (max of the n_ext=999 CRN null), and optionally the at-shot
    clause-subset verdict. Exactness rests on the exchangeability pin (circular-shift
    destruction, fresh registered seed) — if the destruction mechanism ever changes, the
    recipe must re-derive its rates (a registered decision, not an edit)."""
    if not placebo_result:
        return "none"
    max_z = placebo_result.get("max_z")
    gate_ref = placebo_result.get("gate_ref")
    extended_max = placebo_result.get("extended_max")
    at_shot_clause_pass = placebo_result.get("at_shot_clause_pass", False)

    if max_z is None or gate_ref is None:
        return "none"
    if (extended_max is not None and max_z > extended_max) or at_shot_clause_pass:
        return "L2"
    if max_z > gate_ref:  # STRICT > (TS-1.1)
        return "L1"
    return "none"
