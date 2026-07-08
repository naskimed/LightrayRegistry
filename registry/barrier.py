"""The write barrier — pure decide(state, draft) → Decision (TECH_SPEC §3.2/§4/§8).

Purity (REG-INV-19): decide() reads ONLY (state, draft). All physical hashes were computed by
the impure ingest stage and injected into the payload (computed_*); decide() compares
declared-vs-computed values already inside the event. Identical verdicts across calls,
restarts, and replay.

EVALUATION ORDER (prevents bricking the brake — TECH_SPEC §3.2, TS-2.0 §5.5.1):
  1. schema (S)                — payload validates against its model
  2. CONDITIONAL-FIRE          — a scheduler event citing a live, human-authored, non-disarmed,
                                 non-stale arming event is legal REGARDLESS of per-type ⛔;
                                 integrity checks (spend, hashes) still run.
  3. actor LAW                 — REG-INV-22 (apparatus, human-only categorically) and
                                 REG-INV-25 (scheduler two-class authority). Code, not config.
  4. actor ALLOWLIST           — the seeded B/O matrix content (autonomy-constants; DATA).
  5. STAT-INV-02               — cycle closure (discretionary rejected while a cycle is open);
                                 carve-out: fired conditionals (step 2) and human apparatus /
                                 kill-class events are never cycle-rejected.
  6. per-type checks           — the REG-INV / STAT-INV catalog.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .schemas.envelope import (
    ACTOR_BOUNDARY, ACTOR_HUMAN, ACTOR_OPERATOR, ACTOR_SCHEDULER, ACTOR_SHADOW,
    AGENT_ACTORS, LOOP_ACTORS, EventDraft,
)
from .schemas.payload_registry import validate_payload
from .schemas.state import RegistryState
from .canon import sha256_canon
from . import predicates, spend

# ---- rejection codes (TECH_SPEC §4, enumerated; TS-2.0 additions included) ------------------
CODES = [
    "SCHEMA_INVALID", "REF_UNRESOLVED", "FROZEN_MUTATION", "ORDER_VIOLATION",
    "RESULT_BEFORE_FREEZE", "BUDGET_EXCEEDED", "WINDOWS_SPENT", "NO_COUNTS_STAMP",
    "NO_HYPOTHESIS", "POST_HOC_HYPOTHESIS", "DUPLICATE_KEY", "SEED_DEDUP",
    "WRONG_PARAM_FAMILY", "CRN_MISMATCH", "HASH_MISMATCH", "PC_ECHO_MISMATCH", "GIT_DIRTY",
    "PREDICATE_RED", "ACTOR_FORBIDDEN", "NO_REHEARSAL", "SEEDS_UNDECLARED",
    "LOOK_BUDGET_ZERO", "QUOTABLE_ONLY_INPUT", "POSTMORTEM_IDENTITY_FAIL",
    "POSTMORTEM_BEFORE_SPEND", "CARRYOVER_MISSING", "CONDITIONAL_STALE", "DUST_PROMOTION",
    # TS-2.0
    "SCORECARD_CONFLICT", "RECOMPUTE_ON_CACHED", "CYCLE_OPEN_DISCRETIONARY",
    "COVERAGE_DEFICIT", "EMISSION_CAP",
    # implementation-surfaced (to fold into the spec table at next TS bump)
    "KILLED_AXIS", "VELOCITY_EXCEEDED", "CHANNEL_SUSPENDED",
]


@dataclass
class Decision:
    accepted: bool
    code: Optional[str] = None
    reason: Optional[str] = None
    dedup_noop: bool = False        # duplicate-identical scorecard: accept as no-op (STAT-INV-03)
    fired_conditional: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _reject(code: str, reason: str) -> Decision:
    return Decision(accepted=False, code=code, reason=reason)


# ---- apparatus law (REG-INV-22 — single source; the matrix must agree, never the reverse) ----
APPARATUS_EVENTS = frozenset({
    "constants.register", "constants.amend",
    "windowset.register", "windowset.supersede",
    "readout.void", "cert.revoke",
    "conditional.arm", "conditional.disarm",
})

# REG-INV-25 mechanical-materialization list (incl. the TS-2.0 fourth extension, signed Q1)
SCHEDULER_MECHANICAL = frozenset({
    "replay.verified", "artifact.integrity_checked", "cert.certify", "cert.displace",
    "card.emit", "cycle.open", "cycle.close", "stage.dispatch", "scorecard.emit",
})

# Seeded allowlists — the B/O (and loop) matrix columns. DATA: the autonomy-constants doc
# overrides these once registered (changing agent powers is a constants.amend, not a code edit).
SEEDED_ALLOWLIST: dict[str, frozenset] = {
    ACTOR_HUMAN: frozenset(),  # empty = everything not law-forbidden (scheduler-only types checked below)
    ACTOR_BOUNDARY: frozenset({
        "dataset.register", "feature.register", "feature.status_change", "featureset.freeze",
        "family.register", "family.activate",
        "block.register", "block.freeze", "block.supersede", "block.kill_axis", "block.close",
        "scope.mint", "rules.propose", "note.record",
    }),
    ACTOR_SHADOW: frozenset({"shadow_ranking"}),
    ACTOR_OPERATOR: frozenset({"artifact.register", "artifact.stamp", "artifact.attest_missing",
                               "note.record"}),
    "loop": frozenset({
        "trials.open_batch", "trials.record", "trials.close_batch",
        "artifact.register", "artifact.stamp", "dataset.register",
        "readout.record", "cert.clause_stamp", "note.record",
    }),
}
# scheduler-mechanical events (incl. cert.certify/displace) are human-forbidden UNLESS imported —
# the M3 historical certify imports via imported:true; live human certs are scheduled-channel only.
HUMAN_FORBIDDEN = SCHEDULER_MECHANICAL | frozenset({"queue_reorder"})


def decide(state: RegistryState, draft: EventDraft) -> Decision:
    # ---- 0. idempotency ----------------------------------------------------------------
    if draft.event_id in state.dedup:
        return Decision(accepted=True, dedup_noop=True, reason="event_id already applied")

    # ---- 1. schema (S-class) ------------------------------------------------------------
    try:
        payload = validate_payload(draft.type, draft.payload)
    except Exception as e:
        return _reject("SCHEMA_INVALID", f"{draft.type}: {e}")

    # ---- 2. conditional-fire FIRST -------------------------------------------------------
    fired_cond = None
    if draft.actor == ACTOR_SCHEDULER:
        fired_cond = _match_fired_conditional(state, draft, payload)
        if isinstance(fired_cond, Decision):        # stale/dead arming → explicit reject
            return fired_cond

    # ---- 3. actor LAW ---------------------------------------------------------------------
    if fired_cond is None:
        law = _actor_law(state, draft)
        if law is not None:
            return law
        # ---- 4. actor ALLOWLIST ------------------------------------------------------------
        allow = _allowlist(state, draft)
        if allow is not None:
            return allow

    # ---- 5. STAT-INV-02 cycle closure (with the brake carve-out) --------------------------
    if (state.open_cycle and draft.provenance == "discretionary"
            and fired_cond is None
            and not (draft.actor == ACTOR_HUMAN and (draft.type in APPARATUS_EVENTS
                                                     or draft.type == "readout.void"))):
        return _reject("CYCLE_OPEN_DISCRETIONARY",
                       f"cycle {state.open_cycle} is open; boundary works between cycles "
                       "(STAT-INV-02; conditional-fired + human apparatus events are exempt)")

    # ---- 5b. provenance (P-class, REG-INV-05) ---------------------------------------------
    if draft.provenance == "discretionary" and not draft.imported:
        if not (draft.hypothesis and draft.reasoning and draft.expected_outcome):
            return _reject("NO_HYPOTHESIS",
                           "discretionary events REQUIRE hypothesis + reasoning + expected_outcome")

    # ---- 6. per-type checks ----------------------------------------------------------------
    handler = _HANDLERS.get(draft.type)
    if handler:
        d = handler(state, draft, payload)
        if d is not None:
            return d

    return Decision(accepted=True, fired_conditional=fired_cond)


# ============================== layers 2–4 ====================================================
def _match_fired_conditional(state: RegistryState, draft: EventDraft, payload: dict):
    """A scheduler emission citing a LIVE human arming whose event_body matches → legal.
    Returns cond_id, or a Decision (explicit stale reject), or None (not a conditional fire)."""
    for cite in draft.cites:
        cond = state.conditionals.get(cite)
        if not cond:
            continue
        if cond.get("status") != "armed":
            return _reject("ORDER_VIOLATION", f"conditional {cite} is {cond.get('status')}")
        pred = cond.get("predicate", {})
        if predicates.deployed_version(pred.get("name", "")) != pred.get("version"):
            return _reject("CONDITIONAL_STALE",
                           f"conditional {cite}: deployed predicate version drifted from the "
                           "pinned one — human re-arm required (never fire on drifted semantics)")
        body = cond.get("event_body", {})
        try:
            body_norm = validate_payload(body.get("type", ""), body.get("payload", {}))
        except Exception:
            body_norm = body.get("payload", {})
        if body.get("type") != draft.type or sha256_canon(body_norm) != sha256_canon(payload):
            return _reject("ORDER_VIOLATION",
                           f"conditional {cite}: emitted body does not match the armed body")
        if draft.type == "readout.request" and state.suspensions.get("readout_conditional_channel"):
            return _reject("CHANNEL_SUSPENDED",
                           "readout-conditional channel is SUSPENDED pending human review "
                           "(extended-SUSPEND alarm; re-arm is human-only, REG-INV-22)")
        return cite
    return None


def _actor_law(state: RegistryState, draft: EventDraft) -> Optional[Decision]:
    t, a = draft.type, draft.actor
    if a in AGENT_ACTORS or a in LOOP_ACTORS:
        if t in APPARATUS_EVENTS:
            return _reject("ACTOR_FORBIDDEN",
                           f"REG-INV-22: {t} is measurement apparatus — human-only categorically "
                           "(the brake is not editable by the braked)")
        if t in SCHEDULER_MECHANICAL:
            return _reject("ACTOR_FORBIDDEN", f"{t} is scheduler-mechanical (REG-INV-25)")
        if t == "queue_reorder":
            return _reject("ACTOR_FORBIDDEN",
                           "queue_reorder is legal ONLY as a fired conditional citing human "
                           "arming + shadow qualification (STAT-INV-07/13)")
        if t == "readout.request":
            return _reject("ACTOR_FORBIDDEN",
                           "the v9 agent readout grant is RETIRED (v10 §2 SIGNED); readouts fire "
                           "via per-batch human-armed conditionals; H-direct = degraded mode")
    if a == ACTOR_SCHEDULER and draft.type not in SCHEDULER_MECHANICAL:
        return _reject("ACTOR_FORBIDDEN",
                       f"REG-INV-25: scheduler may emit only the mechanical list or fired "
                       f"conditionals — {draft.type} is neither")
    if a == ACTOR_HUMAN and draft.type in HUMAN_FORBIDDEN and not draft.imported:
        return _reject("ACTOR_FORBIDDEN", f"{draft.type} is scheduler-materialized "
                       "(imported historical acts are exempt via imported:true)")
    return None


def _allowlist(state: RegistryState, draft: EventDraft) -> Optional[Decision]:
    a = draft.actor
    key = "loop" if a in LOOP_ACTORS else a
    seeded = SEEDED_ALLOWLIST.get(key)
    if seeded is None or not seeded:      # human: no allowlist beyond law
        return None
    doc = state.constants.get("autonomy_constants")
    if doc:
        for e in doc.get("entries", []):
            if e.get("key") == f"allowlist:{key}" and isinstance(e.get("value"), list):
                seeded = frozenset(e["value"])   # registered content overrides the seed
                break
    if draft.type not in seeded:
        return _reject("ACTOR_FORBIDDEN",
                       f"{a} may not emit {draft.type} (autonomy-constants allowlist)")
    return None


# ============================== per-type handlers =============================================
def _h_dataset_register(state, draft, p):
    existing = state.snapshots.get(p["snapshot_id"])
    if existing and existing.get("raw_sha256") != p["raw_sha256"]:
        return _reject("FROZEN_MUTATION",
                       "REG-INV-14: same snapshot name, different hash — register a NEW version")
    return _hash_check(p)


def _h_featureset_freeze(state, draft, p):
    if p["featureset_id"] in state.featuresets:
        return _reject("FROZEN_MUTATION", "featureset already frozen — immutable (supersede only)")
    for f in p["columns"]:
        if f not in state.features:
            return _reject("REF_UNRESOLVED", f"feature {f} not registered")
    return None


def _h_block_register(state, draft, p):
    if p["featureset_hash"] not in state.featuresets:
        return _reject("REF_UNRESOLVED",
                       f"REG-INV-08: featureset {p['featureset_hash']} unknown/unfrozen")
    if p["family_id"] not in state.families:
        return _reject("REF_UNRESOLVED", f"family {p['family_id']} not registered")
    pop = state.populations.get(p.get("population_ref") or "")
    if pop and pop.get("status") == "quotable_only":
        return _reject("QUOTABLE_ONLY_INPUT",
                       "REG-INV-18: quotable-only artifacts are rejected as computational inputs")
    if pop and "mutation_audit" in p.get("gates_required", []):
        if not pop.get("mutation_audit_pass") and pop.get("causality_class") != "legacy_attested":
            return _reject("PREDICATE_RED",
                           "REG-INV-20: population lacks a passing mutation-audit stamp")
    for arm in p["arms"]:
        if arm.get("budget", 0) <= 0:
            return _reject("BUDGET_EXCEEDED", f"arm {arm['arm_id']}: budgets required for EVERY arm")
    for k in state.kill_list:
        if k.get("axis") and k["axis"] in (p.get("family_id"), *(p.get("axes", []) or [])):
            return _reject("KILLED_AXIS",
                           f"axis {k['axis']} was killed ({k.get('rationale','')}) — spent "
                           "hypotheses are never retried (cite the kill-check)")
    return None


def _h_block_freeze(state, draft, p):
    blk = state.blocks.get(p["block_id"])
    if not blk:
        return _reject("REF_UNRESOLVED", f"block {p['block_id']} not registered")
    if blk.get("frozen"):
        return _reject("FROZEN_MUTATION", "REG-INV-01: frozen blocks are immutable")
    # REG-INV-16 by chain position: no masked/OOS-scope results for this block may precede
    # the freeze; IS trial records are EXEMPT (they are the deflation input).
    for r in state.readouts.values():
        if r.get("block_id") == p["block_id"]:
            return _reject("RESULT_BEFORE_FREEZE",
                           "REG-INV-16: masked results exist before freeze (chain position)")
    return None


def _h_trials_open(state, draft, p):
    blk = state.blocks.get(p["block_id"])
    if not blk:
        return _reject("REF_UNRESOLVED", f"block {p['block_id']} not registered")
    if not blk.get("frozen"):
        return _reject("ORDER_VIOLATION", "trials require a FROZEN block")
    remaining = blk.get("budget_remaining")
    if remaining is not None and p["n_planned"] > remaining:
        return _reject("BUDGET_EXCEEDED",
                       f"open_batch reserves budget BEFORE compute: {p['n_planned']} > {remaining}")
    return None


def _h_trials_record(state, draft, p):
    batch = state.trials_batches.get(p["batch_id"])
    if not batch or batch.get("closed"):
        return _reject("ORDER_VIOLATION", "no open batch for this record")
    if p["n_distinct_keys"] != p["n_rows"]:
        return _reject("DUPLICATE_KEY",
                       "KEY≠seed doctrine: declared distinct-KEY count must equal row count "
                       "(seed-based dedup ⇒ SEED_DEDUP upstream)")
    blk = state.blocks.get(p["block_id"], {})
    frozen_null = (blk.get("null_spec") or {}).get("shift_vector_sha256")
    if frozen_null and p.get("null_spec_hash") and p["null_spec_hash"] != frozen_null:
        return _reject("CRN_MISMATCH",
                       "REG-INV-07: manifest null spec ≠ the block's frozen CRN spec "
                       "(shared shift vectors are the max-null's validity)")
    git = (p.get("engine_stamp") or {}).get("git", "")
    if not git or git in ("nogit", "dirty") or git.endswith("-dirty"):
        return _reject("GIT_DIRTY", "REG-INV-13: scored results require a clean engine git stamp")
    if p.get("pc_echo") is not None:
        pc_doc = state.constants.get("pc") or {}
        expected = pc_doc.get("pc_echo_hash")   # registered as the hash of the canonical PC dict
        if expected and sha256_canon(p["pc_echo"]) != expected:
            return _reject("PC_ECHO_MISMATCH",
                           "the PC struct threaded through the computation ≠ registered pc_echo_hash "
                           "(the drift class the registry exists to kill)")
    return None


def _h_artifact_register(state, draft, p):
    if draft.actor == ACTOR_SCHEDULER and p.get("role") != "session_capture":
        return _reject("ACTOR_FORBIDDEN",
                       "scheduler may register artifacts with role: session_capture ONLY")
    return _hash_check(p, declared="declared_sha256", computed="computed_sha256")


def _h_windowset_supersede(state, draft, p):
    old = state.windowsets.get(p["old_windowset_id"])
    if not old:
        return _reject("REF_UNRESOLVED", f"windowset {p['old_windowset_id']} unknown")
    old_wivs = {w["wiv_id"] for w in old.get("windows", [])}
    carried = {c["wiv_id"] for c in p.get("carryover", [])}
    spent = {w for w in old_wivs
             if state.windows.get(w, {}).get("spends")}
    missing = spent - carried
    if missing:
        return _reject("CARRYOVER_MISSING",
                       f"REG-INV-15: supersession must carry spends AND cumulative k for {sorted(missing)} "
                       "(amending a windowset must never resurrect spent windows)")
    return None


def _h_scope_mint(state, draft, p):
    if p["windowset_id"] not in state.windowsets:
        return _reject("REF_UNRESOLVED", f"windowset {p['windowset_id']} unknown")
    return None  # velocity cap enforced via autonomy constants at scheduler dispatch


def _h_readout_request(state, draft, p):
    if p["block_id"] not in state.blocks:
        return _reject("REF_UNRESOLVED", f"block {p['block_id']} unknown")
    blk = state.blocks[p["block_id"]]
    if not blk.get("frozen"):
        return _reject("ORDER_VIOLATION", "readout requires a FROZEN block")
    purpose = p.get("purpose", "readout")

    if purpose == "postmortem":
        # REG-INV-21 (other direction): postmortem-class BEFORE the spend exists is rejected
        lineage = state.windowsets.get(p["windowset_id"], {}).get("lineage_id", p["windowset_id"])
        lin = state.lineages.get(lineage, {})
        if not lin.get("one_shot_map"):
            return _reject("POSTMORTEM_BEFORE_SPEND",
                           "REG-INV-21: postmortem-class events before the spend exists are rejected")
    if purpose == "readout":
        # REG-INV-23 battery
        if not p.get("rehearsal_artifact_ref"):
            return _reject("NO_REHEARSAL",
                           "REG-INV-23: a rehearsal artifact (end-to-end on TRAIN, emits nothing "
                           "per the registered silent_v1 spec) is required before unmask")
        for arm in blk.get("arms", []):
            if arm.get("role") == "real" and not arm.get("seeds_declared"):
                return _reject("SEEDS_UNDECLARED",
                               f"REG-INV-23: stochastic arm {arm.get('arm_id')} declares no seeds "
                               "(the S3-unseeded lesson, moved PRE-shot)")
        # counts-stamp for the EXACT (windowset, population) pair
        stamp = state.artifacts.get(p.get("counts_stamp_ref", ""), {})
        pair_ok = any(
            s.get("stamp_kind") == "counts" and s.get("passed")
            and s.get("detail", {}).get("windowset_id") == p["windowset_id"]
            and s.get("detail", {}).get("population_ref") == p["population_ref"]
            for s in stamp.get("stamps", []))
        if not pair_ok:
            return _reject("NO_COUNTS_STAMP",
                           "REG-INV-03: no counts-stamp for this exact (windowset, population) "
                           "pair (the W1-empty lesson made mechanical)")
    month = draft.ts.strftime("%Y-%m") if draft.ts else None
    ok, code, why = spend.can_spend(state, p, month=month)
    if not ok:
        return _reject(code, why)
    return None


def _h_readout_record(state, draft, p):
    req = state.readouts.get(p["readout_id"])
    if not req or req.get("recorded"):
        return _reject("ORDER_VIOLATION", "readout.record must match exactly one open request")
    if not p.get("info_rows_present"):
        return _reject("PREDICATE_RED", "REG-INV-17: info rows (dust) are mandatory in readouts")
    return None


def _h_readout_void(state, draft, p):
    r = state.readouts.get(p["readout_id"])
    if not r:
        return _reject("REF_UNRESOLVED", f"readout {p['readout_id']} unknown")
    if r.get("voided"):
        return _reject("ORDER_VIOLATION", "readout already voided (no double-restore of the slot)")
    ev = p.get("evidence", {})
    if not ev.get("unmask_artifact_absent"):
        return _reject("PREDICATE_RED",
                       "void is legal only with no-interim-emission evidence "
                       "(absent unmask artifact + engine log + note); any partial emission ⇒ spent")
    return None


def _h_cert_clause_stamp(state, draft, p):
    if state.readouts and _candidate_is_dust(state, p["candidate_id"]):
        return _reject("DUST_PROMOTION", "REG-INV-11: dust is never promotable — categorical")
    return None


def _h_cert_certify(state, draft, p):
    if draft.imported:
        return None  # historical certify imports as what it was (discretionary human act)
    if _candidate_is_dust(state, p["candidate_id"]):
        return _reject("DUST_PROMOTION", "REG-INV-11: dust is never promotable")
    ok, _ = predicates.evaluate("cert_gate_green", "1", state, {"candidate_id": p["candidate_id"]})
    if not ok:
        return _reject("PREDICATE_RED",
                       "REG-INV-09: certification requires the FULL frozen gate green, "
                       "clause-granular (5/5)")
    return None


def _h_cert_displace(state, draft, p):
    if draft.imported:
        return None
    ok, _ = predicates.evaluate("cert_gate_green", "1", state, {"candidate_id": p["new_incumbent"]})
    if not ok:
        return _reject("PREDICATE_RED", "REG-INV-09: displacement only on gate-green")
    return None


def _h_conditional_arm(state, draft, p):
    pred = p["predicate"]
    if predicates.deployed_version(pred["name"]) is None:
        return _reject("REF_UNRESOLVED", f"predicate {pred['name']} not deployed")
    if predicates.deployed_version(pred["name"]) != pred["version"]:
        return _reject("CONDITIONAL_STALE",
                       "pinned predicate version ≠ deployed — arm against the deployed version")
    body = p.get("event_body", {})
    try:
        validate_payload(body["type"], body.get("payload", {}))
    except Exception as e:
        return _reject("SCHEMA_INVALID", f"armed event body invalid: {e}")
    return None


def _h_scorecard_emit(state, draft, p):
    sc = p["scorecard"]
    key_hash = sha256_canon(sc["eval_key"])
    existing = state.scorecards.get(key_hash)
    if existing:
        if existing.get("payload_sha256") == sc.get("payload_sha256"):
            return Decision(accepted=True, dedup_noop=True,
                            reason="STAT-INV-03: duplicate identical scorecard — dedup, never fork")
        return _reject("SCORECARD_CONFLICT",
                       "same eval_key, different bytes — determinism violation (STAT-INV-01/03); "
                       "loud, never a fork")
    return None


def _h_stage_dispatch(state, draft, p):
    ek = (p.get("inputs") or {}).get("eval_key")
    if ek:
        key_hash = sha256_canon(ek)
        if key_hash in state.scorecards:
            return _reject("RECOMPUTE_ON_CACHED",
                           "STAT-INV-04: re-admission consumes cache, never recomputes")
    if not state.open_cycle or state.open_cycle != p.get("cycle_id"):
        return _reject("ORDER_VIOLATION", "stage.dispatch requires ITS cycle to be open")
    return None


def _h_cycle_open(state, draft, p):
    if state.open_cycle:
        return _reject("ORDER_VIOLATION", f"cycle {state.open_cycle} is already open")
    return None


def _h_cycle_close(state, draft, p):
    if state.open_cycle != p["cycle_id"]:
        return _reject("ORDER_VIOLATION", "no such open cycle")
    cyc = state.cycles.get(p["cycle_id"], {})
    valid = set(cyc.get("stage0_valid", []))
    covered = {state.scorecards[k]["eval_key"]["config_key"]
               for k in cyc.get("stage1_scorecards", []) if k in state.scorecards}
    deficit = sorted(valid - covered)
    if deficit:
        return _reject("COVERAGE_DEFICIT",
                       f"STAT-INV-08: {len(deficit)} Stage-0-valid registered configs lack "
                       f"Stage-1 scorecards (first 10: {deficit[:10]}) — the cycle cannot close")
    return None


def _h_rules_adopt(state, draft, p):
    if draft.actor != ACTOR_SCHEDULER:
        return _reject("ACTOR_FORBIDDEN",
                       "STAT-INV-10: rules.adopt only via scheduler materialization of a green "
                       "probation predicate")
    return None


def _h_constants_amend(state, draft, p):
    doc = state.constants.get(p["series"])
    if doc and doc.get("doc_id") != p["old_doc_id"]:
        return _reject("ORDER_VIOLATION",
                       f"amend must link the LIVE doc ({doc.get('doc_id')}), got {p['old_doc_id']}")
    return None


def _hash_check(p: dict, declared: str = "raw_sha256", computed: str = "computed_raw_sha256"):
    d, c = p.get(declared), p.get(computed)
    if d and c and d != c:
        return _reject("HASH_MISMATCH", f"declared {declared} ≠ ingest-computed value (H-class)")
    return None


def _candidate_is_dust(state: RegistryState, candidate_id: str) -> bool:
    for r in state.readouts.values():
        if candidate_id in (r.get("dust_candidates") or []):
            return True
    return False


_HANDLERS = {
    "dataset.register": _h_dataset_register,
    "featureset.freeze": _h_featureset_freeze,
    "block.register": _h_block_register,
    "block.freeze": _h_block_freeze,
    "trials.open_batch": _h_trials_open,
    "trials.record": _h_trials_record,
    "artifact.register": _h_artifact_register,
    "windowset.supersede": _h_windowset_supersede,
    "scope.mint": _h_scope_mint,
    "readout.request": _h_readout_request,
    "readout.record": _h_readout_record,
    "readout.void": _h_readout_void,
    "cert.clause_stamp": _h_cert_clause_stamp,
    "cert.certify": _h_cert_certify,
    "cert.displace": _h_cert_displace,
    "conditional.arm": _h_conditional_arm,
    "scorecard.emit": _h_scorecard_emit,
    "stage.dispatch": _h_stage_dispatch,
    "cycle.open": _h_cycle_open,
    "cycle.close": _h_cycle_close,
    "rules.adopt": _h_rules_adopt,
    "constants.amend": _h_constants_amend,
}
