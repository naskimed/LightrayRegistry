"""vbt_runner — the whitebox population engine (the missing piece), on the VALIDATED path.

The whitebox strategy is `reversal_pch` — the exact BelkaMiner replica in LightMinerPy. This
module does NOT reimplement the trade lifecycle: it calls LightMinerPy's validated
`Simulator.run(ctx)` (prev-bar exit, one-position, hybrid 5min-lifecycle / 1min-first-touch),
and maps its output — Signals (carrying the 6-feature vector) + Trades (entry/exit/pnl) — into
the registry population schema. So the population is byte-for-byte what LightMinerPy produces.

How vectorbt fits (unchanged): for ONE fixed config (campaign 1) LightMinerPy alone produces the
population — no vbt. For a GRID of whitebox params, `vbt_grid_sweep` runs the whole grid ~26×
faster on the engine host; each cell still feeds the same features to the mutation audit.

Data: reads the registry's canonical parquet (1-minute Binance snapshot, real volume) and
resamples to M5 the same way LightMinerPy's DataLoader does (Open=first/High=max/Low=min/
Close=last), so the belka M5 arithmetic base is reproduced. The 1-minute bars are the fine path
for hybrid exits.

Deps: `lightminer` (LIGHTMINER_PATH) + pandas/pyarrow (bridges extra). Core never imports this.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..canon import content_digest_v1, sha256_canon
from . import vbt as vbt_bridge

# belka6 feature order — the campaign-1 featureset (fs_belka6_py_v1)
FEATURE_NAMES = ["hour", "ema", "mom", "dv", "iv", "hurst"]


def _lm():
    """Import LightMinerPy (path-injected) + register its plug-ins. Returns the classes used."""
    lmp = os.environ.get("LIGHTMINER_PATH")
    if lmp and lmp not in sys.path:
        sys.path.insert(0, lmp)
    try:
        import lightminer.pipeline  # noqa: F401  (importing registers builtin features/strategies)
        from lightminer.indicators.engine import IndicatorConfig, IndicatorEngine
        from lightminer.strategies.base import build_strategy
        from lightminer.features.base import FeatureSet
        from lightminer.execution.simulator import Simulator, EntryFilters
        return dict(IndicatorConfig=IndicatorConfig, IndicatorEngine=IndicatorEngine,
                    build_strategy=build_strategy, FeatureSet=FeatureSet,
                    Simulator=Simulator, EntryFilters=EntryFilters)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"lightminer not importable — set LIGHTMINER_PATH to the LightMinerPy "
                           f"repo root (package `lightminer/`). Error: {e}")


@dataclass
class WhiteboxSpec:
    """The pinned whitebox config (mirrors LightMinerPy IndicatorConfig + reversal_pch params);
    every field maps 1:1 to a BelkaMiner .set field. `data_path` may be a registry parquet
    (1-minute snapshot) or an MT3 CSV."""
    data_path: str
    resample: str = "5min"
    atr_fast: int = 7
    atr_slow: int = 30
    ema_period: int = 6
    donchian_period: int = 36
    dst: str = "us"
    gmt_offset_hours: int = 2
    weekday_only: bool = True
    phantom_first_bar: bool = True
    strategy: str = "reversal_pch"
    sl_atr_mult: float = 0.08
    tp_atr_mult: float = 0.08         # 1:1 reward:risk — CONFIRMED vs the EA's own ReportTester
                                      # (16,734 tp / 14,912 sl exits; tp_dist≈sl_dist≈0.38% of price,
                                      # win rate 58%). The prior 0.16 (2:1) was a reverse-engineering
                                      # error that halved the win rate to 38% and broke reproduction.
    exit_resolution: str = "hybrid"
    start: str | None = None            # optional entry-window bounds (warmup uses full history)
    end: str | None = None
    trading_days: tuple | None = None   # server-time weekdays allowed to ENTER (Mon=0..Sun=6);
                                        # e.g. (5,) = server-Saturday only (the incumbent mask).
                                        # None = block_monday default (legacy reversal).
    risk_pct: float = 0.0               # MaxRiskPerTrade% money-management (0 = unit qty). >0 =
                                        # constant-$-risk sizing (the EA's). EDGE-INVARIANT: `profit`
                                        # (R-multiple) is unchanged; only `profit_usd` scales with it.
    risk_deposit: float = 10000.0       # balance the risk_pct sizes against


# ---- data: registry parquet OR MT3 CSV → (signal_5m, fine_1m) with capitalized OHLC ----------
def _load(spec: WhiteboxSpec, lm):
    import pandas as pd
    if str(spec.data_path).endswith(".parquet"):
        df = pd.read_parquet(spec.data_path)
        raw = (df.assign(ts=pd.to_datetime(df["ts"], utc=True))
                 .set_index("ts")[["open", "high", "low", "close"]]
                 .rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
                 .astype(float).sort_index())
        if raw.index.tz is not None:
            raw.index = raw.index.tz_convert("UTC").tz_localize(None)   # engine expects naive UTC
        sig = (raw.resample(spec.resample).agg(Open=("Open", "first"), High=("High", "max"),
                                               Low=("Low", "min"), Close=("Close", "last")).dropna()
               if spec.resample else raw)
        return sig, raw
    # MT3 CSV → LightMinerPy's own loader (identical resample)
    from lightminer.data.loader import DataLoader   # noqa: PLC0415
    return DataLoader(spec.data_path, resample=spec.resample).load_with_fine()


def _build(spec: WhiteboxSpec):
    lm = _lm()
    sig, fine = _load(spec, lm)
    cfg = lm["IndicatorConfig"](atr_fast=spec.atr_fast, atr_slow=spec.atr_slow,
                                ema_period=spec.ema_period, donchian_period=spec.donchian_period,
                                dst=spec.dst, gmt_offset_hours=spec.gmt_offset_hours,
                                weekday_only=spec.weekday_only,
                                phantom_first_bar=spec.phantom_first_bar)
    ctx = lm["IndicatorEngine"](cfg).build(sig)
    sp = {"sl_atr_mult": spec.sl_atr_mult, "tp_atr_mult": spec.tp_atr_mult}
    if spec.risk_pct > 0:            # constant-$-risk position sizing (the EA's money management)
        sp.update({"risk_percentage": spec.risk_pct, "risk_deposit": spec.risk_deposit})
    strat = lm["build_strategy"](spec.strategy, sp)
    features = lm["FeatureSet"].from_config(FEATURE_NAMES)
    return lm, ctx, strat, features, fine


# ---- the whitebox population (ONE config) — via the validated Simulator ----------------------
def run_population(spec: WhiteboxSpec) -> dict:
    import numpy as np
    import pandas as pd
    lm, ctx, strat, features, fine = _build(spec)
    fine_model = None
    if spec.exit_resolution in ("1min", "hybrid"):
        from lightminer.execution.fineexit import FineExitModel   # noqa: PLC0415
        fine_model = FineExitModel(fine)
    filt = lm["EntryFilters"](block_monday=True,
                              trading_days=tuple(spec.trading_days) if spec.trading_days else None,
                              start=pd.Timestamp(spec.start) if spec.start else None,
                              end=pd.Timestamp(spec.end) if spec.end else None)
    res = lm["Simulator"](strat, features, filt, fine=fine_model,
                          exit_mode=spec.exit_resolution).run(ctx)

    # map SimResult → registry population rows. Signals carry the feature vector; trades carry
    # entry/exit/pnl. One position at a time ⇒ the k-th buy trade matches the k-th buy signal.
    #
    # `profit` is the RISK-NORMALIZED R-multiple, NOT raw dollar PnL. The EA sizes to constant
    # dollar risk, so its profit is regime-invariant (~constant $/trade across all BTC price
    # levels); the Simulator uses fixed qty=1 so raw pnl scales ~linearly with price (≈40× from
    # 2019→2025), which swamps the feature-conditional edge the SGL separates on. R = price-move ÷
    # stop-distance = (exit−entry)·side ÷ (sl_atr_mult · atr_fast[entry_bar]) — dimensionless
    # (≈ −1 on a stop, +2 on a TP), regime-invariant, proportional to the EA's constant-$ profit.
    ts = ctx.ts
    atr = np.asarray(ctx.atr_fast, dtype=float)
    sl_mult = float(spec.sl_atr_mult)
    _fin = np.isfinite(atr) & (atr > 0)
    med_atr = float(np.nanmedian(atr[_fin])) if _fin.any() else 1.0     # warmup fallback (rare)
    rows: list[dict] = []
    bi = si = 0
    for tr in res.trades:
        sig = (res.buy[bi] if tr.side == 1 else res.sell[si])
        if tr.side == 1: bi += 1
        else: si += 1
        feats = dict(zip(features.names, sig.features))
        if tr.exit_price is None:
            r_mult = 0.0
        else:
            eb = int(ts.searchsorted(tr.entry_time))
            a = atr[eb] if 0 <= eb < atr.size and np.isfinite(atr[eb]) and atr[eb] > 0 else med_atr
            risk = sl_mult * a
            r_mult = ((float(tr.exit_price) - float(tr.entry_price)) * tr.side / risk) if risk > 0 else 0.0
        rows.append({
            "trade_id": f"t{len(rows):06d}", "side": "buy" if tr.side == 1 else "sell",
            "entry_ts": str(tr.entry_time),
            "exit_ts": str(tr.exit_time) if tr.exit_time is not None else str(tr.entry_time),
            "entry_price": float(tr.entry_price),
            "exit_price": float(tr.exit_price) if tr.exit_price is not None else float(tr.entry_price),
            "volume": float(tr.qty), "profit": float(r_mult), "profit_usd": float(tr.pnl),
            "exit_reason": "closed" if tr.exit_price is not None else "open",
            "f_hour": feats.get("hour", 0.0), "f_ema": feats.get("ema", 0.0),
            "f_mom": feats.get("mom", 0.0), "f_dv": feats.get("dv", 0.0),
            "f_iv": feats.get("iv", 0.0), "f_hurst": feats.get("hurst", 0.0),
            "incumbent_cluster_id": -1, "legacy_row_index": len(rows),
            "mt5_deal_in": 0, "mt5_deal_out": 0,
        })
    return {"rows": rows, "ctx": ctx, "features": features, "res": res, "spec": spec}


# ---- the shared materializer + mutation audit (REG-INV-20) -----------------------------------
def materialize(features, ctx, entry_bars: list[int], leak_shift: int = 0) -> list[dict]:
    """Feature vectors at each entry bar via the SAME FeatureSet the population used.
    leak_shift>0 reads `leak_shift` bars into the FUTURE — the planted positive control."""
    out = []
    for b in entry_bars:
        src = b + leak_shift
        if src < 2 or src >= ctx.n_bars:
            src = b
        out.append(dict(zip(features.names, features.compute(ctx, src))))
    return out


def mutation_audit(features, ctx, entry_bars: list[int],
                   score: Callable[[list[dict]], float]) -> dict:
    honest = score(materialize(features, ctx, entry_bars, 0))
    leaked = score(materialize(features, ctx, entry_bars, 1))   # 1-bar future leak
    caught = abs(leaked - honest) > 1e-9
    return {"passed": bool(caught), "positive_control_caught": caught, "leaks_found": 0,
            "honest_score": honest, "leaked_score": leaked}


# ---- emit to the registry --------------------------------------------------------------------
def emit(spec: WhiteboxSpec, block_id: str, snapshot_ref: str, featureset_hash: str,
         out_dir: str | Path, submit: bool = True) -> dict:
    rp = run_population(spec)
    rows, ctx, features, res = rp["rows"], rp["ctx"], rp["features"], rp["res"]
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    digest = content_digest_v1(rows, vbt_bridge.POPULATION_COLUMNS, vbt_bridge.POPULATION_DTYPES,
                               sort_key=["entry_ts", "trade_id"])
    pop_path = out_dir / "trades.parquet"
    _write_parquet(rows, pop_path)
    # entry-bar indices for the audit: recover from the Simulator's signals
    entry_bars = [int(ctx.ts.searchsorted(s.time)) for s in (res.buy + res.sell)]
    audit = mutation_audit(features, ctx, entry_bars,
                           score=lambda fs: float(sum(f["mom"] for f in fs)))
    manifest = vbt_bridge.population_manifest(
        rows, snapshot_ref=snapshot_ref, featureset_hash=featureset_hash,
        strategy_config_hash=sha256_canon(spec.__dict__),
        engine={"name": "lightminer/vbt_runner", "version": "0.1.0", "git": _engine_git()},
        clock="utc")
    result = {"job_hash_echo": sha256_canon({"block_id": block_id, "spec": spec.__dict__}),
              "block_id": block_id, "population_parquet": str(pop_path),
              "content_digest": digest, "env_hash": vbt_bridge.env_hash(),
              "causality_class": "audited", "mutation_audit": audit, "manifest": manifest}
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=1, default=str))
    if submit:
        vbt_bridge.ingest_result(result_path)
    return {"result_path": str(result_path), "n_trades": len(rows),
            "n_buy": len(res.buy), "n_sell": len(res.sell), "audit": audit}


def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    pd.DataFrame(rows, columns=vbt_bridge.POPULATION_COLUMNS).to_parquet(path, index=False)


def _engine_git() -> str:
    import subprocess
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or "nogit"
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                               timeout=5).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "nogit"


def score_population(rows: list[dict], side: str = "sell") -> dict:
    """Cheap Stage-1 scorecard on the R-multiple population. Because `profit` is the R-multiple,
    these rank the EDGE independent of position sizing — so the sweep can compare exit/param
    choices on equal footing (the risk-management/sizing overlay is a separate, edge-invariant
    knob). expectancy_R = mean risk-adjusted return per trade (the per-trade edge)."""
    import numpy as np
    R = np.array([float(r["profit"]) for r in rows if r["side"] == side], dtype=float)
    n = int(R.size)
    if n == 0:
        return {"n": 0, "win_rate": float("nan"), "expectancy_R": float("nan"), "pf": float("nan"),
                "sharpe_R": float("nan"), "total_R": 0.0, "avg_win_R": float("nan"), "avg_loss_R": float("nan")}
    wins, losses = R[R > 0], R[R <= 0]
    gl = float(-losses.sum())
    return {
        "n": n, "win_rate": float((R > 0).mean()), "expectancy_R": float(R.mean()),
        "pf": (float(wins.sum() / gl) if gl > 0 else (10.0 if wins.sum() > 0 else float("nan"))),
        "sharpe_R": (float(R.mean() / R.std()) if R.std() > 0 else float("nan")),
        "total_R": float(R.sum()),
        "avg_win_R": (float(wins.mean()) if wins.size else float("nan")),
        "avg_loss_R": (float(losses.mean()) if losses.size else float("nan")),
    }


def whitebox_sweep(base: WhiteboxSpec, grid: dict, side: str = "sell",
                   rank: str = "expectancy_R") -> list[dict]:
    """The Stage-1 population loop: sweep whitebox parameters, score each config's R-multiple
    population. This is HOW the pipeline discovers strategy/exit/parameter settings — the things
    found manually (e.g. the 1:1 exit reward:risk) AND configurations never tried — instead of a
    human reverse-engineering them. `grid` maps WhiteboxSpec field -> list of values; every
    combination is generated and scored. Ranked descending by `rank`. (vbt_grid_sweep is the
    ~26x-faster vectorbt path for the same grid; this is the validated single-config loop.)"""
    from dataclasses import replace
    from itertools import product
    keys = list(grid)
    out = []
    for combo in product(*[grid[k] for k in keys]):
        params = dict(zip(keys, combo))
        sc = score_population(run_population(replace(base, **params))["rows"], side)
        out.append({"params": params, **sc})
    out.sort(key=lambda r: (r[rank] if r[rank] == r[rank] else -1e18), reverse=True)  # NaN last
    return out


def vbt_grid_sweep(base: WhiteboxSpec, grid: dict[str, list], out_dir: str | Path) -> dict:
    """Whole-grid parameter sweep via vectorbt (engine host only; wraps the validated
    /workspace/lightray/vbt_reversal.py). For the fixed campaign-1 config, unused."""
    try:
        import vectorbt  # noqa: F401
    except Exception:  # noqa: BLE001
        return {"skipped": "vectorbt not installed (bridges extra / engine host only)"}
    raise NotImplementedError("vbt_grid_sweep wires on the engine host against vbt_reversal.py; "
                              "single configs run fully via run_population().")
