"""marketdata.fetch_binance_futures — USDT-M futures dumps from data.binance.vision (v3).

Today: funding rates (monthly zips, ~3 events/day, 2019-09+). Same no-key public dumps as
the spot fetcher. Output: canonical parquet [ts (UTC event/settlement time, naive), rate].
A funding rate is FINAL at its settlement ts — usable for entries strictly after ts.
Snapshot discipline: callers pin the output sha in the ledger; re-fetch = new snapshot.

Usage: python -m registry.marketdata.fetch_binance_futures --symbol BTCUSDT \
           --start 2019-09 --out .../funding_BTCUSDT.parquet
"""
from __future__ import annotations

import argparse
import io
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


def _months(start: str) -> list[str]:
    now = datetime.now(timezone.utc)
    end_y, end_m = now.year, now.month  # current month has no monthly dump yet
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while (y, m) < (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _fetch_month(symbol: str, month: str) -> pd.DataFrame | None:
    url = f"{BASE}/{symbol}/{symbol}-fundingRate-{month}.zip"
    try:
        raw = urllib.request.urlopen(url, timeout=60).read()
    except Exception:  # noqa: BLE001 — pre-listing months simply don't exist
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None)
    if not str(df.iloc[0, 0]).lstrip("-").isdigit():      # header row present
        df = df.iloc[1:].reset_index(drop=True)
    ts_ms = pd.to_numeric(df.iloc[:, 0])
    unit = "us" if ts_ms.iloc[0] > 10**14 else "ms"       # 2025+ dumps switched to micros
    return pd.DataFrame({"ts": pd.to_datetime(ts_ms, unit=unit),
                         "rate": pd.to_numeric(df.iloc[:, -1])})


def fetch(symbol: str, start: str, out: Path) -> None:
    frames = []
    for month in _months(start):
        df = _fetch_month(symbol, month)
        if df is not None:
            frames.append(df)
    if not frames:
        raise RuntimeError("no funding months fetched")
    allf = (pd.concat(frames).drop_duplicates("ts").sort_values("ts")
            .reset_index(drop=True))
    out.parent.mkdir(parents=True, exist_ok=True)
    allf.to_parquet(out, index=False)
    print(f"funding: {len(allf)} events {allf.ts.min()} .. {allf.ts.max()} -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default="2019-09")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    fetch(a.symbol, a.start, a.out)


if __name__ == "__main__":
    main()
