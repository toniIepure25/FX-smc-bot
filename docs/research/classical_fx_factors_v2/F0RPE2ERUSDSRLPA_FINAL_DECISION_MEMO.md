# Gate F0-RP-E2E-R-USDSR-LPA Final Decision

Decision: `BLOCKED_BY_RATE_SOURCE_ACCESS`.

The predecessor publication-availability block remains valid and unchanged. No actual legacy publication timestamp was invented. Legacy EFFR publication was represented as a conservative publication-day envelope, and legacy values became usable only at the first portfolio execution strictly after that envelope closed. Modern final-history values became usable only after the frozen same-day revision-complete boundary.

The publication-availability overlay was committed before numerical rate parsing or economic outcomes. USD `NY_FED_EFFR_V3` and the V4 vintage store were certified at `f92e5a315094d61d7118fdcf07fbae403a8b414f`. Phase 13 then attempted the remaining bounded live official adapters only after that commit. The first permitted remaining request, `ECB_EONIA_ESTR_V2` for EONIA, returned `OFFICIAL_ENDPOINT_HTTP_STATUS_404`; no source snapshot was persisted, no numerical rows were exposed to a parser, and no market-provider request was sent.

Development, validation and replication were not accessed because remaining adapter certification did not pass. The 2023-2025 interval remained excluded from all calculations and decisions. NZD and NZDUSD remained inaccessible. No result authorizes live-capital deployment.

Reached artifacts:

- `publication_censoring_overlay.json`: interval-censored publication model frozen before parse.
- `usd_adapter_v3_certification.json`: USD V3 certification `PASS`.
- `vintage_store_v4_certification.json`: V4 certification `PASS`.
- `usd_asof_availability_audit.json`: legacy/modern as-of checks `PASS`.
- `live_adapter_certification.json`: Phase 13 stopped at `BLOCKED_BY_RATE_SOURCE_ACCESS`.

Quality gate reached before final commit:

- Full pytest: `1409 passed`, 91 warnings.
- Targeted Ruff: `PASS`.
- Targeted mypy: `PASS`.
- Node wrapper tests: `2 passed`.
- `git diff --check`: `PASS`.
- Broad Ruff: existing baseline debt outside this gate delta; not remediated here.
