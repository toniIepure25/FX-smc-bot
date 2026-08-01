# BOJ Predecessor Block Inheritance

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_JPY_SOURCE_RECONCILIATION_V1`

Status: `PREDECESSOR_BLOCK_PRESERVED_NOT_REVERSED`

The predecessor gate ended with `BLOCKED_BY_OFFICIAL_RATE_ADAPTER`.

The preserved blocker is:

```text
adapter_id:
BOJ_FINAL_UO_CALL_V2

currency:
JPY

internal series identity:
FM01'STRDCLUCON

failed endpoint:
https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2

failure:
OFFICIAL_ENDPOINT_UNEXPECTED_CONTENT_TYPE_TEXT_HTML

failure stage:
OFFICIAL_SCHEMA_PREFLIGHT
```

The predecessor did not persist a JPY snapshot, parse a JPY numerical row,
create a JPY `RateVersion`, send a market-provider request, or compute an
economic outcome.

The certified USD, EUR, GBP and AUD adapters remain inherited unchanged:
`NY_FED_EFFR_V3`, `ECB_EONIA_ESTR_V3`, `BOE_SONIA_V3` and
`RBA_CASH_RATE_V3`.
