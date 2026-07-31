# Gate F.0 New-Lineage Boundary

## Program identity

- Program: `FX_CLASSICAL_RISK_PREMIA_V1`
- Lineage: `FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1`
- Relationship: `NEW_FINANCIALLY_MOTIVATED_LINEAGE`

The following prior lineages remain closed and are neither reopened nor modified:

- `FX_SMC_STRATEGY_ALPHA_LINEAGE_V1`
- `FX_QUANT_POLARITY_META_V2_LINEAGE_SEAL_V1`

## Scientific boundary

Gate F.0 tests only the preregistered classical FX risk-premia family. It is not
a rescue, extension, inversion, relabeling, or meta-model of SMC, Acceptance,
opening-range, or polarity research.

The implementation must reject, before use:

- prior SMC or polarity outcomes;
- prior feature matrices or model predictions;
- prior row-level trade, feature, position, or return ledgers;
- prior clean-room market files, raw payloads, and acquisition checkpoints;
- any candidate quarantined by a prior lineage;
- any request for the quarantined interval.

Prior closure artifacts may be read only to verify and hash their seals. Their
contents may not become predictors, labels, filters, portfolio inputs, or
selection evidence.

## Required adjudication

The operational boundary must record `PASS` before any downstream F.0 data
access. Any failed guard, seal mismatch, lineage reuse, or inability to prove
separation requires `BLOCKED_BY_NEW_LINEAGE_BOUNDARY`.

This document is an ex-ante protocol specification. It contains no empirical
result and does not authorize data acquisition, replication, or deployment.
