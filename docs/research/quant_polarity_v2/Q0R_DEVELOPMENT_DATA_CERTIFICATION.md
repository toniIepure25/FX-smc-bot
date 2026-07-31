# Q.0-R Development Data Certification

Dataset freeze ID: `FX_QUANT_POLARITY_DEVELOPMENT_2015_2019_V2`.

The clean-room acquisition completed all 480 frozen instrument-side-month
partitions from zero. It promoted 14,910,838 raw side rows. Transient provider
failures were resolved over resumable passes from 21, to 5, to zero unresolved
partitions; no hash-valid completed partition was downloaded again.

All 240 pair-months passed identity, date containment, JSON container, nonzero,
deterministic parsing, UTC normalization, monotonicity, duplicate, finite positive
price, bid/ask spread, M1, M5, session-time basis, manifest, and three-run parity
checks. Missing, failed, and successful zero-row counts are all zero.

The frozen canonical dataset contains 7,455,419 M1 rows and 1,494,623 M5 rows.
Its compact manifest hash is
`246864624e1aa66303b5eb7f5e818186f6d86b290fb79952e36ea093f34715af`.
Raw and canonical files remain outside Git; only aggregate certification and
cryptographic hashes are committed.
