# Gate F0-RP-E2E-R-USDSR-LPA-EURSR Final Decision

Final decision: `BLOCKED_BY_OFFICIAL_RATE_ADAPTER`.

The predecessor ECB HTTP 404 blocker remains valid and unchanged. The blocker was resolved for EUR through correction of the EONIA dataflow series key, not by weakening source validation.

EONIA used the official `EON.D.EONIA_TO.RATE` series. EUR short-term rate used the official `EST.B.EU000A2X2A25.WT` series.

The EONIA/EUR short-term rate transition contained no overlap, gap, interpolation or pre-EUR-short-term-rate substitution. Historical benchmark availability was kept separate from later ECB archival API ingestion. No publication timestamp was inferred from HTTP retrieval or local file metadata.

USD and EUR certifications passed. Remaining live-adapter certification stopped fail-fast at GBP: `BOE_SONIA_V2` returned `OFFICIAL_ENDPOINT_HTTP_STATUS_403`. No GBP snapshot was persisted, no GBP numerical row reached a parser, and no market request was sent.

Development, validation and replication were not accessed because remaining official adapter certification did not complete. The 2023-2025 interval was excluded from all calculations and decisions. NZD and NZDUSD remained inaccessible.

No result authorizes paper-trading, live-capital deployment, validation access, replication access, or a frozen future portfolio.
