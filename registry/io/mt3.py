"""The ONE canonical MT3 CSV reader (deprecates the divergent copies; basis: LightMinerPy's
loader + the utc=True fix). Bridge-scope (pandas)."""
from __future__ import annotations

from pathlib import Path


def read_mt3_csv(path: str | Path):
    """MT3 1-minute export → DataFrame with UTC DatetimeIndex and columns
    open/high/low/close/volume/spread/tickvol (missing ones filled with 0 — the zerovol
    variant zeroes volume/spread/tickvol by construction)."""
    import pandas as pd

    df = pd.read_csv(path, header=None)
    ncols = df.shape[1]
    if ncols >= 9:
        df.columns = ["date", "time", "open", "high", "low", "close",
                      "tickvol", "volume", "spread"][:ncols]
    elif ncols >= 7:
        df.columns = ["date", "time", "open", "high", "low", "close", "volume"][:ncols]
    else:
        raise ValueError(f"unexpected MT3 column count: {ncols}")
    ts = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str),
                        format="%Y.%m.%d %H:%M", utc=True)   # the utc=True fix
    out = df.drop(columns=["date", "time"]).set_index(ts)
    out.index.name = "ts"
    for col in ("volume", "spread", "tickvol"):
        if col not in out.columns:
            out[col] = 0
    return out[["open", "high", "low", "close", "volume", "spread", "tickvol"]]
