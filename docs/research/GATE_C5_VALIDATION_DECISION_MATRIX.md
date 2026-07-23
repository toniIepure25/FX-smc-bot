# Gate C.5 Validation Decision Matrix

Final decision: `BLOCKED_BY_VALIDATION_HANDOFF_AMBIGUITY`

The C.5 validation was stopped before validation access. The frozen C4-B
hypothesis ID, hypothesis hash, pair, interval, horizon, estimand, minimum event
count, and high-level success rule are intact. The machine-readable decision
matrix is not complete enough for one-shot confirmatory validation.

Blocking ambiguities:

- No prospectively frozen matching balance pass/fail threshold was found.
- The C4-B handoff requires exact year/month/session/direction matching, while
  the inherited C4 implementation contains exact-key fallback relaxation and did
  not group the candidate pool by direction.
- The handoff names day-cluster bootstrap CI, but does not state whether CI
  exclusion of zero is mandatory.
- The inherited C4 placebo rule is directional-event based; no unambiguous
  placebo failure rule for the relative-resilience differential was frozen.

Validation and holdout data were not opened.
