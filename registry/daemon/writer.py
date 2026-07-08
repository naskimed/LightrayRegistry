"""The writer thread — the ONLY appender in the whole system.

Serializes every submission (HTTP + inbox + scheduler-internal) through one queue:
ingest(enrich) → decide() → append(fsync) → fold() → per-event projections. The fsync happens
BEFORE the reply future resolves, which is what makes client timeout-then-retry safe
(event_id dedup absorbs the retry).
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass

from ..barrier import Decision, decide
from ..ingest import enrich
from ..ledger import Ledger
from ..reducer import fold
from ..render import append_ledger_md
from ..schemas.envelope import EventDraft
from ..schemas.state import RegistryState


@dataclass
class Submission:
    draft: EventDraft
    reply: Future


class Writer(threading.Thread):
    def __init__(self, ledger: Ledger, state: RegistryState):
        super().__init__(name="writer", daemon=True)
        self.ledger = ledger
        self.state = state
        self.q: "queue.Queue[Submission]" = queue.Queue()
        self._stop = threading.Event()
        self.on_accept = []          # callbacks(event, state) — scheduler hooks (post-fold)

    def submit(self, draft: EventDraft) -> Future:
        f: Future = Future()
        self.q.put(Submission(draft, f))
        return f

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                sub = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                draft = enrich(sub.draft)
                decision = decide(self.state, draft)
                if not decision.accepted or decision.dedup_noop:
                    sub.reply.set_result((decision, None))
                    continue
                event = self.ledger.append(draft)      # fsync inside, BEFORE the ACK
                fold(self.state, event)
                append_ledger_md(event)                # prefix-stable derived render
                sub.reply.set_result((decision, event))
                for cb in self.on_accept:
                    try:
                        cb(event, self.state)
                    except Exception:
                        pass                            # hooks must never take the writer down
            except Exception as e:                      # defensive: writer must not die
                sub.reply.set_result(
                    (Decision(accepted=False, code="SCHEMA_INVALID",
                              reason=f"writer error: {e}"), None))
