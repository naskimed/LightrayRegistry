"""Deterministic card compressors (NS9) — byte-identical on re-emit.

Cards are the boundary session's ONLY sensory input (cards-not-rows). Coarseness applies to
priced, non-certified arms (clause pass/fail + banded magnitudes — near-winners are the
richest conditioning fuel, which is exactly why they leak); certified arms flow to Level-1 in
full. Provisional flags propagate into card text (REG-INV-10). Budget state + k-stamp ride
every card (transparency with ZERO verdict weight).
"""
from __future__ import annotations

from .canon import sha256_canon
from .schemas.state import RegistryState


def _card_id(payload: dict) -> str:
    return "card_" + sha256_canon(payload)[:12]


def _budget_state(state: RegistryState, lineage_id: str) -> dict | None:
    lin = state.lineages.get(lineage_id)
    if not lin:
        return None
    b = lin.get("budget", {})
    return {"k_cumulative": lin.get("k_cumulative", 0),
            "remaining": b.get("remaining"),
            "alarm_remaining": b.get("alarm_remaining"),
            "diagnostic_mode": b.get("diagnostic_mode", False)}


def _band(x: float, edges: list[float]) -> str:
    """Banded magnitude — how MUCH each read leaks is bounded by coarseness (Dwork anchor)."""
    for e in edges:
        if x < e:
            return f"<{e}"
    return f">={edges[-1]}"


def separation_card(state: RegistryState, readout_id: str, coarseness_edges: list[float]) -> dict:
    """Separation card from a recorded readout: certified arms full, others banded."""
    r = state.readouts.get(readout_id, {})
    lineage = state.windowsets.get(r.get("windowset_id", ""), {}).get("lineage_id", "")
    clauses = r.get("five_clause", {}) or {}
    payload = {
        "card_type": "separation",
        "readout_id": readout_id,
        "clause_passfail": {k: bool(v) if isinstance(v, bool) else v.get("pass")
                            for k, v in clauses.items()} if clauses else {},
        "placebo_classification": r.get("placebo_classification", "none"),
        "cert_ineligible": bool(r.get("cert_ineligible")),
        "coarseness_applied": True,
    }
    bs = _budget_state(state, lineage)
    return {"card_id": _card_id(payload), "card_type": "separation",
            "inputs": [readout_id], "payload": payload,
            "coarseness_applied": True, "provisional_flags": _provisional_flags(state),
            "budget_state": bs,
            "k_stamp": (f"look {bs['k_cumulative']} of budget" if bs else None)}


def surface_card(state: RegistryState, block_id: str) -> dict:
    """Surface card over a block's Stage-1 grid summary (plateau lives at BLOCK level, T11)."""
    gs = state.grid_summaries.get(block_id, {})
    payload = {"card_type": "surface", "block_id": block_id,
               "grid_digest": gs.get("grid_digest"),
               "plateau_summary": gs.get("plateau_stats", {})}
    return {"card_id": _card_id(payload), "card_type": "surface",
            "inputs": [block_id], "payload": payload,
            "coarseness_applied": False, "provisional_flags": _provisional_flags(state)}


def stability_card(state: RegistryState, block_id: str, stability: dict) -> dict:
    payload = {"card_type": "stability", "block_id": block_id, **stability}
    return {"card_id": _card_id(payload), "card_type": "stability",
            "inputs": [block_id], "payload": payload,
            "coarseness_applied": False, "provisional_flags": _provisional_flags(state)}


def cluster_card(state: RegistryState, geometry_ref: str, census: dict) -> dict:
    payload = {"card_type": "cluster", "geometry_ref": geometry_ref, **census}
    return {"card_id": _card_id(payload), "card_type": "cluster",
            "inputs": [geometry_ref], "payload": payload,
            "coarseness_applied": False, "provisional_flags": _provisional_flags(state)}


def novelty_card(state: RegistryState, payload: dict) -> dict:
    """Target-blind at schema level — validated by NoveltyCardPayload at emit."""
    return {"card_id": _card_id(payload), "card_type": "novelty",
            "inputs": [payload.get("population_ref", "")], "payload": payload,
            "coarseness_applied": False, "provisional_flags": _provisional_flags(state)}


def _provisional_flags(state: RegistryState) -> list[str]:
    flags = []
    for series, doc in state.constants.items():
        if any(e.get("finality") == "provisional" and not e.get("unknown")
               for e in doc.get("entries", [])):
            flags.append(f"provisional:{series}")
    return sorted(flags)
