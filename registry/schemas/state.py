"""RegistryState (TECH_SPEC §5.1) — derived, in-daemon; snapshot = cache, never authoritative.

View bodies are dicts (the reducer keeps them small and JSON-serializable); correctness lives
in the barrier + payload schemas. state_hash = sha256_canon(model_dump) — recomputed per
append, fail-stop on mismatch (E-class verification).
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..canon import sha256_canon


class RegistryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_seq: int = -1
    head_hash: str = "0" * 64

    # namespaces (dict[str, dict] views keyed by object id)
    snapshots: dict[str, dict] = Field(default_factory=dict)
    features: dict[str, dict] = Field(default_factory=dict)
    featuresets: dict[str, dict] = Field(default_factory=dict)
    families: dict[str, dict] = Field(default_factory=dict)
    populations: dict[str, dict] = Field(default_factory=dict)      # incl. stamp status → usable?
    blocks: dict[str, dict] = Field(default_factory=dict)           # status, budgets remaining per arm
    trials_batches: dict[str, dict] = Field(default_factory=dict)
    windowsets: dict[str, dict] = Field(default_factory=dict)
    windows: dict[str, dict] = Field(default_factory=dict)          # wiv_id → {..., spends: []}
    scopes: dict[str, dict] = Field(default_factory=dict)
    lineages: dict[str, dict] = Field(default_factory=dict)         # {k_cumulative, generation,
                                                                    #  budget:{remaining,floors},
                                                                    #  one_shot_map:{(wiv,scope):ref}}
    placebo_history: dict[str, list[dict]] = Field(default_factory=dict)  # lineage → L1/L2 marks by k
    readouts: dict[str, dict] = Field(default_factory=dict)
    artifacts: dict[str, dict] = Field(default_factory=dict)
    cards: dict[str, dict] = Field(default_factory=dict)
    scorecards: dict[str, dict] = Field(default_factory=dict)       # key_hash → scorecard (evaluated map)
    grid_summaries: dict[str, dict] = Field(default_factory=dict)   # block_id → Stage1GridSummary
    clause_stamps: dict[str, dict] = Field(default_factory=dict)    # candidate → {clause: stamp}
    incumbents: dict[str, Optional[str]] = Field(default_factory=dict)      # lineage → candidate
    incumbent_history: dict[str, list[str]] = Field(default_factory=dict)   # for projection-restore
    constants: dict[str, dict] = Field(default_factory=dict)        # series → latest doc (+history)
    constants_history: dict[str, list[dict]] = Field(default_factory=dict)
    rules: dict[str, dict] = Field(default_factory=dict)            # rule_kind → {live, versions, probation}
    conditionals: dict[str, dict] = Field(default_factory=dict)
    cycles: dict[str, dict] = Field(default_factory=dict)           # cycle_id → {status, pinned versions}
    open_cycle: Optional[str] = None
    kill_list: list[dict] = Field(default_factory=list)             # retro-prohibitions (barrier resolves)
    suspensions: dict[str, Any] = Field(default_factory=dict)       # e.g. readout_conditional_channel
    notes: list[str] = Field(default_factory=list)                  # note event_ids (bodies in log)
    dedup: set[str] = Field(default_factory=set)                    # event_ids seen (idempotency)

    def state_hash(self) -> str:
        d = self.model_dump(mode="json")
        d["dedup"] = sorted(self.dedup)      # sets serialize unordered — pin order for hashing
        return sha256_canon(d)


def empty_state() -> RegistryState:
    return RegistryState()
