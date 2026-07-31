# Gate F.0 Statistical Protocol

This protocol is frozen for `FX_CLASSICAL_RISK_PREMIA_V1`; previous lineage
results and seals do not enter estimation.

## Estimands

- Primary profitability estimand: mean daily net portfolio return.
- Primary economic effect: annualized net geometric return.
- Primary benchmark-relative alpha: candidate daily net return minus the
  matched-turnover random-sign daily net return.
- Factor-adjusted alpha: intercept from a return regression on the four
  non-cash benchmark return series, estimated with Newey-West HAC inference.

Annualization uses 252 trading days. Return confidence intervals are two-sided
95% intervals. Newey-West HAC lag is `5` trading days.

## Required metrics

Report annualized return, annualized volatility, Sharpe, Sortino, Calmar,
maximum drawdown, time under water, CVaR 95%, skew, kurtosis, turnover, spread
cost, commission cost, slippage cost, financing return, financing markup cost,
gross leverage, currency exposure, hit rate, monthly win rate, yearly return,
instrument contribution, and factor contribution.

## Required inference

Compute:

- stationary-bootstrap confidence interval;
- month-cluster bootstrap;
- Newey-West HAC alpha;
- White Reality Check;
- Hansen SPA;
- Romano-Wolf max-T;
- Holm family-wise correction;
- Benjamini-Hochberg FDR sensitivity;
- probabilistic Sharpe ratio (PSR);
- deflated Sharpe ratio (DSR);
- probability of backtest overfitting (PBO).

White Reality Check, SPA, Romano-Wolf, Holm, and FDR operate on the frozen family
of six candidates without post-hoc exclusions. PBO uses the frozen candidate
family and chronological combinatorially symmetric cross-validation. The
stationary bootstrap resamples daily observations; the cluster bootstrap
resamples whole calendar months.

Use `10,000` deterministic resamples/permutations for each applicable procedure.
Bootstrap and permutation seeds are both `1729`. Raw and adjusted p-values must
be reported together. Missing or numerically invalid inference may not be
silently replaced and requires an applicable blocking decision.

This document freezes estimands and methods only; it reports no statistical
outcome.
