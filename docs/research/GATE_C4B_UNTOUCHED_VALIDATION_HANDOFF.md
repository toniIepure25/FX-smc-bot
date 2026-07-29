# Gate C.4-B Untouched Validation Handoff

The original C.4 Acceptance directional-alpha hypothesis failed. This handoff
concerns a new outcome-informed hypothesis lineage. Validation remains untouched
at handoff creation.

```json
{
  "confidence_interval": "day-cluster bootstrap CI",
  "control_construction": "C4 matched controls with exact year/month/session/direction and covariates",
  "entry_exit_convention": "next-bar executable bid/ask entry and horizon exit inherited from C4",
  "event_family": "Acceptance Continuation",
  "failure_threshold": "non-positive event-minus-control differential or absolute directional alpha interpretation",
  "minimum_event_count": 40,
  "new_hypothesis_class": "RELATIVE_RESILIENCE",
  "new_hypothesis_hash": "e8b726734a3b5118709edc7642caa1d4e10bad2509aa9fd0949a0cca2b05290d",
  "new_hypothesis_id": "C4B_USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_V1",
  "no_adaptation_rule": true,
  "original_c4_acceptance_directional_alpha_failed": true,
  "overlap_policy": "primary non-overlap sample",
  "pair": "USDJPY",
  "primary_estimand": "event-minus-matched-control executable markout points",
  "primary_horizon_minutes": 120,
  "statistical_test": "paired permutation with Holm handled only if multiple frozen tests exist",
  "status": "PREPARED_WITHOUT_VALIDATION_ACCESS",
  "success_threshold": "positive event-minus-control differential with non-positive absolute event markout and placebo not reproduced",
  "validation_period": "2020-01-01 through 2022-12-31",
  "validation_remains_untouched_at_handoff_creation": true
}
```
