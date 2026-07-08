"""NS5 registration blocks + arms · trials batches · readouts.

Arm roles: real | info | placebo | control (control lands with TS-MIX adoption; the literal is
present so the schema needs no bump — CONTROL_PROMOTION stays categorical either way).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ArmRole = Literal["real", "info", "placebo", "control"]


class ArmSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arm_id: str
    role: ArmRole
    config_keys: list[str] = Field(default_factory=list)   # engine KEY strings (KEY≠seed)
    budget: int                                             # arms priced at registration (B-class)
    seeds_declared: list[int] = Field(default_factory=list) # REG-INV-23: stochastic arms declare seeds
    notes: Optional[str] = None


class BlockRegister(BaseModel):
    """block.register — the frozen-decision container. Freezing happens as its own event."""
    model_config = ConfigDict(extra="forbid")
    block_id: str                            # blk_<hash8>
    kind: Literal["geometry_sgl", "population_vbt", "rescore", "readout", "rehearsal", "level1"]
    family_id: str
    featureset_hash: str                     # REG-INV-08 referential integrity
    population_ref: Optional[str] = None
    windowset_id: Optional[str] = None
    arms: list[ArmSpec]
    null_spec: Optional[dict] = None         # CRN spec ref: {shift_vector_sha256, n_shuffles_ref, seed_base_ref}
    kill_gates: Optional[dict] = None
    fill_model: Optional[dict] = None        # vbt blocks: pinned {intrabar_ordering, entry_ref, fee_bps, size}
    gates_required: list[str] = Field(default_factory=list)  # e.g. ["mutation_audit"] (REG-INV-20)
    evaluated_map_cited: bool = False        # P3: proposer contract requires citing the map


class BlockFreeze(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    declared_width: int                      # the width gate_ref prices (two-tills, IS till)
    grid_digest: Optional[str] = None        # Stage-1 grids: pins the neighbor set (plateau summary key)


class BlockSupersede(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_block_id: str
    new_block_id: str
    rationale: str


class BlockKillAxis(BaseModel):
    """Retro-prohibition the barrier resolves against — 'spent hypotheses never retried'."""
    model_config = ConfigDict(extra="forbid")
    axis: str                                # e.g. "family:fam_x/param:y-range"
    rationale: str


class BlockClose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str


# ---- trials (batch events referencing trial-table artifacts — never 16k events/night) -------
class TrialsOpenBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    block_id: str
    n_planned: int


class TrialsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    block_id: str
    n_rows: int
    n_distinct_keys: int                     # core checks DECLARED distinct-KEY counts (KEY≠seed)
    rows_file: str                           # FileRef (artifact ref)
    null_max_file: Optional[str] = None      # role: null_of_max artifact
    gate_ref_q95: Optional[float] = None
    dataset_ref: str
    engine_stamp: dict                       # {name, version, git} — git-clean (REG-INV-13)
    null_spec_hash: Optional[str] = None     # must equal the block's frozen null spec (REG-INV-07)
    pc_echo: Optional[dict] = None           # the PC struct threaded through the computation (B5)
    env_hash: Optional[str] = None           # vbt: sha256(sorted pip freeze + platform)


class TrialsCloseBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    block_id: str


# ---- readouts -------------------------------------------------------------------------------
class ReadoutRequest(BaseModel):
    """readout.request — spend-time, pre-unmask. Normally scheduler-fired via a per-batch
    human-armed conditional (NS12 kind); H-direct = degraded mode; agent grant RETIRED."""
    model_config = ConfigDict(extra="forbid")
    readout_id: str
    block_id: str
    windowset_id: str
    scope_id: str
    population_ref: str
    purpose: Literal["readout", "postmortem", "rehearsal"] = "readout"
    gate_table_template_ref: str             # registered BEFORE unmask (REG-INV-23)
    rehearsal_artifact_ref: Optional[str] = None  # required for purpose="readout"
    counts_stamp_ref: str                    # exact (windowset, population) pair (REG-INV-03)


class ReadoutRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readout_id: str
    result_artifact_ref: str
    five_clause: dict                        # clause results (measured; post-shot clauses may pend)
    placebo_result: Optional[dict] = None    # {max_z, gate_ref, extended_max, classification: none|L1|L2}
    info_rows_present: bool                  # REG-INV-17: dust info row mandatory


class ReadoutVoid(BaseModel):
    """HUMAN-ONLY categorically (REG-INV-22). Restores the budget slot. Legal only with the
    no-interim-emission evidence (absent unmask artifact + engine log + a note)."""
    model_config = ConfigDict(extra="forbid")
    readout_id: str
    evidence: dict                           # {unmask_artifact_absent: true, engine_log_ref, note_ref}
