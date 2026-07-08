# CODE_REVIEW.md — first adversarial pass over the LightrayRegistry code (RV-C1)

**Date:** 2026-07-08 · **Method:** 6 code lenses + a LightMinerPy explorer + 10 seeded candidates → 44 findings → 3-refuter verification (partial: hit a model limit mid-verify; **73 upheld / 6 refuted** across completed refuters; the two hardest blockers got a full 3/3). The code had never been run, so every fix below is a pure gain.

**Status key:** ✅ FIXED this pass · ◻️ TRACKED (fix scheduled, noted inline).

## Blockers (all confirmed)

1. ✅ **Writer-thread deadlock on first conditional fire.** `_on_event` ran *inside* the writer thread and called `writer.submit(...).result()` — the queue's only drainer blocked on its own future. Fix: `_on_event` sets a dirty flag; the **scheduler thread** evaluates conditionals in `_tick` (it may safely block on the writer). 4 lenses + seed, 3/3 verified.
2. ✅ **Live-vs-replay divergence: `cond['status']='fired'` mutated outside `fold()`.** Cold replay left it `armed` → `state_hash` mismatch → nightly `replay.verified` red forever. Fix: the **reducer** marks a conditional fired when it folds the fired event (matched by `cites` + body type); the scheduler no longer touches state.
3. ✅ **Ledger construction destructively rewrote the live log.** `_scan_tail`→`_quarantine_tail` truncated at the *first* bad line anywhere, in-place (`wb`), and ran **unlocked** from `reg state`/nightly against a live writer. Fix: `Ledger(writable=False)` for all readers — read-only never rewrites; quarantine happens only in the write-authorized path, only for a torn **final** line, via tmp+rename of the clean prefix. `verify()` now reports a torn tail as recoverable rather than refusing boot.
4. ✅ **The brake channel could never fire: conditional body-hash mismatch.** `_match_fired_conditional` hashed the *raw* armed payload against the *normalized* emitted payload → every legitimate fire (incl. the seeded extended-SUSPEND alarm) rejected as `ORDER_VIOLATION`. Fix: normalize both sides through `validate_payload` before hashing.
5. ✅ **Placebo fails open.** `readout.record` fold trusted a payload-supplied `classification`, so an engine could label an L2 leak as `none` and suppress the SUSPEND alarm. Fix: the reducer **always** derives the class from the raw numbers via `classify_placebo`; payload classification is ignored.
6. ✅ **PC-echo compared incompatible shapes** (`sha256_canon(dict)` vs a hash over a `list`) → always unequal → either always-reject or dead. Fix: compare against an explicit `pc_echo_hash` registered on the pc doc (computed over the same canonical PC dict the engine echoes); absent that field the check is skipped, not falsely failing — the real shape is wired at M5 with the generated `precommit`.
7. ✅ **Emission-cap / rate layer was dead code.** `can_spend` read `payload['month_hint']`, which `ReadoutRequest` (`extra='forbid'`) rejects. Fix: the barrier derives the month from `draft.ts` (ingest stamps it) and passes it to `can_spend`; the schema stays clean.
8. ✅ **`convert_legacy_pair` positional FIFO pairing + unguarded `StopIteration`.** Paired i-th in ↔ i-th inverted-side out by order, contradicting its own deal-id contract, and `next(outs_iter)` could crash. Fix: pair by **deal id** (each in → the next out of the inverted side with a strictly greater deal id), assert per-side counts and `out_deal > in_deal`, raise (not assert) on violation.
9. ✅ **MATLAB MCP `run_named_function` was injectable** via `args_literal` string interpolation — the "registered functions only, never arbitrary code" lock (AC-1.0 §6) was decorative. Fix: `args_literal` is gone; args are passed as a typed JSON list the server renders into MATLAB literals (numbers/quoted-strings only, no expressions). Plus: refuse to start if `BELKASGL_TREE` is unset; tree-escape check uses resolved `is_relative_to`, not `startswith`.
10. ◻️ **Writer append→fold→reply non-atomicity.** An exception after the fsync'd append reports rejection for a *persisted* event. TRACKED: split the writer so a post-append fold error is logged/alarmed, never reported as a rejection (the event is on disk and will fold on replay).

## Majors fixed this pass
- ✅ **Novelty quota permanently zero:** `_live_budget_rule` read `'body'`, `rules.adopt` wrote `'body_ref'`. Now the reducer stores the resolved rule body under `live['body']`.
- ✅ **Look-budget generation bump never reset `consumed`** → refill impossible at exhaustion (REG-INV-24). `_index_look_budget` now resets `consumed_this_generation` when the generation increments.
- ✅ **Duplicate `readout.void` inflated the budget.** Barrier now rejects a void of an already-voided readout.
- ✅ **`promote()` used the live dial rule, not the cycle-pinned one; `KeyError` on unknown `score_fn_version`.** Now reads the cycle's pinned versions and guards the score-fn lookup.
- ✅ **Cross-thread torn reads** (API `/state`, `export_all` iterate writer-mutated dicts). Added an `RLock` in the writer; reads take a locked deep-snapshot.
- ✅ **Agent session hang** — unbounded stdout read + timeout only after EOF + lock held forever. Now uses a bounded reader thread with a hard kill on timeout and guaranteed lock release.
- ✅ **`register_seed` minted name-based `wiv_w1` ids** instead of `wiv_<hash8(data_contract,start,end)>` (the resurrect-spent-windows bug the spec calls out). Fixed to the identity law.
- ✅ **HUMAN_FORBIDDEN arithmetic legalized live human `cert.certify/displace`** (scheduled-only). Fixed so only `imported:true` historical certs pass.

## Majors tracked (fix scheduled, non-blocking for M0–M2)
- ◻️ **`shadow_qualification` reads `rules['shadow_skill']['epochs']` nothing writes** → shadow re-entry channel dead until the scheduler's skill-telemetry updater exists (M10S). Noted; the predicate is correct, its input feed is a later milestone.
- ◻️ **REG-INV-11 dust + REG-INV-21 postmortem-identity checks are partially inert** (`_candidate_is_dust` / byte-identity read fields no reducer populates yet). They wire up when the geometry result carries dust provenance and the postmortem carries its input digests (M5/M7). Tracked so they aren't mistaken for live.
- ◻️ **Nightly cold-replay races the writer.** The replay should run against a locked snapshot, not a concurrent `Ledger()` read. Folds into the RLock snapshot fix; the nightly will snapshot-then-replay.
- ◻️ **Bare `assert` in seed/converter tools** disables under `python -O`. Convert the frozen-pair hash / clock-law / fingerprint gates to explicit `raise`.

## Refuted (6) — not changed
Minor/benign items the refuters knocked down (e.g. the `state_hash` set-ordering concern — already handled by sorting `dedup`; a couple of "crash" claims that were unreachable given other guards). Recorded so they aren't re-raised.
