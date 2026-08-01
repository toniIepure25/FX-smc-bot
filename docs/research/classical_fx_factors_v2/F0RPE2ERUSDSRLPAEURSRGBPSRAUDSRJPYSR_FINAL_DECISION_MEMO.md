# Gate F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR-AUDSR-JPYSR Final Decision

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_JPY_SOURCE_RECONCILIATION_V1`

Decision: `BLOCKED_BY_BOJ_REVISION_PROVENANCE`

The predecessor BOJ HTML-response blocker remains valid and unchanged. The
predecessor blocking adapter was `BOJ_FINAL_UO_CALL_V2`; it used the legacy
interactive-search CGI endpoint and failed at official schema preflight with
`OFFICIAL_ENDPOINT_UNEXPECTED_CONTENT_TYPE_TEXT_HTML`. No predecessor JPY
snapshot, JPY row, JPY `RateVersion`, market request or portfolio result was
created.

The active reconciliation uses the official BOJ API V1 `getDataCode` endpoint:

```text
https://www.stat-search.boj.or.jp/api/v1/getDataCode
```

The API database was `FM01` and the API series code was `STRDCLUCON`. The
database prefix and apostrophe were not passed as part of the `code` parameter.
The display code `FM01'STRDCLUCON` remains provenance text only.

Only the final uncollateralized overnight call rate was selected. The
provisional rate was rejected and was not used.

The BOJ API response `DATE`, metadata `LAST_UPDATE`, HTTP Date header and local
retrieval metadata were treated as source provenance only. They were not used as
historical benchmark publication timestamps. No exact `10:00` publication
timestamp was invented; the reconciliation uses a conservative publication-day
envelope.

The current BOJ API returns current final history. The gate audited BOJ notices
of changes and corrections and searched for historical final-result release
pages for `2010-01-01` through `2022-12-31`. A sufficiently complete official
correction registry could not be established. Because corrected-value leakage
could not be ruled out for current final history, no JPY numerical observations
were persisted and no JPY V3 adapter was implemented.

Development, validation and replication were not accessed. The 2023-2025
interval remained excluded from every calculation and decision. NZD and NZDUSD
remained inaccessible.

No result authorizes paper trading, live-capital deployment, a pull request or a
merge.
