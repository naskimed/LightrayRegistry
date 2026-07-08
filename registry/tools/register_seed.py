"""register_seed — the M3 t=0 driver: constants, look budget, artifacts, conditionals.

Everything imported:true, idempotent (double-run ⇒ zero new events). Window DATES are NOT in
any seed file on purpose (no-remembered-literals): register_windows() requires a pc_v062.json
parsed from the hashed precommit.m — refuse to invent intervals.

Usage:
  python -m registry.tools.register_seed constants
  python -m registry.tools.register_seed artifacts --base /home/alex/Documents/Atesting7/BelkaSGL
  python -m registry.tools.register_seed windows --pc pc_v062.json
  python -m registry.tools.register_seed arm-conditionals
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..canon import sha256_canon, sha256_file
from ._seed import SeedSession, load_seed


def _wiv_id(data_contract: str, start: str, end: str) -> str:
    # wiv_<hash8> over (data_contract, start, end) ONLY — anchor/clock live at windowset level,
    # so an OPEN-16 re-anchor carries spends + k automatically (REG-INV-24 / the spec's law).
    return "wiv_" + sha256_canon({"data_contract": data_contract, "start": start, "end": end})[:8]


def seed_constants() -> None:
    docs = load_seed("constants_seed.json")
    with SeedSession() as s:
        for key, doc in docs.items():
            if key.startswith("_"):
                continue
            s.submit("constants.register", doc, intent=f"seed:{doc['doc_id']}")
        s.report("constants")


def seed_artifacts(base: Path) -> None:
    """recover_artifacts: re-hash the LOCAL copies, assert equality with the registered
    hashes, register in place; attest the missing set."""
    spec = load_seed("tierb_artifacts.json")
    with SeedSession() as s:
        for a in spec["artifacts"]:
            p = base / a["rel"]
            if not p.exists():
                s.submit("artifact.attest_missing",
                         {"name": a["rel"], "expected_role": a["role"],
                          "why": f"absent under {base} at seed time"},
                         intent=f"missing:{a['rel']}")
                continue
            actual = sha256_file(p)
            if actual != a["sha256"]:
                raise ValueError(f"{a['rel']}: local hash {actual} != registered {a['sha256']} — REFUSING")
            s.submit("artifact.register", {
                "artifact_id": f"art_{a['sha256'][:12]}",
                "role": a["role"], "path": str(p),
                "declared_sha256": a["sha256"],
                "provenance": {"source": spec["_provenance"],
                               "git_stamps": spec["git_stamps"], "note": a.get("note")},
            }, intent=f"tierb:{a['rel']}")
        for m in spec.get("attest_missing", []):
            s.submit("artifact.attest_missing", m, intent=f"missing:{m['name']}")
        s.report("artifacts")


def seed_windows(pc_json: Path) -> None:
    """Register ws_sgl_w1w4 from a PARSED precommit doc (produced at M3 from the hashed
    precommit.m — never typed by hand)."""
    pc = json.loads(pc_json.read_text())
    windows = pc["windows"]                        # [{name, start, end, role}] — from the parse
    seed = load_seed("anotherstrategy.json")
    payload = {
        "windowset_id": "ws_sgl_w1w4",
        "data_contract": "anotherstrategy_p0",
        "windows": [{"wiv_id": _wiv_id("anotherstrategy_p0", w["start"], w["end"]),
                     "data_contract": "anotherstrategy_p0",
                     "start": w["start"], "end": w["end"], "role": w["role"]} for w in windows],
        "exclusions": pc.get("exclusions", []),
        "embargo": {"left_days": pc["embargo"]["left_days"],
                    "right_days": pc["embargo"]["right_days"],
                    "right_provisional": True},
        # the legacy set registers exit-anchored on the pair-CSV datetimes, clock = UTC
        # (label corrected by the alignment addendum; mask mechanics byte-identical)
        "anchor_field": "exit",
        "clock": seed["clock_law"]["csv_clock"],
        "status": "live",
    }
    with SeedSession() as s:
        s.submit("windowset.register", payload, intent="seed:ws_sgl_w1w4")
        # constants doc for pc itself
        s.submit("constants.register",
                 {"series": "pc", "doc_id": pc.get("doc_id", "pc_v0.7.0"), "version": 1,
                  "entries": [{"key": k, "value": v, "finality": "provisional"}
                              for k, v in pc.get("scalars", {}).items()],
                  "provenance": {"parsed_from": "precommit.m",
                                 "precommit_sha256": pc.get("precommit_sha256")}},
                 intent="seed:pc")
        s.report("windows")


def arm_conditionals() -> None:
    """ARM the exactly-three M3 conditionals (PLAN §2b): budget-floor alarm, extended-SUSPEND
    alarm, embargo supersession. Human-authored (REG-INV-22); the placebo recipe must already
    be registered (its freeze BLOCKS this arming — amending a tripwire after arming is
    post-hoc gate-editing)."""
    with SeedSession() as s:
        if "placebo_recipe" not in s.state.constants:
            raise SystemExit("REFUSING to arm: the placebo recipe is not registered (freeze blocks arming)")
        lineage = "lin::ws_sgl_w1w4"
        s.submit("conditional.arm", {
            "cond_id": "budget_floor_alarm_gen1",
            "kind": "budget_floor_alarm",
            "predicate": {"name": "budget_floor_alarm", "version": "1",
                          "params": {"lineage_id": lineage}},
            "event_body": {"type": "note.record",
                           "payload": {"title": "BUDGET FLOOR ALARM",
                                       "body": f"lineage {lineage}: slots_remaining <= alarm floor "
                                               "— daily digest escalation", "tags": ["digest"]}},
        }, intent="arm:budget_floor", provenance="discretionary",
            hypothesis="arming the registered budget-floor alarm at M3 seed (PLAN §2b)",
            reasoning="alarm at slots_remaining<=alarm_remaining is a signed constant",
            expected_outcome="digest escalation fires at the floor; no readout consequence")
        s.submit("conditional.arm", {
            "cond_id": "extended_suspend_alarm_gen1",
            "kind": "extended_suspend_alarm",
            "predicate": {"name": "extended_suspend_alarm", "version": "1",
                          "params": {"lineage_id": lineage}},
            "event_body": {"type": "constants.amend",
                           "payload": {"series": "autonomy_constants",
                                       "old_doc_id": "autonomy_v1",
                                       "new_doc_id": "autonomy_v1_suspended",
                                       "version": 2,
                                       "entries": [{"key": "readout_conditional_channel",
                                                    "value": "SUSPENDED_pending_human_review",
                                                    "finality": "provisional"}],
                                       "rationale": "extended-SUSPEND alarm fired (placebo L2 / "
                                                    "3-L1s-in-12 / void / contested / forensic)"}},
        }, intent="arm:extended_suspend", provenance="discretionary",
            hypothesis="arming the extended-SUSPEND alarm at M3 seed (PLAN v10 §2b, PB-1.2 scope)",
            reasoning="single L2 or 3-L1s-in-12 or void/contested/forensic ⇒ suspend the channel",
            expected_outcome="~3%/generation false-SUSPEND; human review + re-arm on fire")
        s.report("conditionals")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["constants", "artifacts", "windows", "arm-conditionals"])
    p.add_argument("--base", type=Path, default=Path("/home/alex/Documents/Atesting7/BelkaSGL"))
    p.add_argument("--pc", type=Path)
    a = p.parse_args()
    if a.what == "constants":
        seed_constants()
    elif a.what == "artifacts":
        seed_artifacts(a.base)
    elif a.what == "windows":
        assert a.pc, "--pc pc_v062.json required (window dates are parsed, never remembered)"
        seed_windows(a.pc)
    elif a.what == "arm-conditionals":
        arm_conditionals()


if __name__ == "__main__":
    main()
