"""autonomous_loop — the AGENT takes over (M8/M9 top layer).

The boundary agent (`claude --print`) reads the ledger digest + budget, and proposes the NEXT
cycle as a bounded, structured decision (run a side, or stop). The cascade EXECUTES it — with the
null-of-max GATE and the look BUDGET enforced underneath, which the agent cannot reach or bypass
(it only proposes from a fixed action menu; apparatus is human-only, REG-INV-22). Every proposal
is recorded with the agent's hypothesis (discretionary schema); the raw agent session JSON is
captured as observer evidence (decision-7). `var/HALT` stops the loop before any dispatch.

This is the full loop: read cards -> agent proposes -> gated cycle -> record -> repeat.

Usage (on the server):
    python -m registry.autonomous_loop --population P.parquet --contract btc_sat \
        [--max-cycles 6] [--trials 30 --runs-per-k 1]   # small budget = fast demo
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .cascade_run import Ledger, LookBudget, cycle

CLAUDE = "/home/alex/.local/bin/claude"

ROLE_PROMPT = """You are the BOUNDARY agent of an autonomous trading-research registry. You do \
NOT see raw trade data or out-of-sample numbers — only the cycle ledger digest below. Your job: \
propose the NEXT research cycle, or stop. You may ONLY choose from this action menu (apparatus — \
budgets, windows, gates — is human-only and not yours to touch):

  {"action":"run_cycle","side":"sell"|"buy","hypothesis":"<why this is worth a search>"}
  {"action":"stop","hypothesis":"<why there is nothing worth proposing>"}

Rules you must follow:
- A cycle whose search was KILLED AT THE GATE (chance-level) is the normal, healthy outcome — it \
means that side/config has no separable structure beyond what the search width finds by luck. Do \
NOT re-propose an identical cycle hoping for a different number; that is noise-mining.
- Propose the OTHER side only if it has not been run this session.
- If both sides have been run and both were killed at the gate, STOP — the honest finding is "no \
certifiable structure on this contract at this trade count."
- Never propose spending looks to "check" something; the gate and budget decide that mechanically.

Reply with EXACTLY ONE JSON object from the menu above. No prose, no code fence."""


def ledger_digest(ledger_path: Path) -> str:
    if not ledger_path.exists():
        return "(no cycles yet — this is the first)"
    lines = []
    for l in ledger_path.read_text().splitlines():
        e = json.loads(l)
        if e["type"] in ("cycle.open", "stage.search.result", "cycle.no_candidate",
                          "readout.record", "cycle.parked"):
            p = e["payload"]
            if e["type"] == "cycle.open":
                lines.append(f"cycle: {p['contract']}/{p['side']} (budget {p['budget_remaining']})")
            elif e["type"] == "stage.search.result":
                lines.append(f"  search: K={p['selected_K']} z={p['selected_z']:.2f} "
                             f"gate_ref={p['gate_ref']:.2f} -> beats_gate={p['beats_gate']}")
            elif e["type"] == "cycle.no_candidate":
                lines.append(f"  KILLED AT GATE: {p['reason']}")
            elif e["type"] == "readout.record":
                lines.append(f"  READOUT uplift={p['uplift']:+.3f} certified={p['certified']}")
            elif e["type"] == "cycle.parked":
                lines.append(f"  PARKED: {p['reason']}")
    return "\n".join(lines)


def ask_agent(digest: str, budget_remaining: int, sides_run: list[str],
              capture_path: Path) -> dict:
    prompt = (f"{ROLE_PROMPT}\n\n=== LEDGER DIGEST ===\n{digest}\n\n"
              f"budget slots remaining: {budget_remaining}\n"
              f"sides already run this session: {sides_run or 'none'}\n\n"
              f"Your one-JSON decision:")
    r = subprocess.run([CLAUDE, "--print", "--output-format", "json", prompt],
                       capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    capture_path.write_text(r.stdout)                  # observer evidence (hash it downstream)
    blob = json.loads(r.stdout)
    text = blob.get("result", "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)


def run(population: str, contract: str, workdir: Path, max_cycles: int,
        trials: int, runs_per_k: int, seed_points: int) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir.parent / "var").mkdir(parents=True, exist_ok=True)
    ledger = Ledger(workdir / "events.jsonl")
    sides_run: list[str] = []

    for i in range(1, max_cycles + 1):
        if (workdir.parent / "var" / "HALT").exists():
            ledger.append("loop.halted", {"cycle": i}); print("HALT — stopping."); return
        budget = LookBudget(workdir / f"budget_{contract}_sell.json")   # shared across sides in demo
        digest = ledger_digest(workdir / "events.jsonl")
        cap = workdir / f"agent_session_{i}.json"
        try:
            proposal = ask_agent(digest, budget.state["remaining"], sides_run, cap)
        except Exception as e:  # noqa: BLE001
            ledger.append("agent.error", {"cycle": i, "error": str(e)[:200]}); print("agent error:", e); return
        ledger.append("agent.proposal", {"cycle": i, "action": proposal.get("action"),
                                          "side": proposal.get("side"),
                                          "hypothesis": proposal.get("hypothesis", "")[:300],
                                          "session_capture": str(cap)})
        print(f"\n=== cycle {i}: agent proposes {proposal} ===")
        if proposal.get("action") == "stop":
            ledger.append("loop.stopped", {"cycle": i, "by": "agent",
                                           "hypothesis": proposal.get("hypothesis", "")[:300]})
            print("Agent chose STOP.")
            return
        side = proposal.get("side", "sell")
        b = LookBudget(workdir / f"budget_{contract}_{side}.json")
        out = cycle(contract, population, side, workdir, ledger, b, trials, runs_per_k, seed_points)
        sides_run.append(side)
        print(f"cycle {i} -> {out.get('verdict')}")
    ledger.append("loop.max_cycles", {"max": max_cycles})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", required=True)
    ap.add_argument("--contract", default="btc_sat")
    ap.add_argument("--workdir", default="/home/alex/lightray/autoloop")
    ap.add_argument("--max-cycles", type=int, default=6)
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--runs-per-k", type=int, default=5)
    ap.add_argument("--seed-points", type=int, default=40)
    a = ap.parse_args()
    run(a.population, a.contract, Path(a.workdir), a.max_cycles, a.trials, a.runs_per_k, a.seed_points)


if __name__ == "__main__":
    main()
