# Gate C.5-A Amended Validation Decision Matrix

Decision matrix complete: `True`

All eleven mandatory criteria must pass. A positive absolute event markout is
not reinterpreted as alpha; it fails the frozen relative-resilience mechanism.

```json
{
  "all_eleven_mandatory_criteria_required": true,
  "amendment_hash": "1d1302fcc01fec3d0be00875026854e8b9e47eee38dd74fa654e824fdab44830",
  "amendment_id": "C5A_C4B_USDJPY_RELATIVE_RESILIENCE_HANDOFF_AMENDMENT_V1",
  "decision_matrix_complete": true,
  "gate": "C.5-A",
  "mandatory_criteria": [
    {
      "comparison_operator": "equals",
      "criterion": "artifact_integrity",
      "criterion_number": 1,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    },
    {
      "comparison_operator": "equals",
      "criterion": "validation_data_quality",
      "criterion_number": 2,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    },
    {
      "comparison_operator": ">=",
      "criterion": "successfully_matched_primary_non_overlap_events",
      "criterion_number": 3,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 40
    },
    {
      "comparison_operator": "equals",
      "criterion": "exact_key_relaxations",
      "criterion_number": 4,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "every_post_match_abs_smd",
      "criterion_number": 5,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0.1
    },
    {
      "comparison_operator": ">",
      "criterion": "mean_event_minus_control_executable_markout",
      "criterion_number": 6,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "paired_permutation_p_value",
      "criterion_number": 7,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0.05
    },
    {
      "comparison_operator": ">",
      "criterion": "ci95_lower_bound",
      "criterion_number": 8,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "<=",
      "criterion": "mean_absolute_event_executable_markout",
      "criterion_number": 9,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": 0
    },
    {
      "comparison_operator": "equals",
      "criterion": "plus_1_day_placebo_reproduces_relative_resilience",
      "criterion_number": 10,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": false
    },
    {
      "comparison_operator": "equals",
      "criterion": "holdout_integrity",
      "criterion_number": 11,
      "mandatory_or_diagnostic": "mandatory",
      "threshold": "PASS"
    }
  ],
  "positive_absolute_event_markout_interpretation": "mechanism drift; fails relative-resilience criterion"
}
```
