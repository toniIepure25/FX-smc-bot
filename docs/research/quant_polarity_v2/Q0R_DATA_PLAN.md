# Q.0-R Data Plan

Protocol ID: `Q0R_CLEAN_ROOM_DATA_RECOVERY_PROTOCOL_V1`.

Development acquisition starts from zero for AUDUSD, NZDUSD, USDCAD, and USDCHF
over 2015-01-01 through 2019-12-31. The immutable plan contains 240 pair-months
and 480 instrument-side-month requests. Eight workers are permitted, with five
attempts, HTTP 429 classification, Retry-After support, bounded exponential
backoff, exact temporary paths, hash-before-promotion, and resumable monthly
manifests.

Replication is conditional on a committed nonempty shortlist. Its separate plan
contains 216 pair-months and 432 side-month requests for the six frozen
instruments over 2020-01-01 through 2022-12-31.

The conservative all-stage peak is 11,236,540,416 bytes, certification scratch is
1,195,376,640 bytes, and the safety margin is 10,737,418,240 bytes. At freeze time
53,325,643,776 bytes were free. The estimate uses formulas only and no old-root
inventory.

The primary provider is `dukascopy-node@1.46.4`; the fallback is the previously
parity-certified native Dukascopy BI5 transport. Raw source is Dukascopy BI5
bid/ask, canonical intermediate is UTC M1 bid/ask OHLC, and execution uses
deterministic M5 bid/ask OHLC.
