# Gate F0-RP Rate Provenance Amendment

## Freeze

Amendment ID: `F0_RATE_PROVENANCE_AMENDMENT_V1`

Status: `FROZEN_BEFORE_ANY_MARKET_OR_RATE_OBSERVATION_ACCESS`

Selected route: `OUTCOME_BLIND_NZD_EXCLUSION`

Route A was preferred and audited first. It was rejected because the official
record for the unscheduled 16 March 2020 OCR reduction does not preserve an
original publication time or provide a deterministic release-time rule for the
exceptional decision. No scheduled time, same-day time, next-day time, or B2 lag
was inferred.

## Amended Universe

The primary instrument universe is EURUSD, GBPUSD, AUDUSD, USDJPY, USDCAD,
USDCHF, EURJPY, GBPJPY, and AUDJPY. The currency set is USD, EUR, GBP, AUD, JPY,
CAD, and CHF.

NZD is `EXCLUDED_BY_OUTCOME_BLIND_RATE_PROVENANCE_AMENDMENT`. NZDUSD is
`EXCLUDED_FROM_PRIMARY_INSTRUMENT_UNIVERSE`. No NZD observation, NZD rate, or
NZDUSD market request is authorized after this amendment.

## Scientific Compatibility

The six-candidate factor family, factor definitions, lookbacks, fixed risk
weights, portfolio construction, volatility target, covariance method,
no-trade band, leverage and currency limits, costs, benchmarks, estimands,
selection criteria, and temporal partitions are unchanged. Volatility targeting
and covariance estimation operate on the amended nine-instrument universe.

The strategy uses a rate only after the later of its official publication and
effective timestamps. Later revisions are not backfilled. Missing rates are not
interpolated; when no legally available official rate exists, the prescribed
action is no position change with a recorded reason.

The machine-readable amendment contains the complete amended registry,
availability envelopes, calendars, day counts, transitions, missing-rate rule,
official evidence, inherited freeze hashes, and proof that no outcome existed.
