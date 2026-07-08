"""Workdir + environment resolution.

The runtime workdir holds the ledger, state snapshots, contracts, inbox, CAS, and the
kill-switch files. It MUST be a real mounted filesystem where atomic same-fs rename works
(verified by the week-1 checks; see docs/TECH_SPEC.md §6).
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_WORKDIR = "LIGHTRAY_REGISTRY_WORKDIR"


def workdir() -> Path:
    """Resolve the runtime workdir. Precedence: env var, then ./var under the repo."""
    root = os.environ.get(ENV_WORKDIR)
    if root:
        return Path(root)
    return Path(__file__).resolve().parent.parent / "var"


# ---- fixed layout under the workdir (TECH_SPEC §6) ----------------------------------------
def ledger_path(w: Path | None = None) -> Path:      return (w or workdir()) / "ledger" / "events.jsonl"
def quarantine_path(w: Path | None = None) -> Path:  return (w or workdir()) / "ledger" / "events.jsonl.quarantine"
def state_dir(w: Path | None = None) -> Path:        return (w or workdir()) / "state"
def contracts_dir(w: Path | None = None) -> Path:    return (w or workdir()) / "contracts"
def inbox_dir(w: Path | None = None) -> Path:        return (w or workdir()) / "inbox"
def inbox_staging(w: Path | None = None) -> Path:    return inbox_dir(w) / "staging"
def inbox_pending(w: Path | None = None) -> Path:    return inbox_dir(w) / "pending"
def inbox_accepted(w: Path | None = None) -> Path:   return inbox_dir(w) / "accepted"
def inbox_rejected(w: Path | None = None) -> Path:   return inbox_dir(w) / "rejected"
def cas_dir(w: Path | None = None) -> Path:          return (w or workdir()) / "artifacts" / "cas"
def sessions_dir(w: Path | None = None) -> Path:     return (w or workdir()) / "sessions"
def reports_dir(w: Path | None = None) -> Path:      return (w or workdir()) / "reports"
def jobs_dir(w: Path | None = None) -> Path:         return (w or workdir()) / "jobs"
def lock_path(w: Path | None = None) -> Path:        return (w or workdir()) / "registry.lock"
def status_path(w: Path | None = None) -> Path:      return (w or workdir()) / "daemon.status.json"
def halt_path(w: Path | None = None) -> Path:        return (w or workdir()) / "HALT"
def readonly_path(w: Path | None = None) -> Path:    return (w or workdir()) / "READONLY"


def ensure_layout(w: Path | None = None) -> Path:
    """Create the full directory layout (idempotent). Returns the workdir."""
    w = w or workdir()
    for p in (
        ledger_path(w).parent, state_dir(w), contracts_dir(w),
        inbox_staging(w), inbox_pending(w), inbox_accepted(w), inbox_rejected(w),
        cas_dir(w), sessions_dir(w), reports_dir(w), jobs_dir(w),
    ):
        p.mkdir(parents=True, exist_ok=True)
    return w


# ---- daemon http (localhost only — v1 security posture is a recorded decision) ------------
API_HOST = "127.0.0.1"
API_PORT = 8377
