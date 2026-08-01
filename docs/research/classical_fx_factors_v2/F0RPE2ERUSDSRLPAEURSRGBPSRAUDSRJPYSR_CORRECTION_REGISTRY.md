# BOJ Final Call-Rate Correction Registry

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_JPY_SOURCE_RECONCILIATION_V1`

Registry ID: `BOJ_FINAL_CALL_RATE_CORRECTION_REGISTRY_V1`

Status: `BLOCKED_INCOMPLETE_OFFICIAL_CORRECTION_REGISTRY`

Decision consequence: `BLOCKED_BY_BOJ_REVISION_PROVENANCE`

Authorized interval: `2010-01-01` through `2022-12-31`.

The official BOJ API V1 identity, database, final call-rate series metadata,
response schema, field mapping and conservative publication-day envelope were
certified before numerical persistence.

The remaining point-in-time problem is revision provenance. The current BOJ API
returns current final history. The gate therefore required an official
correction registry capable of distinguishing uncorrected current values from
values that became available only after an official correction-publication
envelope.

Official sources checked:

```text
Current call money market page:
https://www.boj.or.jp/en/statistics/market/short/mutan/index.htm

Uncollateralized overnight call-rate explanation:
https://www.boj.or.jp/en/statistics/outline/exp/exmutan.htm

Notices by year:
https://www.boj.or.jp/en/statistics/outline/notice_<YYYY>/index.htm
for YYYY = 2010 through 2022

Historical final-result release page patterns:
https://www.boj.or.jp/en/statistics/market/short/mutan/d_release/md/<YYYY>/index.htm
https://www.boj.or.jp/en/statistics/market/short/mutan/<YYYY>/index.htm
for YYYY = 2010 through 2022
```

The notices-by-year pages were reachable for the authorized years and yielded
candidate call-money or money-market notices. The tested historical final-result
release page patterns for 2010 through 2022 did not locate an official archive
that is sufficient to reconstruct point-in-time final-result availability.

Candidate notices identified:

```text
2013:
Alterations in the "Amounts Outstanding in Short-term Money Market /
Certificates of Deposit Outstanding"

2016:
Release of "Call Money Market Data"

2019:
Changes in the Format of "Amounts Outstanding in the Call Money Market"

2020:
Changes in the Format of "Call Money Market Data"
```

These candidates are not a complete official value-correction registry for the
selected final uncollateralized overnight call-rate series over 2010 through
2022. They do not certify the count of value-changing corrections, the affected
observation dates, original final-release publication days, correction
publication days, or corrected-value strategy-availability envelopes required by
the gate.

Correction count: `NOT_CERTIFIABLE`

Value-changing correction completeness: `NOT_CERTIFIABLE`

Original official vintages available: `false`

Corrected-value backward leakage ruled out: `false`

No BOJ official payloads, call-rate values, source snapshots, parsed JPY rows or
JPY `RateVersion` records are committed by this registry.

Fail-closed outcome:

```text
BLOCKED_BY_BOJ_REVISION_PROVENANCE
```
