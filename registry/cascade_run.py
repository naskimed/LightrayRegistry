"""cascade_run — the AUTONOMOUS cascade (M9 substrate), hardened for scale (v3, 2026-07-10).

One cycle, no human hand on it:
    population -> baseline health check (train-only, free)
               -> SCREENING search (+ gate)      [cheap; kills chance-level candidates]
               -> FULL-WIDTH search (+ gate)     [only for screening survivors]
               -> spend one look (locked, deduplicated) -> OOS readout -> five-clause verdict

Brakes, all mechanical: GATE (null-of-the-max at realized width), BUDGET (locked file,
spend-before-unmask, duplicate-spend dedup by readout signature), SELECTABLE-BLOB (train-only),
ARMING (standing policy file — the human authority, delegated in advance per RATIFICATIONS v2),
PLACEBO TWIN (side-scoped SILENT report required), verdict None-block. `var/HALT` stops the
loop before any dispatch. Every step appends to a locked, fsync'd hash-chained ledger.

Concurrency: LookBudget/ARMING/Ledger writes take an exclusive fcntl lock and re-read state
under the lock — safe for parallel cycles. Search results are content-cached by job hash
(deterministic engine => a cache hit IS the result).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from .canon import sha256_canon
from .tools.build_sgl_jobs import build_readout_job, build_search_job, load_pc

MATLAB_CLIENT = "/home/alex/lightray/LightrayRegistry/matlab/registry_client"
BELKASGL = "/home/alex/Documents/Atesting7/BelkaSGL"
CANONICAL = "/home/alex/lightray/snapshots/binance_btcusdt_1m/canonical.parquet"


@contextmanager
def locked(path: Path):
    """Exclusive advisory lock keyed to `path` (sidecar .lock file)."""
    lock = path.parent / (path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _utc() -> str:
    return subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                          capture_output=True, text=True).stdout.strip()


def _sha(path: str) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Ledger:
    """Append-only hash-chained event log. Appends take the lock, re-read the chain tail from
    disk (multi-process safe), and fsync before returning — a crash never tears the chain."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, "genesis"
        seq, prev = 0, "genesis"
        for line in self.path.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                seq = e["seq"] + 1
                prev = e["event_hash"]
        return seq, prev

    def append(self, etype: str, payload: dict) -> str:
        with locked(self.path):
            seq, prev = self._tail()
            ev = {"seq": seq, "ts": _utc(), "type": etype, "payload": payload,
                  "prev_hash": prev}
            ev["event_hash"] = sha256_canon(ev)
            with self.path.open("a") as f:
                f.write(json.dumps(ev) + "\n")
                f.flush()
                os.fsync(f.fileno())
        print(f"  [ledger] {etype} -> {ev['event_hash'][:10]}")
        return ev["event_hash"]


class LookBudget:
    """The per-lineage look budget (REG-INV-24; 30). Spends re-read the file under an
    exclusive lock (parallel-safe) and are DEDUPLICATED by readout signature: re-running the
    identical (population, side, config) readout — e.g. completing a crashed cycle — reuses
    the prior spend instead of double-charging (one envelope = one look)."""

    def __init__(self, path: Path, initial: int = 30, alarm: int = 15, diagnostic: int = 1):
        self.path = path
        with locked(self.path):
            if path.exists():
                self.state = json.loads(path.read_text())
            else:
                self.state = {"initial": initial, "remaining": initial, "consumed": 0,
                              "alarm_remaining": alarm, "diagnostic_remaining": diagnostic,
                              "looks": []}
                self._save()

    def _reload(self) -> None:
        self.state = json.loads(self.path.read_text())

    def can_spend(self) -> bool:
        with locked(self.path):
            self._reload()
            return self.state["remaining"] > 0

    def prior_spend(self, signature: str) -> dict | None:
        with locked(self.path):
            self._reload()
            return next((l for l in self.state["looks"] if l.get("signature") == signature), None)

    def spend(self, readout_id: str, signature: str, digest: str) -> str:
        """Returns 'spent' or 'deduplicated' (identical envelope already charged)."""
        with locked(self.path):
            self._reload()
            prior = next((l for l in self.state["looks"] if l.get("signature") == signature), None)
            if prior:
                return "deduplicated"
            if self.state["remaining"] <= 0:
                raise RuntimeError("BUDGET EXHAUSTED — can_spend false; no readout may fire")
            self.state["remaining"] -= 1
            self.state["consumed"] += 1
            self.state["looks"].append({"readout_id": readout_id, "signature": signature,
                                        "digest": digest, "ts": _utc()})
            self._save()
            return "spent"

    @property
    def alarm(self) -> bool:
        return self.state["remaining"] <= self.state["alarm_remaining"]

    @property
    def diagnostic_mode(self) -> bool:
        return self.state["remaining"] <= self.state["diagnostic_remaining"]

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.path)


def generate_population(spec_dict: dict, pop_dir: Path) -> tuple[str, str, int, int]:
    """Materialize a whitebox population from a proposed config. Content-addressed by config."""
    import hashlib
    from .bridges.vbt_runner import WhiteboxSpec, run_population, _write_parquet
    pop_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps(spec_dict, sort_keys=True).encode()).hexdigest()[:12]
    path = pop_dir / f"pop_{key}.parquet"
    if not path.exists():                              # content-addressed => cache hit is valid
        td = dict(spec_dict).pop("trading_days", (5,))
        sd = {k: v for k, v in spec_dict.items() if k != "trading_days"}
        spec = WhiteboxSpec(data_path=CANONICAL, exit_resolution="hybrid",
                            trading_days=tuple(td) if td else None, **sd)
        rp = run_population(spec)
        _write_parquet(rp["rows"], path)
        n_sell, n_buy = len(rp["res"].sell), len(rp["res"].buy)
    else:
        import pandas as pd
        df = pd.read_parquet(path)
        n_sell = int((df["side"] == "sell").sum())
        n_buy = int((df["side"] == "buy").sum())
    return str(path), _sha(str(path)), n_sell, n_buy


def _mask_cfg(pc: dict) -> dict:
    w = pc["windows"]
    return {"windows": list(zip(w["names"], w["starts"], w["ends"])),
            "exclusions": list(zip(pc["exclusions"]["starts"], pc["exclusions"]["ends"])),
            "embargo": pc["embargo"], "min_window_side": pc["min_window_side"]}


def baseline_health(population: str, side: str, pc: dict) -> dict:
    """TRAIN-ONLY population health (free; target-blind on windows — uses window COUNTS but
    never window outcomes). A geometry search is only worth running on a population whose
    masked-train baseline is alive and whose certifier window can even be measured."""
    import pandas as pd
    from .bridges.vbt_runner import tierb_train_mask
    df = pd.read_parquet(population)
    s = df[df["side"] == side]
    try:
        is_train, win_id, counts = tierb_train_mask(s["entry_ts"].tolist(), _mask_cfg(pc))
    except ValueError as e:                            # a window below min_window_side
        return {"healthy": False, "reason": str(e)[:120]}
    r = s.loc[is_train, "profit"]
    gl = float(-r[r <= 0].sum())
    pf = float(r[r > 0].sum() / gl) if gl > 0 else float("inf")
    out = {"train_n": int(is_train.sum()), "train_pf": round(pf, 4),
           "train_expectancy": round(float(r.mean()), 5), "w4_count": int(counts[-1]),
           "window_counts": counts}
    out["healthy"] = bool(pf >= 1.05 and r.mean() > 0 and counts[-1] >= 30)
    if not out["healthy"]:
        out["reason"] = (f"train PF {pf:.3f} / expectancy {r.mean():+.4f} / "
                         f"W4 count {counts[-1]} — baseline too weak or certifier unmeasurable")
    return out


def run_matlab(fn: str, job_path: str) -> None:
    cmd = ["matlab", "-batch", f"addpath('{MATLAB_CLIENT}'); {fn}('{job_path}')"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=8 * 3600)
    tail = "\n".join(r.stdout.strip().splitlines()[-3:])
    print(f"  [matlab {fn}] {tail}")
    if r.returncode != 0:
        raise RuntimeError(f"matlab {fn} failed (rc={r.returncode}): {r.stderr[-400:]}")


def cached_search(job: dict, job_path: Path, res_path: Path, cache_dir: Path) -> dict:
    """Deterministic engine => the job hash addresses the result. Cache hit skips MATLAB."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = sha256_canon({k: v for k, v in job.items()
                        if k not in ("result_path", "progress_path")})[:20]
    hit = cache_dir / f"{key}.json"
    job_path.write_text(json.dumps(job, indent=1))
    if hit.exists():
        shutil.copy(hit, res_path)
        print(f"  [cache] search hit {key}")
        return json.loads(res_path.read_text())
    run_matlab("registry_sgl_search", str(job_path))
    res = json.loads(res_path.read_text())
    shutil.copy(res_path, hit)
    return res


def _selectable(sel: dict, pc: dict) -> bool:
    bpf = sel.get("blob_pf") or []
    bn = sel.get("blob_n") or []
    bpf = bpf if isinstance(bpf, list) else [bpf]
    bn = bn if isinstance(bn, list) else [bn]
    return any(p is not None and n is not None
               and float(p) >= pc["select"]["sel_pf"] and float(n) >= pc["select"]["sel_min_tr"]
               for p, n in zip(bpf, bn))


def _search_stage(contract: str, population: str, side: str, workdir: Path, ledger: Ledger,
                  tag: str, stage: str, trials: int, runs_per_k: int, seed_points: int) -> dict | None:
    """One gated search stage. Returns the result dict, or None if killed at the gate."""
    sjob = workdir / f"{contract}_{tag}_{stage}_job.json"
    sres = workdir / f"{contract}_{tag}_{stage}.json"
    job = build_search_job(population, side, "z", str(sres),
                           str(workdir / f"{contract}_{tag}_{stage}_prog.jsonl"),
                           trials, seed_points, runs_per_k, None, 42, BELKASGL,
                           f"{contract}_{tag}_{stage}")
    job["objective"] = "z"
    ledger.append("stage.search.dispatch", {"stage": stage, "tag": tag,
                                            "declared_width": 8 * runs_per_k * trials})
    res = cached_search(job, sjob, sres, workdir / "cache")
    sel = res["selected"]
    ledger.append("stage.search.result", {
        "stage": stage, "selected_K": sel["K"], "selected_z": sel["z"],
        "kernel": sel["params"]["kernel"], "gate_ref": res["gate_ref"],
        "gate_priced_configs": res["gate_priced_configs"], "beats_gate": res["selected_beats_gate"],
        "result_sha256": _sha(str(sres))})
    if not res["selected_beats_gate"]:
        ledger.append("cycle.no_candidate", {
            "stage": stage, "reason": f"z {sel['z']:.3f} <= gate_ref {res['gate_ref']:.3f} "
                                       f"at {res['gate_priced_configs']} configs — chance-level"})
        return None
    return res


def cycle(contract: str, population: str, side: str, workdir: Path, ledger: Ledger,
          budget: LookBudget, trials: int, runs_per_k: int, seed_points: int,
          spec: dict | None = None, tag: str = "",
          full_trials: int = 200, full_runs: int = 3, full_seed_points: int = 40) -> dict:
    halt = workdir.parent / "var" / "HALT"
    if halt.exists():
        ledger.append("cycle.halted", {"contract": contract, "reason": "var/HALT present"})
        return {"halted": True}
    tag = tag or side
    pc = load_pc()

    ledger.append("cycle.open", {"contract": contract, "side": side, "spec": spec or {"fixed": True},
                                 "population": population, "population_sha256": _sha(population),
                                 "budget_remaining": budget.state["remaining"]})

    # ── STAGE 0: baseline health (free, train-only) ────────────────────────────────────────
    health = baseline_health(population, side, pc)
    ledger.append("stage.baseline", health)
    if not health.get("healthy"):
        ledger.append("cycle.parked", {"reason": f"POPULATION UNHEALTHY: {health.get('reason','')}"})
        return {"verdict": "population_unhealthy", **{k: health.get(k) for k in ("train_pf", "w4_count")}}

    # ── STAGE 1: SCREENING search + gate ───────────────────────────────────────────────────
    res = _search_stage(contract, population, side, workdir, ledger, tag, "screen",
                        trials, runs_per_k, seed_points)
    if res is None:
        return {"verdict": "no_candidate_screen"}
    if not _selectable(res["selected"], pc):
        ledger.append("cycle.parked", {"reason": "no train-selectable blob at screening — "
                                                  "loser-pocket-only separation; zero-cost kill",
                                        "selected_z": res["selected"]["z"]})
        return {"verdict": "parked_unselectable", "z": res["selected"]["z"]}

    # ── STAGE 2: FULL-WIDTH search + gate (looks are spent only on full-width survivors) ───
    res = _search_stage(contract, population, side, workdir, ledger, tag, "full",
                        full_trials, full_runs, full_seed_points)
    if res is None:
        return {"verdict": "no_candidate_full"}
    sel = res["selected"]
    if not _selectable(sel, pc):
        ledger.append("cycle.parked", {"reason": "no train-selectable blob at full width",
                                        "selected_z": sel["z"]})
        return {"verdict": "parked_unselectable_full", "z": sel["z"]}

    # ── BUDGET brake ────────────────────────────────────────────────────────────────────────
    if budget.diagnostic_mode:
        ledger.append("cycle.parked", {"reason": "diagnostic mode (budget floor)", "z": sel["z"]})
        return {"verdict": "parked_diagnostic", "z": sel["z"]}

    # ── ARMING brake (standing policy = the delegated human authority, RATIFICATIONS v2) ───
    arming_path = workdir / "ARMING.json"
    with locked(arming_path):
        arming = json.loads(arming_path.read_text()) if arming_path.exists() else None
        ok_arm = (arming and arming.get("arms_remaining", 0) >= 1
                  and str(arming.get("armed_by", "")).startswith("human:"))
        if ok_arm:
            arming["arms_remaining"] -= 1
            arming_path.write_text(json.dumps(arming, indent=1))
    if not ok_arm:
        ledger.append("cycle.parked", {"reason": "NO LIVE ARMING", "z": sel["z"]})
        return {"verdict": "parked_unarmed", "z": sel["z"]}

    # ── TWIN brake (side-scoped SILENT report required for this population template) ───────
    twin_path = workdir / "twins" / f"{_sha(population)[:16]}_{side}.json"
    twin = json.loads(twin_path.read_text()) if twin_path.exists() else None
    if not twin or twin.get("verdict") != "SILENT":
        ledger.append("cycle.parked", {"reason": f"NO SILENT TWIN REPORT ({twin_path.name}) — "
                                                  "run registry.twin_check for this side first",
                                        "z": sel["z"]})
        return {"verdict": "parked_no_twin", "z": sel["z"]}
    ledger.append("readout.armed_fire", {"bundle_id": arming.get("bundle_id"),
                                          "arms_remaining": arming["arms_remaining"],
                                          "twin_report": twin_path.name})

    # ── SPEND (locked, deduplicated) then READOUT ───────────────────────────────────────────
    cfg = {k: sel["params"][k] for k in ("K", "kernel", "sigma", "k_nbrs", "gamma", "n_diff",
                                         "w_hour", "w_ema", "w_mom", "w_dv", "w_iv", "w_hurst")}
    signature = sha256_canon({"pop": _sha(population), "side": side, "cfg": cfg})[:24]
    rjob = workdir / f"{contract}_{tag}_readout_job.json"
    rres = workdir / f"{contract}_{tag}_readout.json"
    rj = build_readout_job(cfg, f"{contract}_{tag}", str(rres), side, population, None, None, BELKASGL)
    rjob.write_text(json.dumps(rj, indent=1))
    readout_id = f"{contract}_{tag}_look"
    mode = budget.spend(readout_id, signature, _sha(str(rjob)))
    ledger.append("readout.spend", {"readout_id": readout_id, "signature": signature,
                                    "mode": mode, "budget_remaining": budget.state["remaining"],
                                    "alarm": budget.alarm})
    try:
        run_matlab("registry_readout", str(rjob))
        r = json.loads(rres.read_text())
    except Exception as e:  # noqa: BLE001 — the spend stands (spend-before-unmask); record it
        ledger.append("readout.failed", {"readout_id": readout_id, "signature": signature,
                                          "error": str(e)[-300:],
                                          "note": "spend stands; identical re-run dedups to this spend"})
        return {"verdict": "readout_failed", "error": str(e)[-200:]}
    clauses = five_clause(r, pc)
    verdict = verdict_of(clauses)
    ledger.append("readout.record", {
        "readout_id": readout_id, "signature": signature, "uplift": r.get("uplift"),
        "pooled": r.get("pooled_W2W4"), "S0": r.get("S0_W2W4"),
        "carrier_W4_n": r.get("carrier_W4_n"), "carrier_W4_pf": r.get("carrier_W4_pf"),
        "clauses": clauses, "verdict": verdict, "certified": verdict == "CERTIFIED",
        "result_sha256": _sha(str(rres))})
    print(f"CYCLE DONE: uplift {r.get('uplift')}, VERDICT={verdict}")
    return {"verdict": verdict.lower(), "uplift": r.get("uplift"), "clauses": clauses}


def five_clause(r: dict, pc: dict) -> dict:
    """The five-clause gate, mechanical + fail-closed (None can never pass or crash).
    c3 fix 2026-07-10: degradation is CARRIER pooled-OOS vs CARRIER train (manual semantics)."""
    sel_pf = pc["select"]["sel_pf"]
    floor = pc["select"]["min_window_trades_per_blob"]
    num = lambda v, d=float("nan"): d if v is None else float(v)
    ok = lambda v, thr: v is not None and float(v) >= thr
    pw = r["per_window_pf"]
    if all(k in r for k in ("carrier_W4_h1_pf", "carrier_W4_h2_pf")):
        c4 = bool(num(r["carrier_W4_h1_n"], 0) >= 15 and num(r["carrier_W4_h2_n"], 0) >= 15
                  and ok(r["carrier_W4_h1_pf"], 1.0) and ok(r["carrier_W4_h2_pf"], 1.0))
    else:
        c4 = None
    if "carrier_pool_pf" in r:
        c3 = bool(ok(r["carrier_pool_pf"], 0) and ok(r["carrier_train_pf"], 1e-9)
                  and num(r["carrier_pool_pf"]) / num(r["carrier_train_pf"]) >= 0.70)
    else:
        c3 = None                                     # result predates the carrier-pool fields
    return {
        "c1_carrier_W4": bool(num(r["carrier_W4_n"], 0) >= floor and ok(r["carrier_W4_pf"], sel_pf)),
        "c2_consistency": bool(sum(1 for x in pw if ok(x, 1.0)) >= 3),
        "c3_degradation": c3,
        "c4_persistence": c4,
        "c5_seed_survival": bool(all(ok(rs["jaccard"], 0.50) and rs["selected"] and
                                     ok(rs["pooled"], num(r["S0_W2W4"], float("inf")))
                                     for rs in r["reseeds"])),
    }


def verdict_of(clauses: dict) -> str:
    """None-block: CERTIFIED requires ALL FIVE True; any None caps at CANDIDATE; False = FAILED."""
    vals = list(clauses.values())
    if any(v is False for v in vals):
        return "FAILED"
    if any(v is None for v in vals):
        return "CANDIDATE"
    return "CERTIFIED"


# ── the W4 re-anchor: pre-signed policy, self-executing (RATIFICATIONS v2) ────────────────────
REANCHOR_POLICY = {
    "virgin_start": "2026-07-01",
    "min_trades_per_side": 400,        # population trades in the virgin span
    "min_span_weeks": 12,
    "new_generation_budget": 30,
}


def maybe_reanchor(reference_population: str, seed_dir: Path, ledger: Ledger) -> bool:
    """When the virgin span (post-2026-06-30) holds >=400 population trades/side AND spans
    >=12 weeks, mint the generation-2 windowset: W1-W3 unchanged (stamped middles-reused),
    old W4 becomes a middle, W5 = the virgin span becomes the forward certifier. Writes
    seed/pc_active.json, which build_sgl_jobs prefers over the v0.6.2 constants. Human
    authority exercised IN ADVANCE via the ratified policy; zero interference at trigger."""
    import pandas as pd
    active = seed_dir / "pc_active.json"
    if active.exists():
        return False                                   # already re-anchored
    df = pd.read_parquet(reference_population)
    ts = pd.to_datetime(df["entry_ts"])
    virgin = df[ts >= REANCHOR_POLICY["virgin_start"]]
    if virgin.empty:
        return False
    span_weeks = (ts.max() - pd.Timestamp(REANCHOR_POLICY["virgin_start"])).days / 7.0
    per_side = virgin.groupby("side").size()
    if (span_weeks < REANCHOR_POLICY["min_span_weeks"]
            or per_side.min() < REANCHOR_POLICY["min_trades_per_side"]):
        return False
    pc = load_pc()
    end = str(ts.max().date())
    pc["windows"] = {
        "names": pc["windows"]["names"] + ["W5"],
        "starts": pc["windows"]["starts"] + [REANCHOR_POLICY["virgin_start"]],
        "ends": pc["windows"]["ends"] + [end],
        "roles": ["backward_only", "middle", "middle", "middle", "forward_certifier"],
    }
    pc["_generation"] = 2
    pc["_reanchor"] = {"policy": REANCHOR_POLICY, "executed_utc": _utc(),
                       "note": "W1-W3 middles reused (gen 2); old W4 demoted to middle; "
                               "W5 = virgin certifier. Pre-signed policy, RATIFICATIONS v2."}
    active.write_text(json.dumps(pc, indent=1))
    ledger.append("windowset.reanchor", {"new_certifier": ["W5", REANCHOR_POLICY["virgin_start"], end],
                                          "generation": 2,
                                          "fresh_budget": REANCHOR_POLICY["new_generation_budget"]})
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--population", required=True)
    ap.add_argument("--side", default="sell")
    ap.add_argument("--workdir", default="/home/alex/lightray/research")
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--runs-per-k", type=int, default=1)
    ap.add_argument("--seed-points", type=int, default=10)
    a = ap.parse_args()
    wd = Path(a.workdir); wd.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(wd / "events.jsonl")
    budget = LookBudget(wd / f"budget_{a.contract}.json")
    t = time.time()
    out = cycle(a.contract, a.population, a.side, wd, ledger, budget,
                a.trials, a.runs_per_k, a.seed_points)
    out["elapsed_s"] = round(time.time() - t, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
