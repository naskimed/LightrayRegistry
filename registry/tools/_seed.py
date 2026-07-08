"""Shared seed plumbing: submit imported events through the SAME write path as everything
else (flock → ingest → barrier → append → fold). Idempotent by deterministic event_id —
double-running any seed script produces zero new events (M3 acceptance)."""
from __future__ import annotations

import json
from pathlib import Path

from ..barrier import decide
from ..daemon.lock import registry_flock
from ..ingest import enrich
from ..ledger import Ledger
from ..reducer import fold, replay
from ..schemas.envelope import ACTOR_HUMAN, EventDraft, make_event_id

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"


def load_seed(name: str) -> dict:
    return json.loads((SEED_DIR / name).read_text())


class SeedSession:
    """One flock, many idempotent submissions."""

    def __init__(self):
        self._cm = registry_flock()

    def __enter__(self):
        self._cm.__enter__()
        self.ledger = Ledger()
        self.state = replay(self.ledger.iter_events())
        self.applied = 0
        self.skipped = 0
        return self

    def __exit__(self, *a):
        return self._cm.__exit__(*a)

    def submit(self, type_: str, payload: dict, intent: str,
               actor: str = ACTOR_HUMAN, imported: bool = True,
               provenance: str = "scheduled", **envelope_extra) -> bool:
        draft = EventDraft(
            event_id=make_event_id(type_, actor, payload, intent=intent),
            type=type_, actor=actor, provenance=provenance,
            payload=payload, imported=imported, **envelope_extra)
        draft = enrich(draft)
        d = decide(self.state, draft)
        if d.dedup_noop:
            self.skipped += 1
            return False
        if not d.accepted:
            raise SystemExit(f"SEED REJECTED [{d.code}] {type_}: {d.reason}")
        ev = self.ledger.append(draft)
        fold(self.state, ev)
        self.applied += 1
        return True

    def report(self, name: str) -> None:
        print(f"{name}: applied={self.applied} skipped(idempotent)={self.skipped}")
