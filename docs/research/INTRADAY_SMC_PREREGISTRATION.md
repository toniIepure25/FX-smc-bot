# Pre-Registration: Intraday SMC/ICT Strategy Validation

**Status**: PRE-REGISTERED — DO NOT MODIFY AFTER HOLDOUT EVALUATION BEGINS

**Date**: 2024-XX-XX (to be filled when development campaign completes)

**Branch**: `research/rigorous-intraday-smc-validation`

---

## 1. Primary Hypotheses

### H1: Sweep Reversal
The `liquidity_sweep_mss_fvg_reversal` strategy, applied to EURUSD and GBPUSD during London and New York sessions, produces positive net daily portfolio returns with a Sharpe ratio significantly greater than zero after realistic transaction costs (spread + slippage + commission).

### H2: Acceptance Continuation
The `liquidity_acceptance_fvg_continuation` strategy produces positive net daily portfolio returns with positive risk-adjusted performance after costs.

### H3: Opening Range Retest
The `opening_range_displacement_fvg_retest` strategy produces positive net daily portfolio returns after costs, tested separately for London and New York opening ranges.

### H4: Incremental Value of SMC Components
The MSS, FVG, and liquidity-sweep components individually contribute positive incremental alpha compared to matched baselines that omit them.

---

## 2. Canonical Strategy Definitions

### Strategy A — Liquidity Sweep MSS FVG Reversal
See `configs/research/intraday_smc/sweep_reversal.yaml` for frozen parameters.

State machine: IDLE → LEVEL_AVAILABLE → LEVEL_BREACHED → RECLAIM_CONFIRMED → MSS_CONFIRMED → FVG_CREATED → ORDER_PENDING → FILLED → CLOSED

### Strategy B — Liquidity Acceptance FVG Continuation
See `configs/research/intraday_smc/acceptance_continuation.yaml`.

State machine: IDLE → LEVEL_AVAILABLE → LEVEL_BREACHED → ACCEPTANCE_CONFIRMED → FVG_CREATED → ORDER_PENDING → FILLED → CLOSED

### Strategy C — Opening Range Displacement FVG Retest
See `configs/research/intraday_smc/opening_range.yaml`.

State machine: IDLE → RANGE_COMPLETE → BREAKOUT_CONFIRMED → FVG_CREATED → ORDER_PENDING → FILLED → CLOSED

---

## 3. Primary Instruments
- EURUSD (primary)
- GBPUSD (primary)
- USDJPY (negative control / generalization)

---

## 4. Primary Sessions
- London (08:00-16:30 Europe/London, DST-aware)
- New York (08:00-17:00 America/New_York, DST-aware)

---

## 5. Parameters
All parameters are frozen in the canonical YAML configs. Sensitivity analysis is permitted only within pre-registered neighborhoods and must use explicit multiple-testing correction.

---

## 6. Data Interval
- Target: 8-10 years of M1 or tick data, resampled to M5/M15/H1
- Minimum: all available real historical data
- Base resolution: M1 bid/ask preferred; M1 mid-price with synthetic spread acceptable but labeled

---

## 7. Transaction Costs
- Spread: 1.5 pips (EURUSD/GBPUSD), 2.0 pips (USDJPY)
- Slippage: 0.3 pips
- Commission: $3.50 round-turn per standard lot
- Cost stress: 1.5×, 2×, 3× as ablations

---

## 8. Dataset Splits
- **Development period**: first 60% of data
- **Validation period**: next 20%
- **Final holdout**: last 20%
- Purge: 5 trading days between splits
- Embargo: maximum trade holding period

Walk-forward validation nested within development data.

---

## 9. Primary Metric
Annualized Sharpe ratio of daily net portfolio returns.

---

## 10. Secondary Metrics
- Net expectancy in R and currency
- Profit factor with bootstrap CI
- Win rate with CI
- Maximum drawdown
- Sortino ratio
- Calmar ratio
- VaR/CVaR at 5%
- Exposure time
- Entry/exit efficiency (MAE/MFE)
- Cost-to-gross-profit ratio

---

## 11. Minimum Sample Requirements
- ≥ 100 trades per strategy-pair-session combination
- ≥ 50 independent trading days with trades
- Results not driven by a single year or pair

---

## 12. Statistical Tests
- Stationary bootstrap CIs (Politis & Romano, 1994) with block length 5
- Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012)
- Deflated Sharpe Ratio for multi-strategy correction
- White's Reality Check for baseline comparisons
- CSCV PBO where applicable

---

## 13. Multiple-Testing Correction
- Holm-Bonferroni for the 3 primary hypotheses (H1-H3)
- Benjamini-Hochberg FDR for ablation families
- DSR for parameter variants

---

## 14. Acceptance Gates

### Pass (positive evidence):
- Net Sharpe > 0 with lower 95% CI > 0
- PSR > 0.95 (benchmark SR = 0)
- Survives 1.5× cost stress
- Profit factor lower CI > 1.0
- ≥ 100 trades
- Walk-forward consistency > 60%

### Conditional pass (regime-specific):
- Positive in specific regime/session but not universally
- Clearly documented and not retroactively cherry-picked

### Inconclusive:
- Positive point estimate but CI includes zero
- Insufficient trades for reliable inference

### Fail (negative evidence):
- Negative expectancy after costs
- Indistinguishable from random baselines
- Fails multiple-testing correction

---

## 15. Permitted Sensitivity Analyses
- Entry at 0%, 50%, 100% FVG mitigation
- 1R/2R/3R targets
- ±1 bar on reclaim/acceptance window
- ±20% on displacement thresholds
- With/without news filter
- All explicitly corrected for multiple testing

---

## 16. Conditions for Inconclusive Result
- Fewer than 50 trades per combination
- Data quality issues affecting > 5% of observations
- Ambiguous fill resolution affecting > 10% of trades
- Walk-forward degradation > 50% vs development

---

## 17. Falsification Criteria
A strategy is considered falsified if:
- Random-direction baseline at matched timestamps produces equivalent performance
- Removing the key SMC component (MSS, FVG, sweep) does not degrade performance
- Performance is isolated to a single parameter value
- Results are entirely driven by 1-2 outlier trades

---

## 18. What This Pre-Registration Does NOT Guarantee
- A positive result does not prove future profitability
- Backtest results are upper bounds on live performance
- This protocol evaluates historical evidence, not future prediction
- All conclusions are conditional on data quality and model assumptions
