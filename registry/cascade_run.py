"""cascade_run — the AUTONOMOUS cascade (M9 substrate).

One cycle, no human hand on it:
    population  ->  masked SEARCH (+ null-of-max GATE)  ->  verdict
        gate FAIL  -> record "no candidate", stop (the normal, healthy outcome)
        gate PASS  -> if a look-budget slot remains: spend it, run the OOS READOUT,
                      stamp the five-clause verdict; else record "candidate parked (budget)"

Every step is appended to a hash-chained ledger (events.jsonl) — replayable, tamper-evident.
The GATE and the BUDGET are the two brakes; neither can be bypassed by this script (a readout
job is only built after both pass). `var/HALT` stops the loop before any dispatch.

This shells the validated MATLAB engine (registry_sgl_search / registry_readout) via job
contracts built by build_sgl_jobs — the engine math is untouched. Runs ON the server (local
matlab), so the daemon/agent can invoke it directly.

Usage:
    python -m registry.cascade_run --contract btc_sat --population P.parquet \
        [--side sell] [--trials 200 --runs-per-k 5] [--workdir ~/lightray/cascade]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .canon import sha256_canon
from .tools.build_sgl_jobs import build_readout_job, build_search_job, load_pc

MATLAB_CLIENT = "/home/alex/lightray/LightrayRegistry/matlab/registry_client"
BELKASGL = "/home/alex/Documents/Atesting7/BelkaSGL"


class Ledger:
    """Append-only hash-chained event log for the cascade (self-contained; the full registry
    barrier is a later join — this proves the loop + gives a replayable record now)."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = "genesis"
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self._prev = json.loads(line)["event_hash"]

    def append(self, etype: str, payload: dict) -> str:
        ev = {"seq": self._count(), "ts": _utc(), "type": etype, "payload": payload,
              "prev_hash": self._prev}
        ev["event_hash"] = sha256_canon(ev)
        with self.path.open("a") as f:
            f.write(json.dumps(ev) + "\n")
        self._prev = ev["event_hash"]
        print(f"  [ledger] {etype} -> {ev['event_hash'][:10]}")
        return ev["event_hash"]

    def _count(self) -> int:
        return sum(1 for _ in self.path.read_text().splitlines()) if self.path.exists() else 0


class LookBudget:
    """The per-lineage look budget (REG-INV-24), now 30. A readout spends one slot; the file IS
    the spend record. can_spend is the hard brake — a readout job is not built at 0 remaining."""

    def __init__(self, path: Path, initial: int = 30, alarm: int = 15, diagnostic: int = 1):
        self.path = path
        if path.exists():
            self.state = json.loads(path.read_text())
        else:
            self.state = {"initial": initial, "remaining": initial, "consumed": 0,
                          "alarm_remaining": alarm, "diagnostic_remaining": diagnostic, "looks": []}
            self._save()

    def can_spend(self) -> bool:
        return self.state["remaining"] > 0

    def spend(self, readout_id: str, digest: str) -> None:
        if not self.can_spend():
            raise RuntimeError("BUDGET EXHAUSTED — can_spend is False; no readout may fire")
        self.state["remaining"] -= 1
        self.state["consumed"] += 1
        self.state["looks"].append({"readout_id": readout_id, "digest": digest, "ts": _utc()})
        self._save()

    @property
    def alarm(self) -> bool:
        return self.state["remaining"] <= self.state["alarm_remaining"]

    @property
    def diagnostic_mode(self) -> bool:
        return self.state["remaining"] <= self.state["diagnostic_remaining"]

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=1))


def _utc() -> str:
    return subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                          capture_output=True, text=True).stdout.strip()


def _sha(path: str) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_matlab(fn: str, job_path: str) -> None:
    cmd = ["matlab", "-batch", f"addpath('{MATLAB_CLIENT}'); {fn}('{job_path}')"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600)
    tail = "\n".join(r.stdout.strip().splitlines()[-3:])
    print(f"  [matlab {fn}] {tail}")
    if r.returncode != 0:
        raise RuntimeError(f"matlab {fn} failed (rc={r.returncode}): {r.stderr[-400:]}")


def cycle(contract: str, population: str, side: str, workdir: Path, ledger: Ledger,
          budget: LookBudget, trials: int, runs_per_k: int, seed_points: int) -> dict:
    halt = workdir.parent / "var" / "HALT"
    if halt.exists():
        ledger.append("cycle.halted", {"contract": contract, "reason": "var/HALT present"})
        return {"halted": True}

    ledger.append("cycle.open", {"contract": contract, "side": side, "population": population,
                                 "population_sha256": _sha(population),
                                 "budget_remaining": budget.state["remaining"]})

    # ── STAGE: masked SEARCH + gate ────────────────────────────────────────────────────────
    sjob = workdir / f"{contract}_{side}_search_job.json"
    sres = workdir / f"{contract}_{side}_search.json"
    job = build_search_job(population, side, "z", str(sres), str(workdir / f"{contract}_{side}_prog.jsonl"),
                           trials, seed_points, runs_per_k, None, 42, BELKASGL, f"{contract}_{side}_search")
    job["objective"] = "z"
    sjob.write_text(json.dumps(job, indent=1))
    ledger.append("stage.search.dispatch", {"job_sha256": _sha(str(sjob)), "objective": "z",
                                             "selector": "z", "declared_width": len(job["K_values"]) * runs_per_k * trials})
    run_matlab("registry_sgl_search", str(sjob))
    res = json.loads(sres.read_text())
    sel = res["selected"]
    ledger.append("stage.search.result", {
        "selected_K": sel["K"], "selected_z": sel["z"], "kernel": sel["params"]["kernel"],
        "gate_ref": res["gate_ref"], "gate_priced_configs": res["gate_priced_configs"],
        "beats_gate": res["selected_beats_gate"], "result_sha256": _sha(str(sres))})

    # ── GATE decision (brake #1) ───────────────────────────────────────────────────────────
    if not res["selected_beats_gate"]:
        ledger.append("cycle.no_candidate", {
            "reason": f"selected z {sel['z']:.3f} <= gate_ref {res['gate_ref']:.3f} at width "
                      f"{res['gate_priced_configs']} configs — chance-level, correctly killed"})
        print(f"CYCLE DONE: no candidate (z {sel['z']:.3f} <= gate {res['gate_ref']:.3f}).")
        return {"verdict": "no_candidate", "z": sel["z"], "gate_ref": res["gate_ref"]}

    # ── BUDGET decision (brake #2) ─────────────────────────────────────────────────────────
    if budget.diagnostic_mode:
        ledger.append("cycle.parked", {"reason": "diagnostic mode (budget floor) — candidate held, "
                                                  "no readout", "selected_z": sel["z"]})
        return {"verdict": "parked_diagnostic", "z": sel["z"]}
    if not budget.can_spend():
        ledger.append("cycle.parked", {"reason": "budget exhausted", "selected_z": sel["z"]})
        return {"verdict": "parked_exhausted", "z": sel["z"]}

    # ── STAGE: OOS READOUT (spends one look) ───────────────────────────────────────────────
    cfg = {k: sel["params"][k] for k in ("K", "kernel", "sigma", "k_nbrs", "gamma", "n_diff",
                                         "w_hour", "w_ema", "w_mom", "w_dv", "w_iv", "w_hurst")}
    rjob = workdir / f"{contract}_{side}_readout_job.json"
    rres = workdir / f"{contract}_{side}_readout.json"
    rj = build_readout_job(cfg, f"{contract}_{side}", str(rres), side, population, None, None, BELKASGL)
    rjob.write_text(json.dumps(rj, indent=1))
    readout_id = f"{contract}_{side}_look_{budget.state['consumed'] + 1}"
    budget.spend(readout_id, _sha(str(rjob)))          # can_spend already true; decrement BEFORE unmask
    ledger.append("readout.spend", {"readout_id": readout_id, "budget_remaining": budget.state["remaining"],
                                    "alarm": budget.alarm})
    run_matlab("registry_readout", str(rjob))
    r = json.loads(rres.read_text())
    clauses = five_clause(r, load_pc())
    ledger.append("readout.record", {
        "readout_id": readout_id, "uplift": r["uplift"], "pooled": r["pooled_W2W4"], "S0": r["S0_W2W4"],
        "carrier_W4_n": r["carrier_W4_n"], "carrier_W4_pf": r["carrier_W4_pf"],
        "clauses": clauses, "certified": all(clauses.values()), "result_sha256": _sha(str(rres))})
    print(f"CYCLE DONE: readout uplift {r['uplift']:+.3f}, clauses {clauses}, "
          f"CERTIFIED={all(clauses.values())}")
    return {"verdict": "certified" if all(clauses.values()) else "read_not_certified",
            "uplift": r["uplift"], "clauses": clauses}


def five_clause(r: dict, pc: dict) -> dict:
    """The five-clause gate as a mechanical verdict (was judged by eye). clause4 (persistence)
    is not yet computed by the readout -> reported None (partial gate, honest)."""
    sel_pf = pc["select"]["sel_pf"]
    floor = pc["select"]["min_window_trades_per_blob"]
    pw = r["per_window_pf"]
    return {
        "c1_carrier_W4": bool(r["carrier_W4_n"] >= floor and r["carrier_W4_pf"] >= sel_pf),
        "c2_consistency": bool(sum(1 for x in pw if x >= 1.0) >= 3),
        "c3_degradation": bool(r["pooled_W2W4"] / max(r["carrier_train_pf"], 1e-9) >= 0.70),
        "c4_persistence": None,   # not computed by current readout (70%-train anchor refit)
        "c5_seed_survival": bool(all(rs["jaccard"] >= 0.50 and rs["selected"] and
                                     rs["pooled"] >= r["S0_W2W4"] for rs in r["reseeds"])),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--population", required=True)
    ap.add_argument("--side", default="sell")
    ap.add_argument("--workdir", default="/home/alex/lightray/cascade")
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--runs-per-k", type=int, default=5)
    ap.add_argument("--seed-points", type=int, default=40)
    a = ap.parse_args()
    wd = Path(a.workdir); wd.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(wd / "events.jsonl")
    budget = LookBudget(wd / f"budget_{a.contract}_{a.side}.json")
    t = time.time()
    out = cycle(a.contract, a.population, a.side, wd, ledger, budget,
                a.trials, a.runs_per_k, a.seed_points)
    out["elapsed_s"] = round(time.time() - t, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
