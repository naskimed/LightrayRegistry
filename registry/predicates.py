"""Named + versioned predicate functions (V-class). NO string DSL, NO eval — conditionals and
gates cite predicates by (name, version); version drift ⇒ the citing conditional is STALE.

Predicate signature: fn(state, params) -> bool. Pure reads of RegistryState only.
"""
from __future__ import annotations

from typing import Any, Callable

from .schemas.state import RegistryState

PredicateFn = Callable[[RegistryState, dict], bool]

# name -> (version, fn). Bump the version on ANY semantic change — armed conditionals pinned
# to the old version go stale and require human re-arm (never fire on drifted semantics).
PREDICATES: dict[str, tuple[str, PredicateFn]] = {}


def predicate(name: str, version: str):
    def deco(fn: PredicateFn) -> PredicateFn:
        PREDICATES[name] = (version, fn)
        return fn
    return deco


def deployed_version(name: str) -> str | None:
    entry = PREDICATES.get(name)
    return entry[0] if entry else None


def evaluate(name: str, pinned_version: str, state: RegistryState, params: dict) -> tuple[bool, bool]:
    """Returns (fired, stale). stale=True ⇒ never fire (human re-arm required)."""
    entry = PREDICATES.get(name)
    if entry is None or entry[0] != pinned_version:
        return False, True
    version, fn = entry
    return bool(fn(state, params)), False


# ---- the seed predicate set ---------------------------------------------------------------

@predicate("budget_floor_alarm", "1")
def _budget_floor_alarm(state: RegistryState, params: dict) -> bool:
    """Fires when slots_remaining <= alarm_remaining (floors in slots-REMAINING; comparator
    per review-5). Consequence (in the conditional's event body): daily digest entry."""
    lin = state.lineages.get(params["lineage_id"], {})
    budget = lin.get("budget", {})
    remaining = budget.get("remaining")
    alarm = budget.get("alarm_remaining")
    return remaining is not None and alarm is not None and remaining <= alarm


@predicate("extended_suspend_alarm", "1")
def _extended_suspend_alarm(state: RegistryState, params: dict) -> bool:
    """PLAN v10 §2b (b): placebo L2 single · >=3 L1s in 12 batches · any readout.void ·
    contested readout · letter-green cert failing its post-hoc forensic ⇒ SUSPEND the
    readout-conditional channel. INPUT SCOPE (PB-1.2): READOUT-BATCH placebo results ONLY —
    search-stage twins are scorecard telemetry and never reach this predicate.
    Read-audit violations are deliberately ABSENT (they keep the decision-7 chain)."""
    lineage_id = params["lineage_id"]
    marks = state.placebo_history.get(lineage_id, [])
    if any(m.get("classification") == "L2" for m in marks):
        return True
    # 3-in-12: rolling over the lineage's accepted-batch sequence BY K, cross-generation;
    # voided readouts contribute nothing (their numbers never existed).
    live = [m for m in marks if not m.get("voided")]
    window = live[-12:]
    if sum(1 for m in window if m.get("classification") == "L1") >= 3:
        return True
    lin = state.lineages.get(lineage_id, {})
    if lin.get("any_readout_void") or lin.get("contested_readout") or lin.get("cert_forensic_fail"):
        return True
    return False


@predicate("readout_battery_green", "1")
def _readout_battery_green(state: RegistryState, params: dict) -> bool:
    """The per-batch readout-firing predicate (NS12 kind i): the NAMED batch's REG-INV-23
    battery green + look budget > 0 + STAT-INV-09 emission cap respected. The barrier
    re-checks all of it at readout.request time anyway — this just decides WHEN to fire."""
    from .spend import can_spend  # local import to avoid cycle
    req = params["readout_request"]           # the fully-formed event body's payload
    ok, _code, _why = can_spend(state, req, check_only=True)
    return ok


@predicate("shadow_qualification", "1")
def _shadow_qualification(state: RegistryState, params: dict) -> bool:
    """Shadow re-entry (PLAN §5/§9, amended): Spearman >= 0.10 vs Stage-4 scorecard outcomes
    in >= 3 of 4 consecutive epochs; certified-yield-per-slot non-inferior (>= 0) over the
    span. Inputs are telemetry rows the scheduler maintains in state.rules['shadow_skill']."""
    skill = state.rules.get("shadow_skill", {})
    epochs = skill.get("epochs", [])[-4:]
    if len(epochs) < 4:
        return False
    hits = sum(1 for e in epochs if e.get("spearman_margin", 0.0) >= 0.10)
    yield_ok = all(e.get("yield_delta_per_slot", 0.0) >= 0.0 for e in epochs)
    return hits >= 3 and yield_ok


@predicate("g2_and_alignment_green", "1")
def _g2_and_alignment_green(state: RegistryState, params: dict) -> bool:
    """The embargo-supersession arming predicate (SEED_PACK §2): G2 five-feature parity stamp
    green AND the txt↔csv hour-alignment stamp green (measured 2026-07-07; the formal stamps
    import at M3 as artifact.stamp events)."""
    need = {("parity", params.get("g2_artifact")), ("counts", params.get("alignment_artifact"))}
    for kind, art in need:
        if not art:
            return False
        a = state.artifacts.get(art, {})
        stamps = a.get("stamps", [])
        if not any(s.get("stamp_kind") in (kind, "verified") and s.get("passed") for s in stamps):
            return False
    return True


@predicate("cert_gate_green", "1")
def _cert_gate_green(state: RegistryState, params: dict) -> bool:
    """REG-INV-09: the FULL frozen five-clause gate, clause-granular, 5/5 measured_pass (or
    pre_authorized where the ledger records it) — the scheduler materializes cert.certify."""
    stamps = state.clause_stamps.get(params["candidate_id"], {})
    clauses = ["w4_per_blob", "regime_consistency", "degradation", "persistence", "seed_survival"]
    return all(stamps.get(c) in ("measured_pass", "pre_authorized") for c in clauses)
