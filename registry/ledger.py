"""Hash chain & log mechanics (TECH_SPEC §3.3).

- events.jsonl: one canonical-JSON event per line, O_APPEND + fsync per record.
- event_hash = sha256_canon(envelope − event_hash); prev_hash = previous event's hash;
  genesis prev_hash = "0"*64.
- verify() walks the chain; reports the exact first-bad seq on any flipped byte; a truncated
  tail line is quarantined (events.jsonl.quarantine), clean-through-seq reported.
- Chain-head anchoring: synchronous LOCAL git commit of the head hash at every block.freeze,
  readout.request, cert.*; asynchronous push with blocking alarm on failure (event acceptance
  never depends on network).
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Iterator, Optional

from . import config
from .canon import canonical_bytes
from .schemas.envelope import Event, EventDraft, compute_event_hash, utc_now

GENESIS_HASH = "0" * 64
ANCHOR_TYPES = {"block.freeze", "readout.request",
                "cert.clause_stamp", "cert.certify", "cert.displace", "cert.revoke"}


class LedgerCorruption(Exception):
    """Mid-file (non-tail) unparseable line — the log is NEVER auto-truncated; manual recovery."""


@dataclass
class VerifyResult:
    ok: bool
    n_events: int
    head_hash: str
    first_bad_seq: Optional[int] = None
    reason: Optional[str] = None
    quarantined_tail: bool = False


class Ledger:
    """The single append point. Only the daemon's writer thread (or the CLI in single-user
    mode under the same flock) ever constructs one for writing."""

    def __init__(self, path: Path | None = None, writable: bool = True):
        self.path = path or config.ledger_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writable = writable          # read-only constructions NEVER rewrite the log
        self._next_seq, self._head = self._scan_tail()

    # ---- read side ---------------------------------------------------------------------
    def _scan_tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS_HASH
        raw_lines = [ln for ln in self.path.read_bytes().split(b"\n") if ln.strip()]
        if not raw_lines:
            return 0, GENESIS_HASH
        last = None
        for idx, ln in enumerate(raw_lines):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                is_final = (idx == len(raw_lines) - 1)
                if not is_final:
                    # mid-file corruption is NOT a torn tail — never silently rewrite the log
                    raise LedgerCorruption(
                        f"unparseable line at index {idx}/{len(raw_lines)} (not the tail) — "
                        "manual recovery required; the log is NOT auto-truncated")
                if self.writable:
                    self._quarantine_final(raw_lines)   # crash mid-append: drop the torn tail
                break
            else:
                last = obj
        if last is None:
            return 0, GENESIS_HASH
        return last["seq"] + 1, last["event_hash"]

    def _quarantine_final(self, raw_lines: list[bytes]) -> None:
        """Move the torn FINAL line to quarantine, rewrite the clean prefix via tmp+rename
        (atomic). ONLY reached on a write-authorized construction holding the registry flock."""
        torn, clean = raw_lines[-1], raw_lines[:-1]
        with open(config.quarantine_path(self.path.parent.parent), "ab") as q:
            q.write(torn + b"\n")
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "wb") as f:
            for ln in clean:
                f.write(ln + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def iter_events(self) -> Iterator[Event]:
        if not self.path.exists():
            return
        with open(self.path, "rb") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                yield Event.model_validate(json.loads(raw))

    @property
    def head_hash(self) -> str:
        return self._head

    @property
    def next_seq(self) -> int:
        return self._next_seq

    # ---- write side --------------------------------------------------------------------
    def append(self, draft: EventDraft) -> Event:
        """Chain-stamp + fsync-append an ACCEPTED draft. Caller (writer thread) has already
        run ingest + barrier. fsync happens BEFORE the caller ACKs the client (safe retry)."""
        envelope = draft.model_dump(mode="json")
        envelope["seq"] = self._next_seq
        envelope["ts"] = utc_now().isoformat()
        envelope["prev_hash"] = self._head
        envelope["event_hash"] = ""  # placeholder for shape; removed for hashing
        body = dict(envelope)
        body.pop("event_hash")
        envelope["event_hash"] = compute_event_hash(body)

        event = Event.model_validate(envelope)
        # Write EXACTLY the dict we hashed (envelope) — never a re-serialization of the model:
        # pydantic's datetime rendering can differ byte-wise from isoformat(), and the chain
        # hash must recompute from the raw line (verify() reads raw dicts).
        line = canonical_bytes(envelope) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)

        self._next_seq += 1
        self._head = event.event_hash

        if event.type in ANCHOR_TYPES:
            anchor_head(self._head, event.type, self.path)
        return event


def verify(path: Path | None = None) -> VerifyResult:
    """Walk the chain from seq 0. Exact first-bad seq on any flipped byte."""
    path = path or config.ledger_path()
    if not path.exists():
        return VerifyResult(ok=True, n_events=0, head_hash=GENESIS_HASH)
    raw_lines = [ln for ln in path.read_bytes().split(b"\n") if ln.strip()]
    prev = GENESIS_HASH
    n = 0
    for idx, raw in enumerate(raw_lines):
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                if idx == len(raw_lines) - 1:
                    # a torn FINAL line is RECOVERABLE (crash mid-append) — clean through n
                    return VerifyResult(ok=True, n_events=n, head_hash=prev,
                                        quarantined_tail=True,
                                        reason="torn final line (dropped at next write)")
                return VerifyResult(ok=False, n_events=n, head_hash=prev, first_bad_seq=n,
                                    reason=f"mid-file unparseable line at index {idx}")
            if d.get("seq") != n:
                return VerifyResult(ok=False, n_events=n, head_hash=prev, first_bad_seq=n,
                                    reason=f"seq gap: expected {n}, found {d.get('seq')}")
            if d.get("prev_hash") != prev:
                return VerifyResult(ok=False, n_events=n, head_hash=prev, first_bad_seq=n,
                                    reason="prev_hash mismatch (chain break)")
            body = dict(d)
            claimed = body.pop("event_hash")
            if compute_event_hash(body) != claimed:
                return VerifyResult(ok=False, n_events=n, head_hash=prev, first_bad_seq=n,
                                    reason="event_hash mismatch (content tampered)")
            prev = claimed
            n += 1
    return VerifyResult(ok=True, n_events=n, head_hash=prev)


# ---- git anchoring ---------------------------------------------------------------------
def anchor_head(head_hash: str, reason: str, ledger_path: Path) -> None:
    """Synchronous LOCAL commit of the chain head (cheap, no network); push is async and
    failure raises an alarm file, never blocks acceptance. No-op outside a git repo."""
    repo = ledger_path.parent.parent  # workdir; anchors live in workdir/.git if present
    anchor_file = repo / "chain_head.txt"
    try:
        anchor_file.write_text(f"{head_hash}  # {reason} @ {utc_now().isoformat()}\n")
        if (repo / ".git").exists():
            subprocess.run(["git", "-C", str(repo), "add", "chain_head.txt"],
                           capture_output=True, timeout=10)
            subprocess.run(["git", "-C", str(repo), "commit", "-m",
                            f"anchor {head_hash[:12]} ({reason})"],
                           capture_output=True, timeout=10)
            # async push: fire-and-forget; alarm on failure is the puller's job (daemon checks)
            subprocess.Popen(["git", "-C", str(repo), "push"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # anchoring must never take the write path down; the nightly integrity sweep alarms
        (repo / "ANCHOR_ALARM").touch()
