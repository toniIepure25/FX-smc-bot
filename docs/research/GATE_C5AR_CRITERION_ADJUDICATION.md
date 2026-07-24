# Gate C5-A-R Criterion Adjudication

Final decision: `USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_NOT_VALIDATED`

| # | Criterion | Observed | Rule | Passed |
| ---: | --- | --- | --- | --- |
| 1 | artifact_integrity | `PASS` | equals `PASS` | `True` |
| 2 | validation_data_quality | `PASS` | equals `PASS` | `True` |
| 3 | successfully_matched_primary_events | `1192` | >= `40` | `True` |
| 4 | exact_key_relaxations | `0` | equals `0` | `True` |
| 5 | every_post_match_abs_SMD | `{'spread': 0.02026055574499356, 'atr': 0.031762838550213744, 'pre_event_volatility': 0.05813439292604498, 'pre_event_trend': 0.00041490711061651676, 'range_position': -0.010403247286512483}` | every_abs<= `0.1` | `True` |
| 6 | mean_event_minus_control_executable_differential | `27.453020134228165` | > `0` | `True` |
| 7 | paired_permutation_p_value | `0.004497751124437781` | <= `0.05` | `True` |
| 8 | 95pct_day_cluster_bootstrap_CI_lower_bound | `14.784214406740844` | > `0` | `True` |
| 9 | mean_absolute_event_executable_markout | `11.33724832214778` | <= `0` | `False` |
| 10 | plus_24h_placebo_reproduces_relative_resilience | `False` | equals `False` | `True` |
| 11 | holdout_integrity | `PASS` | equals `PASS` | `True` |
