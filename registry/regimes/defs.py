"""regimes.defs — slow market-state labels for Tier-2 side selection (Program 2, v3).

A regime is a LOW-parameter (<=2 free params) label series computed from market data up to
and including label_ts, usable for entries at effective_ts onward. Daily regimes label at
day-D close and become effective at D+1 00:00 UTC — a full-day lag, so no intraday
knowability argument is ever needed. Content-addressed: regime_key = sha over the spec,
the source snapshot sha, and REGIME_CODE_VERSION (a formula change mints new artifacts,
never mutates old ones).

Initial rule-based regimes (no new data needed):
  trend_sma(fast_d, slow_d)  -> {0: down, 1: up}     SMA cross on daily closes
  vol_tercile(window_d)      -> {0: low, 1: mid, 2: high}  realized vol vs EXPANDING
                                terciles (causal — boundaries use only past data)
funding_sign lands with the futures data layer (Tier 3 era).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from ..canon import sha256_canon

REGIME_CODE_VERSION = "rg_v1"
VALID_NAMES = ("trend_sma", "vol_tercile")
MAX_PARAMS = 2
_WARMUP_DAYS = 200          # expanding-quantile warmup for vol_tercile


@dataclass(frozen=True)
class RegimeSpec:
    name: str
    params: dict = field(default_factory=dict)
    source: str = "spot_bars"
    effective_lag: str = "1d"

    def __post_init__(self):
        if self.name not in VALID_NAMES:
            raise ValueError(f"unknown regime {self.name!r} (valid: {VALID_NAMES})")
        if len(self.params) > MAX_PARAMS:
            raise ValueError(f"regime {self.name}: {len(self.params)} params > {MAX_PARAMS}")


def regime_key(spec: RegimeSpec, source_sha: str) -> str:
    return sha256_canon({"spec": asdict(spec), "src": source_sha,
                         "code": REGIME_CODE_VERSION})[:12]


def daily_closes(bars: pd.DataFrame) -> pd.Series:
    """Daily close series (UTC calendar days) from a canonical bar frame with ts+close.
    Returned index is NAIVE UTC — the population convention (entry_ts strings are naive
    UTC), so downstream merge_asof joins never mix aware/naive dtypes."""
    b = bars[["ts", "close"]].copy()
    ts = pd.to_datetime(b["ts"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
    b["ts"] = ts
    return b.set_index("ts")["close"].resample("1D").last().dropna()


def compute_regime(spec: RegimeSpec, bars: pd.DataFrame) -> pd.DataFrame:
    """-> DataFrame[label_ts, label(int8), effective_ts]. label at label_ts uses data
    <= label_ts ONLY; effective_ts = label_ts + 1 day at 00:00 UTC (daily regimes)."""
    close = daily_closes(bars)
    if spec.name == "trend_sma":
        f, s = int(spec.params["fast_d"]), int(spec.params["slow_d"])
        if f >= s:
            raise ValueError(f"trend_sma: fast_d {f} must be < slow_d {s}")
        label = (close.rolling(f).mean() > close.rolling(s).mean()).astype("int8")
        label = label[close.rolling(s).mean().notna()]
    elif spec.name == "vol_tercile":
        w = int(spec.params["window_d"])
        lr = np.log(close).diff()
        rv = lr.rolling(w).std()
        # causal tercile boundaries: expanding quantiles of PAST rv only (shifted so the
        # boundary at day D is computed from rv up to D-1)
        q33 = rv.expanding(_WARMUP_DAYS).quantile(1 / 3).shift(1)
        q67 = rv.expanding(_WARMUP_DAYS).quantile(2 / 3).shift(1)
        ok = rv.notna() & q33.notna() & q67.notna()
        label = pd.Series(np.select([rv <= q33, rv <= q67], [0, 1], default=2),
                          index=rv.index).astype("int8")[ok]
    else:  # pragma: no cover — guarded by __post_init__
        raise ValueError(spec.name)
    out = pd.DataFrame({"label_ts": label.index, "label": label.to_numpy()})
    # label from day D's close is effective from D+1 00:00 UTC
    out["effective_ts"] = out["label_ts"].dt.normalize() + pd.Timedelta(days=1)
    return out.reset_index(drop=True)
