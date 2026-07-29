# P0-R-DCR-A1A Data Requirement Amendment

Amendment: `P0RDCR_DATA_REQUIREMENT_AMENDMENT_V1`

Status: `FROZEN_BEFORE_DATA_ACCESS`

Hash: `e6b93c1ef826ce0f2338b965ecc37b547b4be5da10e835748b7b2667747f9c25`

This amendment was frozen before market-data path enumeration or economic outcomes.

## Exact Contract

- Source: Dukascopy tick/BI5 bid and ask.
- Canonical intermediate: UTC M1 bid/ask OHLC.
- Execution: deterministic M5 bid/ask OHLC, adverse-first.
- Warm-up: 500 M5 bars using `max(500, 46 + 288)`.
- Exit: earliest SL, TP, originating-session cutoff, FX-week close, or final bar.
- Sessions: 08:00 inclusive to 11:00 exclusive in the named IANA timezone.
- FX week: Sunday 17:00 to Friday 17:00 America/New_York.
- EURUSD and GBPUSD: strategy required.
- USDJPY: optional diagnostic; not required for execution, benchmarks, or tiers.

No candidate parameter, signal, SL, TP, order expiry, estimand, benchmark, or Tier criterion is changed.
