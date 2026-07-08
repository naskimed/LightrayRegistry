"""Inbox poller — the ONLY engine submission path (filesystem, atomic same-fs rename).

Engines write JSON to inbox/staging/<name>.json then rename into inbox/pending/. The poller
routes each file through the writer; accepted files move to accepted/, rejects to rejected/
with a <name>.reason.json alongside. Crash recovery: pending files are simply reprocessed —
client event_id dedup prevents double-apply.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .. import config
from ..schemas.envelope import EventDraft
from ..store import write_json_atomic
from .writer import Writer


class InboxPoller(threading.Thread):
    def __init__(self, writer: Writer, poll_seconds: float = 2.0):
        super().__init__(name="inbox", daemon=True)
        self.writer = writer
        self.poll = poll_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        pending = config.inbox_pending()
        accepted = config.inbox_accepted()
        rejected = config.inbox_rejected()
        while not self._stop.is_set():
            for p in sorted(pending.glob("*.json")):
                self._process(p, accepted, rejected)
            time.sleep(self.poll)

    def _process(self, path: Path, accepted: Path, rejected: Path) -> None:
        try:
            raw = json.loads(path.read_text())
            draft = EventDraft.model_validate(raw)
        except Exception as e:
            write_json_atomic(rejected / f"{path.stem}.reason.json",
                              {"code": "SCHEMA_INVALID", "reason": str(e)})
            os.replace(path, rejected / path.name)
            return
        decision, event = self.writer.submit(draft).result()
        if decision.accepted:
            os.replace(path, accepted / path.name)
            if event is not None:
                write_json_atomic(accepted / f"{path.stem}.ack.json",
                                  {"seq": event.seq, "event_hash": event.event_hash,
                                   "dedup_noop": decision.dedup_noop})
        else:
            write_json_atomic(rejected / f"{path.stem}.reason.json",
                              {"code": decision.code, "reason": decision.reason})
            os.replace(path, rejected / path.name)
