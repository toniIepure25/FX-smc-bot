# Gate C.2 — Decision Memo

## Decision: `BLOCKED_BY_DATA_ACCESS`

The runtime integration is complete and verified. The blocking factor is
the lack of real bid/ask historical data, which requires either:
- A successful Dukascopy automated download (network-dependent)
- Manual JForex export
- OANDA API credentials

No strategy alpha claims are made in this gate.

## Gate Summary

| Component | Status |
|-----------|--------|
| Stateful runtime protocol | IMPLEMENTED |
| V2 runtime factory | IMPLEMENTED |
| Intraday backtest engine | IMPLEMENTED |
| Signal → order conversion | IMPLEMENTED |
| Execution event feedback | IMPLEMENTED |
| Cost wiring (swap, commission) | IMPLEMENTED |
| Pair-specific pip arithmetic | FIXED |
| Strategy corrections (max_fvg_bars, pair) | FIXED |
| BidAsk data model | IMPLEMENTED |
| Executable ablations | IMPLEMENTED |
| Dukascopy provider | IMPLEMENTED (untested on real server) |
| OANDA provider | IMPLEMENTED (requires credentials) |
| MT5 importer | IMPLEMENTED |
| Cross-validation utility | IMPLEMENTED |
| End-to-end tests (34) | PASSING |
| Synthetic control campaign | PASSING (deterministic) |
| Real data smoke test | BLOCKED (no data available) |

## Test Results

- **493 tests passing** (459 original + 34 new)
- **0 Ruff errors** on all new and modified files
- **91 warnings** (all pre-existing `datetime.utcnow()` deprecation)
- **Deterministic** synthetic campaign (SHA-verified)

## Commits

1. `feat(alpha): add stateful strategy runtime and V2 factory`
2. `fix(alpha): correct pair-specific pip and strategy semantics`
3. `feat(backtest): add intraday engine with lifecycle reconciliation`
4. `feat(data): add bid/ask model and historical FX providers`
5. `feat(research): add executable ablation framework`
6. `test: add Gate C.2 end-to-end runtime integration tests`
7. `docs: issue Gate C.2 integration and data decision`

## Architecture

### How V2 strategies now reach the engine

```
IntradayBacktestEngine.run(data)
  └── per bar, per pair:
      ├── _process_exits()    → PositionClosedEvent → runtime
      ├── _process_pending()  → OrderFilledEvent → runtime
      ├── _process_swap()     → tracks overnight costs
      └── for each runtime matching pair:
          runtime.on_bar(CausalBarContext)
            → list[OrderIntent]
            → LIMIT Order (next-bar activation)
            → OrderAcceptedEvent → runtime
```

### Lifecycle event flow

```
OrderIntent (strategy) → Order (engine) → Fill → Position → ClosedTrade
    ↓                       ↓               ↓                   ↓
OrderAccepted       (pending in portfolio)  OrderFilled    PositionClosed
    → runtime                                 → runtime      → runtime
```

## Files Added

| File | Purpose |
|------|---------|
| `src/fx_smc_bot/alpha/intraday/runtime.py` | Runtime protocol, event types, CausalBarContext |
| `src/fx_smc_bot/alpha/intraday/factory.py` | V2 runtime factory with config loading |
| `src/fx_smc_bot/backtesting/intraday_engine.py` | V2 intraday backtest engine |
| `src/fx_smc_bot/data/bidask.py` | BidAskBarSeries data model |
| `src/fx_smc_bot/data/historical_providers.py` | Dukascopy, OANDA, MT5 providers |
| `src/fx_smc_bot/research/ablations.py` | Executable ablation framework |
| `tests/test_gate_c2/test_runtime_integration.py` | 34 end-to-end tests |
| `tests/test_gate_c2/helpers.py` | Synthetic data generators |
| `scripts/run_gate_c2_control.py` | Synthetic control campaign |

## Files Modified

| File | Change |
|------|--------|
| `src/fx_smc_bot/alpha/intraday/sweep_reversal.py` | Pair pip fix, max_fvg_bars via DISPLACEMENT_CONFIRMED state |
| `src/fx_smc_bot/alpha/intraday/acceptance_continuation.py` | Pair pip fix |
| `src/fx_smc_bot/alpha/intraday/opening_range.py` | Hardcoded pair fix |
| `src/fx_smc_bot/alpha/intraday/state_machine.py` | Added DISPLACEMENT_CONFIRMED state |

## Unresolved Risks

1. **No real data acquired**: Dukascopy download not attempted (network),
   OANDA credentials not available. This is the primary blocker.
2. **Synthetic zero trades**: Random walks don't produce SMC event sequences.
   Real data is required to verify the full lifecycle with actual signals.
3. **HTF bias**: acceptance_continuation accepts `htf_bias` parameter but
   does not use it. Preserved as documented for future ablation.
4. **Mid-price execution**: Current engine uses mid-price with spread model.
   True bid/ask execution requires `BidAskBarSeries` integration into
   the engine's fill logic.

## Next Steps

```bash
# 1. Attempt Dukascopy data acquisition
python -c "
from fx_smc_bot.data.historical_providers import DukascopyProvider
from fx_smc_bot.config import TradingPair
from datetime import datetime
p = DukascopyProvider()
r = p.download(TradingPair.EURUSD, datetime(2023,6,1), datetime(2023,6,2))
print(f'Rows: {r.rows}, Errors: {r.errors}')
"

# 2. If OANDA credentials available
export OANDA_API_TOKEN="..."
python -c "
from fx_smc_bot.data.historical_providers import OandaProvider
from fx_smc_bot.config import TradingPair
from datetime import datetime
p = OandaProvider()
r = p.download(TradingPair.EURUSD, datetime(2023,6,1), datetime(2023,6,2))
print(f'Rows: {r.rows}')
"

# 3. Full data acquisition gate
python scripts/run_intraday_smc_campaign.py --stage development ...
```
