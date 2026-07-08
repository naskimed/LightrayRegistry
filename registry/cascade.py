"""TS-2.0 §5.5.3 — promotion as projection (apparatus per v10.1) + score functions.

promote(s→s+1, cycle) for s ∈ {1,2,3} ONLY — Stage 0→1 is coverage-LAW (STAT-INV-08),
capacity guarded by the R20 lattice census, never by a budget cut.

Scores are computed AT PROJECTION TIME from scorecard metrics under the CYCLE-PINNED
score_fn_version (T1: scorecards carry no score; a score-fn amend re-orders at zero recompute).
Everything below the cut PARKS with its scorecard intact — conscious supersession (signed Q3):
the ancestor hard floor is REMOVED; kills only via explicit block.kill_axis. The realized cut
is TELEMETRY, never a stored constant. Novelty penalty = APPARATUS because it is a
promotion-projection component (ordering authority), not because it is label-bearing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .schemas.state import RegistryState

# ---- score functions (APPARATUS: versioned, human-only amend via constants) -----------------
ScoreFn = Callable[[dict], float]   # metrics dict -> promotion scalar
SCORE_FUNCTIONS: dict[str, ScoreFn] = {}


def score_fn(version: str):
    def deco(fn: ScoreFn) -> ScoreFn:
        SCORE_FUNCTIONS[version] = fn
        return fn
    return deco


@score_fn("score_v1")
def _score_v1(metrics: dict) -> float:
    """Seed score function (registers provisional at M3; human-only amend thereafter).
    Stage 1: costed profit proxy · Stage 2: coverage-weighted blob contribution ·
    Stage 3: sep_z relative to gate_ref · Stage 4: haircut-adjusted survival."""
    stage = metrics.get("stage")
    if stage == 1:
        return float(metrics.get("net_pf_proxy", 0.0))
    if stage == 2:
        contrib = sum(b.get("contrib", 0.0) for b in metrics.get("per_blob", []))
        return contrib * float(metrics.get("coverage", 0.0))
    if stage == 3:
        return float(metrics.get("sep_z", 0.0)) - float(metrics.get("gate_ref", 0.0))
    if stage == 4:
        return -float(metrics.get("fidelity_haircut", 1.0))
    return 0.0


# ---- the projection --------------------------------------------------------------------------
@dataclass
class PromotionResult:
    stage_from: int
    promoted: list[str]                 # eval-key hashes, final order
    parked: list[str]                   # below the cut — scorecards intact, re-enter at zero recompute
    realized_cut_score: float | None    # TELEMETRY (thresholds are observations)
    novelty_promoted: list[str] = field(default_factory=list)


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def promote(state: RegistryState, cycle_id: str, stage_from: int,
            capacity: int, trade_ids: dict[str, set] | None = None) -> PromotionResult:
    """Deterministic function of (scorecards, dial_budget_rule[cycle], score_fn_version[cycle],
    promotion_predicate_version[cycle]). `capacity` = the downstream stage budget expressed as
    a slot count (the scheduler converts CPU budget / unit cost → slots). `trade_ids` maps
    key_hash → trade-id set (from populations) for the novelty penalty."""
    if stage_from not in (1, 2, 3):
        raise ValueError("promote() applies at s ∈ {1,2,3} only — Stage 0→1 is coverage-LAW")
    cyc = state.cycles.get(cycle_id) or {}
    fnv = cyc.get("score_fn_version", "score_v1")   # PINNED at cycle.open, not the live rule
    fn = SCORE_FUNCTIONS.get(fnv)
    if fn is None:
        raise ValueError(f"cycle {cycle_id} pins score_fn_version {fnv!r} not in deployed "
                         f"SCORE_FUNCTIONS {sorted(SCORE_FUNCTIONS)} — cycle.open should have "
                         "validated this against deployed code")

    eligible = [(kh, sc) for kh, sc in state.scorecards.items()
                if sc["eval_key"]["stage"] == stage_from]
    # order by score; tie-break = eval_key lexicographic (hash-stable)
    scored = sorted(eligible,
                    key=lambda kv: (-fn(kv[1]["metrics"]),
                                    _lex_key(kv[1]["eval_key"])))

    # novelty quota: a reserved share promoted under the Jaccard trade-id-overlap penalty
    rule = _live_budget_rule(state)
    quota_share = float(rule.get("novelty_quota_share", 0.0))
    n_novel = int(capacity * quota_share)
    n_score = capacity - n_novel

    promoted: list[str] = [kh for kh, _ in scored[:n_score]]
    novelty: list[str] = []
    if n_novel > 0 and trade_ids:
        promoted_sets = [trade_ids.get(kh, set()) for kh in promoted]
        rest = [(kh, sc) for kh, sc in scored[n_score:]]
        # penalize overlap with the already-promoted set's trade-ids (bandit-lite floor)
        def novelty_key(kv):
            kh, sc = kv
            overlap = max((jaccard(trade_ids.get(kh, set()), s) for s in promoted_sets),
                          default=0.0)
            return (overlap, -fn(sc["metrics"]), _lex_key(sc["eval_key"]))
        for kh, _sc in sorted(rest, key=novelty_key)[:n_novel]:
            novelty.append(kh)
    promoted_all = promoted + novelty
    parked = [kh for kh, _ in scored if kh not in set(promoted_all)]
    cut = None
    if promoted_all:
        last = state.scorecards[promoted_all[len(promoted) - 1 if promoted else 0]]
        cut = fn(last["metrics"])
    return PromotionResult(stage_from=stage_from, promoted=promoted_all, parked=parked,
                           realized_cut_score=cut, novelty_promoted=novelty)


def _lex_key(eval_key: dict) -> str:
    return "|".join(str(eval_key[k]) for k in sorted(eval_key))


def _live_budget_rule(state: RegistryState) -> dict:
    r = state.rules.get("dial_budget_rule", {})
    live = r.get("live") or {}
    body = live.get("body") or {}
    return body if body else {"novelty_quota_share": 0.0}


# ---- Stage-0 validity (the coverage-law side; the R20 census guards capacity) ----------------
def stage0_enumerate(state: RegistryState) -> list[str]:
    """Enumerate Stage-0-valid REGISTERED coordinates (schema/contract/warm-up/cap checks are
    the block registrations' job — validity here = frozen block arms with real configs).
    Scout populations are pre-registration and produce NO Stage-1 scorecards (T9)."""
    valid: list[str] = []
    for blk in state.blocks.values():
        if not blk.get("frozen") or blk.get("closed"):
            continue
        for arm in blk.get("arms", []):
            if arm.get("role") == "real":
                valid.extend(arm.get("config_keys", []))
    return sorted(set(valid))
