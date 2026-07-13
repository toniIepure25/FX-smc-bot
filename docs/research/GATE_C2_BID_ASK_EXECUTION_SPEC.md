# Gate C.2 — Bid/Ask Execution Specification

## Data Model

### BidAskBarSeries

```
bid_open  bid_high  bid_low  bid_close
ask_open  ask_high  ask_low  ask_close
volume    tick_volume
```

Derived properties computed on demand:
```
mid_open  = (bid_open + ask_open) / 2
mid_high  = (bid_high + ask_high) / 2
mid_low   = (bid_low + ask_low) / 2
mid_close = (bid_close + ask_close) / 2
spread_open  = ask_open - bid_open
spread_close = ask_close - bid_close
```

### Invariants

| Invariant | Validation |
|-----------|-----------|
| ask_open >= bid_open | Per-bar check |
| ask_close >= bid_close | Per-bar check |
| bid_close > 0 | Per-bar check |
| Valid bid OHLC | H >= max(O,C), L <= min(O,C) |
| Valid ask OHLC | H >= max(O,C), L <= min(O,C) |

**Edge case**: Separate bid and ask extrema within a bar mean that
`ask_high >= bid_high` is NOT guaranteed because each side's high may
occur at different ticks. This is documented but not flagged as an error.

## Execution Side Rules

| Action | Price Side |
|--------|-----------|
| Long entry | Ask (buy at ask) |
| Long exit | Bid (sell at bid) |
| Short entry | Bid (sell at bid) |
| Short exit | Ask (buy at ask) |

The current `IntradayBacktestEngine` uses mid-price `BarSeries` with
spread applied via `SlippageModel`. When `BidAskBarSeries` data is
available, the engine should use the correct side directly.

## Mid-Only Compatibility Mode

When only mid-price data is available:
- Spread is applied via `FixedSpreadSlippage` or `VolatilitySlippage`
- Data is explicitly labeled as mid-only
- Cannot receive final-data certification for research conclusions
- Acceptable for exploratory analysis only

## Resampling Rules

Bid and ask channels are resampled independently:
- bid_open = first bid tick in period
- bid_high = max of all bid ticks in period
- bid_low = min of all bid ticks in period
- bid_close = last bid tick in period
- (same for ask side)

Mid-price is NOT resampled — it is derived from resampled bid/ask.
