# BOJ Final Call-Rate API Schema Reconciliation

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_JPY_SOURCE_RECONCILIATION_V1`

Reconciliation ID: `BOJ_FM01_FINAL_CALL_RATE_API_RECONCILIATION_V1`

Status: `FROZEN_BEFORE_JPY_RATE_VERSION_PERSISTENCE`

The active BOJ API endpoint is `https://www.stat-search.boj.or.jp/api/v1/getDataCode`.

The database is `FM01`. The API series code is `STRDCLUCON`. The display code
`FM01'STRDCLUCON` is provenance only and must not be passed as `code`.

The selected series identity is:

```text
SERIES_CODE:
STRDCLUCON

NAME_OF_TIME_SERIES:
Call Rate, Uncollateralized Overnight, Average (Daily)

UNIT:
percent per annum

FREQUENCY:
DAILY
```

The exact response paths are:

```text
series container:
$.RESULTSET[0]

survey dates:
$.RESULTSET[0].VALUES.SURVEY_DATES

values:
$.RESULTSET[0].VALUES.VALUES
```

`SURVEY_DATES[i]` maps to the observation date. `VALUES[i] / 100` maps to the
annualized decimal rate. The internal series id is
`BOJ_FINAL_UNCOLLATERALIZED_OVERNIGHT_CALL_RATE`, with `ACT/365 Fixed` day
count and `Tokyo business day` calendar.

The BOJ response `DATE`, metadata `LAST_UPDATE`, HTTP Date header and retrieval
timestamp are source provenance only. They are not original historical
publication timestamps.

Schema fingerprint:

```text
3074acf303240eec8333c835ee33b82d19fdf1c8448d9e64c6bb3535b6e66f77
```

No individual call-rate values, payload fragments, rate distributions or
release-file contents are committed by this reconciliation.
