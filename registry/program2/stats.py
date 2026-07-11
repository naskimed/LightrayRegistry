"""program2.stats — the Tier-2 statistic: regime-conditional family vs its own baseline (v3).

The selection statistic is DELTA vs the unconditional family, not raw conditional PF —
raw pooled PF inherits the price trend any trend-regime measures, which the twin battery
correctly flags as confounded. Pre-ratified fallback if the week-2 twin pilot fires on the
delta statistic too: per-quarter demeaned profits (implemented here as demean="quarter").

Side policies map (side, regime label) -> keep. The conditional strategy identity is
sha256_canon({"pop": pop_sha, "regime": regime_key, "policy": policy_name}) — that is what
gets pinned, pooled, examined, and deduplicated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# policy -> set of (side, label) kept. 2-state regimes use labels {0,1};
# vol terciles use {0,1,2}. Label -1 (pre-warmup) is ALWAYS dropped.
POLICIES: dict[str, set[tuple[str, int]]] = {
    "long_up_short_down":   {("buy", 1), ("sell", 0)},
    "long_up_flat_down":    {("buy", 1)},
    "flat_up_short_down":   {("sell", 0)},
    "long_down_short_up":   {("buy", 0), ("sell", 1)},          # contrarian control
    "long_low_vol":         {("buy", 0)},
    "long_high_vol":        {("buy", 2)},
    "short_high_vol":       {("sell", 2)},
    "both_low_vol":         {("buy", 0), ("sell", 0)},
}


def conditional_series(df: pd.DataFrame, regime_col: str, policy: str) -> pd.DataFrame:
    """Rows of the family kept by the side policy, time-ordered. Requires regime_col."""
    keep = POLICIES[policy]
    lab = df[regime_col].astype(int)
    mask = pd.Series(False, index=df.index)
    for side, label in keep:
        mask |= (df["side"] == side) & (lab == label)
    mask &= lab >= 0
    return df.loc[mask].sort_values("entry_ts").reset_index(drop=True)


def _pf(r: np.ndarray) -> float:
    gl = float(-r[r <= 0].sum())
    return float(r[r > 0].sum() / gl) if gl > 0 else 10.0


def _demean(df: pd.DataFrame, how: str | None) -> pd.DataFrame:
    if not how:
        return df
    if how != "quarter":
        raise ValueError(how)
    d = df.copy()
    q = pd.to_datetime(d["entry_ts"]).dt.to_period("Q")
    d["profit"] = d["profit"] - d.groupby(q)["profit"].transform("mean")
    return d


def tier2_stat(family: pd.DataFrame, regime_col: str, policy: str,
               n_boot: int = 2000, block: int = 20, seed: int = 7,
               demean: str | None = None) -> dict:
    """Delta-vs-unconditional PF on the SAME (masked-train) rows + circular block
    bootstrap p. family = the full family's train rows (both sides), time-ordered."""
    fam = _demean(family.sort_values("entry_ts").reset_index(drop=True), demean)
    cond = conditional_series(fam, regime_col, policy)
    n, m = len(fam), len(cond)
    if m < 30:
        return {"n_cond": m, "verdict": "insufficient_n"}
    r_all = fam["profit"].to_numpy()
    # membership mask aligned to fam's positional order
    keep = pd.Series(False, index=range(n))
    lab = fam[regime_col].astype(int)
    for side, label in POLICIES[policy]:
        keep |= ((fam["side"] == side) & (lab == label)).reset_index(drop=True)
    keep &= (lab >= 0).reset_index(drop=True)
    keep = keep.to_numpy()
    delta = _pf(r_all[keep]) - _pf(r_all)
    rng = np.random.RandomState(seed)
    boots = np.empty(n_boot)
    n_blocks = int(np.ceil(n / block))
    for b in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        idx = ((starts[:, None] + np.arange(block)[None, :]) % n).ravel()[:n]
        rb, kb = r_all[idx], keep[idx]
        boots[b] = (_pf(rb[kb]) - _pf(rb)) if kb.sum() >= 10 else 0.0
    return {"n_cond": int(keep.sum()), "n_family": n,
            "pf_cond": round(_pf(r_all[keep]), 4), "pf_uncond": round(_pf(r_all), 4),
            "delta_pf": round(float(delta), 4),
            "p_boot": round(float((boots <= 0).mean()), 4),
            "demean": demean or "none"}
