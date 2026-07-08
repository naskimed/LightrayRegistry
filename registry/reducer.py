"""Pure reducer: fold(state, event) → state (TECH_SPEC §4).

REPLAY APPLIES REDUCERS ONLY, NEVER BARRIERS — barrier validity is an append-time property.
Reducers must therefore accept every event that is IN the log, unconditionally, and must be
deterministic (REG-INV-19: double replay ⇒ identical state hash).

REDUCER_VERSION is stamped on events at append; bump it on ANY semantic change here (a reducer
edit must never retroactively "invalidate" history — versioning is what keeps old logs replayable
through upcasters).
"""
from __future__ import annotations

from .canon import sha256_canon
from .schemas.envelope import Event
from .schemas.state import RegistryState
from .spend import classify_placebo

REDUCER_VERSION = "1"


def fold(state: RegistryState, ev: Event) -> RegistryState:
    """Mutates-in-place for speed; the daemon treats state as owned by the writer thread.
    Cold replay builds a fresh state, so purity is over (log) → state, which is what matters."""
    if ev.event_id in state.dedup:
        return state  # idempotent replay/resubmit (REG-INV-04)
    p = ev.payload
    t = ev.type

    if t == "dataset.register":
        state.snapshots[p["snapshot_id"]] = {**p, "seq": ev.seq}

    elif t == "feature.register":
        state.features[p["feature_id"]] = {**p, "seq": ev.seq}
    elif t == "feature.status_change":
        f = state.features.setdefault(p["feature_id"], {})
        f["status"] = p["to_status"]
        if p.get("swap_out"):
            state.features.setdefault(p["swap_out"], {})["status"] = "extended"
    elif t == "featureset.freeze":
        state.featuresets[p["featureset_id"]] = {**p, "seq": ev.seq}
    elif t == "family.register":
        state.families[p["family_id"]] = {**p, "seq": ev.seq}
    elif t == "family.activate":
        state.families.setdefault(p["family_id"], {})["status"] = "active"

    elif t == "block.register":
        state.blocks[p["block_id"]] = {
            **p, "seq": ev.seq, "frozen": False,
            "budget_remaining": sum(a.get("budget", 0) for a in p.get("arms", [])),
        }
    elif t == "block.freeze":
        b = state.blocks.setdefault(p["block_id"], {})
        b["frozen"] = True
        b["declared_width"] = p.get("declared_width")
        b["grid_digest"] = p.get("grid_digest")
    elif t == "block.supersede":
        state.blocks.setdefault(p["old_block_id"], {})["superseded_by"] = p["new_block_id"]
    elif t == "block.kill_axis":
        state.kill_list.append({"axis": p["axis"], "rationale": p["rationale"], "seq": ev.seq})
    elif t == "block.close":
        state.blocks.setdefault(p["block_id"], {})["closed"] = True

    elif t == "trials.open_batch":
        state.trials_batches[p["batch_id"]] = {**p, "seq": ev.seq, "closed": False, "records": []}
        b = state.blocks.setdefault(p["block_id"], {})
        if b.get("budget_remaining") is not None:
            b["budget_remaining"] -= p["n_planned"]   # reserve BEFORE compute (B-class)
    elif t == "trials.record":
        batch = state.trials_batches.setdefault(p["batch_id"], {"records": []})
        batch["records"].append({k: p[k] for k in
                                 ("n_rows", "n_distinct_keys", "rows_file", "gate_ref_q95")
                                 if k in p})
    elif t == "trials.close_batch":
        state.trials_batches.setdefault(p["batch_id"], {})["closed"] = True

    elif t == "artifact.register":
        state.artifacts[p["artifact_id"]] = {**p, "seq": ev.seq, "stamps": []}
        if p.get("role") == "population":
            state.populations[p["artifact_id"]] = {
                "status": p.get("status", "usable"), "mutation_audit_pass": False,
                "causality_class": (p.get("provenance") or {}).get("causality_class"),
            }
    elif t == "artifact.stamp":
        a = state.artifacts.setdefault(p["artifact_id"], {"stamps": []})
        a.setdefault("stamps", []).append(
            {k: p[k] for k in ("stamp_kind", "passed", "detail")})
        if p["stamp_kind"] == "mutation_audit" and p["passed"]:
            state.populations.setdefault(p["artifact_id"], {})["mutation_audit_pass"] = True
    elif t == "artifact.attest_missing":
        state.artifacts[f"missing::{p['name']}"] = {**p, "status": "attested_missing", "seq": ev.seq}
    elif t == "artifact.integrity_checked":
        a = state.artifacts.setdefault(p["artifact_id"], {"stamps": []})
        a["last_integrity_ok"] = p["ok"]

    elif t == "card.emit":
        state.cards[p["card_id"]] = {**p, "seq": ev.seq}

    elif t == "scorecard.emit":
        sc = p["scorecard"]
        key_hash = sha256_canon(sc["eval_key"])
        state.scorecards[key_hash] = sc
        cyc = state.cycles.get(p.get("cycle_id") or "", None)
        if cyc is not None and sc["eval_key"]["stage"] == 1:
            cyc.setdefault("stage1_scorecards", []).append(key_hash)

    elif t == "windowset.register":
        lineage = p.get("lineage_id") or f"lin::{p['windowset_id']}"
        state.windowsets[p["windowset_id"]] = {**p, "lineage_id": lineage, "seq": ev.seq}
        for w in p.get("windows", []):
            state.windows.setdefault(w["wiv_id"], {**w, "spends": []})
        state.lineages.setdefault(lineage, {"k_cumulative": 0, "generation": 1,
                                            "one_shot_map": {}, "emission_months": []})
    elif t == "windowset.supersede":
        new = p["new_windowset"]
        old = state.windowsets.get(p["old_windowset_id"], {})
        lineage = old.get("lineage_id", f"lin::{new['windowset_id']}")
        state.windowsets[p["old_windowset_id"]] = {**old, "status": "historical",
                                                   "superseded_by": new["windowset_id"]}
        state.windowsets[new["windowset_id"]] = {**new, "lineage_id": lineage, "seq": ev.seq}
        for w in new.get("windows", []):
            state.windows.setdefault(w["wiv_id"], {**w, "spends": []})
        # carryover: spends + cumulative k ride the wiv lineage (REG-INV-15)
        for c in p.get("carryover", []):
            wv = state.windows.setdefault(c["wiv_id"], {"spends": []})
            wv["spends"] = c.get("spends", wv.get("spends", []))
    elif t == "scope.mint":
        state.scopes[p["scope_id"]] = {**p, "seq": ev.seq}

    elif t == "readout.request":
        state.readouts[p["readout_id"]] = {**p, "seq": ev.seq, "recorded": False, "voided": False}
        if p.get("purpose", "readout") == "readout":
            _consume_slot(state, p, ev)
    elif t == "readout.record":
        r = state.readouts.setdefault(p["readout_id"], {})
        r["recorded"] = True
        r["five_clause"] = p.get("five_clause")
        placebo = p.get("placebo_result") or {}
        cls = classify_placebo(placebo)   # ALWAYS derive from raw numbers — never trust a
                                          # payload-supplied classification (fails-open otherwise)
        r["placebo_classification"] = cls
        req_ws = r.get("windowset_id", "")
        lineage = state.windowsets.get(req_ws, {}).get("lineage_id", req_ws)
        lin = state.lineages.setdefault(lineage, {})
        marks = state.placebo_history.setdefault(lineage, [])
        if r.get("purpose", "readout") == "readout":
            marks.append({"k": lin.get("k_cumulative", 0), "classification": cls,
                          "readout_id": p["readout_id"], "voided": False})
        if cls == "L1":
            r["cert_ineligible"] = True     # LOCAL consequence only; slot stays consumed (OQ-9)
    elif t == "readout.void":
        r = state.readouts.setdefault(p["readout_id"], {})
        r["voided"] = True
        _restore_slot(state, r)
        ws = r.get("windowset_id", "")
        lineage = state.windowsets.get(ws, {}).get("lineage_id", ws)
        state.lineages.setdefault(lineage, {})["any_readout_void"] = True
        for m in state.placebo_history.get(lineage, []):
            if m.get("readout_id") == p["readout_id"]:
                m["voided"] = True          # voids contribute no L1 (numbers never existed)

    elif t == "cert.clause_stamp":
        st = state.clause_stamps.setdefault(p["candidate_id"], {})
        st[p["clause"]] = p["stamp"]
    elif t == "cert.certify":
        state.clause_stamps.setdefault(p["candidate_id"], {})["certified"] = True
    elif t == "cert.displace":
        lin = p["lineage_id"]
        prev = state.incumbents.get(lin)
        if prev:
            state.incumbent_history.setdefault(lin, []).append(prev)
        state.incumbents[lin] = p["new_incumbent"]
    elif t == "cert.revoke":
        lin = p["lineage_id"]
        if state.incumbents.get(lin) == p["candidate_id"]:
            hist = state.incumbent_history.get(lin, [])
            state.incumbents[lin] = hist.pop() if hist else None   # automatic projection-restore
        state.clause_stamps.setdefault(p["candidate_id"], {})["revoked"] = True

    elif t == "constants.register":
        doc = {**p, "seq": ev.seq, "entries_hash": sha256_canon(p.get("entries", []))}
        state.constants[p["series"]] = doc
        state.constants_history.setdefault(p["series"], []).append(doc)
        _index_look_budget(state, p)
    elif t == "constants.amend":
        doc = {**p, "doc_id": p["new_doc_id"], "seq": ev.seq,
               "entries_hash": sha256_canon(p.get("entries", []))}
        state.constants[p["series"]] = doc
        state.constants_history.setdefault(p["series"], []).append(doc)
        _index_look_budget(state, p)
        _apply_suspension(state, p)

    elif t == "conditional.arm":
        state.conditionals[ev.event_id] = {**p, "status": "armed", "armed_by": ev.actor,
                                           "seq": ev.seq}
    elif t == "conditional.disarm":
        for cid, c in state.conditionals.items():
            if c.get("cond_id") == p["cond_id"] and c.get("status") == "armed":
                c["status"] = "disarmed"

    elif t == "rules.propose":
        r = state.rules.setdefault(p["rule_kind"], {"versions": [], "live": None})
        r.setdefault("proposals", []).append({**p, "event_id": ev.event_id, "seq": ev.seq})
    elif t == "rules.adopt":
        r = state.rules.setdefault(p["rule_kind"], {"versions": [], "live": None})
        prop = next((pr for pr in r.get("proposals", [])
                     if pr.get("event_id") == p["proposal_ref"]), None)
        body = (prop or {}).get("proposed", {})     # cascade._live_budget_rule reads live['body']
        if r.get("live"):
            r["versions"].append(r["live"])
        r["live"] = {"version": p["adopted_version"], "body": body,
                     "body_ref": p["proposal_ref"], "adopted_seq": ev.seq}
    elif t == "rules.revert":
        r = state.rules.setdefault(p["rule_kind"], {"versions": [], "live": None})
        for v in reversed(r.get("versions", [])):
            if v.get("version") == p["to_version"]:
                r["live"] = v                # projection-restore of the prior version exactly
                break

    elif t == "cycle.open":
        state.cycles[p["cycle_id"]] = {**p, "seq": ev.seq, "status": "open",
                                       "stage0_valid": [], "stage1_scorecards": []}
        state.open_cycle = p["cycle_id"]
    elif t == "cycle.close":
        state.cycles.setdefault(p["cycle_id"], {})["status"] = "closed"
        state.open_cycle = None
    elif t == "stage.dispatch":
        cyc = state.cycles.setdefault(p["cycle_id"], {})
        cyc.setdefault("dispatches", []).append(
            {"job_kind": p["job_kind"], "job_id": p["job_id"], "seq": ev.seq})
        if p["job_kind"] == "stage0_enumerate":
            valid = (p.get("inputs") or {}).get("stage0_valid")
            if valid:
                cyc["stage0_valid"] = list(valid)

    elif t == "shadow_ranking":
        skill = state.rules.setdefault("shadow_skill", {"epochs": []})
        skill.setdefault("rankings", []).append({"epoch": p["epoch_id"], "seq": ev.seq})
    elif t == "queue_reorder":
        state.rules.setdefault("handoff_queue", {})["order"] = p["new_order"]

    elif t == "replay.verified":
        pass  # informational; the log line IS the record
    elif t == "note.record":
        state.notes.append(ev.event_id)

    # conditional fire is recorded by REPLAY, not the scheduler: a scheduler event citing an
    # armed conditional whose body type matches marks it fired (deterministic on cold replay).
    if ev.actor == "scheduler:daemon":
        for _cid in ev.cites:
            _c = state.conditionals.get(_cid)
            if _c and _c.get("status") == "armed" and (_c.get("event_body") or {}).get("type") == t:
                _c["status"] = "fired"

    # chain bookkeeping
    state.dedup.add(ev.event_id)
    state.as_of_seq = ev.seq
    state.head_hash = ev.event_hash
    return state


def _consume_slot(state: RegistryState, p: dict, ev: Event) -> None:
    ws = state.windowsets.get(p["windowset_id"], {})
    lineage = ws.get("lineage_id", p["windowset_id"])
    lin = state.lineages.setdefault(lineage, {"k_cumulative": 0, "one_shot_map": {},
                                              "emission_months": []})
    lin["k_cumulative"] = lin.get("k_cumulative", 0) + 1
    budget = lin.get("budget")
    if budget:
        budget["consumed_this_generation"] = budget.get("consumed_this_generation", 0) + 1
        budget["remaining"] = max(0, budget.get("remaining", 0) - 1)
        budget["alarm_fired"] = budget["remaining"] <= budget.get("alarm_remaining", 0)
        budget["diagnostic_mode"] = budget["remaining"] <= budget.get("diagnostic_remaining", 0)
    for w in ws.get("windows", []):
        if w.get("role") == "forward_certifier":
            key = f"{w['wiv_id']}::{p['scope_id']}"
            lin["one_shot_map"][key] = p["readout_id"]
            state.windows.setdefault(w["wiv_id"], {"spends": []})["spends"].append(
                {"scope": p["scope_id"], "readout": p["readout_id"],
                 "slot_index": budget.get("consumed_this_generation") if budget else None,
                 "k_cumulative": lin["k_cumulative"]})
    month = ev.ts.strftime("%Y-%m")
    lin.setdefault("emission_months", []).append(month)


def _restore_slot(state: RegistryState, readout: dict) -> None:
    """readout.void restores the budget slot (the budget IS spend; void restores spend)."""
    ws = state.windowsets.get(readout.get("windowset_id", ""), {})
    lineage = ws.get("lineage_id", readout.get("windowset_id", ""))
    lin = state.lineages.get(lineage, {})
    budget = lin.get("budget")
    if budget and readout.get("purpose", "readout") == "readout":
        budget["remaining"] = budget.get("remaining", 0) + 1
        budget["consumed_this_generation"] = max(0, budget.get("consumed_this_generation", 1) - 1)
    for key, ref in list(lin.get("one_shot_map", {}).items()):
        if ref == readout.get("readout_id"):
            del lin["one_shot_map"][key]


def _index_look_budget(state: RegistryState, p: dict) -> None:
    """A look_budget constants doc materializes the lineage budget view."""
    if p["series"] != "look_budget":
        return
    entries = {e["key"]: e.get("value") for e in p.get("entries", [])}
    lineage = entries.get("lineage_id")
    if not lineage:
        return
    lin = state.lineages.setdefault(lineage, {"k_cumulative": 0, "one_shot_map": {},
                                              "emission_months": []})
    initial = entries.get("initial_budget", 0)
    new_gen = entries.get("generation", 1)
    cur = lin.get("budget", {})
    # a generation bump (calendar re-anchor / human refill) resets consumed; k_cumulative NEVER resets
    consumed = 0 if new_gen != cur.get("generation") else cur.get("consumed_this_generation", 0)
    lin["budget"] = {
        "initial_budget": initial,
        "alarm_remaining": entries.get("alarm_remaining", 0),
        "diagnostic_remaining": entries.get("diagnostic_remaining", 0),
        "consumed_this_generation": consumed,
        "remaining": max(0, initial - consumed),
        "generation": entries.get("generation", 1),
    }


def _apply_suspension(state: RegistryState, p: dict) -> None:
    """The extended-SUSPEND alarm's fired constants.amend flips the channel flag."""
    for e in p.get("entries", []):
        if e.get("key") == "readout_conditional_channel":
            state.suspensions["readout_conditional_channel"] = \
                (e.get("value") == "SUSPENDED_pending_human_review")


def replay(events) -> RegistryState:
    """Cold replay from seq 0 — reducers only, never barriers."""
    state = RegistryState()
    for ev in events:
        state = fold(state, ev)
    return state
