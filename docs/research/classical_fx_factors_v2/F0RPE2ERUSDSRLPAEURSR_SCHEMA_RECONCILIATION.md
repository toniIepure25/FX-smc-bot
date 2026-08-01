# ECB SDMX CSV Reconciliation

Reconciliation ID: `ECB_EONIA_ESTR_SDMX_CSV_RECONCILIATION_V1`.

EONIA requires `KEY=EON.D.EONIA_TO.RATE` and `FREQ=D`; `TIME_PERIOD` maps to the observation date and `OBS_VALUE / 100` maps to the annualized decimal rate.

Euro short-term rate requires `KEY=EST.B.EU000A2X2A25.WT`, `FREQ=B`, `BENCHMARK_ITEM=EU000A2X2A25` and `DATA_TYPE_EST=WT`; `TIME_PERIOD` maps to the observation date and `OBS_VALUE / 100` maps to the annualized decimal rate.

Benchmark publication availability is kept separate from ECB archival API retrieval time. No publication timestamp is inferred from HTTP retrieval or local file metadata.
