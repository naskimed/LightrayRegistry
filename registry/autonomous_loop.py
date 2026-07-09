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

from .cascade_run import Ledger, LookBudget, cycle, generate_population

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

ROLE_PROMPT = f"""You are the BOUNDARY research agent of an autonomous trading-research registry \
on ONE market (BTC). You see only the ledger digest below — never raw trades or OOS numbers you \
haven't already been shown. Your job: propose the NEXT whitebox config to explore, or stop. You \
may ONLY choose values from this fixed menu (apparatus — windows, budgets, gates — is human-only):

  strategy: reversal_pch (fade the channel break) | breakout_pch (trade with it) | momentum_pa
  sl_atr_mult: 0.05 | 0.08 | 0.12        tp_atr_mult: 0.05 | 0.08 | 0.12 | 0.16 | 0.24
  donchian_period: 20 | 36 | 50          atr_fast: 7 | 14
  trading_days: saturday | all | weekend | monday        side: sell | buy

Reply with EXACTLY ONE JSON object, no prose, no code fence:
  {{"action":"explore","strategy":"...","sl_atr_mult":..,"tp_atr_mult":..,"donchian_period":..,\
"atr_fast":..,"trading_days":"..","side":"..","hypothesis":"<what structure you expect and why>"}}
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
    if not ledger_path.exists():
        return "(no cycles yet — first proposal)"
    out, cur = [], None
    for l in ledger_path.read_text().splitlines():
        e = json.loads(l); p = e["payload"]; t = e["type"]
        if t == "cycle.open":
            cur = p.get("spec", {})
            out.append(f"cycle: {p.get('side')} {json.dumps(cur)[:120]}")
        elif t == "cycle.population_invalid":
            out.append("  -> POPULATION INVALID (too sparse for the windows)")
        elif t == "stage.search.result":
            out.append(f"  search: K={p['selected_K']} z={p['selected_z']:.2f} "
                       f"gate={p['gate_ref']:.2f} -> beats_gate={p['beats_gate']}")
        elif t == "cycle.no_candidate":
            out.append("  -> KILLED AT GATE (chance-level)")
        elif t == "readout.record":
            out.append(f"  -> READOUT uplift={p['uplift']:+.3f} certified={p['certified']} "
                       f"(fails: {[k for k, v in p['clauses'].items() if v is False]})")
        elif t == "agent.proposal":
            pass
    return "\n".join(out) or "(no completed cycles yet)"


def ask_agent(digest: str, budget_remaining: int, cap: Path) -> dict:
    prompt = (f"{ROLE_PROMPT}\n\n=== LEDGER DIGEST (configs explored so far) ===\n{digest}\n\n"
              f"budget slots remaining: {budget_remaining}\n\nYour one-JSON decision:")
    r = subprocess.run([CLAUDE, "--print", "--output-format", "json", prompt],
                       capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    cap.write_text(r.stdout)
    text = json.loads(r.stdout).get("result", "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)


def validate(prop: dict) -> dict | None:
    """Enforce the menu — reject anything off-menu (the agent cannot invent values)."""
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
    return spec


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
            prop = ask_agent(ledger_digest(workdir / "events.jsonl"), budget.state["remaining"], cap)
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
        spec = validate(prop)
        if spec is None:
            ledger.append("agent.rejected", {"cycle": i, "reason": "off-menu proposal"}); continue
        side = prop["side"]
        tag = f"{spec['strategy']}_{prop['trading_days']}_d{spec['donchian_period']}_a{spec['atr_fast']}" \
              f"_sl{spec['sl_atr_mult']}_tp{spec['tp_atr_mult']}_{side}"
        try:
            pop, sha, n_sell, n_buy = generate_population(dict(spec), workdir / "pops")
        except Exception as e:  # noqa: BLE001
            ledger.append("population.failed", {"cycle": i, "error": str(e)[:200]}); continue
        ledger.append("population.generated", {"cycle": i, "tag": tag, "sha256": sha,
                                               "n_sell": n_sell, "n_buy": n_buy, "spec": spec})
        out = cycle(contract, pop, side, workdir, ledger, budget, trials, runs_per_k, seed_points,
                    spec=spec, tag=tag)
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
