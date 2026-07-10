# registry_delta — 2026-07-08 authoring-bench bundle

Drop-in files for the LightrayRegistry checkout (paths mirror the repo). Authored in the
Claude app bench; nothing here has touched a ledger. The barrier on your machine is the
validator; you are the ratifier.

## Contents

- `registry/tools/descriptor_emit.py` — the agent's eyes. FROZEN field list (user, 2026-07-08):
  per (side, component) per feature — n, median, iqr, p05, p95, bowley_skew. Target-blind by
  allowlist; byte-identical re-emit proven by `--selftest` (ran green on the bench). DECOUPLED
  from TS-MIX adoption by user decision: partition source #1 = `incumbent_cluster_id` from the
  converted P0; the mixture, if adopted, is just a second partition source.
- `seed/features_seed.json` — NS2 catalog transcription (FS-1.3 + SEED_PACK §2 derivation).
  35 payloads, ALL validated against `schemas/features.FeatureRegister` on the bench.
- `seed/families_programs_seed.json` — NS4 families (sgl_soft/sgl_rank active, mixture_t
  dormant; three vbt population families dormant) + `ns5_programs` constants (P0–P6, exit-family
  law, sizing, scouting doctrine, renderer requirement). 6 family payloads validated.
- `registry/tools/register_domain_seed.py` — registrar for both files (SeedSession pattern,
  idempotent, source citations ride the envelope `reasoning` field).
- `registry/tools/arm_supersession.py` — the MISSING third M3 conditional (register_seed's
  docstring promises three, arms two). Transcribed from SEED_PACK §2; uses the EXISTING
  predicate `g2_and_alignment_green` v1; 55d→46d final, entry/UTC re-anchor, carryover built
  from wiv lineage at arm time (stale-on-drift is designed behavior).

## Run order (your machine)

1. `git`-add the bundle; move the docs set into `docs/` (M0 close-out house rule) and
   RE-HASH: features/seed-pack sha256s cited inside the seed files must match the `docs/`
   copies (they were computed from the uploaded sources:
   FEATURES d346b2fc… · SEED_PACK 47664749…). Mismatch ⇒ stop, reconcile versions first.
2. `python -m registry.tools.descriptor_emit --selftest` (independent re-proof on your box).
3. Existing drivers first: `register_seed constants` → `convert_legacy_pair` → `register_seed
   artifacts` → `parse_precommit` → `register_seed windows` → `register_seed arm-conditionals`.
4. New: `register_domain_seed features` → `register_domain_seed families`.
5. Emit the first cards: `descriptor_emit --pop-dir <converter out> --drafts inbox/staging`
   (drafts carry actor `scheduler`; append via the daemon path or your seed session).
6. HUMAN-ONLY, after review, after G-stamps exist: `arm_supersession --pc pc_v062.json
   --g2-artifact … --alignment-artifact …`. Do not delegate; do not pre-arm before stamps.

## Flags & open items (changelog rule — nothing silently dropped)

- REQUIRES_HUMAN_APPEND: step 6 (windowset.supersede arming) and everything register_seed
  already gates as apparatus. The two seed registrars are non-apparatus registrations.
- `key_scheme_version: "ks_v1"` in families is a PROPOSED placeholder — exact KEY format
  strings sit on the TS-MIX ⟦GAP⟧ register; nod or amend before first block.freeze.
- `f_stale_frac` window: doc-silent; 288 placeholder flagged inside the entry.
- OPEN (user): sjm_sparse reconciliation — register dormant vs conscious decline. NOT added.
- OPEN (recorded): typed-hypothesis envelope v2 (P6) — current fields are prose strings.
- The boundary skill (`boundary-agent-v0-SKILL.md`, shipped earlier) is the interactive twin
  of `roles/boundary.md`; durable learnings fold back into the role file.
