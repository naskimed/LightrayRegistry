"""NS8 artifacts — registered in place (path + sha256) or in CAS; stamps are additive."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ArtifactRole = Literal[
    "trial_table", "null_of_max", "engine_cache", "rehearsal", "session_capture",
    "parity_fixture", "card_input", "readout_result", "postmortem", "gate_completion",
    "population", "snapshot", "config_pair", "log", "other",
]

ArtifactStatus = Literal["usable", "quotable_only", "attested_missing"]


class ArtifactRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str                         # art_<hash12> of content
    role: ArtifactRole
    path: Optional[str] = None               # in-place registration (large .mat/parquet)
    cas_sha256: Optional[str] = None         # small JSON/cards copied into CAS
    declared_sha256: Optional[str] = None
    computed_sha256: Optional[str] = None    # ingest-injected; H-class compares
    content_digest: Optional[str] = None     # parquet identity (digest_scheme_version below)
    digest_scheme_version: Optional[str] = None
    status: ArtifactStatus = "usable"
    provenance: dict = Field(default_factory=dict)   # source machine/path/git etc.


class ArtifactStamp(BaseModel):
    """Additive stamp (mutation_audit, parity, counts, ...) — event-logged, file additive."""
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    stamp_kind: Literal["mutation_audit", "parity", "counts", "integrity", "verified", "other"]
    passed: bool
    detail: dict = Field(default_factory=dict)
    # counts stamps: detail = {windowset_id, population_ref, per_window_counts} — REG-INV-03
    # mutation_audit: detail = {positive_control_caught: true, leaks_found: 0} — REG-INV-20


class ArtifactAttestMissing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    expected_role: ArtifactRole
    why: str


class ArtifactIntegrityChecked(BaseModel):
    """Nightly sweep result (scheduler-mechanical, REG-INV-25)."""
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    ok: bool
    recomputed_sha256: Optional[str] = None
