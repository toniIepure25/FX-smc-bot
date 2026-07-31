# Gate F.0 Rate and Financing Contract

This contract belongs to `FX_CLASSICAL_RISK_PREMIA_V1` and does not reuse the
closed SMC or quant-polarity lineages.

## Required point-in-time registry

The machine-readable registry must resolve each semantic identifier to an
official source before any rate acquisition:

| Currency | Required series | Authoritative publisher | Day count |
|---|---|---|---|
| USD | Effective Federal Funds Rate (EFFR) | Federal Reserve Bank of New York | ACT/360 |
| EUR | EONIA, followed by Euro short-term rate (ESTR) | Official benchmark administrator / ECB | ACT/360 |
| GBP | Sterling Overnight Index Average (SONIA) | Bank of England | ACT/365 |
| JPY | TONAR / uncollateralized overnight call rate | Bank of Japan | ACT/365 |
| AUD | Interbank overnight cash rate | Reserve Bank of Australia | ACT/365 |
| NZD | Official overnight interbank cash rate | Reserve Bank of New Zealand | ACT/365 |
| CAD | Target for the overnight rate (`V39079`) | Bank of Canada | ACT/365 |
| CHF | Swiss Average Rate Overnight (SARON) | SIX benchmark administrator | ACT/360 |

For every series and transition, the registry must freeze: exact external series
identifier, publisher, economic meaning, observation date, original publication
timestamp, effective timestamp, day-count convention, missing-value rule, and
predecessor/successor mapping. EUR must explicitly document the EONIA-to-ESTR
transition. The CAD target series is used for the complete frozen interval so
that no retrocalculated pre-administration CORRA history enters the strategy.
Any administrator or methodology transition must retain original point-in-time
availability.

No reconstructed unofficial series is permitted. An official public mirror is
acceptable only when it preserves publication or vintage timestamps. A value
becomes strategy-eligible at the later of its original publication and effective
timestamps. Official values may then be carried forward until the next official
observation; backfilling before original publication is forbidden.

## Financing

For long base/short quote exposure:

```text
daily financing return =
    (base overnight rate - quote overnight rate - broker markup)
    * applicable day-count fraction
```

For short base/long quote exposure, reverse the rate differential while retaining
the financing markup as a cost. The financed calendar-day count must reflect
actual Wednesday or provider-specific multi-day rollover.

Frozen annualized broker markups are `0.50%` (base), `1.00%` (stress_1), and
`1.50%` (stress_2). Financing return and markup cost must be recorded separately
and reconciled to NAV.

Complete point-in-time provenance is a precondition, not a claimed result here.
If it cannot be established for every required currency and interval, adjudicate
`BLOCKED_BY_RATE_DATA_PROVENANCE`; carry and financing may not be omitted.
