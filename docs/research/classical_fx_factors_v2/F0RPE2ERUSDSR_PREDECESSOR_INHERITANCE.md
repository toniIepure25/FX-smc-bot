# Gate F0-RP-E2E-R-USDSR Predecessor Inheritance

Status: `PREDECESSOR_FAILURE_PRESERVED_NOT_REVERSED`.

Gate `F0RPE2ER_USD_SCHEMA_RECONCILIATION_V1` starts from commit
`f460fe6a2f5c83fee8e06dd0168d983f9bfa70f3`. The predecessor decision remains
`BLOCKED_BY_OFFICIAL_RATE_ADAPTER`. Its blocking adapter remains
`NY_FED_EFFR_V2`, and its failure remains `SOURCE_RESPONSE_SCHEMA_VIOLATION` at
the `RESPONSE_FIREWALL` stage. This gate does not reinterpret that response as
matching the predecessor schema and does not replace the predecessor FAIL.

The single predecessor USD request covered EFFR from 2016-01-04 through
2016-01-08. The HTTP 200 response was rejected atomically. It persisted zero
source snapshots, exposed zero numerical rows to the parser, created zero rate
observation identities and versions, sent zero market requests, and produced
zero economic outcomes.

The predecessor decision, adapter matrix, adapter certification, integrity
audit, prohibited-data audit, reproducibility manifest, and final memo are
pinned by LF-normalized SHA-256 hashes in
`results/gate_f0rpe2erusdsr/predecessor_failure_inheritance.json`.

Scientific protocol lock `F0RPE2ERUSDSR_PROTOCOL_INHERITANCE_V1` preserves the
factor, portfolio, cost, benchmark, inference, selection, replication, rate
provenance, and future-only integrity contracts. Only parser, schema
normalization, adapter, firewall, persistence, and orchestration implementation
may change. No scientific value changes in phases 0-2.
