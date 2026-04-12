# BOS-Only USDJPY Final Validation Report

Generated: 2026-04-12T18:47:22.265661

## Executive Summary

**Decision: CONTINUE_PAPER_TRADING** (confidence: low-medium)

BOS-only USDJPY has been evaluated across 27 temporal windows,
4 execution stress scenarios, 5 spread multipliers, and 2 data sources.

## Holdout Performance

- Sharpe: 0.850
- PF: 1.96
- MaxDD: 12.6%
- Trades: 220
- Win%: 29.1%

## OOS Summary

- Mean Sharpe: 1.599
- Std: 2.060
- % positive: 63%
- % above 0.3: 63%
- Worst fold: -0.975
- Best fold: 4.043

## Data Validation

- Yahoo holdout Sharpe: 0.850
- Synth holdout Sharpe: 0.000
- Synth positive: No
- Spread robustness: positive through 3.0x

## Promotion Scorecard

- Score: 8/8
- Gate verdict (revised 25% WR): pass