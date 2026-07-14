# Gate C.3 — Bid/Ask Engine Validation

## Execution Semantics Implemented

### Entry Rules (BidAskFillEngine)

| Order | Direction | Fill Condition | Fill Price Base |
|-------|-----------|---------------|-----------------|
| LIMIT | LONG | `ask_low <= limit_price` | limit_price |
| LIMIT | SHORT | `bid_high >= limit_price` | limit_price |
| MARKET | LONG | immediate | ask_open |
| MARKET | SHORT | immediate | bid_open |
| STOP | LONG | `ask_high >= stop_price` | stop_price |
| STOP | SHORT | `bid_low <= stop_price` | stop_price |

### Exit Rules

| Direction | SL Trigger | TP Trigger | Mark-to-Market |
|-----------|-----------|-----------|----------------|
| LONG | `bid_low <= SL` | `bid_high >= TP` | bid |
| SHORT | `ask_high >= SL` | `ask_low <= TP` | ask |

### Spread Handling

- **BID_ASK_NATIVE mode**: No synthetic spread added. `NativeBidAskSlippage`
  returns `spread_cost=0`. Historical spread is implicit in bid/ask prices.
- **MID_PRICE_EXPLORATORY_MODE**: `FixedSpreadSlippage` adds synthetic half-spread
  to each side. Labeled as exploratory only.

### Cost Decomposition

For every closed trade:
```
net_pnl = gross_pnl - commission_cost + swap_cost
```

In bid/ask mode, `spread_cost` from the slippage model is 0 because
the spread is already embedded in the fill prices. The
`bid_ask_execution_effect` field records the difference between
ideal mid-price PnL and actual bid/ask PnL.

### Same-Bar Ambiguity

Conservative policy (default): SL checked first when both SL and TP
are within the bar's range. Bid/ask mode uses the correct price side
for each check.

## Tests

28 new tests covering:
- Long limit using ask_low
- Short limit using bid_high
- Long exit using bid
- Short exit using ask
- Market orders using correct side
- No synthetic spread on bid/ask data
- Cost decomposition equation
- Execution mode labeling
- Dukascopy JPY/non-JPY scaling
- OANDA request construction (no count)
- MT5 timezone conversion
- Bid/ask resampling independence
