"""Ingest / enrichment — the IMPURE half of the write path (TECH_SPEC §4).

Computes physical file sha256s and injects them into the event payload (computed_* fields),
so decide() can stay PURE: it compares declared-vs-computed values already inside the event.
Purity and hash-verification reconciled. MATLAB never hashes — the bridge/ingest does.
"""
from __future__ import annotations

import os
from pathlib import Path

from .canon import sha256_file
from .schemas.envelope import EventDraft, utc_now
from .schemas.payload_registry import validate_payload

# payload field pairs to enrich: (path_field, declared_field, computed_field)
_ENRICH_RULES: dict[str, list[tuple[str, str, str]]] = {
    "dataset.register": [("path", "raw_sha256", "computed_raw_sha256")],
    "artifact.register": [("path", "declared_sha256", "computed_sha256")],
}


def enrich(draft: EventDraft) -> EventDraft:
    """Return a draft whose payload carries computed hashes where a rule applies and the file
    is reachable. Missing files leave computed_* unset — the barrier's H-class only compares
    when BOTH sides are present (in-place artifacts on other hosts hash at the nightly sweep)."""
    # normalize the payload to the VALIDATED model dump — the canonical-hash input must be
    # schema-coerced bytes (cross-language identity, TECH_SPEC §1.1). On validation failure we
    # leave the payload untouched: decide()'s S-class check rejects with the proper code.
    if draft.ts is None:
        draft = draft.model_copy(update={"ts": utc_now()})   # stamp the daemon clock at ingest
    try:
        draft = draft.model_copy(update={"payload": validate_payload(draft.type, draft.payload)})
    except Exception:
        pass
    rules = _ENRICH_RULES.get(draft.type)
    if not rules:
        return draft
    payload = dict(draft.payload)
    for path_field, _declared, computed in rules:
        p = payload.get(path_field)
        if p and os.path.exists(p) and Path(p).is_file():
            payload[computed] = sha256_file(p)
    return draft.model_copy(update={"payload": payload})
