# A0R3C Forensic Evaluator Certification

Certification verdict: `FAIL`
Corrected exploratory rerun: `NOT_RUN_CERTIFICATION_FAILED`

A0R3B numerical results are not eligible for scientific no-go adjudication.

## Blocking Source Defects

| Defect | Evidence | Required fix |
|---|---|---|
| SURROGATE_MID_RETURN_EXECUTION | execution_components_bps uses mid.pct_change() for gross PnL | use side-correct ask/bid entry and exit fills |
| SYNTHETIC_HALF_SPREAD_COST_APPROXIMATION | costs subtract half-spread approximation rather than fill prices | compute execution prices directly from bid/ask fills |
| SYNTHETIC_STATISTICS_IMPORT | A0R3B imports a0r2_statistics synthetic-only interfaces | replace with certified deterministic bootstrap/statistical methods |
| A0R2_STATISTICS_MARKED_SYNTHETIC_ONLY | a0r2_statistics.py module docstring says synthetic-only | do not use these outputs for scientific claims |
| FROZEN_HORIZONS_NOT_EXECUTED | A0R3B source has no certified holding/target horizon state machine | implement frozen holding/exit semantics before rerun |

## Configuration Consumption Summary

| Family | Evaluated trials | USED | IGNORED | UNSPECIFIED |
|---|---:|---:|---:|---:|
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | 14 | 6 | 20 | 8 |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | 10 | 5 | 21 | 8 |
| F03_VOLATILITY_BREAKOUT | 11 | 5 | 21 | 8 |
| F04_LIQUIDITY_SHOCK_REVERSAL | 7 | 4 | 22 | 8 |
| F05_SPREAD_AWARE_EXECUTION_GATING | 9 | 4 | 22 | 8 |
| F10_INTRADAY_SEASONALITY | 9 | 4 | 22 | 8 |
| F11_REGIME_CONDITIONED_TREND_REVERSAL | 12 | 4 | 23 | 8 |
| F12_COST_SENSITIVE_ML_ABSTENTION | 14 | 4 | 23 | 8 |

## First Blocked Dimensions

| Family | Field | Reason |
|---|---|---|
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | holding_horizon | varies_within_evaluated_trials_but_not_used |
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | random_seed | varies_within_evaluated_trials_but_not_used |
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | stop_rule | varies_within_evaluated_trials_but_not_used |
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | target_horizon | varies_within_evaluated_trials_but_not_used |
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | training_window | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | feature_list | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | holding_horizon | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | random_seed | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | session_anchor | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | stop_rule | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | target_horizon | varies_within_evaluated_trials_but_not_used |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | training_window | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | holding_horizon | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | random_seed | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | session_anchor | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | stop_rule | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | target_horizon | varies_within_evaluated_trials_but_not_used |
| F03_VOLATILITY_BREAKOUT | training_window | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | holding_horizon | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | random_seed | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | session_anchor | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | stop_rule | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | target_horizon | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | training_window | varies_within_evaluated_trials_but_not_used |
| F04_LIQUIDITY_SHOCK_REVERSAL | variant | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | holding_horizon | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | random_seed | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | session_anchor | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | spread_forecaster | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | stop_rule | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | target_horizon | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | training_window | varies_within_evaluated_trials_but_not_used |
| F05_SPREAD_AWARE_EXECUTION_GATING | variant | varies_within_evaluated_trials_but_not_used |
| F10_INTRADAY_SEASONALITY | frozen_categories | varies_within_evaluated_trials_but_not_used |
| F10_INTRADAY_SEASONALITY | holding_horizon | varies_within_evaluated_trials_but_not_used |

## Certified Executable Trials

| Family | A0R3B pre-cert evaluated | Certified executable |
|---|---:|---:|
| F01_SESSION_OPENING_MOMENTUM_REVERSAL | 14 | 0 |
| F02_QUOTE_RUN_CONTINUATION_EXHAUSTION | 10 | 0 |
| F03_VOLATILITY_BREAKOUT | 11 | 0 |
| F04_LIQUIDITY_SHOCK_REVERSAL | 7 | 0 |
| F05_SPREAD_AWARE_EXECUTION_GATING | 9 | 0 |
| F10_INTRADAY_SEASONALITY | 9 | 0 |
| F11_REGIME_CONDITIONED_TREND_REVERSAL | 12 | 0 |
| F12_COST_SENSITIVE_ML_ABSTENTION | 14 | 0 |

## Holdout Integrity

- 2018+ market/outcome files opened by A0R3C: `0`
- Provider acquisition run: `False`
- Frozen PASS-strata dataset changed: `False`
- Registered 1200-trial universe changed: `False`
