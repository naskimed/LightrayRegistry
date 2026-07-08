"""NS9 cards — deterministic compressor outputs; the boundary session's only sensory input.

Byte-identical on re-emit; coarseness constant applies to non-certified priced arms;
provisional flags propagate into card text (REG-INV-10). The novelty card is target-blind at
schema level (no payoff field is representable).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CardType = Literal["separation", "surface", "stability", "cluster", "novelty", "descriptor"]
# "descriptor" rides PORT P9 (ADOPTED); its emitter lands with the TS-MIX adoption event.


class Band(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lo: float
    hi: float
    n: int


class NoveltyCardPayload(BaseModel):
    """TARGET-BLIND AT SCHEMA LEVEL (REG-INV-29 pattern) — no payoff field exists here.
    Ranks the pre-registration scout lane; graduation is boundary-discretionary (D3)."""
    model_config = ConfigDict(extra="forbid")
    population_ref: str
    reference_geometry_ref: str
    knn_params: dict                          # {k, tau, r_max} — CITED from the frozen bridge
                                              # Artifact's actual keys, never free-typed.
                                              # NB: this r_max = kNN neighbor-radius cap,
                                              # UNRELATED to the exit-family barrier_ratio bound.
    abstain_fraction: float                   # frozen_knn out-of-support share — the novelty scalar
    affinity_histogram: list[Band]
    energy_distances: dict[str, float]        # vs each registered population, frozen feature space
    coordinate_class_mismatch: list[str] = Field(default_factory=list)  # e.g. ["hurst"]


class CardEmit(BaseModel):
    """card.emit — scheduler-mechanical (REG-INV-25). Payload dict is validated by the
    compressor for its card_type; the envelope carries the registered inputs."""
    model_config = ConfigDict(extra="forbid")
    card_id: str                              # card_<hash12> of payload
    card_type: CardType
    inputs: list[str]                         # registered artifact/event refs
    payload: dict
    coarseness_applied: bool = False          # priced non-certified arms: banded/clause-only
    provisional_flags: list[str] = Field(default_factory=list)
    budget_state: Optional[dict] = None       # {k, slots_remaining, floors} — carried to the boundary
    k_stamp: Optional[str] = None             # "look k of budget N" — transparency, ZERO verdict weight
