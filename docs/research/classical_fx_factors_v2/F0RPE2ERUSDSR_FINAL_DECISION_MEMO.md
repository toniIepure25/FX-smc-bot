# Gate F0-RP-E2E-R-USDSR Final Decision

Decision: `BLOCKED_BY_USD_PUBLICATION_AVAILABILITY`.

The predecessor USD schema failure remains valid and unchanged. Its failed decision, adapter matrix and certification artefact were not overwritten or reclassified.

The official EFFR response was reconciled through explicitly versioned legacy and modern schemas rather than permissive key guessing. The modern response also contains OBFR rows, so EFFR normalization is frozen to exact `type == EFFR` selection.

No internal normalized field was represented as an official response field. Publication and revision availability were derived only through the frozen official provenance contract. Fetch time, file metadata, observation values and an invented end-of-day clock instant were never used as publication evidence.

The modern final-history value has a conservative exact availability envelope of 14:30 America/New_York on the next authorized publication business day and would be eligible at the 17:05 portfolio execution. The legacy rule identifies only the end of the publication day. It does not identify the exact aware timestamp required by `RateVersion`. The gate therefore stopped before implementing `NY_FED_EFFR_V3`, parsing numerical rows or persisting rate versions.

Development, validation and replication were accessed only in preregistered order. None was reached. The 2023-2025 interval remained excluded from every calculation and decision. NZD and NZDUSD remained inaccessible.

Any selected portfolio remains unconfirmed until genuinely future prospective evidence satisfies the frozen requirements. No portfolio was selected or frozen, no future data were collected, and no result authorizes live-capital deployment.
