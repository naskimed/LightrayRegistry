# SEED_PACK.md — NS2/NS3 seed pack + session decisions (registrable form)

**Version:** SP-1.4 (SP-1.0 = research-session handoff 2026-07-07; SP-1.1 = review applied; SP-1.2 = v10 rescope; SP-1.3 = versioning repair same day; **SP-1.4 = alignment-addendum consequences, 2026-07-07**: mask clock corrected — the incumbent mask is `server_saturday_only` in GMT+2 US-DST, the csv datetimes are UTC; alignment-diff condition precedent MEASURED green; legacy windowset clock label corrected to the pair-CSV clock = UTC; Friday-lead-in open item dissolved)
**SP-1.3 changelog:** the v10.2 round changed SP-1.2's bytes without a version bump (§7's armed-list line fixed to the PLAN v10 §2b list; precedence re-pinned to the head PLAN.md) — same-name-different-content is REG-INV-14's pattern applied to documents; this line repairs it.
**SP-1.2 changelog (PLAN v10 adoption — chassis-neutral content unchanged):** D3 rescoped — scout graduation proposals are **boundary-session** discretionary events (the in-loop proposer retired with v9 decisions 3/5/6 per the SIGNED v10 §2 supersession; same machinery, same schema, different station). §7's sequence is **hosted as M9S campaign one** (gates + supersession + scouting wave + P1–P3 + tournament 1 run as cascade stages); the novelty card becomes the Stage 0→1 scoring instrument.
**Precedence:** the head `PLAN.md` (v10) + TECH_SPEC govern mechanics (content below is chassis-neutral; SP-1.2 changelog carries the v10 rescope); this pack supplies domain content. Verification anchors (hashes, fingerprints, reconstructed mask, converter assertions) live in `ANOTHERSTRATEGY_pair_verification.md` (**FILED in this folder, with the 2026-07-07 addendum** — byte-equality discharged; alignment diff green under the clock law) and are referenced, not restated.
**SP-1.1 review deltas (applied, per the apply-or-decline rule):**
- **D1 (user decision):** lookback cap = the **derived 45d dv-envelope**, registered as a FORMULA (`max_effective_lookback = dv_envelope`, conditional-on-G2), consciously superseding the registered 30d choice → FEATURES.md amended to FS-1.1.
- **D2 (user decision):** novelty card computes through the **full 6-feature certified geometry** with `hurst_rs` standing in for EA-hurst, carrying a registered **`coordinate_class_mismatch: hurst`** flag on every card (free-layer ranking tolerates the bias; the flag prevents silent forgetting).
- **D3 (user decision):** scout graduation = **standard proposer discretionary machinery** (family.activate / block.register with hypothesis + cites; coverage-diversity evidence required by the agent contract). The pack's "human call" phrasing is retired — zero-click epoch stands; no carve-out.
- **D4 (rationale fix):** decision 10's "legacy safe via affine-invariance" was the wrong justification (train-only global scaling does not fix within-sample era drift — the raw-ema axis partially encodes price epoch). Legacy is safe because it is **certified on its OOS record**, and any definitional change is a new version regardless.
- **Verified in review:** §2 embargo arithmetic (41+3+1=45, +1 buffer); G1 fingerprints sum to 1,146/1,373 with K=6; the condition-precedent structure (G2-green empirically proves EA=SMA before the 46d fires — safe failure mode if red); the supersession exercises the `wiv_` interval-identity fix exactly as designed (mask semantics change, interval ids don't, spends + k carry); P6 scales are symmetric (ratio stays 1:1 — consistent with the exit-family law).

---

## §1 — Decisions registered this session (attribute: user unless noted)

1. **P0 frozen, never regenerated.** The legacy pair (hashes in the verification note) is the first reference; anchor constants derive from its bytes or register `attested_unknown`. `generating_config: attested_unknown` (three independent falsifications of both candidate .sets).
2. **Exit-family law.** v1 exits symmetric and frozen per population family; asymmetry only via registered exit-family decision within `barrier_ratio ∈ [1/2, 2]` (**r_max = 2**); blob floors scale with the ratio if ever opened; **win rate is never a gate quantity** (metrics dictionary); trailing stops and bar-count time-stops excluded from v1 grammar with rationale (path-dependent labels break triple-barrier comparability).
3. **Fixed-R sizing for all generated arms**; legacy compounding sizing preserved on P0 only (volume column stored for R-normalization).
4. **Fork-and-unify (featuresets).** `fs_belka6_ea` (legacy_attested; exists only on the frozen pair; EA-hurst unrecoverable per LightMinerPy `docs/HURST.md`) vs **`fs_belka6_py_v1`** (audited pending G2; hurst_rs; ema raw to preserve parity semantics) as distinct hashed sets. **All 2,519 legacy entries re-materialized under the Python set** so every population — legacy and future — shares ONE audited coordinate system; EA columns retained as provenance.
5. **Scouting doctrine.** Mechanism exploration runs label-masked (feature-only parquet; payoff column withheld until family registration); the **novelty card** — frozen_knn abstain fraction through the certified geometry (all 6 features, `coordinate_class_mismatch: hurst` flag per D2) + affinity/vote histogram + pairwise energy distance in the frozen feature space — is the registered free-layer instrument ranking scouts (target-blind). **Graduation to priced blocks via the proposer's standard discretionary machinery** with coverage-diversity evidence (D3).
6. **Renderer requirement (into the TS).** NS3 renders one registered config → two deterministic outputs: vbt spec (Tier-1) and MT5 .set (Level-2). Rendered .sets hard-pin the Clustering_Trading_Setup block to optimize=N (the `||Y` flags observed in both real .sets are a standing out-of-band selection channel; closed structurally).
7. **Grid-anchor rule (S-class).** Every registered grid must contain the incumbent/production value as an anchor config (observed violations: _StopLoss 0.08 ∉ [0.01,0.07]; PCh_Period 36 ∉ [100,300] — surfaces that can't see production are surfaces you can't read).
8. **Mask grammar (SP-1.4-corrected).** Population-shaping masks are **(day,hour)→(day,hour) windows WITH A REGISTERED CLOCK** — the incumbent population's own mask is **`server_saturday_only`** (whole-day Saturday, 2,519/2,519 entries) in `clock: gmt+2_us_dst`; its UTC image is `Fri 21:00 → Sat ~22:00` (DERIVED, season-ragged — the previously-registered "server Fri 21:00→Sat ~22:00" mislabeled the clock: the csv datetimes are UTC). The .set day encodings still match nothing; empirical mask stays authoritative.
9. **Per-file encoding detection** in the converter (pair is txt UTF-16-BOM / csv plain ASCII).
10. **ema v2 candidate.** The raw price-difference ema violates the scale-free rule (σ≈2155 across a 7k→100k asset); legacy stands on its certified OOS record (D4); `ema_atr` (vendor-normalized) enters the extended pool as a seat-tournament replacement candidate — a registered definitional version, never an edit.

## §2 — DRAFT: windowset supersession `ws_sgl_w1w4_v2` (ARM at M3; fires on stamps)

**One supersession, two OPENs:** re-anchors masks on **entry times, UTC** (closes OPEN-16) and replaces the provisional right embargo **55d → 46d final** (closes OPEN-9's embargo half *from code, conditional on G2*). Bundling exercises spend-carryover once.

**Derivation (LightMinerPy `indicators/engine.py` — the binding memory inventory):** `dv = ATR_slow/ATR_fast`; ATR = **SMA of True Range (not Wilder)**, slow=30, fast=7, on weekday-only D1; features read the previous completed weekday D1 (shift=1) by UTC date; TR seeds from the prior calendar-day close. SMA(30) memory is finite and exact: 29 weekday steps ≈ **41 calendar days** worst case + **3d** worst shift gap (Mon→Fri) + **1d** TR seed ⇒ **oldest information = entry − 45d, hard cutoff, no ε**. `ema(6)` (`ewm_from_zero`, α=2/7): 5%-tail ≈ 13 calendar days, 0.1%-tail ≈ 29d — dominated. `mom`/`iv` ≤ ~13d; `hurst_rs` ≈ 4h; `hour` = 0. **Right embargo = 46d** (45 + 1 registered buffer). Left 2d unchanged (max holding 29.8h); entry-anchoring makes the left purge exact. Recovered: 3 interior right edges × 9d = **27 interior days returned to training**.

**Condition precedents (the arming predicate):** (a) **G2 five-feature parity stamped green** — this is what makes the SMA derivation apply to the EA-computed P0 (elementwise dv agreement across 2,519 entries rules out Wilder); if G2 red, the conditional never fires and 55d stands — safe failure mode; (b) txt↔csv hour-alignment diff green — **MEASURED GREEN 2026-07-07** (pair-verification addendum A3: positional alignment confirmed 2,519/2,519 under the clock law txt=csv+2/+3 US-DST; the formal stamp imports at M3); (c) spend-carryover asserted from window-interval lineage — **W1–W4 spends AND cumulative k carry to v2** (interval ids unchanged: only mask semantics move, which live at windowset level); the legacy set stays registered exit-anchored on the pair-CSV datetimes — **clock label corrected to UTC** (the csv column is UTC per addendum A3; mask mechanics byte-identical, only the label moves) — so the July shot's masks remain bit-reproducible.

**Mechanics:** `windowset.supersede` is human-only (REG-INV-22); armed as a pre-signed conditional (human-authored body + the stamp predicates), fired by the scheduler under REG-INV-25 class (ii). Amending after arming is post-hoc gate-editing — the arithmetic above is final in this draft, subject only to sign-off before arming.

**Does NOT close:** OPEN-9's lookahead half — the EA binary's own feature computation stays `legacy_attested` until the EA-source read; still required before live.

## §3 — Verification gates

- **G1 — incumbent Artifact round-trip** (seam gate; an afternoon): build `Artifact(classifier_kind="centroid")` from the txt's mean/std + centroids; classify the txt's own 2,519 raw rows; **accept iff the cluster column reproduces exactly** — BUY fingerprint {323,216,322,235,1,49}, SELL {357,174,56,160,363,263} (sums verified 1,146/1,373; K=6). By-products: the registered incumbent Artifact for M3; frozen_knn variant check at incumbent defaults (k=11, τ=0.6).
- **G2 — feature parity** (materializer gate): recompute `fs_belka6_py_v1` from the M5 snapshot at the CSV entry timestamps; compare elementwise to txt columns 3–7 per feature. **Expected: hour/ema/mom/dv/iv green; hurst red BY DESIGN** (the fork rationale). Green-on-five ⇒ audited class for all future populations ⇒ §2 precedent (a).
- **G3 — legacy re-materialization:** emit the P0 parquet with `fs_belka6_py_v1` columns alongside the frozen EA columns; five-feature parity is its acceptance. The unification move made concrete.
- **Alignment diff** (test_alignment dry-run): txt col-2 hours vs CSV entry hours, positional per side — §2 precedent (b).

## §4 — NS2 seed

- **Core (parity set):** `fs_belka6_py_v1` = hour, ema (raw — parity semantics), mom, dv, iv, hurst_rs. Hashed; audited pending G2. Fork sibling `fs_belka6_ea` = legacy_attested, frozen pair only.
- **Extended pool (~20; all `materialize()`-computable):** fam_liquidity {Amihud, Corwin-Schultz, volume-z vs 30d same-hour, stale-bar fraction} · fam_vol_structure {RV/BV jump ratio, semivariance ratio, realized skew} · fam_location {7d Donchian %, drawdown-from-30d-high in vol units} · fam_flow {signed-volume imbalance, CLV mean} · fam_memory +{VR(12), AC(1)} · fam_time +{day-of-week, weekend flag} · fam_trend +{SMA-ratio 1d/7d} · fam_momentum +{ROC ratio, RSI(48)} · fam_vol_level +{fast/slow RV ratio, Parkinson(288)} · **ema_atr** (decision 10). Dormant: CUSUM/SADF, entropy, frac-diff. Pending: fam_exogenous (OPEN-2).
- **Lookback cap (D1, supersedes FS-1.0's 30d):** `max_effective_lookback = dv_envelope` (**currently 45 calendar days**, derived not chosen, conditional-on-G2) — any feature at or below the binding envelope can never move the embargo; anything longer registers dormant behind an explicit embargo-reopen decision.
- **Seat economics unchanged:** d_max = 12/side; belka6 holds 6; tournaments = liquidity → vol_structure → location.

## §5 — NS3 seed

- **Mechanism families:** fam_reversal_band (slot 1 — engine-validated, parity-anchored) · fam_session_time · fam_breakout_channel (= PCh; donchian.py + verify harness exist) · fam_tsmom (momentum.py + verify harness exist) · fam_level_touch · fam_vwap_reversion · fam_vol_event · fam_carry_funding (pending, OPEN-2). **Composition rule:** one mechanism per config + at most one (day,hour)-window modifier; depth 1; no free indicator mining.
- **Constraint classes:** pinned execution (fill model, fees) · population-shaping (windows, spread/news filters; target-blind; per-mask counts stamps — never pooled across masks) · label-geometry (exit set — frozen per family, decision 2) · entry-mechanism (coarse grids 3–5/axis; declared units in σ/bars/%; declared expected monotonicity for the bake rule) · deployment artifact (cluster memberships — Artifact-written only).
- **Population floor:** `min_population_per_config` ≈ 1,000/side over the IS freeze (target-blind auto-kill; exact number = open item 8.3). Entry filters minimal by doctrine — conditionality belongs to the geometry layer.

## §6 — Population program

| Arm | Axis varied (all else pinned to anchor) | Purpose |
|---|---|---|
| P0 | — frozen legacy pair (+G3 audited columns) | reference; incumbent lives here |
| P1 | mechanism → fam_reversal_band, anchor window | first generated arm; zero new validation surface |
| P2 | window → Sat 22:00 → Sun 24:00 | weekend-liquidity replication arm |
| P3 | window → same 25h shape, midweek | **falsification arm** — ranked above P2 in epistemic value |
| P4 | window → full week | density ceiling; candidate pre-built: `BTCUSD_featuresD.txt` (25,098 rows) pending verification (8.1) |
| P5 | mechanism → session_time or breakout_channel | cross-mechanism geometry transfer (Decomposition portability) |
| P6 (gated) | exit scale → symmetric {0.5×, 1×, 2×} of the **measured** barrier | first registered exit-family decision; never pooled across scales |

Plus the **scouting wave** (decision 5 as amended by D2/D3): many mechanisms cheap, feature-only, novelty cards; high-novelty targets = expansion/breakout, vol-event/jump states, weekday sessions, level-touch (the incumbent samples weekend stretched-quiet states). **Barrier measurement pass precedes P6**: derive true SL/TP distances from CSV exit bytes vs entry prices (first trade suggests ~0.3% of price — nowhere near the .set's 0.08, whatever its units); exits register from bytes, not config.

## §7 — Sequence

1. Co-locate pair + repos + M5 snapshot (server). 2. **G1**. 3. **G2** → 4. **G3** → 5. supersession fires (§2; armed at M3 alongside the budget-floor + extended-SUSPEND alarms — the PLAN v10 §2b armed list; the R11 conditional is retired). Parallel: barrier-measurement pass; featuresD verification (8.1); label-masked scouting harness in vbt_runner. Then P1–P3 as the first registered family block + window arms; NS2 tournament 1 (liquidity) after the first cards.

## §8 — Open items

1. **featuresD provenance** — which run, which mask; is `BTCUSD_firstTest.txt` its CSV twin? A verified 25k population changes scouting economics.
2. ~~Friday 21:00 lead-in intent~~ — **DISSOLVED (SP-1.4):** in the generating clock the mask is a whole-day Saturday window; the Friday lead-in was a UTC artifact. Nothing to explain, nothing left open.
3. **Population floor number** (default 1,000/side proposed).
4. OrderDayOfWeek encoding semantics — cosmetic; empirical mask is authoritative.
5. Hour-alignment diff execution (blocked only on co-location).
6. OPEN-9 lookahead half — EA-source read before live (unchanged).
7. OQ-7 (card coarseness) — unchanged deadline: before M7.
