"""TS-2.0 §5.5 — EvalKey, Scorecard (pure measurement record), StageMetrics, the dial split,
and the cycle machinery payloads.

Load-bearing choices (all signed 2026-07-07, DELTA_2_3_REVIEW themes):
- Scorecard has NO score field and NO status field (T1): the promotion scalar is computed by
  the projection AT PROJECTION TIME under the CYCLE-PINNED score_fn_version — a score-fn amend
  re-orders at zero recompute; promoted/parked/killed is projection state, never content.
- EvalKey.stage ∈ {1,2,3,4}: Stage 0 emits a validity list (a projection), not scorecards.
- geometry_ref: required iff stage >= 2 (model validator).
- plateau_stat is NOT per-config (T11): it lives in the block-level Stage-1 GRID SUMMARY whose
  key includes the block/grid digest.
- Stage3 placebo_telemetry: none|exceeds_gate_ref — search-width n=200 TELEMETRY ONLY, never
  an extended-SUSPEND alarm input (PB-1.2).
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..canon import sha256_canon


class EvalKey(BaseModel):
    """THE evaluated-map key (PORT P3)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    config_key: str                          # engine's exact KEY string (KEY≠seed doctrine)
    key_scheme_version: str
    matrix_digest: str                       # population content_digest
    featureset_hash: str
    geometry_ref: Optional[str] = None       # adopted-geometry Artifact hash
    stage: Literal[1, 2, 3, 4]
    scorer_version: str                      # per-stage metric-block definition version
    predicate_version: str
    cost_model_version: str                  # IN the key: an amend invalidates by key —
                                             # rescore is the intended, priced consequence

    @model_validator(mode="after")
    def _geometry_iff_stage2plus(self) -> "EvalKey":
        if self.stage >= 2 and not self.geometry_ref:
            raise ValueError("stage >= 2 requires geometry_ref")
        if self.stage < 2 and self.geometry_ref:
            raise ValueError("stage < 2 must not carry geometry_ref")
        return self

    def key_hash(self) -> str:
        return sha256_canon(self.model_dump(mode="json"))


class Stage1Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[1] = 1                    # the discriminator tag (inside the member)
    n_trades: int
    gross_pf: float
    net_pf_proxy: float                      # costed at eval_key.cost_model_version (seed: v0_flat)
    kill_gate_results: dict
    population_floor_pass: bool
    mask_window_id: str
    # NO plateau_stat here (T11) — see Stage1GridSummary.


class Stage2Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[2] = 2
    per_blob: list[dict]                     # [{blob, n, contrib}] — FULL here; coarseness at cards
    coverage: float
    dust_fraction: float
    abstain_rate: float


class Stage3Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[3] = 3
    sep_z: float
    gate_ref: float                          # at the cohort's width (two-tills, IS till)
    max_null_quantile_position: float
    placebo_telemetry: Literal["none", "exceeds_gate_ref"] = "none"
    # ^ search-width twin at the REGISTERED n=200 — NEVER an alarm input (PB-1.2 scoping).
    feature_perm_verdict: str
    crn_stamp_ref: str


class Stage4Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal[4] = 4
    fidelity_haircut: float
    fill_quality: dict
    cost_model_residual: float
    determinism_rerun_hash: str


StageMetrics = Union[Stage1Metrics, Stage2Metrics, Stage3Metrics, Stage4Metrics]


class Scorecard(BaseModel):
    """Frozen, canonical-JSON hashed, deterministic — a PURE MEASUREMENT RECORD."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    scorecard_id: str                        # sc_<stage>_<hash16(eval_key)> — display handle;
                                             # identity = payload_sha256 (full)
    eval_key: EvalKey
    inputs: list[str]                        # registered artifact refs
    metrics: StageMetrics = Field(discriminator="stage")
    flags: list[str] = Field(default_factory=list)   # provisional propagation (REG-INV-10)
    payload_sha256: str
    # NO `score`, NO `score_fn_version`, NO status (T1).


class ScorecardEmit(BaseModel):
    """scorecard.emit — scheduler-mechanical (REG-INV-25, signed Q1). The deterministic scorer
    computes the Scorecard from ingested result manifests; the payload embeds it."""
    model_config = ConfigDict(extra="forbid")
    scorecard: Scorecard
    cycle_id: str


class Stage1GridSummary(BaseModel):
    """Block-level Stage-1 summary — plateau lives HERE, keyed by the grid (T11)."""
    model_config = ConfigDict(extra="forbid")
    block_id: str
    grid_digest: str                         # pinned at block.freeze
    scorer_version: str
    plateau_stats: dict[str, float]          # config_key -> neighbor-delta stat
    payload_sha256: str


# ---- the dial split (signed Q2: budgets STAY P7-probationable, moved to the RULES namespace) --
class CpuBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_hours: float


class DialBudgetRule(BaseModel):
    """RULES-namespace object — P7-PROBATIONABLE (STAT-INV-10 lifecycle). Ancestor-verbatim
    backing: 'dial budgets = search apparatus — they choose who sits the exam, never the grade.'
    STAT-INV-05 firewall is SCHEMA-LEVEL here too: no field referencing windows, spend, or the
    look budget exists (extra='forbid' makes the fixture fail at validation)."""
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    version: int
    stage_budgets: dict[str, CpuBudget]      # keys: "stage1".."stage4"
    novelty_quota_share: float               # capacity share (HOW MANY exploration slots — not who)


class DialConstants(BaseModel):
    """NS11 — human-only shell (constants.amend; barrier law unchanged)."""
    model_config = ConfigDict(extra="forbid")
    dial_id: str
    version: int
    unit_costs_ref: str                      # cascade_unit_costs_v1 (provisional until re-measure)
    budget_rule_ref: str                     # cites the LIVE DialBudgetRule; pinned per cycle


# ---- cycle machinery (TS-2.0 §5.5.1) --------------------------------------------------------
class CycleOpen(BaseModel):
    """Versions PINNED at open; rule/apparatus adoptions apply at the NEXT open, never mid-cycle."""
    model_config = ConfigDict(extra="forbid")
    cycle_id: str
    dial_budget_rule_version: str
    score_fn_version: str
    promotion_predicate_version: str
    cost_model_version: str


class CycleClose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_id: str
    # barrier checks STAT-INV-08 (COVERAGE_DEFICIT, deficit enumerated) before accepting


class StageDispatch(BaseModel):
    """stage.dispatch — the scheduler's record of a stage job (replay determinism = M8S)."""
    model_config = ConfigDict(extra="forbid")
    cycle_id: str
    job_kind: Literal[
        "stage0_enumerate", "stage1_sweep_vbt", "stage2_bridge_assign",
        "stage3_null_battery", "stage4_fidelity_l2", "rehearsal", "score_external_labels",
    ]
    job_id: str
    inputs: dict


# ---- rules channel payloads (P7 probation, STAT-INV-10) --------------------------------------
class RulesPropose(BaseModel):
    """Boundary-proposable, TARGET-BLIND predicates/rules ONLY (P7): contract screens,
    redundancy screens, novelty scoring, dial budgets. Label-touching = apparatus = rejected."""
    model_config = ConfigDict(extra="forbid")
    rule_kind: Literal["dial_budget_rule", "contract_screen", "redundancy_screen", "novelty_scoring"]
    proposed: dict                            # the rule body (e.g. DialBudgetRule dump)
    replay_report_ref: Optional[str] = None   # counterfactual replay screen evidence


class RulesAdopt(BaseModel):
    """ONLY via scheduler materialization of a green probation predicate (STAT-INV-10)."""
    model_config = ConfigDict(extra="forbid")
    proposal_ref: str
    rule_kind: str
    adopted_version: str
    probation_predicate: dict                 # {name, version} that went green


class RulesRevert(BaseModel):
    """Projection-restore of the prior version exactly (the cert.revoke precedent)."""
    model_config = ConfigDict(extra="forbid")
    rule_kind: str
    from_version: str
    to_version: str
    reason: str
