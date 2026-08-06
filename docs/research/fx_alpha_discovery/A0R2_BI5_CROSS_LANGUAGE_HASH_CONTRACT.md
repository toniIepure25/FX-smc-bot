# A0R2 BI5 Cross-Language Hash Contract

`A0R2_BI5_CROSS_LANGUAGE_AGGREGATE_CONTRACT_V1` compares only aggregate
identities.  It never emits payload rows, prices, timestamp lists, URLs, or
clean-room paths.

Both implementations hash original compressed bytes for `raw_sha256` and use
compact UTF-8 JSON for ordered timestamps and integer OHLC rows. Volume
identity is SHA-256 over the original four-byte big-endian IEEE-754 fields of
included records in source order. Both positive and negative zero volumes are
excluded; non-finite volumes are rejected. Out-of-day and non-monotonic
offsets, and invalid raw OHLC relationships, are reported structurally rather
than repaired.
