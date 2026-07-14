# Gate C.3R — Parser Cross-Check

## Purpose

Verify that `dukascopy-node` output matches expectations before
trusting it for full acquisition.

## Test Conditions

- Pairs: EURUSD, USDJPY
- Date: 2023-06-15 (Thursday, full trading day)
- Timeframe: M1
- Sides: bid, ask

## Results

### EURUSD

| Metric | Bid | Ask |
|--------|-----|-----|
| Row count | 1,415 | 1,415 |
| First open | 1.08427 | 1.08430 |
| First spread | 0.00003 (0.3 pips) |  |
| Price range | 1.069–1.084 | Plausible |
| Ask < Bid | None | — |
| Timestamps | UTC | — |

### USDJPY

| Metric | Bid |
|--------|-----|
| Row count | 1,439 |
| First open | 139.968 |
| JPY scaling | Correct (values ~140, not ~0.001 or ~14000) |
| Ask < Bid | None |
| Timestamps | UTC |

## Weekend Handling

Weekend days produce 0 rows as expected. The library correctly
returns empty arrays for non-trading periods.

## Verdict

**PASS** — dukascopy-node produces correctly scaled, UTC-timestamped
M1 OHLC data with genuine bid/ask separation.
