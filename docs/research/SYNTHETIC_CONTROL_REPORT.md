# Synthetic Control Experiment Report

**Date**: 2026-07-13
**Branch**: `research/rigorous-intraday-smc-validation`
**Purpose**: Software verification via deterministic synthetic data (NOT evidence of market alpha)

---

## Experiment Design

- **Data**: Dukascopy-style GBM synthetic M5 data, seed=42
- **Pairs**: EURUSD, GBPUSD, USDJPY
- **Coverage**: 2018-01-02 → 2024-12-31 (~525k bars per pair)
- **Timeframes**: M5 (execution), H1 (HTF context), M15/H4 (resampled)

## Critical Finding: Integration Gap

**The campaign engine (`run_intraday_smc_campaign.py` → `intraday_campaign.py` → `BacktestEngine`) does NOT use the new intraday SMC detectors.**

The `BacktestEngine.run()` method calls `generate_candidates()` from `alpha.candidates`, which uses legacy detectors:
- `SweepReversalDetector` (from `alpha.setup_families` — legacy, NOT the new V2 detector)
- `BOSContinuationDetector`
- `FVGRetraceDetector`

The new detectors are **independently implemented and tested** but not wired into the campaign pipeline:
- `SweepReversalDetectorV2` (`alpha/intraday/sweep_reversal.py`)
- `AcceptanceContinuationDetector` (`alpha/intraday/acceptance_continuation.py`)
- `OpeningRangeDetector` (`alpha/intraday/opening_range.py`)

### Impact
- **No end-to-end campaign test is possible** for the intraday SMC strategies
- State-transition funnels cannot be generated from the campaign engine
- The unit tests verify individual detector behavior but not full-pipeline integration
- This is a **BLOCKING** defect for Stages 16-22

### Required Fix
Wire the V2 detectors into either:
1. The `generate_candidates` registry (register them alongside legacy detectors), OR
2. A dedicated intraday campaign engine that directly calls `process_bar()` on each detector

Option 2 is preferred because the V2 detectors have a different interface (they accept raw OHLC arrays + snapshot, not a `MultiTimeframeContext`).

---

## Unit-Level Verification (Completed)

Although the full campaign pipeline is not integrated, the individual components have been verified:

### State Machine Framework
- StrategyTracker manages concurrent instances ✓
- Terminal state cleanup works ✓
- Level deduplication prevents double-registration ✓

### Sweep Reversal Detector (Unit Tests)
- Full lifecycle: level → breach → reclaim → MSS → displacement → FVG → signal ✓
- Sweep without reclaim → invalidated ✓
- Causal swing confirmation ✓
- Long/short symmetry ✓

### Acceptance Continuation Detector (Unit Tests)
- False breakout rejected ✓
- Valid acceptance with consecutive closes ✓
- Long/short symmetry ✓

### Opening Range Detector (Unit Tests)
- Range completion after window close ✓
- Session cutoff expiration ✓
- Bullish/bearish breakout ✓
- DST-aware window boundaries ✓

### Execution Layer
- Market orders fill at next-bar open ✓
- Conservative fill policy: SL checked first ✓
- Same-bar exit now wired into engine (fixed during audit) ✓
- Commission deducted in both ledger and portfolio (fixed during audit) ✓

### Statistical Inference
- Stationary bootstrap produces valid CIs ✓
- PSR uses daily SR (fixed during audit) ✓
- Holm-Bonferroni rejects correctly ✓
- BH-FDR controls false discovery rate ✓

---

## State-Transition Funnels (Not Available)

Full funnels cannot be generated because the detectors are not wired into the campaign engine. The expected funnels are documented here for future completion:

### Sweep Reversal Funnel (Expected)
| Stage | Count | Notes |
|-------|-------|-------|
| Eligible liquidity levels | ? | Depends on structure detection |
| Breaches | ? | Requires sweep detection |
| Qualifying sweep excursions | ? | min_pips_excursion filter |
| Reclaims | ? | max_reclaim_bars window |
| MSS confirmations | ? | find_causal_swing + check_mss |
| Displacement confirmations | ? | body_ratio + tr_ratio + CLV |
| FVG creation | ? | FVG must form after displacement |
| Pending orders | ? | Limit order at FVG retest level |
| Filled orders | ? | Price touches limit within max_order_bars |
| Expired orders | ? | max_order_bars exceeded |
| Invalidated instances | ? | Failed transitions |
| Closed trades | ? | SL or TP hit |

### Acceptance Continuation Funnel (Expected)
| Stage | Count |
|-------|-------|
| Eligible liquidity levels | ? |
| Breaks | ? |
| Displaced breaks | ? |
| Acceptance confirmations | ? |
| FVG creation | ? |
| Retests | ? |
| Pending orders | ? |
| Fills | ? |
| Invalidations | ? |
| Closed trades | ? |

### Opening Range Funnel (Expected)
| Stage | Count |
|-------|-------|
| Completed opening ranges | ? |
| Qualifying range breaks | ? |
| Displacement confirmations | ? |
| FVG creation | ? |
| Retests | ? |
| Pending orders | ? |
| Fills | ? |
| Invalidations | ? |
| Closed trades | ? |

---

## Conclusion

The synthetic control experiment identified a **critical integration gap**: the new intraday SMC strategy detectors (V2) are implemented and unit-tested but are not wired into the campaign/backtest engine. This means:

1. No full end-to-end campaign test has been executed
2. No state-transition funnels have been generated
3. The campaign CLI runs the legacy BOS strategy, not the intraday SMC strategies

**Status: BLOCKED_BY_IMPLEMENTATION**
