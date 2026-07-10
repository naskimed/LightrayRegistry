# FEATURES.md — the NS2 catalog & doctrine (feature space of record)

**Version:** FS-1.3 (implements the head `PLAN.md` — v10.3 — + TECH_SPEC §NS2; content chassis-neutral; feature-space research promoted 2026-07-07)
**FS-1.3 changelog (alignment addendum, 2026-07-07):** the `hour` feature's CLOCK is now PINNED — `hour = server-clock hour (GMT+2, US-DST) derived deterministically from the UTC M5 snapshot` (the pair addendum proved txt hour = csv-UTC hour +2 winter/+3 US-DST summer on all 2,519 rows). **G2's five-feature parity depends on this pin** — naive UTC hour fails every row by construction. The same clock mapping already exists, validated, in the vbt engine.
**FS-1.2 changelog:** re-pinned to the head plan; three stragglers of the retired 30d constant fixed (fam_break/fam_transform now cite the 45d dv-envelope; the volume-z at-the-cap flag DISSOLVED — 30d sits comfortably inside 45d, the accidental-amendment concern has no referent).
**Provenance:** two corpus searches (belka6 definitions, bake rule, embargo arithmetic) + three literature searches (AFML Part 4; the empirical bars-only battery; crypto predictor sets). Reviewed and confirmed with three flags applied (d_max made explicit; fam_liquidity data dependency pinned; per-side n corrected).
**Decisions registered (user, 2026-07-07):** fam_exogenous registered as `pending` (arrival = schema no-op) · tournament order = **liquidity → vol_structure → location** · **`d_max = 12` per side**.
**FS-1.1 changelog (conscious supersessions from SEED_PACK SP-1.1):**
- **`max_effective_lookback`: 30d (chosen, FS-1.0) → the DERIVED `dv_envelope` — currently 45 calendar days** (SMA(30) weekday-D1 worst case 41d + shift gap 3d + TR seed 1d), registered as a **formula** (`formula_ref: dv_envelope`), **conditional on G2** (elementwise dv parity proves the EA's ATR is SMA; if G2 red, the derivation doesn't apply and the cap question reopens). Rationale for superseding a registered user decision: ≤-envelope is a *theorem* ("cannot move the embargo"), 30d was a margin — and the user confirmed the reversal explicitly.
- **The featureset FORKS:** `fs_belka6_ea` (legacy_attested; frozen pair only; EA-hurst unrecoverable) vs **`fs_belka6_py_v1`** (audited pending G2; `hurst_rs`; ema raw for parity semantics). All 2,519 legacy entries re-materialized under the Python set (G3) — one audited coordinate system across every population; EA columns kept as provenance.
- **`ema_atr`** confirmed in the extended pool as the seat-tournament replacement candidate for raw ema (scale-free violation; legacy stands on its certified OOS record, not on an invariance argument).
**Changelog rule (inherited):** every change lands as *applied* or *consciously declined*, never silently dropped.

---

## 1. Doctrine

### 1.1 The industry standard is a taxonomy of families, not a list of indicators

Both canons agree. The academic canon (López de Prado, *Advances in Financial ML*, Part 4 "Useful Financial Features") covers exactly: **structural breaks, entropy features, microstructural features**, plus **fractional differentiation** as the stationarity-preserving transform layer. The empirical-finance canon is the standard bars-only battery computed on every serious OHLCV dataset: realized variance at multiple frequencies, bipower variation, Parkinson/Yang-Zhang range volatility, Roll and Corwin-Schultz implied spreads, AC(1) and variance ratios, jump statistics, Amihud illiquidity, dollar volume, staleness/gap metrics. Crypto-specific literature adds nothing structurally new at the bars-only level — its additions (sentiment, macro, on-chain, funding/OI) are **exogenous series**, deferred by OPEN-2.

The registry consumes the standard exactly as NS2 was built to: **one seat per family in core; alternates recorded as `correlate_of`** (an evicted representative's alternate can take the seat without re-derivation). Within-family correlation is enormous — RSI, ROC, and Momentum are nearly one axis — so **the seat tournament must be run family-diverse, or twelve seats buy four families**.

### 1.2 Hygiene laws (encoded in the NS2 schema, not left to discipline)

1. **Scale-free definitions only.** Every feature is a ratio of horizons, a return, or a vol-normalized distance — never a level. This keeps the train-only winsorize → robust-scale → signed-log pipeline stable across regimes (the §7.10 lesson generalized: rolling-relative definitions are coverage-stable where absolute ones aren't).
2. **Market-state-only.** Every feature is a function of `(snapshot, entry_ts)` — never of the trade, the position, or the strategy. This is what lets **one materializer serve both the EA population and vbt populations**, and it makes target-blindness (SPEC-Inv 17) true *by construction* rather than by audit.
3. **Causality classes carry over from NS2:** all catalog families below are computable inside `materialize()` from the M5 snapshot ⇒ class **`audited`** (mutation audit + positive control) — an upgrade over belka6's `legacy_attested`. `fam_exogenous` features are class `pending` until data exists.
4. **Arithmetic base:** M5 snapshot, 288 bars/day. Per-side population sizes are ~1,146 BUY / ~1,373 SELL (not the ~2,500 total-row figure — the seat cap is sized against the per-side numbers).

### 1.3 The lookback↔embargo coupling (the constraint no literature will state)

The windowset's 55d right-embargo edge **derives from the binding feature's memory** — the Wilder slow leg's plateau is ≈52.4d. A long-memory feature is therefore not just a column: it forces embargo re-derivation ⇒ **windowset supersession with spend carryover** — machinery that exists, but as a *registered cost*, never a silent side effect.

**Registered NS2 constant (FS-1.1, user-confirmed supersession):** `max_effective_lookback = dv_envelope` — the DERIVED binding-memory bound, currently **45 calendar days** (see SEED_PACK §2; conditional on G2). Every candidate in §2 respects it by design. Longer-memory candidates (SADF, long-window Hurst, 90d+ ranges, deep frac-diff tails) are parked **dormant behind an explicit "worth re-opening the embargo?" decision** — the conflict surfaces at feature-registration time, not at readout time.

### 1.4 Seat economics (user decision: `d_max = 12` per side)

`d_max = 12` ≈ n/100 per side — conservative for distance-based geometry at this trade count (dimension dilution bites early; the geometry has no built-in shrinkage, unlike L1 heads or LASSO layers, so the cap sits on the one component that can't defend itself). belka6 occupies 6 seats ⇒ **exactly three family tournaments fit before the cap binds** (≈2 survivor seats each). Raising d_max later = one `constants.amend`, consciously.

---

## 2. The family catalog (registered at M3 alongside the belka6 import)

All lookbacks in bars unless noted; 288 = 1 day. Status at seed: `core` (in every run) / `extended` (available to registered searches) / `dormant` (registered, hashed, never computed until promoted) / `pending` (blocked on data).

| Family | Representative features (lookback) | Seed status | Notes |
|---|---|---|---|
| **fam_time** *(occupied)* | `hour` (belka6 — **clock PINNED: server GMT+2 US-DST from UTC snapshot, FS-1.3**); day-of-week; weekend flag | core + 2 ext | 24/7 market; weekend = distinct liquidity regime; day-features share the pinned clock (the incumbent mask is Saturday-only in it) |
| **fam_trend** *(occupied)* | `EMA(6)` daily (belka6); close/SMA ratio 1d vs 7d | core + 1 ext | the ratio pair is the scale-free form |
| **fam_momentum** *(occupied)* | `Momentum(1)` (belka6); ROC(12)/ROC(288) ratio; RSI(48) | core + 2 ext | RSI/ROC/Momentum ≈ one axis — alternates, `correlate_of` |
| **fam_vol_level** *(occupied)* | `dv`, `iv` (belka6); fast/slow RV ratio (48/2016); Parkinson or Yang-Zhang (288) | core + 2 ext | range estimators exploit intra-period H/L — more efficient than close-to-close |
| **fam_vol_structure** *(NEW — tournament slot 2)* | jump ratio RV/BV (288); up/down semivariance ratio (288); realized skew (864) | 3 ext | structure ≠ level: jumps/asymmetry are what distinguish COVID-shape from FTX-shape at fixed vol |
| **fam_liquidity** *(NEW — tournament slot 1)* | Amihud \|r\|/dollar-volume (288); Corwin-Schultz spread; volume z-score vs 30d same-hour profile; stale-bar fraction | 4 ext | **the OOS archetypes (W2/W3) are liquidity-crisis events and the current coordinate system cannot see liquidity.** Data dependency: §5 |
| **fam_flow** *(NEW)* | signed-volume imbalance, candle-direction tick rule (48); close-location-value mean (48) | 2 ext | the standard bars-only order-flow proxies |
| **fam_location** *(NEW — tournament slot 3)* | position in 7d range (Donchian %); drawdown from 30d high, vol units | 2 ext | cheap, interpretable; the census showed session-and-range-shaped geometry |
| **fam_memory** *(occupied)* | `Hurst(50)` (belka6); VR(12); rolling AC(1) (288) | core + 2 ext | |
| **fam_break** | CUSUM stat; SADF explosiveness | **dormant** | AFML: breaks offer the best risk/reward (others unprepared) — but SADF's lookback exceeds the 45d dv-envelope cap ⇒ behind the embargo-reopen gate |
| **fam_entropy** | permutation / LZ entropy of return signs (288) | **dormant** | AFML chapter 2 of 3 |
| **fam_transform** | frac-diff close (FFD, d≈0.4) | **dormant** | one-seat candidate; FFD weight tails can exceed the 45d envelope ⇒ cap check at activation |
| **fam_exogenous** | funding, basis, OI, taker imbalance | **pending** | registered NOW per user decision — OPEN-2 closing = activation event, schema no-op |

Seed breadth: **~20 extended features** across the table — wide enough for the screens to have material, narrow enough that free-layer characterization stays cheap.

---

## 3. The three tournaments (order = user decision)

Each tournament is the existing registered mechanic — nothing new is invented:

1. **Activate** the family (registered event, hypothesis attached).
2. **Contract screen** (warm-up feasibility, NaN coverage, cap compliance) → **redundancy screen** (deterministic family ordering for tie-breaks; survivors seated, losers `screened_out, correlate_of=X`) → **structure contribution** (target-blind: bootstrap ARI shift, eigengap, blob/dust ratio) → **ablation**.
3. **Equal-dimension seat tournament at fixed d** — swap the family's survivors in against belka6's weakest columns at the SAME d=12 (never "does adding help" — gross-of-dimension ablation is the add-only bias in metric form).
4. Surface cards → **bake rule** (monotone + plateau + time-stable ⇒ promotion candidate); cliff/asset-dependence ⇒ demotion evidence.

**Order (registered):** ① `fam_liquidity` — archetype-driven (W2/W3 are liquidity events) and the data already exists; ② `fam_vol_structure` — separates crisis shapes at fixed vol level; ③ `fam_location` — cheap, interpretable, matches the census geometry. Reorder later only by conscious supersession (the OPEN-9 EA-source read is the one anticipated cause).

---

## 4. NS2 constants to register at M3 (single source: the registered constants doc, not this file)

| Constant | Value | Rationale |
|---|---|---|
| `d_max` (per side) | **12** | §1.4; ≈n/100/side; three-tournament arithmetic exact |
| `max_effective_lookback` | **`dv_envelope` (currently 45d, derived; conditional-on-G2)** | §1.3 + FS-1.1; embargo coupling made law as a THEOREM, not a margin |
| `tournament_order` | liquidity, vol_structure, location | §3 |
| `family_screen_order` | registration order, ties → cheaper warm-up | deterministic redundancy-screen survivor (hash-stable working set) |
| `seat_tiebreak` | evict | eviction is cheap + reversible; retention of a dead column costs geometry forever |

---

## 5. Data dependencies & precision notes (pinned per review)

- **fam_liquidity requires the VOLUME-BEARING snapshot**, not the zerovol variant (whose volume columns were deliberately destroyed). In the volume-bearing Binance snapshots, `VOL` is integer-rounded — rounded-to-zero small bars can inflate Amihud, so **`TICKVOL` (trade count) is the registered alternative denominator**; the choice is recorded in the feature definition, not left to the implementer.
- **Stale-bar fraction on the zerovol snapshot must use unchanged-OHLC detection**, never zero-volume detection.
- Per-side n (~1,146 / ~1,373) is the sizing basis for everything in §1.4 — not total rows.
- **The `hour` clock pin (FS-1.3):** the EA computed `hour` in the MT5 server clock (GMT+2 with US-DST) while the snapshot timestamps are UTC — the materializer must apply the registered clock mapping (already implemented + validated in the vbt engine) before emitting `f_hour`. Any feature referencing day boundaries (day-of-week, weekend flag, same-hour volume profiles) uses the SAME registered clock, consciously — mixed-clock day features would be silent nonsense.

---

## 6. Open items

- **fam_break / fam_entropy / fam_transform activation** — each is a dormant registered family; break-family activation additionally requires the **embargo-reopen decision** (windowset supersession + spend carryover priced in).
- **fam_exogenous** — waits on OPEN-2; activation is an event, not a schema change.
- **frac-diff one-seat candidacy** — if activated, FFD threshold must be chosen so effective memory ≤ cap, or it joins the embargo-gated set.
- Feature-set hash churn discipline (from the registered design): core-set changes batch into scheduled registry versions; exploratory feature-set versions mint freely per hypothesis.
