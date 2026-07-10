"""NS1 snapshots · NS2 features/featuresets · NS4 param families."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CausalityClass = Literal["audited", "legacy_attested", "pending"]
FeatureStatus = Literal["core", "extended", "dormant", "pending", "screened_out"]


class DatasetRegister(BaseModel):
    """NS1 market-data snapshot registration (dataset.register)."""
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str                        # snap_<hash12> display handle
    source_kind: Literal["mt3_csv", "binance_export", "attested_external"]
    raw_sha256: str                         # declared by client
    computed_raw_sha256: Optional[str] = None  # injected by ingest; barrier H-class compares
    n_rows: int
    canonical_content_digest: Optional[str] = None
    digest_scheme_version: Optional[str] = None
    ts_range: tuple[str, str]
    stamp_semantics: Literal["bar_open"] = "bar_open"
    clock: Literal["utc"] = "utc"
    variants: list[str] = Field(default_factory=list)   # e.g. ["zerovol"]
    path: str                                            # registered in place (large data)


class FeatureRegister(BaseModel):
    """NS2 feature (feature.register)."""
    model_config = ConfigDict(extra="forbid")
    feature_id: str
    family: str
    definition: str                          # human definition; the materializer ref is code
    dtype: str
    lookback_bars: int
    knowable_at: Literal["entry"] = "entry"
    causality_class: CausalityClass
    status: FeatureStatus
    correlate_of: Optional[str] = None       # evicted representative's alternate (seat tournament)
    # The clock pin (FS-1.3): any time/day feature MUST name its clock explicitly.
    clock: Optional[str] = None              # e.g. "gmt+2_us_dst" for `hour`


class FeatureStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_id: str
    from_status: FeatureStatus
    to_status: FeatureStatus
    swap_out: Optional[str] = None           # REQUIRED at d_max promote-to-core (seat atomicity)


class FeaturesetFreeze(BaseModel):
    """NS2 immutable hashed column list (featureset.freeze)."""
    model_config = ConfigDict(extra="forbid")
    featureset_id: str                       # fs_<hash8>
    columns: list[str]                       # ordered
    definitions_sha256: str                  # sha256 of ordered definitions
    causality_class: CausalityClass
    materializer_ref: Optional[str] = None


class FamilyRegister(BaseModel):
    """NS4 param family (family.register). KEY≠seed doctrine lives per family."""
    model_config = ConfigDict(extra="forbid")
    family_id: str
    kind: Literal["geometry", "population", "feature"]
    param_schema: Literal["sgl_soft", "sgl_rank", "vbt_population", "mixture_t", "sjm_sparse"]
    key_scheme_version: str
    status: Literal["active", "dormant"] = "dormant"


class FamilyActivate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family_id: str
    # discretionary event — hypothesis lives in the envelope
