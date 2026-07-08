"""Projections to disk (TECH_SPEC §5.2) — all derived, atomic, rebuildable.

contracts/ exports are the ONLY files engines read: blocks, constants, windowsets,
featuresets. Engines never read the log.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .schemas.state import RegistryState
from .store import write_json_atomic


def export_all(state: RegistryState, w: Path | None = None) -> None:
    w = w or config.workdir()
    write_json_atomic(config.state_dir(w) / "snapshot.json",
                      {"derived": True, "as_of_seq": state.as_of_seq,
                       "state": _dump(state)})
    write_json_atomic(config.state_dir(w) / "spend.json", spend_view(state))
    write_json_atomic(config.state_dir(w) / "deflation.json", deflation_view(state))
    cdir = config.contracts_dir(w)
    for block_id, blk in state.blocks.items():
        if blk.get("frozen"):
            write_json_atomic(cdir / "blocks" / f"{block_id}.json", blk)
    for series, doc in state.constants.items():
        write_json_atomic(cdir / "constants" / f"{series}.json", doc)
    for ws_id, ws in state.windowsets.items():
        write_json_atomic(cdir / "windowsets" / f"{ws_id}.json", ws)
    for fs_id, fs in state.featuresets.items():
        write_json_atomic(cdir / "featuresets" / f"{fs_id}.json", fs)


def _dump(state: RegistryState) -> dict:
    d = state.model_dump(mode="json")
    d["dedup"] = sorted(state.dedup)
    return d


def spend_view(state: RegistryState) -> dict:
    """(windowset, window, scope) → readout refs + budget states per lineage."""
    return {
        "windows": {w: {"role": v.get("role"), "spends": v.get("spends", [])}
                    for w, v in state.windows.items()},
        "lineages": {l: {"k_cumulative": v.get("k_cumulative", 0),
                         "budget": v.get("budget"),
                         "one_shot_map": v.get("one_shot_map", {})}
                     for l, v in state.lineages.items()},
    }


def deflation_view(state: RegistryState) -> dict:
    """The deflation ledger IS a projection of trials.* + readout.* — priced by replay."""
    per_block: dict[str, dict] = {}
    for b in state.trials_batches.values():
        blk = b.get("block_id", "?")
        agg = per_block.setdefault(blk, {"n_rows": 0, "n_batches": 0})
        agg["n_batches"] += 1
        agg["n_rows"] += sum(r.get("n_rows", 0) for r in b.get("records", []))
    return {"blocks": per_block,
            "readouts": {rid: {"purpose": r.get("purpose"), "recorded": r.get("recorded"),
                               "voided": r.get("voided")}
                         for rid, r in state.readouts.items()}}
