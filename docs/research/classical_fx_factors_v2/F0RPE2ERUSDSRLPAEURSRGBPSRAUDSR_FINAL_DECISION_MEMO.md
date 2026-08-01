# Gate F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR-AUDSR Final Decision Memo

Final decision: `BLOCKED_BY_OFFICIAL_RATE_ADAPTER`

The predecessor AUD blocker remains preserved and unchanged. The failed
`RBA_CASH_RATE_V2` endpoint
`https://www.rba.gov.au/statistics/cash-rate/cash-rate.json` remains recorded as
`OFFICIAL_ENDPOINT_HTTP_STATUS_404`, with no predecessor AUD snapshot, row,
market request or economic result reclassified.

This gate replaced the nonexistent active AUD source with the official RBA
Statistical Table F1 contract. The certified AUD adapter is
`RBA_CASH_RATE_V3`, using the actual `Interbank Overnight Cash Rate` series
code `FIRMMCRID`, not the Cash Rate Target, target change, total return index,
high/low cash-market rates, volume or transaction count.

The current RBA workbook was handled under the frozen quarantine ingress
overlay. Post-2022 observation dates were structurally encountered to establish
row scope. Post-2022 numerical cells were not decoded, persisted or used. No
official workbook and no rate rows were committed.

AUD publication evidence is intentionally conservative. The adapter does not
claim an actual intraday publication timestamp. It derives Publication Date as
the immediately following RITS business day and makes the rate available only at
the first frozen 17:05 New York execution strictly after the publication-day
envelope closes.

After `RBA_CASH_RATE_V3` passed, the remaining adapter continuation stopped
fail-fast at `BOJ_FINAL_UO_CALL_V2`. The official BOJ preflight returned HTTP
200 with `text/html`, not the declared final JSON response shape. No JPY source
snapshot or rate version was persisted. CAD and CHF were not certified after the
JPY fail-fast blocker.

Development, validation, independent replication and future portfolio freezing
were not run because all seven required currencies did not pass. No market
provider request was sent, no economic outcome was computed, no pull request or
merge was created, and no live-capital authorization exists.
