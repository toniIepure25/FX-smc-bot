# Gate C.4 Event-Alpha Results

## Event Counts
```json
{
  "by_family": {
    "liquidity_acceptance_fvg_continuation": 3977,
    "liquidity_sweep_mss_fvg_reversal": 1774,
    "opening_range_london": 694,
    "opening_range_new_york": 800
  },
  "by_family_direction": {
    "liquidity_acceptance_fvg_continuation|LONG": 2068,
    "liquidity_acceptance_fvg_continuation|SHORT": 1909,
    "liquidity_sweep_mss_fvg_reversal|LONG": 900,
    "liquidity_sweep_mss_fvg_reversal|SHORT": 874,
    "opening_range_london|LONG": 354,
    "opening_range_london|SHORT": 340,
    "opening_range_new_york|LONG": 409,
    "opening_range_new_york|SHORT": 391
  },
  "by_family_session": {
    "liquidity_acceptance_fvg_continuation|asia": 1193,
    "liquidity_acceptance_fvg_continuation|london": 800,
    "liquidity_acceptance_fvg_continuation|new_york": 1004,
    "liquidity_acceptance_fvg_continuation|other": 980,
    "liquidity_sweep_mss_fvg_reversal|asia": 457,
    "liquidity_sweep_mss_fvg_reversal|london": 328,
    "liquidity_sweep_mss_fvg_reversal|new_york": 605,
    "liquidity_sweep_mss_fvg_reversal|other": 384,
    "opening_range_london|london": 694,
    "opening_range_new_york|new_york": 800
  },
  "by_family_year": {
    "liquidity_acceptance_fvg_continuation|2015": 774,
    "liquidity_acceptance_fvg_continuation|2016": 762,
    "liquidity_acceptance_fvg_continuation|2017": 812,
    "liquidity_acceptance_fvg_continuation|2018": 879,
    "liquidity_acceptance_fvg_continuation|2019": 750,
    "liquidity_sweep_mss_fvg_reversal|2015": 361,
    "liquidity_sweep_mss_fvg_reversal|2016": 489,
    "liquidity_sweep_mss_fvg_reversal|2017": 420,
    "liquidity_sweep_mss_fvg_reversal|2018": 313,
    "liquidity_sweep_mss_fvg_reversal|2019": 191,
    "opening_range_london|2015": 132,
    "opening_range_london|2016": 137,
    "opening_range_london|2017": 146,
    "opening_range_london|2018": 141,
    "opening_range_london|2019": 138,
    "opening_range_new_york|2015": 160,
    "opening_range_new_york|2016": 160,
    "opening_range_new_york|2017": 162,
    "opening_range_new_york|2018": 169,
    "opening_range_new_york|2019": 149
  }
}
```

## Overlap Audit
```json
{
  "by_family_non_overlap": {
    "liquidity_acceptance_fvg_continuation": 2440,
    "liquidity_sweep_mss_fvg_reversal": 1389,
    "opening_range_london": 694,
    "opening_range_new_york": 800
  },
  "non_overlap_primary_events": 5323,
  "overlapped_primary_events": 1922,
  "total_events": 7245
}
```

## Primary Estimands
```json
{
  "families": {
    "liquidity_acceptance_fvg_continuation": {
      "cluster_bootstrap_ci95_mean_diff_points": [
        6.3252850111418315,
        21.790929169814817
      ],
      "holm_adjusted_p_value": 0.021989005497251374,
      "mean_event_markout_points": -3.66885245901655,
      "mean_event_minus_control_points": 13.754508196721174,
      "mean_matched_control_markout_points": -17.423360655737724,
      "median_event_markout_points": -10.99999999999568,
      "median_event_minus_control_points": 10.99999999999568,
      "n_events": 2440,
      "paired_permutation_p_value": 0.005497251374312844,
      "positive_forward_return_probability": 0.46352459016393444,
      "trimmed_mean_event_markout_points": -5.79713114754117
    },
    "liquidity_sweep_mss_fvg_reversal": {
      "cluster_bootstrap_ci95_mean_diff_points": [
        -21.65365587176299,
        -4.74573832156042
      ],
      "holm_adjusted_p_value": 0.03798100949525238,
      "mean_event_markout_points": -8.406047516198633,
      "mean_event_minus_control_points": -13.451403887688675,
      "mean_matched_control_markout_points": 5.045356371490041,
      "median_event_markout_points": -9.999999999990905,
      "median_event_minus_control_points": -12.000000000000455,
      "n_events": 1389,
      "paired_permutation_p_value": 0.01899050474762619,
      "positive_forward_return_probability": 0.468682505399568,
      "trimmed_mean_event_markout_points": -7.6648697214734165
    },
    "opening_range_london": {
      "cluster_bootstrap_ci95_mean_diff_points": [
        6.015287649989427,
        23.54029143475591
      ],
      "holm_adjusted_p_value": 0.03748125937031484,
      "mean_event_markout_points": 0.21181556195970366,
      "mean_event_minus_control_points": 15.15994236311225,
      "mean_matched_control_markout_points": -14.948126801152547,
      "median_event_markout_points": -4.5000000000001705,
      "median_event_minus_control_points": 15.000000000007674,
      "n_events": 694,
      "paired_permutation_p_value": 0.01249375312343828,
      "positive_forward_return_probability": 0.4654178674351585,
      "trimmed_mean_event_markout_points": -2.165467625899192
    },
    "opening_range_new_york": {
      "cluster_bootstrap_ci95_mean_diff_points": [
        -9.925967601652154,
        11.230362524851277
      ],
      "holm_adjusted_p_value": 0.9885057471264368,
      "mean_event_markout_points": -9.677499999999919,
      "mean_event_minus_control_points": 0.0950000000001873,
      "mean_matched_control_markout_points": -9.772500000000104,
      "median_event_markout_points": -9.000000000000341,
      "median_event_minus_control_points": 6.000000000000227,
      "n_events": 800,
      "paired_permutation_p_value": 0.9885057471264368,
      "positive_forward_return_probability": 0.4675,
      "trimmed_mean_event_markout_points": -10.199999999999989
    }
  },
  "multiple_testing": "Holm correction across primary non-overlap family tests"
}
```

## Internal Temporal Replication
```json
{
  "liquidity_acceptance_fvg_continuation": {
    "discovery": {
      "mean_event_markout_points": -2.103185595567882,
      "mean_event_minus_control_points": 18.22368421052636,
      "n_events": 1444,
      "years": [
        2015,
        2016,
        2017
      ]
    },
    "replication": {
      "mean_event_markout_points": -5.938755020080684,
      "mean_event_minus_control_points": 7.2751004016060214,
      "n_events": 996,
      "years": [
        2018,
        2019
      ]
    }
  },
  "liquidity_sweep_mss_fvg_reversal": {
    "discovery": {
      "mean_event_markout_points": -8.822564102564003,
      "mean_event_minus_control_points": -16.46871794871751,
      "n_events": 975,
      "years": [
        2015,
        2016,
        2017
      ]
    },
    "replication": {
      "mean_event_markout_points": -7.425120772946856,
      "mean_event_minus_control_points": -6.345410628019312,
      "n_events": 414,
      "years": [
        2018,
        2019
      ]
    }
  },
  "opening_range_london": {
    "discovery": {
      "mean_event_markout_points": 2.8554216867471656,
      "mean_event_minus_control_points": 22.173493975903614,
      "n_events": 415,
      "years": [
        2015,
        2016,
        2017
      ]
    },
    "replication": {
      "mean_event_markout_points": -3.7204301075270227,
      "mean_event_minus_control_points": 4.727598566307897,
      "n_events": 279,
      "years": [
        2018,
        2019
      ]
    }
  },
  "opening_range_new_york": {
    "discovery": {
      "mean_event_markout_points": -8.744813278008424,
      "mean_event_minus_control_points": 6.311203319502256,
      "n_events": 482,
      "years": [
        2015,
        2016,
        2017
      ]
    },
    "replication": {
      "mean_event_markout_points": -11.091194968553062,
      "mean_event_minus_control_points": -9.327044025157035,
      "n_events": 318,
      "years": [
        2018,
        2019
      ]
    }
  }
}
```

## Robustness
```json
{
  "liquidity_acceptance_fvg_continuation": {
    "all_events_mean_diff_points": 11.189338697510573,
    "exclude_top_spread_decile_mean_diff_points": 12.807681976900271,
    "mid_markout_mean_diff_points": 11.239753583102772,
    "non_overlap_mean_diff_points": 13.754508196721174,
    "session_mean_diff_points": {
      "asia": 8.616093880972349,
      "london": 18.278749999999793,
      "new_york": 6.99302788844592,
      "other": 12.833673469387753
    },
    "year_by_year_mean_diff_points": {
      "2015": 33.86175710594296,
      "2016": 10.652230971128764,
      "2017": 1.4125615763544412,
      "2018": 11.959044368600555,
      "2019": -1.980000000000151
    }
  },
  "liquidity_sweep_mss_fvg_reversal": {
    "all_events_mean_diff_points": -7.319052987598358,
    "exclude_top_spread_decile_mean_diff_points": -5.4488286066581635,
    "mid_markout_mean_diff_points": -7.30806087936861,
    "non_overlap_mean_diff_points": -13.451403887688675,
    "session_mean_diff_points": {
      "asia": -9.15973741794253,
      "london": -8.518292682927036,
      "new_york": -10.133884297519913,
      "other": 0.3307291666663206
    },
    "year_by_year_mean_diff_points": {
      "2015": -27.493074792243444,
      "2016": -0.8486707566459359,
      "2017": 2.4738095238102407,
      "2018": 2.0159744408943427,
      "2019": -22.586387434554787
    }
  },
  "opening_range_london": {
    "all_events_mean_diff_points": 15.15994236311225,
    "exclude_top_spread_decile_mean_diff_points": 17.855999999999906,
    "mid_markout_mean_diff_points": 15.197406340057757,
    "non_overlap_mean_diff_points": 15.15994236311225,
    "session_mean_diff_points": {
      "london": 15.15994236311225
    },
    "year_by_year_mean_diff_points": {
      "2015": 3.856060606061685,
      "2016": 15.583941605838314,
      "2017": 44.917808219178134,
      "2018": 4.687943262410954,
      "2019": 4.768115942028686
    }
  },
  "opening_range_new_york": {
    "all_events_mean_diff_points": 0.0950000000001873,
    "exclude_top_spread_decile_mean_diff_points": -2.136111111110929,
    "mid_markout_mean_diff_points": -0.08562499999999972,
    "non_overlap_mean_diff_points": 0.0950000000001873,
    "session_mean_diff_points": {
      "new_york": 0.0950000000001873
    },
    "year_by_year_mean_diff_points": {
      "2015": 11.618750000001299,
      "2016": 8.43749999999952,
      "2017": -1.0308641975311392,
      "2018": 0.32544378698254184,
      "2019": -20.275167785234807
    }
  }
}
```

## Power And Sensitivity
```json
{
  "liquidity_acceptance_fvg_continuation": {
    "mde80_two_sided_alpha05_points": 14.061585121967383,
    "n_events": 2440,
    "sd_pair_diff_points": 248.0682380680274
  },
  "liquidity_sweep_mss_fvg_reversal": {
    "mde80_two_sided_alpha05_points": 16.264893632834536,
    "n_events": 1389,
    "sd_pair_diff_points": 216.49322950618784
  },
  "opening_range_london": {
    "mde80_two_sided_alpha05_points": 16.604405422991615,
    "n_events": 694,
    "sd_pair_diff_points": 156.2230213194723
  },
  "opening_range_new_york": {
    "mde80_two_sided_alpha05_points": 19.60973061961117,
    "n_events": 800,
    "sd_pair_diff_points": 198.08819283383625
  }
}
```
