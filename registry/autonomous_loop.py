"""autonomous_loop — the AGENT does real research (M8/M9 top layer).

The boundary agent (`claude --print`) reads the ledger digest + budget and proposes the next
WHITEBOX config to explore — strategy family, exit reward:risk, structural params, side — or
stops. The cascade then MATERIALISES that population, runs the masked search + null-of-max GATE,
and — only if the candidate beats its gate AND a look-budget slot remains — spends one look and
runs the OOS readout + five-clause verdict. In-sample exploration is free; OOS reads are the
scarce resource (budget 30). The GATE and BUDGET are enforced beneath the agent, which proposes
only from a fixed menu (apparatus is human-only, REG-INV-22). var/HALT stops before any dispatch.

This is the population loop + geometry loop coupled under an agent: the real research.

Usage (on the server):
    python -m registry.autonomous_loop --contract btc [--max-cycles 20] [--trials 40 --runs-per-k 1]
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .cascade_run import Ledger, LookBudget, cycle, generate_population, maybe_reanchor

CLAUDE = "/home/alex/.local/bin/claude"

# The bounded action space — the agent may ONLY pick from these (keeps the search honest + finite).
MENU = {
    "strategy": ["reversal_pch", "breakout_pch", "momentum_pa"],
    "sl_atr_mult": [0.05, 0.08, 0.12],
    "tp_atr_mult": [0.05, 0.08, 0.12, 0.16, 0.24],
    "donchian_period": [20, 36, 50],
    "atr_fast": [7, 14],
    "trading_days": {"saturday": [5], "all": None, "weekend": [5, 6], "monday": [0]},
    "side": ["sell", "buy"],
}

# The FEATURE CATALOG (NS2) — the agent fills up to 12 SEATS from these (FS d_max=12, free
# seat-swapping ratified). "belka6" = the validated 6-feature set (no seats). fc_* = the
# 40-feature AFML catalog attached at entry bars, incl. the volume/order-flow family.
CATALOG = [
    "fc_ret_1", "fc_ret_5", "fc_ret_20", "fc_ret_50", "fc_fracdiff_d04", "fc_fracdiff_d06",
    "fc_rv_20", "fc_rv_50", "fc_parkinson_20", "fc_parkinson_50", "fc_yangzhang_20",
    "fc_yangzhang_50", "fc_garmanklass_20", "fc_rogerssatchell_20", "fc_vol_ratio_5_50",
    "fc_vol_of_vol_20", "fc_rsi_14", "fc_roc_10", "fc_macd_hist", "fc_bb_pctb_20",
    "fc_lr_slope_20", "fc_adx_14", "fc_ema_dist_20", "fc_skew_50", "fc_kurt_50",
    "fc_zscore_20", "fc_tsrank_50", "fc_clv", "fc_autocorr_5", "fc_var_ratio_2",
    "fc_amihud_20", "fc_vol_zscore_50", "fc_vwap_dist", "fc_taker_imb", "fc_taker_imb_ma20",
    "fc_corwin_schultz", "fc_roll_spread_20", "fc_hour_sin", "fc_hour_cos", "fc_dow",
]

ROLE_PROMPT = f"""You are the BOUNDARY research agent of an autonomous trading-research registry \
on ONE market (BTC). You see only the ledger digest below — never raw trades or OOS numbers you \
haven't already been shown. Your job: propose the NEXT whitebox config to explore, or stop. You \
may ONLY choose values from this fixed menu (apparatus — windows, budgets, gates — is human-only):

  strategy: reversal_pch (fade the channel break) | breakout_pch (trade with it) | momentum_pa
  sl_atr_mult: 0.05 | 0.08 | 0.12        tp_atr_mult: 0.05 | 0.08 | 0.12 | 0.16 | 0.24
  donchian_period: 20 | 36 | 50          atr_fast: 7 | 14
  trading_days: saturday | all | weekend | monday        side: sell | buy
  features: "belka6" (the validated 6-feature set) OR a list of 2-12 SEATS from the catalog:
    returns/stationarity: fc_ret_1 fc_ret_5 fc_ret_20 fc_ret_50 fc_fracdiff_d04 fc_fracdiff_d06
    volatility: fc_rv_20 fc_rv_50 fc_parkinson_20 fc_parkinson_50 fc_yangzhang_20 fc_yangzhang_50 \
fc_garmanklass_20 fc_rogerssatchell_20 fc_vol_ratio_5_50 fc_vol_of_vol_20
    trend/momentum: fc_rsi_14 fc_roc_10 fc_macd_hist fc_bb_pctb_20 fc_lr_slope_20 fc_adx_14 fc_ema_dist_20
    distributional: fc_skew_50 fc_kurt_50 fc_zscore_20 fc_tsrank_50 fc_clv
    serial: fc_autocorr_5 fc_var_ratio_2
    MICROSTRUCTURAL (volume/order-flow — the family price-only features never had): fc_amihud_20 \
fc_vol_zscore_50 fc_vwap_dist fc_taker_imb fc_taker_imb_ma20 fc_corwin_schultz fc_roll_spread_20
    time: fc_hour_sin fc_hour_cos fc_dow
  Seat guidance: avoid spending two seats on near-collinear features (e.g. many volatility \
estimators at the same window); mix families; the microstructural family is unexplored territory.

Reply with EXACTLY ONE JSON object, no prose, no code fence:
  {{"action":"explore","strategy":"...","sl_atr_mult":..,"tp_atr_mult":..,"donchian_period":..,\
"atr_fast":..,"trading_days":"..","side":"..","features":"belka6"|["fc_...",...],\
"hypothesis":"<what structure you expect and why>"}}
  {{"action":"stop","hypothesis":"<why nothing worth exploring remains>"}}

Research discipline you MUST follow:
- A config KILLED AT THE GATE means its in-sample separation is chance-level — do NOT re-propose \
the same or a trivially-different config hoping for a different number; that is noise-mining.
- A config that BEAT THE GATE but FAILED CERTIFICATION (clause 1 = weak in the deployment window) \
has real in-sample structure that doesn't generalize — vary the STRATEGY or STRUCTURE next, not a \
0.01 exit tweak.
- Explore the space with intent: cover families and structural regimes before fine exit tuning. \
Prefer configs whose hypothesis is mechanistically different from what's been tried.
- Every OOS readout spends one budget slot; the gate spends nothing. Spend looks on genuinely \
distinct, gate-beating hypotheses only.
- When the distinct, mechanistically-motivated ideas are exhausted or the budget is low, STOP — a \
thorough negative ('no certifiable structure across the explored space') is a real result."""


def ledger_digest(ledger_path: Path) -> str:
    """READ-DIET (fix 2026-07-10): the boundary agent sees VERDICTS, never out-of-sample
    magnitudes — uplift/PF numbers are conditioning fuel a proposer could slowly overfit the
    windows through. In-sample search quantities (z, gate) stay visible: they are free-layer."""
    if not ledger_path.exists():
        return "(no cycles yet — first proposal)"
    out = []
    for l in ledger_path.read_text().splitlines():
        e = json.loads(l); p = e["payload"]; t = e["type"]
        if t == "cycle.open":
            out.append(f"cycle: {p.get('side')} {json.dumps(p.get('spec', {}))[:120]}")
        elif t == "stage.baseline":
            if not p.get("healthy"):
                out.append(f"  -> BASELINE UNHEALTHY ({p.get('reason','')[:60]})")
        elif t == "stage.search.result":
            out.append(f"  search[{p.get('stage','?')}]: K={p['selected_K']} z={p['selected_z']:.2f} "
                       f"gate={p['gate_ref']:.2f} -> beats_gate={p['beats_gate']}")
        elif t == "cycle.no_candidate":
            out.append("  -> KILLED AT GATE (chance-level)")
        elif t == "cycle.parked":
            out.append(f"  -> PARKED: {str(p.get('reason',''))[:70]}")
        elif t == "readout.failed":
            out.append("  -> READOUT FAILED (engine error; spend recorded)")
        elif t == "readout.record":
            fails = [k for k, v in p["clauses"].items() if v is False]
            out.append(f"  -> READOUT VERDICT={p.get('verdict')} (failing clauses: {fails or 'none'})")
        elif t == "windowset.reanchor":
            out.append(f"  ** WINDOWSET RE-ANCHORED: virgin certifier {p['new_certifier']} (gen 2) **")
    return "\n".join(out) or "(no completed cycles yet)" or "(no completed cycles yet)"


def stage1_summary(workdir: Path, top: int = 15) -> str:
    """The mass-sweep map, condensed for the agent: TRAIN-ONLY baseline stats (free layer)."""
    p = workdir / "stage1_map.jsonl"
    if not p.exists():
        return ""
    rows = []
    for l in p.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        for side in ("sell", "buy"):
            s = r.get(side)
            if isinstance(s, dict) and s.get("healthy"):
                rows.append((s["train_pf"], f"{r['strategy']} {r['trading_days_name']} "
                             f"sl{r['sl_atr_mult']} tp{r['tp_atr_mult']} d{r['donchian_period']} "
                             f"a{r['atr_fast']} {side}: train_pf={s['train_pf']} "
                             f"exp={s['train_exp']} n={s['train_n']} w4n={s['w4_count']}"))
    if not rows:
        return ""
    rows.sort(reverse=True)
    return ("\n=== STAGE-1 MAP (masked-TRAIN baselines, free layer; top healthy configs) ===\n"
            + "\n".join(x[1] for x in rows[:top]))


def ask_agent(digest: str, budget_remaining: int, cap: Path, extra: str = "") -> dict:
    prompt = (f"{ROLE_PROMPT}\n\n=== LEDGER DIGEST (configs explored so far) ===\n{digest}\n"
              f"{extra}\n"
              f"budget slots remaining: {budget_remaining}\n\nYour one-JSON decision:")
    r = subprocess.run([CLAUDE, "--print", "--output-format", "json", prompt],
                       capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    cap.write_text(r.stdout)
    text = json.loads(r.stdout).get("result", "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)


def validate(prop: dict) -> tuple[dict, list[str] | None] | None:
    """Enforce the menu — reject anything off-menu (the agent cannot invent values).
    Returns (whitebox_spec, featureset) where featureset None = belka6."""
    if prop.get("action") != "explore":
        return None
    try:
        spec = {
            "strategy": prop["strategy"], "sl_atr_mult": float(prop["sl_atr_mult"]),
            "tp_atr_mult": float(prop["tp_atr_mult"]), "donchian_period": int(prop["donchian_period"]),
            "atr_fast": int(prop["atr_fast"]),
            "trading_days": MENU["trading_days"][prop["trading_days"]],
        }
    except (KeyError, ValueError, TypeError):
        return None
    if (spec["strategy"] not in MENU["strategy"] or spec["sl_atr_mult"] not in MENU["sl_atr_mult"]
            or spec["tp_atr_mult"] not in MENU["tp_atr_mult"]
            or spec["donchian_period"] not in MENU["donchian_period"]
            or spec["atr_fast"] not in MENU["atr_fast"] or prop.get("side") not in MENU["side"]):
        return None
    feats = prop.get("features", "belka6")
    if feats in (None, "belka6"):
        return spec, None
    if (isinstance(feats, list) and 2 <= len(feats) <= 12
            and all(f in CATALOG for f in feats) and len(set(feats)) == len(feats)):
        return spec, list(feats)
    return None


def run(contract: str, workdir: Path, max_cycles: int, trials: int, runs_per_k: int,
        seed_points: int) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir.parent / "var").mkdir(parents=True, exist_ok=True)
    ledger = Ledger(workdir / "events.jsonl")
    budget = LookBudget(workdir / f"budget_{contract}.json")   # ONE shared budget for the contract

    for i in range(1, max_cycles + 1):
        if (workdir.parent / "var" / "HALT").exists():
            ledger.append("loop.halted", {"cycle": i}); print("HALT."); return
        cap = workdir / f"agent_session_{i}.json"
        try:
            prop = ask_agent(ledger_digest(workdir / "events.jsonl"), budget.state["remaining"],
                             cap, stage1_summary(workdir))
        except Exception as e:  # noqa: BLE001
            ledger.append("agent.error", {"cycle": i, "error": str(e)[:200]}); print("agent error:", e); return
        ledger.append("agent.proposal", {"cycle": i, "action": prop.get("action"),
                                          "proposal": {k: prop.get(k) for k in
                                                       ("strategy", "sl_atr_mult", "tp_atr_mult",
                                                        "donchian_period", "atr_fast", "trading_days", "side")},
                                          "hypothesis": prop.get("hypothesis", "")[:300],
                                          "session_capture": str(cap)})
        print(f"\n=== cycle {i}: {prop.get('action')} {prop.get('strategy','')} {prop.get('side','')} ===")
        if prop.get("action") == "stop":
            ledger.append("loop.stopped", {"cycle": i, "by": "agent",
                                           "hypothesis": prop.get("hypothesis", "")[:300]})
            print("Agent STOP."); return
        v = validate(prop)
        if v is None:
            ledger.append("agent.rejected", {"cycle": i, "reason": "off-menu proposal"}); continue
        spec, featureset = v
        side = prop["side"]
        fs_suffix = "" if not featureset else f"_fs{len(featureset)}"
        tag = f"{spec['strategy']}_{prop['trading_days']}_d{spec['donchian_period']}_a{spec['atr_fast']}" \
              f"_sl{spec['sl_atr_mult']}_tp{spec['tp_atr_mult']}_{side}{fs_suffix}"
        try:
            pop, sha, n_sell, n_buy = generate_population(dict(spec), workdir / "pops",
                                                          with_catalog=bool(featureset))
        except Exception as e:  # noqa: BLE001
            ledger.append("population.failed", {"cycle": i, "error": str(e)[:200]}); continue
        ledger.append("population.generated", {"cycle": i, "tag": tag, "sha256": sha,
                                               "n_sell": n_sell, "n_buy": n_buy, "spec": spec,
                                               "featureset": featureset or "belka6"})
        # pre-signed W4 re-anchor: self-executes when the virgin-data trigger is met
        try:
            from .tools.build_sgl_jobs import PC_ACTIVE
            if maybe_reanchor(pop, PC_ACTIVE.parent, ledger):
                print("** windowset re-anchored (gen 2, virgin certifier) **")
        except Exception as e:  # noqa: BLE001
            ledger.append("reanchor.check_error", {"error": str(e)[:150]})
        # crash-continuation (fix 2026-07-10): one failed cycle must never kill the loop —
        # the failure is recorded and the agent sees it in the next digest.
        try:
            out = cycle(contract, pop, side, workdir, ledger, budget, trials, runs_per_k,
                        seed_points, spec=spec, tag=tag, featureset=featureset)
        except Exception as e:  # noqa: BLE001
            ledger.append("cycle.error", {"cycle": i, "tag": tag, "error": str(e)[-250:]})
            print(f"cycle {i} ERROR (recorded, continuing): {e}")
            continue
        print(f"cycle {i} -> {out.get('verdict')} (budget {budget.state['remaining']})")
    ledger.append("loop.max_cycles", {"max": max_cycles})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", default="btc")
    ap.add_argument("--workdir", default="/home/alex/lightray/research")
    ap.add_argument("--max-cycles", type=int, default=20)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--runs-per-k", type=int, default=1)
    ap.add_argument("--seed-points", type=int, default=10)
    a = ap.parse_args()
    run(a.contract, Path(a.workdir), a.max_cycles, a.trials, a.runs_per_k, a.seed_points)


if __name__ == "__main__":
    main()
