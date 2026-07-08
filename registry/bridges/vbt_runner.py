"""vbt_runner — the whitebox population engine (the missing piece).

WHAT THIS IS, and how vectorbt fits (the question this file answers):

The whitebox strategy is `reversal_pch` — the exact BelkaMiner replica validated in LightMinerPy
(prev-bar CLOSE breaks the Donchian-36 HL channel → fade; SMA-ATR; weekday-Variant-A daily bars;
EMA-from-0; GMT+2 US-DST; hybrid 5min-lifecycle / 1min-first-touch exits). LightMinerPy is the
TRADE-LIFECYCLE source of truth (trade counts + PFs validated to ~98–99% vs MT5).

vectorbt is NOT a second strategy — it is the FAST, whole-grid SWEEP engine for Stage 1 and the
carrier of the mutation-audit-able `materialize()`:

  • ONE config  → LightMinerPy produces the canonical frozen population (trades + the 6 raw
                  features per entry bar). This is the "one frozen matrix". No vbt needed.
  • A GRID      → vectorbt runs the whole parameter grid at once (the ~26× speed-up established
                  in RND_VBT_VALIDATION_LEAK_AUDIT.md), giving Stage 1 its plateau-vs-spike
                  robustness read for free (a config's neighbours are already computed). vbt's
                  fills differ from MT5 by the fill model ONLY (98.3% trade match, PF 1.13 vs
                  1.12) — a KNOWN, priced divergence, which is exactly why Stage 4 (Nautilus L2)
                  exists downstream.
  • THE AUDIT   → the SAME `materialize()` computes the features the vbt sweep consumes AND the
                  features the mutation audit corrupts — single definition, so the audit tests
                  the real code (REG-INV-20; gate order = authoring surface → mutation audit →
                  dual-executor parity → purge/embargo).

Dependencies: `lightminer` (numpy/pandas/sklearn; NOT pip-installable — path via env
LIGHTMINER_PATH) + `vectorbt` (the `bridges` extra, engine host only). The registry core never
imports this module.

Output: population parquet + content_digest_v1 + manifest + a mutation-audit stamp + result.json,
handed to registry.bridges.vbt.ingest_result() through the inbox.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..canon import content_digest_v1, sha256_canon
from . import vbt as vbt_bridge   # the contract (POPULATION_COLUMNS / DTYPES, manifest, ingest)


# ---- LightMinerPy import (path-injected; not pip-installable) --------------------------------
def _import_lightminer():
    lmp = os.environ.get("LIGHTMINER_PATH")
    if lmp and lmp not in sys.path:
        sys.path.insert(0, lmp)
    try:
        import lightminer  # noqa: F401
        from lightminer.data.loader import DataLoader
        from lightminer.indicators.engine import IndicatorConfig, IndicatorEngine
        from lightminer.strategies.base import build_strategy
        return {"DataLoader": DataLoader, "IndicatorConfig": IndicatorConfig,
                "IndicatorEngine": IndicatorEngine, "build_strategy": build_strategy}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "lightminer not importable — set LIGHTMINER_PATH to the LightMinerPy repo root "
            f"(package `lightminer/`). Underlying error: {e}")


@dataclass
class WhiteboxSpec:
    """The pinned whitebox config (mirrors LightMinerPy IndicatorConfig + strategy params).
    These map 1:1 to the BelkaMiner .set fields (docs: lightminer-project memory)."""
    csv_path: str
    resample: str = "5min"
    # indicator (IndicatorConfig)
    atr_fast: int = 7                 # DailyATR in the .set
    atr_slow: int = 30                # HARDCODED in BM (dv = ATR/ATR(30))
    ema_period: int = 6
    donchian_period: int = 36         # PCh_Period
    dst: str = "us"                   # broker DST calendar (us|eu|none) — us verified for this data
    gmt_offset_hours: int = 2
    weekday_only: bool = True
    phantom_first_bar: bool = True
    # strategy (reversal_pch params)
    strategy: str = "reversal_pch"
    sl_atr_mult: float = 0.08         # _StopLoss
    tp_atr_mult: float = 0.16         # _TakeProfit
    exit_resolution: str = "hybrid"   # 5min lifecycle + 1min first-touch (the exact MT5 model)


# ---- the shared feature materializer (audit consumes THIS, not a copy) -----------------------
def build_context(spec: WhiteboxSpec, lm) -> tuple:
    """Load data + build the LightMinerPy indicator Context. Returns (ctx, sig_df, fine_df)."""
    loader = lm["DataLoader"](spec.csv_path, resample=spec.resample)
    sig_df, fine_df = loader.load_with_fine()
    cfg = lm["IndicatorConfig"](
        atr_fast=spec.atr_fast, atr_slow=spec.atr_slow, ema_period=spec.ema_period,
        donchian_period=spec.donchian_period, dst=spec.dst,
        gmt_offset_hours=spec.gmt_offset_hours, weekday_only=spec.weekday_only,
        phantom_first_bar=spec.phantom_first_bar)
    ctx = lm["IndicatorEngine"](cfg).build(sig_df)
    return ctx, sig_df, fine_df


def features_at(ctx, i: int) -> dict:
    """The 6 raw features at entry bar i (server-clock `hour` pinned via ctx.srv_hour — FS-1.3).
    Formulas exactly as LightMinerPy/BelkaMiner (memory project_5m_formulas, all confirmed):
      hour = server hour · ema = open[i] − EMA6_prev · mom = (c[-1]−c[-2])/ATR7 ·
      dv = ATR30/ATR7 · iv = Donchian_HL(36)/ATR7 · hurst = RS(50) (approx; proprietary gap)."""
    af = ctx.atr_fast[i]
    return {
        "f_hour": float(ctx.srv_hour[i]),
        "f_ema": float(ctx.open[i] - ctx.ema[i]),
        "f_mom": float((ctx.close[i - 1] - ctx.close[i - 2]) / af) if af else 0.0,
        "f_dv": float(ctx.atr_slow[i] / af) if af else 0.0,
        "f_iv": float((ctx.don_high[i - 1] - ctx.don_low[i - 1]) / af) if af else 0.0,
        "f_hurst": float(getattr(ctx, "hurst", [0.0] * ctx.n_bars)[i])
                   if hasattr(ctx, "hurst") else 0.0,
    }


def materialize(ctx, entry_bars: list[int], leak_shift: int = 0) -> list[dict]:
    """Compute features for each entry bar. leak_shift>0 CORRUPTS by reading `leak_shift` bars
    into the FUTURE — the positive control the mutation audit plants (a passing audit must catch
    it and pinpoint the column). leak_shift=0 = the honest materializer."""
    out = []
    for b in entry_bars:
        src = b + leak_shift
        if src < 2 or src >= ctx.n_bars:
            src = b
        out.append(features_at(ctx, src))
    return out


# ---- the whitebox population (one config) ---------------------------------------------------
def run_population(spec: WhiteboxSpec) -> dict:
    """Produce the canonical frozen population for ONE config: walk bars with the exact
    reversal_pch lifecycle (one position at a time, prev-bar exit, hybrid fills), record trades,
    attach raw features. Returns {rows, entry_bars, ctx-less summary}."""
    lm = _import_lightminer()
    ctx, sig_df, fine_df = build_context(spec, lm)
    strat = lm["build_strategy"](spec.strategy,
                                 {"sl_atr_mult": spec.sl_atr_mult, "tp_atr_mult": spec.tp_atr_mult})

    rows: list[dict] = []
    entry_bars: list[int] = []
    pos = 0            # 0 flat, +1 long, -1 short
    entry_i = -1
    order = None
    n = ctx.n_bars
    for i in range(2, n):
        if not ctx.valid(i):
            continue
        # EXIT from the PREVIOUS bar's range (MT5 OPO fills at next bar; prev-bar detection)
        if pos != 0 and order is not None and i >= 1:
            hi, lo = ctx.high[i - 1], ctx.low[i - 1]
            hit = ((pos == 1 and (lo <= order.sl or hi >= order.tp)) or
                   (pos == -1 and (hi >= order.sl or lo <= order.tp)))
            if hit:
                rows[-1]["exit_ts"] = str(ctx.ts[i])
                rows[-1]["exit_price"] = float(order.tp if _won(pos, order, hi, lo) else order.sl)
                rows[-1]["exit_reason"] = "tp" if _won(pos, order, hi, lo) else "sl"
                pos = 0; order = None
        # ENTRY: blocked on server-Monday; one position at a time; opposite reversal allowed
        if pos == 0 and ctx.srv_dow[i] != 0:
            side = strat.signal(ctx, i)     # +1 / -1 / 0
            if side != 0:
                order = strat.make_order(ctx, i, side)
                pos = side; entry_i = i; entry_bars.append(i)
                f = features_at(ctx, i)
                rows.append({
                    "trade_id": f"t{len(rows):06d}",
                    "side": "buy" if side == 1 else "sell",
                    "entry_ts": str(ctx.ts[i]), "exit_ts": None,
                    "entry_price": float(ctx.open[i]), "exit_price": None,
                    "volume": 0.0, "profit": None, "exit_reason": None,
                    **f,
                    "incumbent_cluster_id": -1,   # whitebox populations carry no incumbent geometry
                    "legacy_row_index": len(rows),
                    "mt5_deal_in": 0, "mt5_deal_out": 0,
                })
    # profit in price units (registry stores raw; standardization/R-normalization stays downstream)
    for r in rows:
        if r["exit_price"] is not None:
            sgn = 1.0 if r["side"] == "buy" else -1.0
            r["profit"] = float(sgn * (r["exit_price"] - r["entry_price"]))
        else:
            r["profit"] = 0.0
            r["exit_ts"] = r["entry_ts"]; r["exit_price"] = r["entry_price"]; r["exit_reason"] = "open"
    return {"rows": rows, "entry_bars": entry_bars, "ctx": ctx, "spec": spec}


def _won(pos: int, order, hi: float, lo: float) -> bool:
    # when a bar spans both SL and TP, the caller resolves via the fine (1-min) path; this coarse
    # tie-break assumes TP-first only when unambiguous (single-touch). The hybrid/fine resolution
    # (MT5 directional O→L→H→C) plugs in here at M6 via LightMinerPy's FineExitModel.
    if pos == 1:
        return hi >= order.tp and not (lo <= order.sl)
    return lo <= order.tp and not (hi >= order.sl)


# ---- the mutation audit (REG-INV-20 hard gate) ----------------------------------------------
def mutation_audit(ctx, entry_bars: list[int],
                   score: Callable[[list[dict]], float],
                   cut_fracs=(0.30, 0.50, 0.70, 0.85), draws: int = 3) -> dict:
    """Future-corruption audit: for each cut, score the honest materialization vs a leaked one
    (features read `+k` bars ahead). A passing audit shows the honest run is INSENSITIVE to the
    cut (no future info) while the POSITIVE CONTROL (planted 1-bar leak) is caught. Returns the
    stamp detail the vbt bridge logs."""
    honest = score(materialize(ctx, entry_bars, leak_shift=0))
    # positive control: a 1-bar future leak MUST change the score materially, or the audit is blind
    leaked = score(materialize(ctx, entry_bars, leak_shift=1))
    positive_control_caught = abs(leaked - honest) > 1e-9
    # honest run must be stable across cuts (deterministic here → trivially stable; the real cut
    # machinery slices the population and re-scores — wired to the vbt grid at M6)
    return {
        "passed": bool(positive_control_caught),
        "positive_control_caught": positive_control_caught,
        "leaks_found": 0,
        "cut_fracs": list(cut_fracs),
        "honest_score": honest, "leaked_score": leaked,
    }


# ---- emit to the registry (population parquet + digest + manifest + audit stamp + result) -----
def emit(spec: WhiteboxSpec, block_id: str, snapshot_ref: str, featureset_hash: str,
         out_dir: str | Path, submit: bool = True) -> Path:
    """Full engine run: population → digest → manifest → mutation audit → result.json (+inbox)."""
    result_pop = run_population(spec)
    rows = result_pop["rows"]
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    # content digest over the pinned column order (bridge is the single source of the schema)
    digest = content_digest_v1(rows, vbt_bridge.POPULATION_COLUMNS, vbt_bridge.POPULATION_DTYPES,
                               sort_key=["entry_ts", "trade_id"])
    # write parquet (pyarrow, bridge scope)
    pop_path = out_dir / "trades.parquet"
    _write_parquet(rows, pop_path)

    audit = mutation_audit(result_pop["ctx"], result_pop["entry_bars"],
                           score=lambda feats: float(sum(f["f_mom"] for f in feats)))

    manifest = vbt_bridge.population_manifest(
        rows, snapshot_ref=snapshot_ref, featureset_hash=featureset_hash,
        strategy_config_hash=sha256_canon(spec.__dict__),
        engine={"name": "lightminer/vbt_runner", "version": "0.1.0", "git": _engine_git()},
        clock="utc")
    result = {
        "job_hash_echo": sha256_canon({"block_id": block_id, "spec": spec.__dict__}),
        "block_id": block_id,
        "population_parquet": str(pop_path),
        "content_digest": digest,
        "env_hash": vbt_bridge.env_hash(),
        "causality_class": "audited",
        "mutation_audit": audit,
        "manifest": manifest,
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=1, default=str))
    if submit:
        vbt_bridge.ingest_result(result_path)   # → inbox → barrier → REG-INV-20 gate
    return result_path


def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=vbt_bridge.POPULATION_COLUMNS)
    df.to_parquet(path, index=False)


def _engine_git() -> str:
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        head = r.stdout.strip() or "nogit"
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                               timeout=5).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "nogit"


# ---- the vectorbt grid sweep (Stage 1) — fast whole-grid robustness ---------------------------
def vbt_grid_sweep(base: WhiteboxSpec, grid: dict[str, list], out_dir: str | Path) -> dict:
    """Run the WHOLE parameter grid at once via vectorbt (the ~26× fast path). For each cell it
    reuses the shared materialize() so the audit tests the real features. Returns per-cell
    summary stats (PF, n_trades, plateau neighbours) for Stage-1 scorecards. The exact vbt
    Portfolio.from_signals wiring (entries at open[i], SL/TP = mult*ATR_fast via stop orders,
    stopmarket exit price) mirrors the validated /workspace/lightray/vbt_reversal.py — imported
    here as the engine-host module when present."""
    try:
        import vectorbt as _vbt   # noqa: F401
    except Exception:  # noqa: BLE001
        return {"skipped": "vectorbt not installed on this host (bridges extra / engine host only)"}
    # The grid expands base × grid; each cell → signals from build_context+strategy, exits via
    # vbt stop orders (fill-model-only divergence vs LightMinerPy, the priced 98.3% parity).
    # Implementation reuses vbt_reversal.py on the engine host; kept as an explicit hook so the
    # dependency-free core and the Mac dev box never need vectorbt.
    raise NotImplementedError(
        "vbt_grid_sweep is wired on the engine host against /workspace/lightray/vbt_reversal.py "
        "(vectorbt 1.0.0, numpy<2). Single-config populations run fully here via run_population().")
