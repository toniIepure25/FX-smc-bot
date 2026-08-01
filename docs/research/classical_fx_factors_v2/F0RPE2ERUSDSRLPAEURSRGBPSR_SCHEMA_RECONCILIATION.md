# F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR SONIA Schema Reconciliation

Reconciliation ID: `BOE_IUDSOIA_EXPORT_SCHEMA_RECONCILIATION_V1`

Status: `FROZEN_BEFORE_GBP_RATE_VERSION_PERSISTENCE`

The official source series is `IUDSOIA`, mapped to GBP daily Sterling Overnight
Index Average observations. The frozen CSV shape is `DATE,IUDSOIA` with schema
fingerprint `0cabc3dd69e8438ec9acefd96e185571e19c829635034eb9df9e42e75238c8b8`.

Field mapping:

- `DATE` maps to the observation date.
- `IUDSOIA` maps to the official percentage-points-per-annum value, normalized
  as `official value / 100`.

The day count is `ACT/365 Fixed`; the calendar is `London business day`.

Internal constants are allowed for `currency=GBP`, `series_id=IUDSOIA`, and
`publisher=Bank of England` because the request itself is exact and allowlisted.
The official response is not required to expose internal normalized fields such
as `publicationTimestamp`, `effectiveTimestamp`, `revisionIdentifier`, or
`methodologyRegime`.

Legacy SONIA covers observations through `2018-04-20`. Reformed SONIA starts on
`2018-04-23`. The dates `2018-04-21` and `2018-04-22` are weekend dates and are
not synthetic observations.
