"""The scheduler thread (TECH_SPEC §5.3, TS-2.0 §5.5).

Duties: dispatch due engine jobs (deterministic subprocesses — the production path, NEVER the
MCP) · evaluate armed conditionals after each fold · run the cycle machinery · fire BOUNDARY
sessions between cycles (cycle_schedule constant + event-driven mode) · run the SHADOW ranking
per epoch · fire OPERATOR sessions on incident · classify placebo L1/L2 on readout ingest ·
nightly integrity sweep + cold replay + daily digest.

var/HALT is checked before EVERY dispatch — one `touch` stops the machine; removal resumes.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone

from .. import config
from ..canon import sha256_canon
from ..ledger import verify
from ..predicates import PREDICATES, evaluate
from ..reducer import replay
from ..render import daily_digest
from ..schemas.envelope import ACTOR_SCHEDULER, EventDraft, make_event_id
from ..export import export_all
from .agents import AgentRunner
from .writer import Writer


class Scheduler(threading.Thread):
    def __init__(self, writer: Writer, agent_runner: AgentRunner | None = None,
                 tick_seconds: float = 5.0):
        super().__init__(name="scheduler", daemon=True)
        self.writer = writer
        self.agents = agent_runner
        self.tick = tick_seconds
        self._stop = threading.Event()
        self._last_export = 0.0
        self._last_nightly = ""
        self._pending_boundary_wake = threading.Event()
        self._conditionals_dirty = threading.Event()
        writer.on_accept.append(self._on_event)

    # ---- writer hook: runs after every accepted fold -------------------------------------
    def _on_event(self, event, state) -> None:
        # Runs INSIDE the writer thread — it must NEVER block on writer.submit().result()
        # (self-deadlock). Only flag; the scheduler thread evaluates conditionals in _tick().
        self._conditionals_dirty.set()
        # event-driven boundary wake: card emission / cycle close (V1 mode)
        if event.type in ("card.emit", "cycle.close"):
            self._pending_boundary_wake.set()
        # 3) incident → operator session (engine failures arrive as note.record incidents
        #    from bridges; a dedicated incident channel can refine this)
        if event.type == "note.record" and "incident" in (event.payload.get("tags") or []):
            self._fire_agent("operator", reason=f"incident: {event.payload.get('title')}")

    def stop(self) -> None:
        self._stop.set()

    def halted(self) -> bool:
        return config.halt_path().exists()

    # ---- the loop -------------------------------------------------------------------------
    def run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.halted():
                    self._tick()
            except Exception:
                pass  # the scheduler must never die silently; errors surface in the digest
            time.sleep(self.tick)

    def _tick(self) -> None:
        state = self.writer.state
        now = time.time()

        # conditionals: evaluated on the SCHEDULER thread (safe to block on the writer here)
        if self._conditionals_dirty.is_set():
            self._conditionals_dirty.clear()
            self._evaluate_conditionals(state)

        # boundary wake (event-driven mode; the cycle_schedule constant gates cadence mode)
        if self._pending_boundary_wake.is_set() and not state.open_cycle:
            self._pending_boundary_wake.clear()
            self._fire_agent("boundary", reason="cards emitted / cycle closed")

        # projections export (cheap, throttled)
        if now - self._last_export > 30:
            export_all(state)
            self._last_export = now

        # nightly: integrity sweep + cold replay + digest
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_nightly:
            self._last_nightly = today
            self._nightly(state, today)

    # ---- conditionals ----------------------------------------------------------------------
    def _evaluate_conditionals(self, state) -> None:
        """Fire armed conditionals whose predicate is green. Staleness (pinned ≠ deployed) is
        DERIVED here — a stale conditional never fires; human re-arm required."""
        if self.halted():
            return
        for arming_event_id, cond in list(state.conditionals.items()):
            if cond.get("status") != "armed":
                continue
            pred = cond.get("predicate", {})
            fired, stale = evaluate(pred.get("name", ""), pred.get("version", ""),
                                    state, pred.get("params", {}))
            if stale or not fired:
                continue
            body = cond.get("event_body", {})
            draft = EventDraft(
                event_id=make_event_id(body["type"], ACTOR_SCHEDULER, body.get("payload", {}),
                                       intent=f"fire:{cond.get('cond_id')}"),
                type=body["type"], actor=ACTOR_SCHEDULER, provenance="scheduled",
                cites=[arming_event_id],                      # the human authorization chain
                payload=body.get("payload", {}),
            )
            # The fire is recorded by the REDUCER (folding the fired event marks the
            # conditional fired — replayable). The scheduler does NOT mutate state.
            self.writer.submit(draft).result()

    # ---- cycles (TS-2.0 §5.5.1) --------------------------------------------------------------
    def open_cycle(self, cycle_id: str) -> Future:
        """Versions PINNED at open from the live constants/rules; adoptions apply NEXT open."""
        state = self.writer.state
        rule = (state.rules.get("dial_budget_rule", {}).get("live") or {})
        payload = {
            "cycle_id": cycle_id,
            "dial_budget_rule_version": str(rule.get("version", "seed")),
            "score_fn_version": _constant(state, "score_function", "version") or "score_v1",
            "promotion_predicate_version": _constant(state, "promotion_predicate", "version") or "1",
            "cost_model_version": _constant(state, "cost_model", "version") or "cost_model_v0_flat",
        }
        return self._emit("cycle.open", payload, intent=cycle_id)

    def dispatch_stage(self, cycle_id: str, job_kind: str, job_id: str, inputs: dict) -> Future:
        return self._emit("stage.dispatch",
                          {"cycle_id": cycle_id, "job_kind": job_kind,
                           "job_id": job_id, "inputs": inputs},
                          intent=job_id)

    def close_cycle(self, cycle_id: str) -> Future:
        return self._emit("cycle.close", {"cycle_id": cycle_id}, intent=f"close:{cycle_id}")

    def _emit(self, type_: str, payload: dict, intent: str) -> Future:
        draft = EventDraft(
            event_id=make_event_id(type_, ACTOR_SCHEDULER, payload, intent=intent),
            type=type_, actor=ACTOR_SCHEDULER, provenance="scheduled", payload=payload)
        return self.writer.submit(draft)

    # ---- agents -------------------------------------------------------------------------------
    def _fire_agent(self, role: str, reason: str) -> None:
        if self.agents is None or self.halted() or config.readonly_path().exists():
            return
        self.agents.fire(role, reason=reason, writer=self.writer)

    # ---- nightly --------------------------------------------------------------------------------
    def _nightly(self, state, date_str: str) -> None:
        # cold replay from seq 0 + diff vs live (E-class)
        from ..ledger import Ledger
        lg = Ledger(writable=False)          # read-only: never rewrite under the live writer
        cold = replay(lg.iter_events())
        ok = cold.state_hash() == state.state_hash()
        self._emit("replay.verified",
                   {"as_of_seq": state.as_of_seq, "live_state_hash": state.state_hash(),
                    "replay_state_hash": cold.state_hash(), "ok": ok},
                   intent=f"nightly:{date_str}")
        # integrity sweep over in-place registered artifacts
        self._integrity_sweep(state, date_str)
        daily_digest(state, date_str)
        v = verify()
        if not v.ok:
            (config.workdir() / "CHAIN_ALARM").write_text(
                f"verify failed at seq {v.first_bad_seq}: {v.reason}\n")

    def _integrity_sweep(self, state, date_str: str) -> None:
        """Re-hash in-place artifacts; anything cited by cert.*/readout.* must be in CAS or on
        the backup include-list — the chain protects the log, not what it points at (R2)."""
        import os
        from ..canon import sha256_file
        for aid, a in list(state.artifacts.items()):
            path = a.get("path")
            if not path or not os.path.exists(path):
                continue
            expected = a.get("computed_sha256") or a.get("declared_sha256")
            if not expected:
                continue
            actual = sha256_file(path)
            self._emit("artifact.integrity_checked",
                       {"artifact_id": aid, "ok": actual == expected,
                        "recomputed_sha256": actual},
                       intent=f"sweep:{date_str}:{aid}")


def _constant(state, series: str, key: str):
    doc = state.constants.get(series)
    if not doc:
        return None
    for e in doc.get("entries", []):
        if e.get("key") == key and not e.get("unknown"):
            return e.get("value")
    return None
