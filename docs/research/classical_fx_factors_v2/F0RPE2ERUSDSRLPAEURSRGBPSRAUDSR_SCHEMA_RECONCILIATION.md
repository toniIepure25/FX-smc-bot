# RBA F1 Cash Rate Schema Reconciliation

Gate: `F0RPE2ERUSDSRLPAEURSRGBPSR_AUD_SOURCE_RECONCILIATION_V1`

Reconciliation ID: `RBA_F1_CASH_RATE_SCHEMA_RECONCILIATION_V1`

Status: `FROZEN_BEFORE_AUD_RATE_VERSION_PERSISTENCE`

## Official Field

The selected AUD short-rate series is the RBA Statistical Table F1 `Interbank Overnight Cash Rate`, with series code `FIRMMCRID` where the workbook supplies a code row.

The selected worksheet is `Data`.

The date column is `A`.

The selected Cash Rate column is `D`.

The unit is `Per cent`, normalized by dividing by 100 into an annualized decimal rate.

The internal series identity is:

```text
currency:
AUD

series_id:
RBA_CASH_RATE

calendar:
RITS business day

day_count:
ACT/365 Fixed
```

## Rejected Fields

The adapter rejects `Cash Rate Target`, `Change in the Cash Rate Target`, `Total Return Index`, high/low interbank cash-rate columns, cash-market transaction volume and cash-market transaction count.

The target column is not used as a fallback and is not treated as equivalent to the actual interbank overnight Cash Rate.

## Source Boundaries

Historical F1:

```text
endpoint:
https://www.rba.gov.au/statistics/tables/xls-hist/f01dhist.xls

format:
OLE2/BIFF .xls

schema fingerprint:
fce982bc4adbf9c3f5b1588780320b78be96b38b155e0981a1a1de9e9cfff65a
```

Current F1:

```text
endpoint:
https://www.rba.gov.au/statistics/tables/xls/f01d.xlsx

format:
OOXML .xlsx

schema fingerprint:
abcaf1b6d80a76d816fd580b6b74a88080054a4c69d5ffbbf568345fc4f5b492
```

The current workbook is handled under `RBA_F1_QUARANTINE_AWARE_INGRESS_V1`. Post-2022 observation dates may be structurally encountered only to establish row scope; post-2022 numerical cells are not decoded, persisted or used.

## Publication Semantics

For observation date `T`, `T` is the Report Date. Publication Date is the immediately following RITS business day.

The adapter does not claim an actual intraday publication timestamp. It uses `PUBLICATION_DAY_ENVELOPE`, with lower bound `00:00 Australia/Sydney` on Publication Date and upper bound `00:00 Australia/Sydney` on the following calendar day, exclusive.

Strategy availability is the first frozen 17:05 `America/New_York` execution strictly after that upper bound.

Revision identifier is `null`; revision status is `FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID`.
