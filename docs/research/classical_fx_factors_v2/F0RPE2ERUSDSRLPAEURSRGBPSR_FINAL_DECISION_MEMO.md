# Gate F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR Final Decision Memo

Final decision: `BLOCKED_BY_OFFICIAL_RATE_ADAPTER`

The predecessor Bank of England HTTP 403 blocker remains valid and unchanged.
It is preserved as a historical result for `BOE_SONIA_V2`.

The active SONIA adapter now uses the officially documented Bank of England
IADB machine-readable export contract. The CSV route includes `csv.x=yes`; the
selected `CSVF=TN` code is represented as `TABULAR_NO_TITLES`, not columnar.
No browser-protection mechanism was bypassed.

Internal normalized fields were not represented as literal IADB fields. Legacy
and reformed SONIA were separated at the April 2018 methodology boundary:
`2018-04-20` is the final legacy observation and `2018-04-23` is the first
reformed observation. Benchmark publication was kept separate from database
ingestion and source retrieval.

Historical manifests were verified against their recorded Git commits rather
than the current working tree. Development, validation and replication were not
accessed because the remaining adapter continuation stopped fail-fast at
`RBA_CASH_RATE_V2` with `OFFICIAL_ENDPOINT_HTTP_STATUS_404`.

The 2023-2025 interval remained excluded from all calculations and decisions.
NZD and NZDUSD remained inaccessible. No result authorizes live-capital
deployment.
