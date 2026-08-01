# F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR-AUDSR Predecessor Inheritance

Status: `PREDECESSOR_BLOCK_PRESERVED_NOT_REVERSED`

The predecessor gate ended at `BLOCKED_BY_OFFICIAL_RATE_ADAPTER` after the
active AUD adapter `RBA_CASH_RATE_V2` requested the nonexistent endpoint
`https://www.rba.gov.au/statistics/cash-rate/cash-rate.json` and received
`OFFICIAL_ENDPOINT_HTTP_STATUS_404`.

That predecessor blocker is retained as historical evidence. It is not
reclassified, overwritten, or treated as a successful AUD source.

No AUD source snapshot was persisted, no AUD numerical row reached a parser, no
AUD `RateVersion` was created, no market request was sent, and no economic
outcome was computed before this gate.
