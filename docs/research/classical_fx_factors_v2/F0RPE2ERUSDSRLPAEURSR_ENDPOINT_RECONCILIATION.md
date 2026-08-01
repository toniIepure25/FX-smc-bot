# ECB Endpoint Reconciliation

Reconciliation ID: `ECB_EONIA_ESTR_SOURCE_RECONCILIATION_V1`.

The active EONIA source is `https://data-api.ecb.europa.eu/service/data/EON/D.EONIA_TO.RATE` with `format=csvdata`. The invalid predecessor combination `EON.B.EU000A2X2A25.WT` is explicitly rejected.

The active euro short-term rate source is `https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT` with `format=csvdata`. Every request must carry `startPeriod`, `endPeriod`, `format=csvdata` and `detail=full`.
