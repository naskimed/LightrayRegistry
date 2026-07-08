"""register_snapshot — register a canonical parquet as an NS1 dataset (dataset.register).

Registered IN PLACE (path + hashes; large data is never copied into the log). Dual identity:
  • file sha256  — transport / integrity;
  • content_digest — the STABLE identity (parquet bytes drift across pyarrow versions), computed
    over the canonical column arrays' raw little-endian bytes in pinned order — the same spirit
    as canon.content_digest_v1, but vectorized so a 4.5M-row snapshot registers in seconds.

This is a REAL registration (imported=false) — a fresh data contract, not a t=0 legacy import.
The fresh Binance spot BTCUSDT snapshot is a DIFFERENT data contract from the legacy broker
BTCUSD the incumbent lives on (crossing datasets is a new registration — the W1-empty lesson);
new-research OOS windows on it are a fresh lineage with a fresh look budget.

Usage:
  python -m registry.tools.register_snapshot --id snap_binance_btcusdt_1m \
         --parquet /workspace/snapshots/binance_btcusdt_1m/canonical.parquet \
         --source binance_export
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ..canon import sha256_file
from ._seed import SeedSession

DIGEST_SCHEME = "snap_digest_v1"
CANON_COLS = ["open", "high", "low", "close", "volume", "quote_volume",
              "trades", "taker_buy_base", "taker_buy_quote"]
CANON_DTYPES = {c: ("int64" if c == "trades" else "float64") for c in CANON_COLS}


def content_digest_parquet(parquet: Path) -> tuple[str, int, tuple[str, str]]:
    """Vectorized canonical digest over the OHLCV columns + row count + ts range. Sorted by ts
    (the fetcher already guarantees this) so the digest is order-stable."""
    import pandas as pd

    df = pd.read_parquet(parquet)
    df = df.sort_values("ts").reset_index(drop=True)
    h = hashlib.sha256()
    h.update(DIGEST_SCHEME.encode())
    h.update(f"n={len(df)}".encode())
    for c in CANON_COLS:
        arr = df[c].to_numpy()
        arr = arr.astype("<i8") if CANON_DTYPES[c] == "int64" else arr.astype("<f8")
        h.update(c.encode())
        h.update(arr.tobytes())
    ts0 = str(df["ts"].iloc[0]); ts1 = str(df["ts"].iloc[-1])
    h.update(f"{ts0}|{ts1}".encode())
    return h.hexdigest(), len(df), (ts0, ts1)


def register(snapshot_id: str, parquet: Path, source_kind: str, variants: list[str]) -> None:
    file_sha = sha256_file(parquet)
    digest, n_rows, (ts0, ts1) = content_digest_parquet(parquet)
    payload = {
        "snapshot_id": snapshot_id,
        "source_kind": source_kind,            # binance_export | mt3_csv | attested_external
        "raw_sha256": file_sha,                 # declared; ingest recomputes → H-class check
        "n_rows": n_rows,
        "canonical_content_digest": digest,
        "digest_scheme_version": DIGEST_SCHEME,
        "ts_range": [ts0, ts1],
        "stamp_semantics": "bar_open",
        "clock": "utc",
        "variants": variants,
        "path": str(parquet),
    }
    with SeedSession() as s:
        # imported=false: a fresh data contract, NOT a legacy t=0 import
        s.submit("dataset.register", payload, intent=f"snapshot:{snapshot_id}", imported=False)
        s.report(f"snapshot {snapshot_id}")
    print(f"registered {snapshot_id}: rows={n_rows:,} range {ts0} → {ts1}")
    print(f"  file sha256:     {file_sha}")
    print(f"  content_digest:  {digest}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--parquet", type=Path, required=True)
    p.add_argument("--source", default="binance_export")
    p.add_argument("--variants", nargs="*", default=[])
    a = p.parse_args()
    if not a.parquet.exists():
        raise SystemExit(f"parquet not found: {a.parquet} (run fetch_binance first)")
    register(a.id, a.parquet, a.source, a.variants)


if __name__ == "__main__":
    main()
