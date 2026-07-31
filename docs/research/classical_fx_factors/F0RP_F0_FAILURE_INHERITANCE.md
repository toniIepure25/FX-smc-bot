# Gate F0-RP F0 Failure Inheritance

## Status

`F0_BLOCK_PRESERVED_NOT_REVERSED`

Gate F0 remains finally blocked by `BLOCKED_BY_RATE_DATA_PROVENANCE`. Its
blocking currency remains NZD and its blocking series remains
`B2_OVERNIGHT_INTERBANK_CASH_RATE`.

The original official B2 historical download did not preserve an original
publication timestamp for each observation. The documented approximate update
window and possible lag did not satisfy the frozen point-in-time contract, and
no timestamp was inferred.

Before Gate F0-RP began, the nine required original artifacts were hashed from
the clean checkout and matched their tracked contents. The original decision,
registries, certifications, quality record, safety audits, reproducibility
manifest, and final memo were not edited.

The inherited record states that zero market provider requests and zero rate
provider requests were sent. No market or rate observations were loaded, and no
development, validation, or replication outcome was generated.
