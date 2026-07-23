# Gate C.4-A Power Decision Audit

Finding: MDE80 was not preregistered as a confirmation threshold and was not
used by the decision engine.

```json
{
  "acceptance_exact_answer": {
    "actual_failed_mandatory_criteria": [
      "positive_event_primary_effect"
    ],
    "effect_points": 13.754508196721174,
    "mde80_points": 14.061585121967383,
    "mde_caused_mixed_decision": false
  },
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "decision_if_mde_were_used": "not applicable; prohibited by preregistration",
      "mde80_points": 14.061585121967383,
      "mde_preregistered_as_confirmation_threshold": false,
      "mde_used_by_decision_engine": false,
      "observed_effect_below_mde80": true,
      "observed_mean_event_minus_control_points": 13.754508196721174
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "decision_if_mde_were_used": "not applicable; prohibited by preregistration",
      "mde80_points": 16.264893632834536,
      "mde_preregistered_as_confirmation_threshold": false,
      "mde_used_by_decision_engine": false,
      "observed_effect_below_mde80": true,
      "observed_mean_event_minus_control_points": -13.451403887688675
    },
    "opening_range_london": {
      "decision_if_mde_were_used": "not applicable; prohibited by preregistration",
      "mde80_points": 16.604405422991615,
      "mde_preregistered_as_confirmation_threshold": false,
      "mde_used_by_decision_engine": false,
      "observed_effect_below_mde80": true,
      "observed_mean_event_minus_control_points": 15.15994236311225
    },
    "opening_range_new_york": {
      "decision_if_mde_were_used": "not applicable; prohibited by preregistration",
      "mde80_points": 19.60973061961117,
      "mde_preregistered_as_confirmation_threshold": false,
      "mde_used_by_decision_engine": false,
      "observed_effect_below_mde80": true,
      "observed_mean_event_minus_control_points": 0.0950000000001873
    }
  },
  "finding": "MDE80 is a non-decision power diagnostic and was not used in the C4 decision engine.",
  "status": "PASS"
}
```
