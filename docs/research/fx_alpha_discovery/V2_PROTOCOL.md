# FX_INTRADAY_ALPHA_DISCOVERY_V2 — Prospective Discovery Protocol

**Status:** `FROZEN_PRE_OUTCOME`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V2`
**Lineage:** `FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1`
**Readiness gate:** `A0R4_V2_PROSPECTIVE_READINESS_V1`
**Config freeze:** [`configs/research/fx_intraday_alpha_search_v2.yaml`](../../../configs/research/fx_intraday_alpha_search_v2.yaml)
**Code:** `src/fx_smc_bot/research/v2/`

V2 exists because V1 repeatedly stalled on semantic/infrastructure repair gates. The fix
is not another recovery gate (A0R3G, A0R3H, …) but a **factory rebuild**: a typed schema, a
deterministic compiler, a capability-grounded search space, a unified execution kernel, a
frozen statistical protocol and a frozen survivor predicate — all defined **before** any
2018+ outcome is inspected. This is not data snooping because every specification below is
frozen and hashed prior to holdout access.

## 1. Structural fix for the recurring blocker

The compiler has exactly two terminal states — `ADMITTED_EXECUTABLE` and
`REJECTED_PRE_OUTCOME`. There is **no `BLOCKED` state**. A strategy that cannot be fully
specified against the frozen dataset is rejected before outcome evaluation rather than
carried forward as an unresolved semantic blocker. Result: **0 admitted trials with
unresolved semantic blockers**, permanently.

## 2. Capability grounding (honest, never proxied)

The frozen dataset is three USD majors (EURUSD, GBPUSD, USDJPY) at Dukascopy **M1 bid/ask
OHLC**, development 2015–2017, holdout 2018–2019. The full matrix is
[`results/gate_a0r4/data_capability_matrix.json`](../../../results/gate_a0r4/data_capability_matrix.json).

* **Never** reads the `volume` field (an unreliable tick-volume proxy).
* Tick quote-arrival/update-rate, order-book depth, JPY crosses, AUD/other majors,
  currency-factor cross-sections and triangular cross rates are **UNSUPPORTED** and never
  reconstructed from M1. `M1 bar count != quote update count`.

## 3. Admitted families (complete executable semantics)

Eight families are admitted, each with an exact `FeatureSpec`/`SignalSpec`/`ExecutionSpec`
(and `ModelSpec` for model families). See `search_space.py` and the config freeze.

| Family | Feature | Notes |
| --- | --- | --- |
| F01 | session_momentum | vol-normalised session-open return, anchor-gated |
| F02 | signed_return_run | M1 signed-return run length only (tick variants rejected) |
| F03 | volatility_breakout | `(rolling_range / Wilder ATR) − 1` gate + prior high/low break |
| F04 | liquidity_shock_m1 | mean-reversion after `spread_z & abnormal_return_z` shock bar (explicit M1 proxy) |
| F05 | spread_zscore | execution-alpha gating via deterministic seasonal-median / HAR-linear spread forecast |
| F10 | seasonality_cell | prior-only expanding cell means (hour-of-session, day-of-week) |
| F11 | regime_trend | quantile-bin or fixed-seed GMM regime; momentum in turbulent, fade in calm |
| F12 | ml_abstention | causal walk-forward logistic/ridge with purge+embargo, long/short/abstain |

**Rejected pre-outcome families:** F06 (cross-pair), F07 (currency factor), F08
(triangular), F09 (cross-sectional) — all require instruments/cross-sections never
acquired. **Rejected variants:** F02/F04 tick variants, F05 tree/EN forecasters, F11 HMM,
F12 tree/NN models. All documented in
[`results/gate_a0r4/rejected_pre_outcome.json`](../../../results/gate_a0r4/rejected_pre_outcome.json).

Family count is a scientific choice, not a target: **twelve was not preserved for its own
sake.**

## 4. Executable specification surface

Every admitted spec fixes: input bars & interval; price representation; bid/ask usage;
feature formula, units, lookback, warm-up, min observations, normalization; entry
threshold, direction, signal timestamp; entry eligibility, minimum one-bar latency,
side-correct entry/exit prices; holding/exit/stop/target rules; adverse-first same-bar
behaviour; missing-quote (no synthetic fill); session/rollover/DST behaviour; position
sizing abstraction; transaction cost/slippage/commission and 1.5x/2.0x stress. Model
families additionally fix: feature vector, target, preprocessing/standardization, training
window (expanding, prior-only), retrain cadence, embargo, purge, seed, score→action and
abstention mapping, min observations and failure behaviour.

## 5. Unified execution kernel

The single canonical execution path (`kernel.py`) reuses the **certified** A0R3D
side-correct event state machine — one implementation, no forks — pinned by golden tests
(long/short, JPY/non-JPY scaling, invalid quotes, mandatory flat, latency, stop/target
collision, rollover, cost stress).

## 6. Statistical protocol (frozen)

[`results/gate_a0r4/statistical_protocol.json`](../../../results/gate_a0r4/statistical_protocol.json).
Progression `DISCOVERY → INTERNAL CONFIRMATION → EXTERNAL VALIDATION → INDEPENDENT
REPLICATION` uses the already-inspected development region for discovery and a strictly
chronological, non-overlapping partition of the untouched holdout:

| Stage | Region | Window |
| --- | --- | --- |
| Discovery | development | 2015–2017 |
| Internal confirmation | holdout | 2018-01-01 … 2018-06-30 |
| External validation | holdout | 2018-07-01 … 2018-12-31 |
| Independent replication | holdout | 2019 |

Controls: purged expanding walk-forward, purge = label horizon, embargo = max feature
lookback + max holding, instrument/year leave-one-out, parameter-neighborhood stability,
White Reality Check, Hansen SPA, Romano-Wolf, Holm, BH-FDR, PSR, DSR, CSCV PBO, realistic
costs + stress. Denominator = number of admitted executable trials actually evaluated
(≤ 1200 ceiling). No split boundary is a function of any observed outcome.

## 7. Survivor predicate (frozen)

[`results/gate_a0r4/survivor_predicate.json`](../../../results/gate_a0r4/survivor_predicate.json).
A `REVIEW_RANKING` is informational only; ranking above losing candidates never confers
survivorship. A scientific survivor must jointly satisfy net profitability, Sharpe ≥ 0.5,
trade/day sufficiency, ≥ 60% fold positivity, instrument leave-one-out positivity, ≥ 60%
neighborhood sign-stability, 1.5x/2.0x cost-stress positivity, Romano-Wolf p ≤ 0.05, CSCV
PBO ≤ 0.5, and full data-integrity (no 2018+ pre-discovery reads; deterministic
reproduction PASS). Thresholds are hashed and must never be relaxed to manufacture
survivors.

## 8. Holdout firewall

The 2018+ region is protected structurally (`firewall.py`): any attempt to open a 2018+
market/outcome file raises before a byte is decoded. The readiness gate demonstrates a
permitted 2015 read and a correctly-blocked 2018 attempt with
`2018_plus_market_or_outcome_files_opened = 0`
([`results/gate_a0r4/holdout_firewall_audit.json`](../../../results/gate_a0r4/holdout_firewall_audit.json)).

## 9. Reproducibility

Every materialized trial carries a config/semantic/capability/execution/protocol hash
chain plus repository-relative provenance (no absolute developer paths). Clean-room
re-materialization is byte-identical
([`results/gate_a0r4/reproducibility_audit.json`](../../../results/gate_a0r4/reproducibility_audit.json)).

## 10. Next gate

`V2_ALPHA_DISCOVERY_RUN` — the actual discovery on the 2015–2017 development region,
followed only later by the strictly-separate confirmation/validation/replication cascade
on the untouched holdout. **That run is deliberately not performed in the readiness gate.**
