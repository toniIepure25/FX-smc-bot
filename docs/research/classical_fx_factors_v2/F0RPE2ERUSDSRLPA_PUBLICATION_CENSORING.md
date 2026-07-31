# Gate F0-RP-E2E-R-USDSR-LPA Publication Censoring Overlay

Overlay ID: `F0RPE2ERUSDSRLPA_PUBLICATION_CENSORING_OVERLAY_V1`.

Status: `FROZEN_BEFORE_NUMERICAL_RATE_PARSING`.

The overlay separates actual publication time, publication evidence bounds and deterministic strategy availability. Exact evidence may carry an actual timestamp. Bounded-time and publication-day evidence must keep the actual timestamp null.

For legacy EFFR, the evidence interval begins at 00:00 America/New_York on the certified publication day and ends at the exclusive 00:00 boundary of the next calendar day. That boundary is not the actual publication timestamp. The rate becomes usable only at the first frozen 17:05 FX execution strictly after the interval closes.

For modern EFFR, approximately 09:00 remains descriptive rather than an exact lower bound. The conservative interval therefore begins at 00:00 and closes at the frozen 14:30 same-day revision-complete boundary. That boundary is not asserted to be an actual revision timestamp for any row. A same-day 17:05 execution is eligible after it.

Official revision identifiers are nullable. A final-history row without one is classified `FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID`. A deterministic internal storage key is not represented as an official revision identifier.

The V4 migration must create a new clean database, retain append-only versions and dataset-freeze pinning, and expose only explicit as-of queries. No numerical rate parsing or economic outcome preceded this freeze.
