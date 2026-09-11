# V3 Program Review — FX Intraday Alpha Discovery (V1 → V2 → V3.1)

**Artifact:** `V3_PROGRAM_REVIEW_V1`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V3` · lineage `FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1`
**Type:** DIAGNOSTIC / META-RESEARCH ONLY
**Starting SHA:** `3107ab899e564f61601df4897a5133d95bdee1db`
**Machine-readable twin:** `results/gate_v3f/v3_program_review.json`

> **Scope and invariants.** This is a post-program review of *why* the research
> program failed to produce a scientific survivor and *which classes of
> hypotheses* remain worth pursuing. It runs **no new candidate search, no
> parameter tuning, no near-miss rescue, no V4 design, and no 2018+ access**.
> The V3.1 result is treated as immutable. Firewall for this session:
> **2018+ provider requests = 0, 2018+ reads = 0** (only committed pre-2018
> artifacts and source were read).

---

## 0. The immutable V3.1 result

| | Universe A (executable) | Universe B (price-alpha-only) |
|---|---|---|
| evaluated | 992 | 52 |
| runtime-valid | 992 | 52 |
| zero-trade | 169 | 0 |
| positive raw (net 1x > 0) | 20 | 0 |
| positive @1.5x | 13 | 0 |
| positive @2.0x | 12 | 0 |
| **scientific survivors** | **0** | **0** |

Statistics: **WRC p = 1.0, Hansen SPA p = 0.730, CSCV PBO = 0.186**;
Romano-Wolf / Holm / BH-FDR / hierarchical **all 0 significant**.

**Verdict:** `V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR`.

---

## 1. Program-level failure taxonomy

Primary cause = the **first** failure in the causal chain
(activity → gross edge → cost → cost-stress → time → instrument → multiplicity).
Secondary causes are listed separately so no candidate is forced into one box.

### 1.1 Primary causes (Universe A, n = 992)

| Code | Cause | Count | % |
|---|---|---|---|
| **A** | NO_SIGNAL — mid-to-mid gross < 0 (no edge before costs) | 476 | 48.0% |
| **B** | COST_DOMINATED — gross > 0 but net 1x < 0 | 272 | 27.4% |
| **D** | LOW_ACTIVITY — zero-trade or below the horizon trade floor | 239 | 24.1% |
| **C** | STRESS_FRAGILE — net 1x > 0 but fails 2.0x cost stress | 5 | 0.5% |

**Reading:** nearly half the program has *no intrinsic edge*; a quarter has a
real gross edge that *costs destroy*; a quarter *never trades enough*; almost
nothing is merely cost-stress-fragile. The binding constraints are **signal
existence** and **turnover/cost**, not fine-tuning.

### 1.2 Secondary causes (how many candidates exhibit each)

`no_adjusted_significance` 992 · `low_sharpe_dsr` 986 · `loo_unstable` 985 ·
`fold_unstable` 983 · `gross_negative` 515 · `cost_destroys_edge` 288 ·
`zero_trade` 169 · `insufficient_trades` 70 · `year_concentrated` 10 ·
`fragile_2_0x` 8 · `fragile_1_5x` 7.

Every candidate fails multiple-testing (by construction, since the program-level
max statistic is null), and ~98% fail Sharpe/DSR, LOO and fold consistency —
the failures are **systemic, not idiosyncratic**.

### 1.3 By horizon

- **H0 micro-intraday:** D 97 · B 169 · A 171 — the micro arena is dominated by
  cost and no-signal; it is the most hostile horizon.
- **H1 session-daily:** A 305 · B 103 · D 142 · C 5 — the only horizon that
  produced *any* cost-stress-fragile (near-miss) candidates.

### 1.4 By domain (primary cause)

| Domain | A | B | C | D | Dominant |
|---|---|---|---|---|---|
| A classical-technical | | | | 91 | LOW_ACTIVITY (zero-trade) |
| B time-series-momentum | 104 | 58 | 4 | | NO_SIGNAL |
| C mean-reversion | 1 | 75 | | 60 | COST_DOMINATED |
| D volatility-range | 49 | 20 | | 6 | NO_SIGNAL |
| E microstructure | 2 | 58 | | | COST_DOMINATED |
| F seasonality | 63 | 12 | | | NO_SIGNAL |
| G cross-pair | | 37 | | | COST_DOMINATED |
| H stat-arb | 112 | | | | NO_SIGNAL |
| I applied-math | 29 | 8 | 1 | 82 | LOW_ACTIVITY + NO_SIGNAL |
| K cost-aware | 56 | 4 | | | NO_SIGNAL |
| L machine-learning | 60 | | | | NO_SIGNAL |

### 1.5 Qualitative (non-metric) categories

- **G NEIGHBORHOOD_INSTABILITY** — the raw-positive points are isolated
  parameter wins whose family neighborhood is negative (single-trade Donchian
  and Kalman wins).
- **I REGIME_SPECIFIC** — 10 net-positive candidates put >70% of gross edge in a
  single calendar year; the 4 USDJPY trend-pullback positives are
  turnover/regime specific.
- **J MODEL_CAPACITY_MISMATCH** — the families are linear/threshold/hand-crafted
  (see §7).
- **K DATA_CAPABILITY_MISMATCH** — `V3_E_TICK_ARRIVAL_INTENSITY` and
  `V3_E_ORDER_BOOK_IMBALANCE` were **rejected pre-outcome** (they need
  tick-arrival / order-book depth the M1 set lacks) → **UNTESTED, not refuted**.
- **L HORIZON_MISMATCH** — H2/H3 are price-alpha-only (overnight financing
  unsupported); H0 is cost-hostile.

---

## 2. Family-level postmortem

`n` candidates · `zt` zero-trade · `raw+` net-1x-positive · `1.5x`/`2x` cost
survivors · `medNet`/`bestNet` (bps) · `bestSharpe` · `foldPass`/`looPass` ·
`fracGrossNeg` = share with negative mid-to-mid gross.

| Family (domain) | n | zt | raw+ | 1.5x | 2x | medNet | bestNet | bestSh | fold | loo | grossNeg | dominant |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_DONCHIAN (A) | 91 | 59 | 7 | 5 | 5 | 0.0 | 26.6 | 0.0 | 0.02 | 0.02 | 0.14 | LOW_ACTIVITY |
| B_TSMOM_VOLSCALED (B) | 75 | 0 | 0 | 0 | 0 | −26917 | −4914 | −1.02 | 0.00 | 0.00 | 0.87 | NO_SIGNAL |
| B_TREND_PULLBACK (B) | 91 | 0 | 4 | 0 | 0 | −4524 | 1356 | 0.37 | 0.01 | 0.00 | 0.43 | COST_DOMINATED |
| C_OU_HALFLIFE (C) | 60 | 60 | 0 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.00 | 0.00 | 0.00 | LOW_ACTIVITY |
| C_ZSCORE_OVERSHOOT (C) | 76 | 0 | 0 | 0 | 0 | −4160 | −202 | −0.14 | 0.01 | 0.00 | 0.01 | COST_DOMINATED |
| D_COMPRESSION_BREAK (D) | 75 | 0 | 0 | 0 | 0 | −1239 | −221 | −2.33 | 0.00 | 0.00 | 0.73 | NO_SIGNAL |
| E_SPREAD_GATED (E) | 60 | 0 | 0 | 0 | 0 | −5357 | −1115 | −0.28 | 0.00 | 0.00 | 0.03 | COST_DOMINATED |
| F_SESSION_MOMENTUM (F) | 75 | 0 | 0 | 0 | 0 | −8875 | −573 | −0.49 | 0.00 | 0.00 | 0.84 | NO_SIGNAL |
| G_XSMOM (G) | 32 | 0 | 0 | 0 | 0 | −7697 | −4.5 | 0.0 | 0.00 | 0.00 | 0.78 | NO_SIGNAL |
| G_USD_FACTOR (G) | 37 | 0 | 0 | 0 | 0 | −202574 | −68665 | −4.31 | 0.00 | 0.00 | 0.00 | COST_DOMINATED |
| H_COINTEGRATION (H) | 20 | 0 | 0 | 0 | 0 | −17509 | −16264 | −1.73 | 0.00 | 0.00 | 1.00 | NO_SIGNAL |
| H_TRIANGULAR (H) | 112 | 0 | 0 | 0 | 0 | −29671 | −5288 | −0.73 | 0.00 | 0.00 | 1.00 | NO_SIGNAL |
| I_CHANGEPOINT (I) | 60 | 50 | 1 | 0 | 0 | 0.0 | 154 | 0.13 | 0.02 | 0.00 | 0.12 | LOW_ACTIVITY |
| I_KALMAN_TREND (I) | 60 | 0 | 8 | 8 | 7 | −116 | 156 | 7.49 | 0.07 | 0.08 | 0.70 | LOW_ACTIVITY |
| K_COST_GATED (K) | 60 | 0 | 0 | 0 | 0 | −20529 | −5885 | −2.05 | 0.00 | 0.00 | 0.93 | NO_SIGNAL |
| L_META_LABEL (L) | 60 | 0 | 0 | 0 | 0 | −4909 | −3388 | −1.37 | 0.00 | 0.00 | 1.00 | NO_SIGNAL |

**Structural lessons (no near-miss is "the answer"):**

1. **The only family with cost-robust raw positives is `I_KALMAN_TREND`**
   (8 raw+, 7 survive 2.0x, best Sharpe 7.49) — but it is **sparse** (1–98
   trades vs a 120-trade floor, DSR 0.0). Its failure is *activity*, not
   *edge*. This is the single most important structural signal in the program.
2. **Mean-reversion / microstructure / cross-pair (C/E/G) have gross edge but
   are high-turnover** → cost-dominated. The edge is real; the arena is not.
3. **Stat-arb (H) and ML (L) are 100% gross-negative** — no edge at all on M1
   price-only.
4. **Three families are over-restrictive** (A, C_OU, I_CHANGEPOINT) and never
   trade enough — a *design* property, i.e. scientific evidence against those
   configurations.
5. **Fold and LOO pass rates are ~0 everywhere** — no candidate is stable
   across time *and* instruments, which is why multiplicity significance is 0.

---

## 3. Cost decomposition

The frozen cost model is **unchanged**: real bid/ask spread inside side-correct
fills + `0.10 bps` commission/slippage per fill (0.20 bps/round-trip at 1.0x).
Because `net(mult)` is linear in `mult`, the mid-to-mid zero-cost gross is
back-solved as `gross = 3·net_1x − 2·net_1_5x` and
`total_cost_1x = 2·(net_1x − net_1_5x)` (linearity verified to ~5e-7).

Program level (823 A-candidates with trades):

- **515 (63%)** have **negative mid-to-mid gross** → the signal is
  *intrinsically* negative (no edge before costs).
- **288 (35%)** have **positive gross that costs destroy** → *positive gross but
  uneconomic net*.
- **20 (2%)** are net-positive at 1x; **none** survive the full predicate.

Per-family median (with trades): the cost eats **286–450% of gross** in the
gross-positive families:

| Family | medGross | medNet1x | medCost1x | %gross consumed | intrNeg | posGrossUnecon | netPos |
|---|---|---|---|---|---|---|---|
| C_ZSCORE | +2913 | −4160 | 7675 | 326% | 1 | 75 | 0 |
| E_SPREAD | +3307 | −5357 | 8705 | 287% | 2 | 58 | 0 |
| G_USD_FACTOR | +45606 | −202574 | 241935 | 450% | 0 | 37 | 0 |
| B_TREND_PULLBACK | +71 | −4524 | 4879 | 698% | 39 | 48 | 4 |
| I_KALMAN_TREND | −20 | −116 | 73 | 148% | 42 | 10 | 8 |
| H_TRIANGULAR | −18928 | −29671 | 11738 | n/a | 112 | 0 | 0 |
| L_META_LABEL | −1718 | −4909 | 3197 | n/a | 60 | 0 | 0 |

**What each gross-positive family would need to become plausible** (no cost
model change):

- `C_ZSCORE`, `E_SPREAD`, `G_USD_FACTOR`: **lower turnover / longer horizon**
  (or a tighter-spread venue) so cost/trade ≪ edge/trade.
- `B_TREND_PULLBACK`: a **stronger signal or lower cost** (all 4 positives fail
  2.0x).
- `I_KALMAN_TREND`: **more activity** (the edge exists but is too sparse).

The critical distinction the data supports: **the gross-positive families are
*cost-suppressed*, not *edge-lacking*; the gross-negative families are
*edge-lacking*, not cost-suppressed.** These are different diseases with
different (mostly non-V4-on-same-data) cures.

---

## 4. Zero-trade analysis (169 Universe-A candidates)

All 169 zero-trade candidates fall into **three families**:

| Family | zero-trade | Mechanism (frozen design, not a bug) |
|---|---|---|
| `C_OU_HALFLIFE_REVERSION` | 60 | reversion z-score **AND** OU half-life in [30,1000] bars; the half-life needs lag-1 autocorr ∈ (0,1) over 300 observed bars — the band is almost never satisfied |
| `A_DONCHIAN_BREAKOUT_POST_COMPRESSION` | 59 | breakout-beyond-channel **AND** range-compression regime; the two conditions rarely co-occur |
| `I_CHANGEPOINT_REGIME_SHIFT` | 50 | change-point `dev > thr` over H bars; the regime-shift detector fires rarely on stationary M1 residuals |

**Cause classification:** these are **frozen-hypothesis design** outcomes —
over-restrictive logical conjunctions and regime gates that never open on
pre-2018 M1 data — **not implementation bugs**. They are therefore **scientific
evidence against those configurations** and are **kept in the denominator**
(never silently removed). The remaining zero-trade mechanisms across the program
are: feature warm-up NaNs (first ~480–1000 bars), the executable-quote mask,
the 16:30–17:30 no-entry window, and (for triangles/panel) the requirement that
all legs be contemporaneously observed/executable.

---

## 5. The 20 raw-positive candidates — forensic, not rescue

Studied **only** to understand failure modes. No candidate-specific parameter is
used as a V4 seed.

| Group | n | Why it is NOT a scientific survivor |
|---|---|---|
| **B_TREND_PULLBACK** (all USDJPY, H1) | 4 | Large gross (2.7k–5.9k bps) but high turnover (1.8k–4.9k trades); **all fail 2.0x cost stress and instrument LOO** → COST_DOMINATED + F |
| **I_KALMAN_TREND** (H1) | 8 | The near-miss: 7 survive 2.0x, best Sharpe 7.49, but **only 1–98 trades (min 120) and DSR 0.0** → LOW_ACTIVITY (sparse), not a robust edge |
| **A_DONCHIAN** (H0) | 7 | **1–10 trades (min 250)**; net comes from 1–3 lucky trades → LOW_ACTIVITY, not a signal |
| **I_CHANGEPOINT** (H1 EURUSD) | 1 | gross 1.1k but fails 2.0x, fold 0.38, LOO → COST_DOMINATED + E |

**Common thread:** none of the 20 is simultaneously (a) cost-robust at 2.0x,
(b) statistically sufficient (trades/DSR), (c) fold- and LOO-stable, and (d)
multiplicity-significant. The best individual (V3-0777, Sharpe 7.49) has **5
trades** — a sample too small to be evidence.

---

## 6. V1 → V2 → V3 learning curve

| | V1 | V2 | V3.1 |
|---|---|---|---|
| verdict | `CLOSED_NO_CERTIFIED_V1_ALPHA` | `V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` | `V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` |
| evaluated / registered | 8 / 1200 | 336 / 336 | 992 / 1044 |
| families | 12 | 8 | 18 (+6 archetypes) |
| survivors | 0 | 0 | 0 |
| WRC p | 0.996 | 1.0 | 1.0 |
| SPA p | 1.0 | 0.461 | 0.730 |
| PBO | n/a | 0.129 | 0.186 |
| RW/Holm/BH sig. | 0 | 0 | 0 |
| data | 3 majors, M1, 2015–17 | 3 majors, M1, 2015–17 | 13 instr, M1, 2010–14 |

**What each generation fixed / left unresolved:**

- **V1 → V2:** fixed *semantic/infrastructure* stall (typed schema,
  deterministic compiler, unified execution kernel, frozen protocol). Left
  unresolved: 6 of 12 V1 families never became executable; the data gap
  (3 pairs, 4 years) was the named root cause.
- **V2 → V3:** fixed the *narrow search space* (3 pairs, single horizon) by
  going multi-horizon (H0–H3), 13-instrument cross-sectional, and adding
  composition archetypes. Left unresolved: cross-pair/multi-day structure was
  still data-limited; the microstructure families remained untestable.

**Program-level conclusion (with evidence strength):**

- **A. Repeated absence of alpha under price-only public FX M1 data — STRONG.**
  Three generations, 1388 candidate-equivalent trials, WRC p ≈ 1.0 in every
  generation. This is the dominant explanation.
- **C. Execution-cost dominance — STRONG** for the gross-positive families
  (costs consume 286–450% of gross).
- **D. Missing microstructure information — STRONG** for the *untested*
  (rejected pre-outcome) microstructure families.
- **B. Inadequate model class — MODERATE** (only simple classes were tested).
- **E. Wrong horizon — MODERATE** (H0 cost-hostile; H1 tested; H2/H3 not
  executable).
- **F. Wrong market — WEAK** (only USD majors).
- **G. Wrong validation — WEAK** (the validation was rigorous; the absence is
  real, not an artifact).

The program is **not** showing a validation failure; it is showing a genuine
absence of *identifiable, cost-robust, multiplicity-significant* intraday alpha
in the price-only M1 public-FX information set.

---

## 7. Information-content analysis

**Present in the current set:** M1 bid/ask OHLC (side-correct fills, real
spread); observation / executable-quote masks; cross-pair relationships (13
instruments, panel + 5 triangles); multi-timeframe price history; session /
calendar state.

**Absent:** L2 / order-book depth & imbalance; quote-arrival dynamics / true
tick microstructure; broker/order flow & transaction volume; options / implied
vol; rates / carry / financing history; positioning (COT) / dealer inventory;
news / event / macro-surprise; funding / liquidity stress.

**What is realistically identifiable from the current set:** slow,
**low-turnover**, cross-sectional or multi-day effects that survive the
M1 spread + 0.10 bps/fill cost. The tested **intraday high-turnover** effects
are *not* identifiable (they are cost-dominated).

**Failed families that require absent information:** `V3_E_TICK_ARRIVAL_INTENSITY`
(needs tick-arrival rate) and `V3_E_ORDER_BOOK_IMBALANCE` (needs order-book
depth) — both **rejected pre-outcome**, i.e. the most promising intraday
hypothesis class is **untested, not refuted**. The G/H cross-pair & stat-arb
families are *cost-dominated*, not data-missing.

---

## 8. Market / horizon review (methodological only)

| Arena | Relative cost | Microstructure | Persistent effects | Public data |
|---|---|---|---|---|
| **Intraday spot FX M1 (current)** | highest (spread+comm vs small edge) | rich but *unmeasured* | weak intraday | M1 bid/ask only |
| Multi-day FX | lower (edge scales with horizon) | moderate | moderate (carry needed) | M1 + daily |
| FX futures | lower spread, centralized | richer | moderate | not acquired |
| Equity index futures | lower | **rich** | moderate | **full tick/depth public** |
| Rates futures | low | moderate | **strong (term structure)** | **excellent** |
| Crypto | different regime | **very rich** | mixed | **full tick/depth public** |
| Cross-asset RV | lower | moderate | **strong (structural)** | multi-asset |

**Where costs are lower relative to signal:** multi-day FX, FX/equity/rates
futures, cross-asset RV (edge scales with horizon while cost is per-trade).
**Where microstructure is richer / public data is better:** equity index
futures, crypto, FX futures. **Where persistent effects are more plausible:**
multi-day FX, rates futures, cross-asset RV.

---

## 9. Model-class review

**V3 families were primarily:** linear (rolling OLS, z-scores); threshold-based
(sigma crossings); hand-crafted technical (Donchian, compression, session
windows); simple regime-conditioned (vol quantile bands, OU half-life); simple
ML (expanding logistic meta-label, Kalman filter).

**Not really tested:** state-space / latent-factor (beyond one Kalman drift);
sequence models; nonlinear representation learning / self-supervised TS
embeddings; cross-sectional ranking as a first-class signal; Hawkes /
event-intensity; optimal stopping / DP / control-RL; causal event-response;
full microstructure models (need absent data).

| Future class (family-level) | New capacity | Data needed | Overfit risk | Justified by V1–V3? |
|---|---|---|---|---|
| State-space / latent-factor | separate signal from noise; slow latent drift | current M1 | medium | MODERATE (Kalman was the near-miss but too sparse) |
| Cross-sectional ranking / meta-labeling | rank 13 pairs, trade the spread | current panel | medium | MODERATE (G_xsmom had gross edge, cost-dominated) |
| Sequence / embedding | nonlinear bar-sequence patterns | current M1 | **high** | WEAK (no evidence the effect exists) |
| Hawkes / event-intensity | quote-arrival clustering | **TICK (absent)** | medium | BLOCKED (needs new data) |
| Optimal stopping / control-RL | optimize entry/exit under cost | current M1 | high | WEAK–MODERATE (cuts cost drag, doesn't create edge) |

---

## 10. DO-NOT-REPEAT registry

| # | Do not repeat | Evidence | Action |
|---|---|---|---|
| 1 | High-turnover M1 mean-reversion / spread-gated reversal (C, E) | gross-positive but cost eats 287–326% of gross; 0 survivors in V2 F04/F05 and V3 C/E | ban unless lower-cost venue / longer horizon |
| 2 | Triangular / cointegration stat-arb on M1 (H) | 100% gross-negative (132 candidates) | ban on M1 price-only |
| 3 | Donchian breakout post-compression as standalone H0 (A) | 65% zero-trade; positives are 1–10-trade wins | do not re-sweep |
| 4 | OU-half-life banded reversion (C_OU) & change-point regime shift (I_CHANGEPOINT) | 60/60 and 50/60 zero-trade; gates never open | do not re-sweep the same gates |
| 5 | Parameter sweeps around the 20 raw-positive candidates | all 20 fail the frozen predicate; they are failure modes | **explicitly forbidden** (anti-overfit) |
| 6 | Price-only approximations to tick features (E_TICK, E_ORDER_BOOK) | rejected pre-outcome; M1 cannot proxy arrival/depth | requires real tick/depth data |
| 7 | Ever-larger hand-crafted indicator combinatorics | M-archetypes stack 3 restrictive masks; 0 survivors | ban indicator-stacking as a generator |
| 8 | Post-hoc session / time-of-day optimization | F session-momentum is 84% gross-negative; session works only as a filter | session as filter, never as the signal |
| 9 | Weak 1-minute TA under realistic costs | H0 micro is cost-dominated / no-signal | ban H0 micro as a primary arena without a cost advantage |

---

## 11. High-information next-experiment classes

Each answers a scientific question and is designed to **distinguish** "no edge
exists" vs "representation inadequate" vs "cost destroys edge" vs "missing
microstructure".

| ID | Question | Hypothesis class | New info needed | Minimal test | Expected failure | Justifies a full V4 if |
|---|---|---|---|---|---|---|
| **X1** | Is the absence due to COST or no edge? | the 4 gross-positive cost-dominated families (C/E/G/B-pullback) | lower-cost assumption or longer horizon (no new data) | re-evaluate at reduced cost / H1–H2; does net turn positive? | edge still absent after cost cut → confirms no intrinsic edge | a gross-positive family becomes cost-robust **and** multiplicity-significant at a realistic lower cost / longer horizon |
| **X2** | Does the microstructure hypothesis have alpha now that it can be tested? | quote-arrival intensity / order-book imbalance (V3_E rejected) | **TICK/L2 (NEW data class)** | one small family on tick data, same frozen protocol | tick edge also cost-dominated or absent | a tick-based family clears the frozen predicate → V4 on the new data class |
| **X3** | Is intraday spot FX the right arena? | slow cross-sectional / multi-day FX or futures RV | multi-day or futures data (possibly new market) | port one gross-positive cross-sectional signal (G_xsmom) to daily; check cost/edge | edge doesn't persist at daily frequency | a daily/futures cross-sectional signal is cost-robust and significant |
| **X4** | Is our representation inadequate, or is the signal null? | richer state-space / latent-factor on the SAME data | none | one latent-factor model vs the V3 Kalman near-miss | richer model adds activity but not significant edge | a richer model reveals a significant edge the simple classes missed |
| **X5** | Can timing rescue the gross-positive families? | optimal-stopping / control on entry/exit | none | optimal-exit rule on the B-pullback gross-positive signal; measure cost-drag cut | timing cuts cost but residual edge not significant | timing turns a cost-dominated signal into a significant survivor |

**X1 and X4 are the cheapest, highest-information tests** (no new data): they
directly separate "no edge" from "cost/representation". **X2 is the highest
upside** (the untested microstructure hypothesis) but requires a new data class.

---

## 12. V4 GO / NO-GO decision

### Verdict: `V3_PROGRAM_REVIEW_REQUIRES_NEW_DATA_CLASS`

**Rationale.** The price-only M1 public-FX information set is **exhausted for
the tested intraday hypothesis classes**: three generations, 1388 trials, WRC
p ≈ 1.0, zero survivors. The dominant failure is NO_SIGNAL (48%) with
COST_DOMINANCE (27%) for the gross-positive families. Crucially, the **most
promising** intraday hypothesis class — market microstructure — was **rejected
pre-outcome** because it requires tick/order-book data the M1 set does not
contain, so it is **UNTESTED, not refuted**. A V4 on the *same* data is
therefore **not justified**; a future program requires a **new data class
(tick/L2)** or a **different market/horizon with lower relative cost**.

**Why not `V4_JUSTIFIED`:** no new hypothesis class is testable *and*
likely-successful on the current price-only M1 set. The gross-positive families
are cost-suppressed, not edge-lacking, but the cost structure is a property of
the *arena*, not something model choice can fix.

**If a future program proceeds, the information classes are:** tick /
quote-arrival microstructure (NEW); L2 order-book depth / imbalance (NEW);
multi-day or futures price data for lower relative cost (NEW market/horizon).

**Hypothesis classes worth testing:** microstructure (now testable with new
data); lower-turnover cross-sectional / multi-day FX; richer state-space /
latent-factor on existing data (X4).

**Classes to ban:** high-turnover M1 mean-reversion / spread-gated reversal;
M1 triangular / cointegration stat-arb; price-only approximations to tick
features; indicator-stacking combinatorics; parameter sweeps around the 20
raw-positive failure modes.

**Prospective safeguards:** freeze the statistical protocol + survivor predicate
*before* any V4 outcome; keep the 2018+ holdout sealed and independent;
pre-register the new data class and its capability contract; control
cross-version multiplicity (program-level alpha split); no V4 candidate may be
seeded from a V3 raw-positive parameter.

---

## 13. 2018+ holdout recommendation

**`KEEP_SEALED`.** The sealed 2018+ region is the program's most valuable
remaining **independent** evidence. V3 ended with no survivor, so consuming it
now would spend independent evidence on a null result. It should be reserved
for a **future, genuinely new prospective program** (new data class or new
arena) that first clears a pre-2018 gate. Do **not** open the holdout merely
because V3 ended with no survivor.

---

## 14. Final report

- **Starting SHA:** `3107ab899e564f61601df4897a5133d95bdee1db`
- **Program-level conclusion:** three generations (V1/V2/V3.1, 1388
  candidate-equivalent trials) found **no scientific survivor** under price-only
  public FX M1 data (WRC p ≈ 1.0 throughout). The dominant cause is **absence of
  identifiable intraday edge (A, 48%)**, compounded by **cost dominance of
  gross-positive high-turnover families (B, 27%)** and **over-restrictive
  low-activity configurations (D, 24%)**.
- **Dominant failure modes:** NO_SIGNAL > COST_DOMINATED > LOW_ACTIVITY ≫
  STRESS_FRAGILE.
- **Family/domain patterns:** C/E/G gross-positive but cost-dominated; H/L
  gross-negative; A/C_OU/I_CHANGEPOINT over-restrictive; I_KALMAN the sparse
  near-miss.
- **Cost-vs-signal:** 63% of trading candidates are intrinsically negative; 35%
  are positive-gross-but-uneconomic; cost consumes 286–450% of gross in the
  gross-positive families.
- **169 zero-trade:** all in 3 over-restrictive families (C_OU 60, A 59,
  I_CHANGEPOINT 50) — frozen-design evidence, kept in the denominator.
- **20 raw-positive:** 4 cost-dominated USDJPY pullbacks, 8 sparse Kalman
  near-misses, 7 single-trade Donchian wins, 1 unstable change-point — none
  simultaneously cost-robust, sufficient, stable, and significant.
- **Information that appears missing:** tick/L2 microstructure, order flow,
  carry/financing, options/IV, positioning, news/macro, funding stress.
- **Classes NOT to repeat:** see §10 (9 items).
- **High-information next experiments:** X1 (cost vs no-edge), X2 (tick
  microstructure), X3 (arena/horizon), X4 (representation), X5 (timing).
- **Is the current FX/M1/public-price set exhausted?** **Yes, for the tested
  intraday hypothesis classes.** The untested microstructure class needs a new
  data class; the gross-positive classes need a different cost regime.
- **2018+ firewall counters (this session):** provider requests = 0, reads = 0.
- **V4 GO/NO-GO:** `V3_PROGRAM_REVIEW_REQUIRES_NEW_DATA_CLASS`.
- **Next gate:** program review complete; **STOP** — do not begin V4 in this
  session.
