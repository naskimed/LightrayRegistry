"""arm_supersession — the MISSING third M3 conditional (PLAN v10 §2b / SEED_PACK SP-1.4 §2).

register_seed.arm_conditionals() arms budget-floor + extended-SUSPEND; its own docstring
promises three. This module arms the third: the windowset supersession ws_sgl_w1w4 ->
ws_sgl_w1w4_v2 — re-anchor masks on ENTRY times UTC (closes OPEN-16) and right embargo
55d -> 46d FINAL (closes OPEN-9's embargo half, from code, conditional on G2). Fires on the
EXISTING predicate g2_and_alignment_green v1 (already in predicates.py). Safe failure mode:
G2 red => never fires => 55d stands.

HUMAN-ONLY (REG-INV-22): windowset.supersede and conditional.arm are apparatus/kill-class.
Run this yourself, after review, after seed_windows() — never let an agent run it.
Amending after arming is post-hoc gate-editing (SEED_PACK §2 mechanics line).

Carryover: asserted from window-interval lineage AT ARM TIME (wiv ids unchanged — only mask
semantics move, which live at windowset level; spends + cumulative k carry). If spends move
between arming and firing, the barrier rejects the fired body as inconsistent and the
conditional goes STALE => human re-arm. That is the designed behavior, not a bug.

Usage:
  python -m registry.tools.arm_supersession --pc pc_v062.json \
      --g2-artifact art_<g2_stamp_hash12> --alignment-artifact art_<align_hash12>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .register_seed import _wiv_id
from ._seed import SeedSession, load_seed

RIGHT_EMBARGO_FINAL_DAYS = 46   # SEED_PACK §2: 45d dv_envelope + 1d registered buffer
LEFT_EMBARGO_DAYS = 2           # unchanged (max holding 29.8h; entry-anchor makes purge exact)


def build_supersede_body(pc: dict, state) -> dict:
    seed = load_seed("anotherstrategy.json")
    dc = "anotherstrategy_p0"
    windows = [{"wiv_id": _wiv_id(dc, w["start"], w["end"]), "data_contract": dc,
                "start": w["start"], "end": w["end"], "role": w["role"]}
               for w in pc["windows"]]
    carryover = []
    for w in windows:
        st = state.windows.get(w["wiv_id"], {}) if state is not None else {}
        carryover.append({"wiv_id": w["wiv_id"],
                          "spends": list(st.get("spends", [])),
                          "k_cumulative": int(st.get("k_cumulative", 0))})
    return {
        "old_windowset_id": "ws_sgl_w1w4",
        "new_windowset_id": "ws_sgl_w1w4_v2",
        "new_windowset": {
            "windowset_id": "ws_sgl_w1w4_v2",
            "data_contract": dc,
            "lineage_id": "lin::ws_sgl_w1w4",          # lineage continues — spend key unchanged
            "windows": windows,                          # interval ids UNCHANGED by design
            "exclusions": pc.get("exclusions", []),
            "embargo": {"left_days": LEFT_EMBARGO_DAYS,
                        "right_days": RIGHT_EMBARGO_FINAL_DAYS,
                        "right_provisional": False},     # FINAL — the theorem, not a margin
            "anchor_field": "entry",                     # the OPEN-16 re-anchor
            "clock": seed["clock_law"]["csv_clock"],     # UTC (addendum A3 label correction)
            "status": "live",
        },
        "carryover": carryover,
        "rationale": ("SEED_PACK §2: dv binding memory = SMA(30) weekday-D1 TR => 41d worst "
                      "+ 3d shift gap + 1d TR seed = 45d hard cutoff; right embargo 46d "
                      "(45+1 buffer); 27 interior days returned to training; conditional on "
                      "G2 five-feature parity (elementwise dv agreement rules out Wilder)."),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pc", type=Path, required=True)
    p.add_argument("--g2-artifact", required=True)
    p.add_argument("--alignment-artifact", required=True)
    a = p.parse_args()
    pc = json.loads(a.pc.read_text())
    with SeedSession() as s:
        body = build_supersede_body(pc, s.state)
        s.submit("conditional.arm", {
            "cond_id": "embargo_supersession_gen1",
            "kind": "windowset_supersession",
            "predicate": {"name": "g2_and_alignment_green", "version": "1",
                          "params": {"g2_artifact": a.g2_artifact,
                                     "alignment_artifact": a.alignment_artifact}},
            "event_body": {"type": "windowset.supersede", "payload": body},
            "note": "third M3 conditional (PLAN v10 §2b); safe failure: G2 red => 55d stands",
        }, intent="arm:embargo_supersession", provenance="discretionary",
            hypothesis="55d->46d right embargo is a theorem given EA-ATR==SMA; G2 proves the premise",
            reasoning="SEED_PACK §2 derivation (41+3+1=45, +1 buffer); wiv interval identity carries spends+k",
            expected_outcome="fires only on green stamps; masks re-anchor entry/UTC; July shot masks stay bit-reproducible")
        s.report("supersession-arm")


if __name__ == "__main__":
    main()
