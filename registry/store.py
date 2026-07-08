"""Disk primitives: atomic JSON writes, JSONL append, and the content-addressed store.

Patterns lifted from LightrayTraderBackend/app/store.py (tmp+replace, JSONL) per the plan's
reuse note. Atomic rename is only atomic on the SAME filesystem — the week-1 check verifies
inbox/staging and inbox/pending share one (TECH_SPEC §6).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator

from .canon import canonical_bytes, sha256_file


# ---- atomic JSON ---------------------------------------------------------------------------
def write_json_atomic(path: str | Path, obj: Any) -> None:
    """tmp + fsync + rename in the target directory (same-fs atomicity)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp.", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_bytes(obj))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: str | Path) -> Any:
    with open(path, "rb") as f:
        return json.load(f)


# ---- JSONL ---------------------------------------------------------------------------------
def append_jsonl(path: str | Path, obj: Any, fsync: bool = True) -> None:
    """O_APPEND single-line write; fsync per record when asked (the ledger always asks)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_bytes(obj) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        if fsync:
            os.fsync(fd)
    finally:
        os.close(fd)


def iter_jsonl(path: str | Path) -> Iterator[tuple[int, dict]]:
    """Yield (0-based line number, parsed object). Raises on malformed NON-tail lines;
    the ledger layer handles tail quarantine itself."""
    with open(path, "rb") as f:
        for i, raw in enumerate(f):
            yield i, json.loads(raw)


# ---- content-addressed store ---------------------------------------------------------------
def cas_put(cas_root: str | Path, src: str | Path) -> tuple[str, Path]:
    """Copy a file into the CAS by its sha256. Returns (sha256, cas_path). Idempotent."""
    cas_root = Path(cas_root)
    digest = sha256_file(src)
    dest = cas_root / digest[:2] / digest
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    return digest, dest


def cas_get(cas_root: str | Path, digest: str) -> Path:
    p = Path(cas_root) / digest[:2] / digest
    if not p.exists():
        raise FileNotFoundError(f"CAS miss: {digest}")
    return p


# ---- inbox submission (atomic same-fs rename; used by clients incl. the MATLAB bridge) ------
def inbox_submit(staging: str | Path, pending: str | Path, name: str, obj: Any) -> Path:
    """Write to staging then rename into pending — the ONLY legal engine submission path."""
    staging, pending = Path(staging), Path(pending)
    staging.mkdir(parents=True, exist_ok=True)
    pending.mkdir(parents=True, exist_ok=True)
    tmp = staging / f"{name}.json"
    with open(tmp, "wb") as f:
        f.write(canonical_bytes(obj))
        f.flush()
        os.fsync(f.fileno())
    final = pending / f"{name}.json"
    os.replace(tmp, final)  # atomic iff same filesystem (week-1 check)
    return final
