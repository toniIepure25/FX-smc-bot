# Gate F0-RP-E2E-R-USDSR USD Schema Reconciliation

Reconciliation ID: `NY_FED_EFFR_SCHEMA_RECONCILIATION_V1`.

Status: `FROZEN_BEFORE_USD_RATE_PERSISTENCE`.

The reconciliation supports only the two discovered fingerprints. Both use `$.refRates`, `effectiveDate`, `percentRate`, `revisionIndicator` and exact `type == EFFR` series selection. The official percentage rate would be divided by 100 for the annual-decimal internal financing convention. Unknown fingerprints, null required fields, non-EFFR normalization, out-of-window rows and conflicting duplicates are rejected.

No internal normalized field is represented as an official response field. `currency`, `series_id` and `source_document_id` are explicit deterministic derivations from adapter authorization, exact row identity and request/snapshot identity. The response does not provide `publicationTimestamp`, `effectiveTimestamp` or a usable normalized `revisionIdentifier`.

The modern provenance contract supplies a conservative exact final-value envelope at 14:30 America/New_York on the next authorized New York Fed publication business day. The legacy contract supplies only the end of that publication day. It does not supply an exact clock instant. Because `RateVersion` requires exact aware publication, effective and strategy-availability timestamps, legacy emission cannot be implemented without inventing a timestamp. No such timestamp was invented, and no rate version was created or persisted.
