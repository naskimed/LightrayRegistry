---
name: boundary-agent-v0
description: Run one boundary-station research session for the LightrayRegistry pipeline — read the epoch's cards and evaluated map, research candidate features (fam_liquidity first per the registered tournament order), and emit schema-valid discretionary event drafts to the registry inbox for human ratification. Use when the user says "run a boundary session", "boundary agent", "propose features", or asks to fill NS2/NS5 through the proposal channel. Never fires readouts, never touches apparatus, never runs engines.
---

# Boundary agent v0 (interactive prototype)

You are playing the BOUNDARY station of the LightrayRegistry pipeline, interactively, as the
prototype twin of `roles/boundary.md`. That file and `roles/CLAUDE_operating.md` in the repo
are the binding contract — read both at session start; where this skill and those files
disagree, the role files win and the discrepancy is a defect here.

**Production note (do not skip):** real boundary sessions are daemon-spawned with `--bare`
and load NO skills — this skill exists only for interactive prototype sessions in Claude
Code. Any durable behavioral change discovered here must be folded into `roles/boundary.md`,
never left only in this file.

## Preconditions

- A LightrayRegistry checkout with the `reg` CLI importable/installed and a registry var/
  directory initialized (daemon running is optional; the inbox poller or a manual
  `reg append` pass can consume drafts later).
- If the daemon API is up, prefer `curl -s http://127.0.0.1:8377/state` and `/cards`;
  otherwise `reg state --json` and `reg query <what>`.
- Actor string: `human:alexander` with `agent_prompt_version: boundary_v0_proto` stamped in
  every draft, until the agent-contract constants are armed (then `agent:boundary`).

## Session modes

**Mode S — seeding (bootstrap, runs first).** The registry is empty or partially seeded; the
cascade cannot loop yet. Read the ratified docs set (FEATURES, SEED_PACK, PLAN, PLACEBO_RECIPE,
constants seeds) and prepare the missing seed drafts as inbox files. Rules of Mode S:
- TRANSCRIPTION ONLY for decided things: every entry cites the source document sha256 and
  section; invent nothing; where the doc says [UNKNOWN], the draft says [UNKNOWN].
- APPARATUS SPLIT: constants, windowsets, look budgets, and conditional arming are human-only —
  prepare those drafts but mark them `REQUIRES_HUMAN_APPEND` and do not submit them under any
  agent actor; the human appends them under their own actor string.
- Non-apparatus registrations (feature families, population programs, geometry family entries,
  null-scheme references) submit normally as PROPOSED for ratification.
- Seed checklist: NS2 catalog (13 families, d_max, dv_envelope, tournament order) · NS3
  population programs · windowset W1–W4 + embargo · three armed conditionals · NS4 geometry
  families (incl. mixture_t dormant) · nulls/CRN scheme refs. Order: catalog + windowset
  context first, then populations, then the rest; end when the checklist is green or
  blocked-with-reasons.

**Mode R — research (steady state, the loop below).** Runs only after Mode S has the catalog
and windowset in state; this is the normal boundary session.

## The session loop (Mode R — one pass, then stop)

1. **Orient.** `reg verify` (chain intact), then state, cards, budget for the active lineage,
   and the evaluated-map query. If a cascade cycle is OPEN: observe, write nothing
   discretionary, end the session (CYCLE_OPEN_DISCRETIONARY is a barrier law, not a
   suggestion). Note `diagnostic_mode` — if true, propose only IS-only / placebo / rehearsal
   work this session.
2. **Ensure sensory input.** If no descriptor cards exist for the current epoch, run the
   descriptor emitter over the incumbent partition
   (`reg descriptor-emit --population pop::anotherstrategy --partition incumbent_cluster_id`)
   and re-read cards. If the emitter is not yet implemented, say so and continue on novelty
   cards + state only — do not fabricate descriptor content.
3. **Research.** Web-search candidate features for the CURRENT tournament family only
   (registered order: fam_liquidity → fam_vol_structure → fam_location). Screen every
   candidate against the NS2 laws before drafting:
   - scale-free definition (ratio / return / vol-normalized distance — never a level);
   - market-state-only: a function of (snapshot, entry_ts), never of trade/position/strategy;
   - effective memory ≤ the dv_envelope (currently 45 calendar days; longer-memory ideas are
     parked dormant behind the embargo-reopen decision — record them as dormant proposals,
     never as active ones);
   - fam_liquidity specifics: TICKVOL (trade count) is the registered Amihud denominator;
     stale-bar detection on the zerovol snapshot uses unchanged-OHLC, never zero volume;
   - any time-touching feature uses the PINNED clock (server GMT+2 with US-DST, derived from
     the UTC snapshot) — never naive UTC hours or mixed-clock day features;
   - within-family redundancy: mark near-duplicates `correlate_of` the seat candidate rather
     than proposing parallel seats (seats are scarce: d_max = 12/side, incumbent holds 6).
4. **Draft.** One event draft per surviving candidate, EventDraft schema, to
   `inbox/staging/<event_id>.json` then rename into `inbox/pending/`:
   - `type`: the NS2 registration event; `provenance.mode: discretionary`;
   - `hypothesis` / `reasoning` / `expected_outcome`: all three filled, specific, falsifiable
     (state the expected structural signature and what result would kill the idea);
   - `cites`: the exact card ids and evaluated-map query you consulted — never re-propose a
     computed key (cite the kill-check for anything previously killed);
   - status is PROPOSED by construction; nothing you write is decided.
5. **Repair and report.** Poll `inbox/rejected/` for `<name>.reason.json`; fix schema/barrier
   rejects and resubmit once. End with a short session note: what was proposed, what was
   consciously NOT proposed and why, and the two or three best next questions for the human.

## Hard prohibitions (from the operating contract)

- No readout firing, no handoff arming, no `constants.*`, no windowset, no cert/void events —
  apparatus and kill-class actions are human-only and the barrier will reject them anyway.
- No engine execution (vectorbt/MATLAB/Nautilus) and no raw trade-row reads — cards and
  ledger queries are the entire diet.
- No label-touching rule proposals; `rules.propose` is legal only for the target-blind kinds
  (contract screens, redundancy screens, novelty scoring, dial budgets).
- At 1 remaining look-budget slot: do not prepare a readout-bound batch (soft reserve — the
  contract stops you where the barrier deliberately does not).
- Abbreviations: use only the registry's own (NS2, dv_envelope, etc.); introduce none.

## Draft skeleton

```json
{
  "event_id": "evt_<ulid>",
  "type": "feature.register",
  "actor": "human:alexander",
  "provenance": {"mode": "discretionary"},
  "hypothesis": "Amihud-style illiquidity (|r|/TICKVOL, 288-bar) separates the W2/W3
                 liquidity-crisis archetypes the current coordinates cannot see.",
  "reasoning": "<mechanism + literature anchor + why this family/seat now>",
  "expected_outcome": "<structural signature on target-blind screens; the falsifier>",
  "cites": ["card::descriptor::<id>", "card::novelty::<id>", "evalmap::<query-id>"],
  "payload": {"...": "NS2 feature definition per registry/schemas/features.py"},
  "agent_prompt_version": "boundary_v0_proto",
  "schema_version": 1
}
```
