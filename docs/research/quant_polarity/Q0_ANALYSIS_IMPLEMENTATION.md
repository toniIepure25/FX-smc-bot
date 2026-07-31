# Q.0 Analysis Implementation Freeze

Status: `FROZEN_BEFORE_DEVELOPMENT_OUTCOME_EXECUTION`

This document removes implementation degrees of freedom left by the aggregate
estimand preregistration. It does not change a candidate, threshold, metric, or
selection criterion.

## Daily factor construction

- Daily close is the final certified M5 mid close of each UTC trading day.
- Daily return is the simple close-to-close percentage return.
- FX time-series momentum is the cross-instrument mean of current daily return
  multiplied by the prior-day sign of the trailing 60-trading-day return.
- Short-term reversal is the cross-instrument mean of current daily return
  multiplied by the negative sign of the previous daily return.
- Broad USD direction is the equal-weight mean of contemporaneous daily returns,
  with `AUDUSD` and `NZDUSD` signs inverted and `USDCAD` and `USDCHF` unchanged.
- Realized volatility is the cross-instrument mean absolute daily return.
- The factor regression includes an intercept and uses Newey-West HAC lag 5.

## Matched-random benchmark

Each accepted candidate trade is matched within the same instrument and year on
session, UTC weekday, ATR quartile, executable-spread quartile, direction, and
holding opportunity. The random entry must permit the same holding-bar count to
finish inside the same amended session and cannot equal the candidate entry.
Selection uses seed `1729` combined with candidate, signal, year, and instrument.

## Model chronology

Calendar years 2016-2019 are outer forward test folds. Calendar year 2015 is the
strictly prior burn-in because no pre-2015 observations are authorized. No fitted
prediction from 2015 is included in meta-candidate performance. Deterministic
inverse candidates remain evaluated over all five development years.

## Cost stress

Base execution uses native bid/ask fills, fixed commission, and fixed slippage.
The 1.5x and 2.0x scenarios scale only contemporaneous executable spread and
slippage. Commission remains fixed. Round-trip spread cash is one half of the sum
of entry-bar and exit-bar M5 close spreads, multiplied by units.

## Integrity

All definitions above were encoded and documented before development signal,
prediction, order, trade, benchmark, or PnL generation. Row-level artifacts remain
local and ignored.
