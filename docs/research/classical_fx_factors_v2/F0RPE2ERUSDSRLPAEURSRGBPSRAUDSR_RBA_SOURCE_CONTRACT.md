# F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR-AUDSR RBA Source Contract

Contract ID: `RBA_STATISTICAL_TABLE_F1_SOURCE_CONTRACT_V1`

The predecessor `RBA_CASH_RATE_V2` blocker is preserved. The active source may
not continue to use `https://www.rba.gov.au/statistics/cash-rate/cash-rate.json`.

The official AUD source contract is RBA Statistical Table F1:

- Historical F1: `https://www.rba.gov.au/statistics/tables/xls-hist/f01dhist.xls`
  for the 2010 warm-up coverage.
- Current F1: `https://www.rba.gov.au/statistics/tables/xls/f01d.xlsx` for
  authorized 2011-2022 research coverage.

The selected economic series is the actual `Australian Interbank Overnight Cash
Rate`. It is not the `Cash Rate Target`, `Cash Rate Total Return Index`, highest
or lowest interbank overnight rate, transaction count, or transaction volume.

Publication is handled conservatively. The Cash Rate report date is the RITS
business day on which the underlying cash market transactions were agreed and
settled. The Publication Date is the immediately following RITS business day.
Because the historical final-history workbook does not expose exact intraday
publication and republication timestamps for each observation, the adapter must
use a publication-day envelope and must not invent an exact publication time.

Revision identifiers remain null unless explicitly supplied by the official
workbook. Expert-judgement metadata must be preserved when present and must not
be used to replace the official Cash Rate with the target independently.
