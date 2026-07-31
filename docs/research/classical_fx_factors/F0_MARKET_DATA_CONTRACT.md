# Gate F.0 Market-Data Contract

Applies only to `FX_CLASSICAL_RISK_PREMIA_V1`. Prior SMC and quant-polarity
lineages remain sealed and provide no market data to this program.

## Frozen source and transformations

| Field | Frozen value |
|---|---|
| Provider | Dukascopy BI5 bid and ask |
| Canonical intermediate | UTC M1 bid/ask OHLC |
| Execution bars | Deterministic M5 bid/ask OHLC |
| Daily research close | Final certified M5 bar immediately preceding 17:00 `America/New_York` |
| Daily execution | First certified executable M5 quote at or after 17:05 `America/New_York` |
| Same-bar ambiguity | Adverse-first |

M1 and M5 construction must be deterministic, timezone-aware, and independently
certified. Bid and ask remain separate through execution and accounting; a
synthetic mid may be used for signal measurement only when explicitly derived
from the certified pair.

For trading day `t`, every signal, volatility estimate, covariance input, rate,
and portfolio decision must have been available before the execution timestamp
for `t`. Signals use observations through `t-1` unless a stricter rule is stated.
No price is forward-filled.

Positions may be held overnight, so financing is mandatory. No weekend position
may remain open beyond Friday 16:55 `America/New_York`. Missing required market
input produces `NO_POSITION_CHANGE_WITH_RECORDED_REASON`.

Provider requests and file access must pass the clean-room capability checks.
Raw BI5, M1/M5 bars, and row-level execution data remain local and uncommitted.
This contract states the protocol only; it does not claim data provenance or
certification.
