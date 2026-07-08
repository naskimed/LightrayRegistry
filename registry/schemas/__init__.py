"""Pydantic v2 schemas — validate at the boundary; hash the VALIDATED dump (canon.py).

Layout (TECH_SPEC §2):
  envelope.py      event envelope, actors, event vocabulary
  blocks.py        NS5 blocks + arms + trials batches
  features.py      NS2 features/featuresets + NS4 param families
  windows.py       NS3/NS7 windowsets, window-interval lineage, scopes, spends
  trials.py        trial-table manifests, null specs (CRN)
  cards.py         NS9 card payloads (5 types + descriptor on adoption)
  constants.py     NS11 constants docs (autonomy, agent contracts, dial, placebo, ...)
  certs.py         NS10 clause stamps, certification, incumbency
  artifacts.py     NS8 artifact registration/stamps
  scorecards.py    TS-2.0 §5.5 EvalKey/Scorecard/StageMetrics + DialBudgetRule
  conditionals.py  NS12 pre-signed conditionals
  budget.py        NS7 per-lineage look budget (REG-INV-24)
  state.py         RegistryState — the derived, rebuildable in-daemon state
"""
