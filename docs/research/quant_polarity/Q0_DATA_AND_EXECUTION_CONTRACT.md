# Q.0 Data and Execution Contract

Executable bid/ask prices and adverse-first same-bar ordering are mandatory.
Original and inverse variants preserve every source-policy rule except direction.

## Frozen Contract

- **source:** `Dukascopy tick/BI5 bid and ask`
- **canonical:** `UTC M1 bid/ask OHLC`
- **execution:** `deterministic M5 bid/ask OHLC`
- **same_bar:** `adverse-first`

Status: **PASS**
