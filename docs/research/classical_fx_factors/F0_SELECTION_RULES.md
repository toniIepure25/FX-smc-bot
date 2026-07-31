# Gate F.0 Selection and Replication Rules

Candidate parameters are not fitted. `FX_CLASSICAL_RISK_PREMIA_V1` uses staged,
mechanical adjudication; the closed SMC and quant-polarity lineages remain
irrelevant to selection.

## Development eligibility: 2011-2016

Require all:

- at least 1,000 eligible daily portfolio observations;
- annualized net return `> 0`;
- Sharpe `> 0`;
- base-cost result `> 0`;
- stress_1 annualized return `>= -1%`;
- positive return in at least 4 of 6 years;
- maximum drawdown `<= 30%`;
- matched-turnover alpha `> 0`;
- PBO `< 0.60`.

At most four candidates may proceed. Freeze and commit the shortlist before
internal-validation data access.

## Internal validation: 2017-2019

Require all:

- annualized net return `> 0`;
- Sharpe `> 0.30`;
- profit after all base costs;
- stress_1 annualized return `>= 0`;
- positive return in at least 2 of 3 years;
- matched-turnover alpha `> 0`;
- Holm-adjusted p-value `< 0.10`;
- Hansen SPA p-value `< 0.10`;
- PSR `> 0.90`;
- DSR probability `> 0.75`;
- maximum drawdown `<= 25%`.

At most two candidates may proceed. Freeze and commit the replication shortlist
before replication data access. An empty shortlist ends the program with
`F0_NO_FACTOR_PORTFOLIO_SURVIVED_INDEPENDENT_REPLICATION`.

## Independent replication: 2020-2022 Tier A

Require all:

- annualized net return `> 0`;
- stationary-bootstrap CI lower bound `> 0`;
- Sharpe `> 0.75`;
- PSR `> 0.95`;
- DSR probability `> 0.90`;
- stress_1 annualized return `> 0`;
- stress_2 annualized return `>= 0`;
- positive return in 2020, 2021, and 2022;
- matched-turnover alpha `> 0`;
- Holm-adjusted p-value `< 0.05`;
- Hansen SPA p-value `< 0.05`;
- factor-adjusted HAC alpha `> 0` with p-value `< 0.05`;
- PBO `< 0.25`;
- maximum drawdown `<= 20%`;
- best month contribution `< 25%` of total PnL;
- best instrument contribution `< 35%` of total PnL.

## Independent replication: Tier B

Require all:

- annualized net return `> 0`;
- stationary-bootstrap CI lower bound `>= -1%` annualized;
- Sharpe `> 0.50`;
- PSR `> 0.90`;
- DSR probability `> 0.75`;
- stress_1 annualized return `>= 0`;
- positive return in at least 2 of 3 years;
- matched-turnover alpha `> 0`;
- Holm-adjusted p-value `< 0.10`;
- Hansen SPA p-value `< 0.10`;
- PBO `< 0.40`;
- maximum drawdown `<= 25%`.

Only Tier A or Tier B may be frozen for future confirmation. Select at most one,
ranking by Tier A over Tier B, then highest replication CI lower bound, highest
stress_1 return, highest DSR probability, lowest PBO, and lowest maximum
drawdown. If none qualifies, return
`F0_NO_FACTOR_PORTFOLIO_SURVIVED_INDEPENDENT_REPLICATION`; otherwise the only
permitted positive decision is
`F0_CLASSICAL_FACTOR_PORTFOLIO_FROZEN_FOR_FUTURE_CONFIRMATION`.

No rule, threshold, shortlist, or ranking tie-break may change after outcomes.
This document contains no adjudication result.
