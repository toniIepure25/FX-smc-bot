# Gate C.3 — Decision Memo

## Decision: `BLOCKED_BY_DATA_ACCESS`

The bid/ask execution engine and provider infrastructure are complete
and verified. The blocking factor remains real historical FX data
acquisition, which requires either:
- Successful Dukascopy automated download (network-dependent)
- Manual JForex historical data export
- OANDA API credentials for secondary source

No profitability metrics were calculated in this gate.

## What Was Built and Fixed

### Bid/Ask Execution Engine
- `BidAskFillEngine` with correct price-side semantics
- `NativeBidAskSlippage`: zero synthetic spread on bid/ask data
- `IntradayBacktestEngine` accepts both `BarSeries` and `BidAskBarSeries`
- Execution mode labeling: `BID_ASK_NATIVE` vs `MID_PRICE_EXPLORATORY_MODE`
- Unified `_close_position` with `bid_ask_execution_effect` tracking
- Cost decomposition: `net_pnl = gross_pnl - commission + swap`

### Provider Bugs Fixed
| Provider | Bug | Impact | Fix |
|----------|-----|--------|-----|
| Dukascopy | Universal `/100000` scaling | USDJPY ≈ 0.001 | Per-pair InstrumentMeta |
| OANDA | `from+to+count` together | API violation | Removed count, time-window batching |
| MT5 | broker_timezone ignored | Wrong UTC timestamps | zoneinfo conversion |

### New Components
- `BidAskFillEngine` in `execution/fills.py`
- `NativeBidAskSlippage` in `execution/slippage.py`
- `bidask_resampling.py`: Independent bid/ask OHLC resampling
- `InstrumentMeta` model for per-pair price scaling
- `MT5ImportResult` metadata with price-type tracking
- Acquisition CLI (`scripts/acquire_fx_history.py`)

### Test Results
- **521 tests passing** (493 previous + 28 new Gate C.3)
- **0 Ruff errors** on all modified files
- **91 warnings** (pre-existing `datetime.utcnow()` deprecation)

## Gate Scorecard

| Component | Status |
|-----------|--------|
| Bid/ask fill engine | VERIFIED |
| Long limit → ask_low | VERIFIED |
| Short limit → bid_high | VERIFIED |
| Long exit → bid | VERIFIED |
| Short exit → ask | VERIFIED |
| No synthetic spread on bid/ask | VERIFIED |
| Cost reconciliation | VERIFIED |
| Execution mode labeling | VERIFIED |
| Dukascopy scaling fixed | VERIFIED |
| OANDA batching fixed | VERIFIED |
| MT5 timezone fixed | VERIFIED |
| Bid/ask resampling | VERIFIED |
| Acquisition CLI | IMPLEMENTED |
| Real data acquired | BLOCKED |
| Data quality certification | BLOCKED |
| Cross-provider validation | BLOCKED |
| Event smoke test | BLOCKED |
| Split freeze | BLOCKED (awaiting data) |

## Commits

1. `feat(execution): add native bid/ask fill engine and slippage`
2. `feat(backtest): integrate BidAskBarSeries into intraday engine`
3. `fix(data): correct Dukascopy scaling and provider semantics`
4. `feat(data): add bid/ask resampling and acquisition CLI`
5. `test: add Gate C.3 bid/ask and provider tests`
6. `docs: issue Gate C.3 decision memo`

## Unresolved Risks
1. **No real data**: Dukascopy download untested on live server
2. **OANDA credentials**: Required for secondary source
3. **Streaming acquisition**: Multi-year download not yet chunked/streamed
4. **Weekend handling**: Not yet differentiated from network errors
5. **Cross-provider validation**: Cannot verify without secondary source

## Holdout Access
The final holdout was not touched during this gate. No profitability
metrics were calculated. No strategy PnL was inspected.
