# Gate F.0 Final Decision Memo

## Decision

`BLOCKED_BY_RATE_DATA_PROVENANCE`

Gate F.0 stopped before market or rate observation acquisition. The frozen NZD
series, `B2_OVERNIGHT_INTERBANK_CASH_RATE`, is available from the official RBNZ
historical download, but that download does not preserve an original
publication timestamp for every observation. The publisher documents an
approximate update window and notes that some quoted-market observations may
have a one-day lag. That is insufficient for the preregistered point-in-time
contract, and no inferred timestamp or unofficial reconstruction was used.

No development, validation, replication, portfolio selection, or future
handoff result was generated. The implemented factor, portfolio, accounting,
inference, market recovery, and rate recovery engines passed 171 Gate F.0
synthetic tests. The complete repository suite passed 1,118 tests and retained
one pre-existing sealed-Q1 raw-byte hash failure caused by CRLF/LF working-tree
normalization; no Gate F.0 test failed.

## Required statements

This program tested a preregistered family of classical FX factors rather than
SMC-derived rules.

All reported results include executable bid/ask costs and overnight financing.
No empirical performance result was produced in this blocked run.

Development, validation and replication access occurred only in their
preregistered order. None of those empirical partitions was accessed.

The quarantined 2023-2025 interval remained untouched.

Any selected portfolio remains unconfirmed until genuinely future prospective
data satisfy the frozen evidence requirements. No portfolio was selected here.

No result authorizes live-capital deployment.
