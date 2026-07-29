# Gate P.0-R-DCR-A1A Final Decision

## Decision

`P0RDCRA1A_ECONOMIC_AUDIT_COMPLETED_NO_FORWARD_TEST`

The outcome-blind amendment was frozen before market-data access. The permitted
2015-2022 dataset was recovered and certified, all four frozen candidates were
executed, and the frozen economic and alpha audit completed. Mechanical
application of the original eligibility rules assigned every candidate to Tier
C. No primary or secondary candidate was selected, and no prospective protocol,
forward configuration, or handoff was created.

## Frozen Contracts

- Amendment: `P0RDCR_DATA_REQUIREMENT_AMENDMENT_V1`, hash
  `e6b93c1ef826ce0f2338b965ecc37b547b4be5da10e835748b7b2667747f9c25`.
- Source: Dukascopy tick/BI5 bid and ask to UTC M1 bid/ask OHLC, then
  deterministic M5 bid/ask OHLC with adverse-first intrabar execution.
- Warm-up: `500` M5 bars from `max(500, 46 + 288)`; no pre-2015 request and no
  trade before warm-up completion.
- Sessions: London and New York `08:00` inclusive to `11:00` exclusive in their
  IANA timezones. The FX week is Sunday 17:00 through Friday 17:00
  `America/New_York`.
- Exit horizon: earliest stop, target, originating-session cutoff, FX-week
  safety close, or final certified bar. Overnight, rollover, and weekend carry
  are prohibited.
- Instruments: EURUSD and GBPUSD are required; USDJPY is optional diagnostic
  only.

## Certified Execution

The dataset freeze is `FX_SMC_STRATEGY_ALPHA_PERMITTED_2015_2022_V2`, hash
`3065b7f507afac9759ae5b319a7550842e24df6e25fd258f2f02c25839dd301a`.
All 192 pair-months were certified, containing 5,969,252 M1 rows and 1,196,691
M5 rows. Execution produced 3,991 accepted trades across 32 candidate-year
units. Row-level ledgers remain local and ignored.

## Economic Result

| Candidate | Trades | Mean net R | Day-cluster 95% CI | PF | Sharpe | Tier |
|---|---:|---:|---:|---:|---:|---|
| Sweep reversal | 202 | 0.0106 | [-0.0747, 0.0995] | 1.0485 | 0.2803 | C |
| Acceptance continuation | 2,676 | -0.1581 | [-0.1989, -0.1191] | 0.6975 | -3.1012 | C |
| London opening range | 360 | -0.0811 | [-0.1465, -0.0134] | 0.7076 | -2.0612 | C |
| New York opening range | 753 | -0.0314 | [-0.0872, 0.0233] | 0.8975 | -0.6831 | C |

No matched-random alpha survived multiplicity adjustment: every Holm-adjusted
value is `1.0`. Sweep reversal was positive only at base cost and became
negative at 1.5x cost; all candidates failed leave-one-year-out positivity.

## Integrity And Quality

All ten sealed-holdout access flags remain false. The inherited tracked
15m/1h/4h CSV files are classified
`LEGACY_TRACKED_NOT_AUTHORIZED_FOR_STRATEGY_ALPHA_V1` and were not used for
outcomes. No raw data, canonical data, provider payload, or row-level ledger is
tracked by this gate.

The final quality gate passed: 859 Python tests, targeted Ruff and mypy, two
Node tests, and `git diff --check`. Broad research static analysis introduced
zero new Ruff and zero new mypy findings relative to `origin/main`.
