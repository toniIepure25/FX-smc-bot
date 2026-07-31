# Gate F0-RP Final Decision Memo

## Decision

`F0RP_RATE_PROVENANCE_RECONCILED_EMPIRICAL_EXECUTION_BLOCKED`

The original Gate F0 rate-provenance block remains valid and unchanged.

The rate-provenance amendment was frozen before any market or rate observation
was accessed. Its ID is `F0_RATE_PROVENANCE_AMENDMENT_V1`, its amendment hash is
`e1a2245542cb74f1eb48bbdba01e9bcd9689662b13d8069602297c97705e904b`,
and its pre-data commit is `62ee708891b8ee056bf8052f74eece2cb71bba49`.

The selected NZD remediation route was determined solely from official source
provenance, not from portfolio performance. Route A could not certify an
official original publication time for the unscheduled 16 March 2020 OCR
decision. No B2 timestamp or lag was inferred. Route B therefore excludes NZD
and NZDUSD and freezes the nine-instrument, seven-currency universe.

## Empirical Status

Empirical execution did not start. The repository has no concrete official
rate-provider adapters, no persisted point-in-time rate panel, and no complete
development, validation, and replication orchestration for the amended
universe. Launching market acquisition alone would create uncertifiable orphan
data, so the gate failed closed with zero market requests, zero rate requests,
and zero observations loaded.

All empirical results, had they been generated, would have included executable
bid/ask costs and point-in-time financing. No empirical result was generated.
Development, validation, and replication therefore remained in their
preregistered order and none was accessed.

The six frozen candidates were not run or ranked. Reality Check, SPA,
Romano-Wolf, Holm, FDR, PSR, DSR, PBO, matched-turnover alpha, HAC alpha, stress
performance, costs, financing, stability, concentration, and Tier adjudication
are all unavailable rather than estimated or imputed.

The quarantined market/rate interval remained untouched. No future prospective
data or storage was accessed, no future candidate was frozen, and no paper or
live-capital handoff was created.

No historical or replication result authorizes live-capital deployment.

## Integrity And Quality

The nine original F0 artifacts retain their starting SHA-256 values. The Q1
manifest, lineage seal, closure lock, and scientific artifacts are unchanged.
The Q1 validator now handles LF/CRLF deterministically and explicitly records
four inherited non-line-ending digest defects without changing historical
claims.

The full suite passed with 1,139 tests. Targeted Ruff and mypy passed with zero
new broad issues, Node passed 2 tests, and `git diff --check` passed.

## Unresolved Risks

- Official rate-provider adapters and source-vintage persistence are absent.
- The amended portfolio engine and complete empirical orchestration are absent.
- The 2019 EONIA-to-ESTR transition needs implemented split-partition recovery.
- No development, validation, replication, or prospective performance evidence exists.
- Four historical Q0-R digest records remain preserved defects in the sealed Q1 manifest.
