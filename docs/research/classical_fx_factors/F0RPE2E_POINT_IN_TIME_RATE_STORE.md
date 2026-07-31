# Gate F0-RP-E2E Point-In-Time Rate Store

The local SQLite schema is `F0RPE2E_RATE_VINTAGE_STORE_V2`. It stores immutable
source snapshots, ingestion runs, series identities, observation identities,
versions, availability events, certification results, dataset freezes, and
daily aligned panels.

Queries require both an explicit strategy timestamp and dataset freeze. A
freeze pins exact version and certification identities; later revisions or
certifications cannot change an earlier replay. Only passing, frozen versions
whose observation date and maximum publication/effective availability are not
later than the strategy timestamp can be returned.

Regression tests cover initial publication, same-day and later revisions,
publication/effective ordering, weekend and holiday carry, missing values,
replay, duplicate conflict, parser-version conflict, freeze pinning, snapshot
request binding, direct SQLite mutation, and future-observation lookahead.
Official row-level rates were not persisted in this gate run.
