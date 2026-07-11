"""regimes.referee — the two structural audits every regime must pass before menu entry (v3).

1. assert_causal: recompute labels on truncated history; every label in the overlap must
   be identical. Catches smoothing/normalization that peeks forward (the leak class the
   twin battery structurally cannot see — the 2026-07-10 z=119 lesson made mechanical).
   A planted-future positive control proves the audit itself has teeth.

2. regime_placebo: circularly shift the LABEL SERIES in day-space (block structure
   preserved) and require the real regime's delta statistic beat the placebo q95. Prices
   "any slow partition of time helps", which profit-shift twins do not fully price.

A regime enters the Tier-2 menu only with BOTH audits ledgered green.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..program2.stats import tier2_stat
from .defs import RegimeSpec, compute_regime

PLACEBO_SEED = 424200


def assert_causal(spec: RegimeSpec, bars: pd.DataFrame, cut_frac: float = 0.7) -> dict:
    """Labels computed on the first cut_frac of bars must equal the full-history labels
    over the overlap (minus nothing: causal formulas cannot change past labels)."""
    full = compute_regime(spec, bars).set_index("label_ts")["label"]
    n = int(len(bars) * cut_frac)
    part = compute_regime(spec, bars.iloc[:n]).set_index("label_ts")["label"]
    overlap = full.index.intersection(part.index)
    mismatches = int((full.loc[overlap] != part.loc[overlap]).sum())
    if mismatches:
        raise AssertionError(f"regime {spec.name} NOT causal: {mismatches} labels changed "
                             f"when future data was appended")
    return {"regime": spec.name, "params": spec.params, "overlap_days": len(overlap),
            "mismatches": 0, "causal": True}


def planted_future_control(bars: pd.DataFrame, cut_frac: float = 0.7) -> dict:
    """Prove the audit has teeth against the class it exists to catch: FULL-SAMPLE
    statistics (the historic EA mean/std-block bug). A deliberately leaky regime —
    label(D) = close(D) > median(close over ALL days) — must show mismatching past
    labels when history is truncated. (The other leak class, label-timing/'use
    tomorrow's label', is defended structurally by effective_ts in the attach join,
    not by this audit — a consistent shift never changes past labels.)"""
    from .defs import daily_closes
    close = daily_closes(bars)
    leaky_full = (close > close.median()).astype("int8")
    part = close.iloc[:int(len(close) * cut_frac)]
    leaky_part = (part > part.median()).astype("int8")
    overlap = leaky_full.index.intersection(leaky_part.index)
    mismatches = int((leaky_full.loc[overlap] != leaky_part.loc[overlap]).sum())
    if mismatches == 0:
        raise AssertionError("planted-future control NOT caught — audit has no teeth")
    return {"planted_mismatches": mismatches, "caught": True}


def regime_placebo(family_train: pd.DataFrame, regime_col: str, policy: str,
                   n_placebos: int = 20, demean: str | None = None) -> dict:
    """Circularly shift the per-trade label assignment in TIME-BLOCK space: the label
    series is rolled by a random number of distinct days, so any slow partition of
    similar shape is tried against the same trades. Real delta must beat placebo q95."""
    fam = family_train.sort_values("entry_ts").reset_index(drop=True)
    real = tier2_stat(fam, regime_col, policy, demean=demean)
    if real.get("verdict") == "insufficient_n":
        return {"verdict": "insufficient_n"}
    days = pd.to_datetime(fam["entry_ts"]).dt.normalize()
    uniq = days.unique()
    day_label = fam.groupby(days)[regime_col].first()          # label is constant per day
    rng = np.random.RandomState(PLACEBO_SEED)
    deltas = []
    for _ in range(n_placebos):
        k = int(rng.randint(1, len(uniq) - 1))
        rolled = pd.Series(np.roll(day_label.to_numpy(), k), index=day_label.index)
        fam_p = fam.copy()
        fam_p[regime_col] = days.map(rolled).astype("int8").to_numpy()
        s = tier2_stat(fam_p, regime_col, policy, n_boot=200, demean=demean)
        deltas.append(s.get("delta_pf", 0.0) if "delta_pf" in s else 0.0)
    q95 = float(np.quantile(deltas, 0.95))
    # PASS/FAIL = candidate admission, deliberately NOT the twin battery's SILENT/LEAKY
    # vocabulary: a FAIL here rejects one regime candidate; it never implies instrument
    # failure and never writes HALT.
    return {"real_delta": real["delta_pf"], "placebo_q95": round(q95, 4),
            "placebo_deltas": [round(d, 4) for d in sorted(deltas)],
            "n_placebos": n_placebos,
            "verdict": "PASS" if real["delta_pf"] > q95 else "FAIL"}
