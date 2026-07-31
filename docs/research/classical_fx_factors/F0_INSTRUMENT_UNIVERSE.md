# Gate F.0 Instrument Universe

Program `FX_CLASSICAL_RISK_PREMIA_V1` uses the following immutable instrument
universe:

```text
EURUSD
GBPUSD
AUDUSD
NZDUSD
USDJPY
USDCAD
USDCHF
EURJPY
GBPJPY
AUDJPY
```

The corresponding immutable currency set is:

```text
USD
EUR
GBP
AUD
NZD
JPY
CAD
CHF
```

Pair notation is base currency followed by quote currency. Long pair exposure
is long base and short quote; short pair exposure reverses those legs.

No instrument or currency may be added, removed, substituted, or selected
after outcomes become available. Missing data do not permit universe changes.
The previous SMC and quant-polarity lineage seals remain closed, and no prior
candidate membership affects this universe.

This is an ex-ante universe freeze and contains no performance result.
