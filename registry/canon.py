"""Canonical JSON + hashing (TECH_SPEC §1.1) and the parquet content-digest scheme v1 (§1.2).

Rules, fixed forever at M0:
- Canonical bytes = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
  allow_nan=False).encode("utf-8").  NaN/Inf are REJECTED (allow_nan=False raises).
- Logical hashes are computed over the *Pydantic-validated model dump*, never raw parsed JSON
  (cross-language identity: MATLAB jsonencode writes 10, Python repr writes 10.0 — schema
  coercion through the validated model is what makes the canonical bytes agree).
- Physical hashes (files) are sha256 over raw bytes.
- Parquet identity is the CONTENT digest (bytes of parquet files are not stable across pyarrow
  versions); the file sha256 is transport only.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

DIGEST_SCHEME_VERSION = "digest_v1"


# ---- canonical JSON ------------------------------------------------------------------------
def canonical_bytes(obj: Any) -> bytes:
    """Canonical JSON bytes. Raises ValueError on NaN/Inf (allow_nan=False)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_canon(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def short(hexdigest: str, n: int = 12) -> str:
    """Truncated-hash display handle (per §1.3 ID conventions). Identity is the FULL hash."""
    return hexdigest[:n]


# ---- content digest v1 (tables) ------------------------------------------------------------
# Pinned column order (the manifest's declared `columns` list, exactly) → rows sorted by the
# declared sort key, tiebreak = lexicographic comparison of each row's full serialized bytes →
# per cell on every nullable column: one presence-flag byte (0x01 present / 0x00 null) followed
# by the value bytes IFF present; float64 = 8 IEEE-754 LE bytes; int64 = 8 LE bytes; strings =
# u32-LE length-prefixed UTF-8; timestamps = int64 µs-since-epoch LE.
# NOT decimal-string normalization (drifts; risk R8).

def _cell_bytes(value: Any, dtype: str) -> bytes:
    if value is None:
        return b"\x00"
    if dtype == "float64":
        return b"\x01" + struct.pack("<d", float(value))
    if dtype == "int64":
        return b"\x01" + struct.pack("<q", int(value))
    if dtype == "timestamp_us":
        return b"\x01" + struct.pack("<q", int(value))  # µs since epoch, pre-converted
    if dtype == "string":
        raw = str(value).encode("utf-8")
        return b"\x01" + struct.pack("<I", len(raw)) + raw
    raise ValueError(f"digest_v1: unsupported dtype {dtype!r}")


def content_digest_v1(
    rows: list[dict[str, Any]],
    columns: list[str],
    dtypes: dict[str, str],
    sort_key: list[str],
) -> str:
    """Content digest over a row-oriented table. Bridges convert their frames to this shape;
    the core stays dependency-free. `columns` is the pinned order; `sort_key` the declared key.
    """
    def row_blob(r: dict[str, Any]) -> bytes:
        return b"".join(_cell_bytes(r.get(c), dtypes[c]) for c in columns)

    def key(r: dict[str, Any]) -> tuple:
        primary = tuple(
            (r.get(k) is None, r.get(k)) for k in sort_key
        )
        return (primary, row_blob(r))  # tiebreak: full serialized row bytes, lexicographic

    h = hashlib.sha256()
    h.update(DIGEST_SCHEME_VERSION.encode())
    h.update(canonical_bytes({"columns": columns, "dtypes": {c: dtypes[c] for c in columns}}))
    for r in sorted(rows, key=key):
        h.update(row_blob(r))
    return h.hexdigest()
