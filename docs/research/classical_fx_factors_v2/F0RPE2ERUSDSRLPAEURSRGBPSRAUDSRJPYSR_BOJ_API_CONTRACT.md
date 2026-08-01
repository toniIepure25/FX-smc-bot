# BOJ API V1 Final Call-Rate Contract

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_JPY_SOURCE_RECONCILIATION_V1`

Contract ID: `BOJ_TIME_SERIES_API_V1_FINAL_CALL_RATE_CONTRACT_V1`

## Active Endpoint

```text
https://www.stat-search.boj.or.jp/api/v1/getDataCode
```

The predecessor endpoint remains preserved only as a blocker:

```text
https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2
```

`BOJ_FINAL_UO_CALL_V3` must not use the predecessor CGI route.

## Required Parameters

```text
format=json
lang=en
db=FM01
code=STRDCLUCON
startDate=<YYYYMM>
endDate=<YYYYMM>
```

The BOJ API separates the database and series code. The full display code
`FM01'STRDCLUCON` may be documented for traceability, but it must not be passed
as the API `code` value.

The active request must not send `resultType=final`, ISO day bounds, or
`code=FM01'STRDCLUCON`.

## Selected Series

The selected series is the final weighted-average uncollateralized overnight
call rate:

```text
database:
FM01

API series code:
STRDCLUCON

frequency:
DAILY

currency:
JPY

unit:
percent per annum
```

Provisional call rates, high/low rates, volumes, collateralized call rates,
policy rates, monthly conversions and frequency-converted rates are rejected.

## Publication And Correction Semantics

The final rate for Tokyo business day `T` is published around 10:00
`Asia/Tokyo` on the next Japan business day. Because “around 10:00” is not an
exact timestamp, the active adapter must use a publication-day envelope:

```text
actual_publication_timestamp:
null

publication_evidence_kind:
PUBLICATION_DAY_ENVELOPE

publication_lower_bound:
00:00 Asia/Tokyo on publication day

publication_upper_bound:
00:00 Asia/Tokyo on the following calendar day, exclusive

strategy availability:
first frozen 17:05 America/New_York execution strictly after publication_upper_bound
```

BOJ response `DATE`, metadata `LAST_UPDATE`, HTTP retrieval time and local file
metadata are provenance only. They are not historical publication timestamps.

Current final history requires an official correction registry before accepted
numerical observations may be persisted.
