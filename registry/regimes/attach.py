"""regimes.attach — join a regime label onto a population, content-addressed (v3).

The validated engine is never touched: the population parquet is generated once by
cascade_run.generate_population, and the regime acts as an added column rg_{name} joined
by merge_asof on effective_ts (backward) — every trade gets the most recent label that was
already effective at its entry. Cache: pop_{sha12}_rg_{regime_key}.parquet; a hit IS the
result (same discipline as the _cat2 catalog join).
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .defs import RegimeSpec, compute_regime, regime_key


def _sha_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def regime_series(spec: RegimeSpec, bars_path: str, cache_dir: Path) -> tuple[pd.DataFrame, str]:
    """Compute (or load cached) regime label series for a pinned bars snapshot."""
    src_sha = _sha_file(bars_path)
    key = regime_key(spec, src_sha)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"reg_{key}.parquet"
    if cached.exists():
        return pd.read_parquet(cached), key
    bars = pd.read_parquet(bars_path)
    reg = compute_regime(spec, bars)
    reg.to_parquet(cached, index=False)
    return reg, key


def attach_regime(pop_path: str, spec: RegimeSpec, bars_path: str,
                  pop_dir: Path) -> tuple[str, str]:
    """-> (joined parquet path, regime_key). Adds column rg_{spec.name} (int8, -1 = no
    label yet, e.g. entries before regime warmup — callers must exclude -1 rows)."""
    reg, key = regime_series(spec, bars_path, pop_dir / "regimes")
    if not (reg["effective_ts"] > reg["label_ts"]).all():
        raise AssertionError("regime lag violated: effective_ts must be strictly after "
                             "label_ts for every label (label-timing leak guard)")
    stem = Path(pop_path).stem                       # pop_{sha12}
    out = pop_dir / f"{stem}_rg_{key}.parquet"
    if out.exists():
        return str(out), key
    df = pd.read_parquet(pop_path)
    entries = pd.DataFrame({"entry_ts": pd.to_datetime(df["entry_ts"])})
    entries["_order"] = range(len(entries))
    merged = pd.merge_asof(entries.sort_values("entry_ts"),
                           reg[["effective_ts", "label"]].sort_values("effective_ts"),
                           left_on="entry_ts", right_on="effective_ts",
                           direction="backward")
    merged = merged.sort_values("_order")
    df[f"rg_{spec.name}"] = merged["label"].fillna(-1).astype("int8").to_numpy()
    df.attrs["regime_spec"] = str(asdict(spec))
    df.to_parquet(out, index=False)
    return str(out), key
