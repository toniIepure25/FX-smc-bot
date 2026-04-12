# Candidate Selection Guide

## Overview

The candidate selection process ranks strategy configurations by a weighted composite score that balances multiple dimensions beyond raw performance. This prevents selection of overfit or fragile strategies.

## Scorecard Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Robustness | 0.25 | How well performance holds under cost/fill stress scenarios |
| Simplicity | 0.15 | Whether added complexity improves over best single component |
| OOS Consistency | 0.20 | Out-of-sample to in-sample Sharpe ratio |
| Execution Fragility | 0.20 | 1 - (stressed Sharpe / neutral Sharpe) |
| Diversification | 0.10 | Balance across pairs, directions, and families |
| Raw Performance | 0.10 | Normalized Sharpe ratio (capped at 3.0) |

## Ranking Process

1. Each `CandidateRun` from the validation campaign is scored on all dimensions
2. A weighted composite score is computed using `ScorecardWeights`
3. Candidates are sorted by composite score descending
4. The champion is the top-ranked candidate that passes or conditionally passes the deployment gate
5. Challengers are other gate-passing candidates

## Selection Outputs

- **Ranking table**: side-by-side comparison of all candidates
- **Selection report**: champion/challenger/rejected breakdown with reasoning
- **Scorecards**: structured data for each candidate used by the decision memo

## Key Principles

- **Simplicity bias**: Prefer simpler strategies when composite scores are close
- **Fragility penalty**: High fragility (>50%) is a blocking concern
- **Gate integration**: Gate failures override ranking regardless of composite score
- **No manual override**: The ranking is deterministic given the same inputs
