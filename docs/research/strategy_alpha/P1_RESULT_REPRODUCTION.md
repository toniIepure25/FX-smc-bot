# Gate P.1 Aggregate Result Reproduction

The reproduction used only committed compact aggregate artifacts. It did not
load market data, provider payloads, or row-level ledgers.

| Candidate | Trades | Mean net R | Day-cluster 95% CI | PF | Sharpe | Matched alpha | Tier |
|---|---:|---:|---:|---:|---:|---:|---|
| SMC_A_SWEEP_REVERSAL_V1 | 202 | 0.010604 | [-0.074715, 0.099501] | 1.048476 | 0.280324 | -0.005109 | TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST |
| SMC_B_ACCEPTANCE_CONTINUATION_V1 | 2676 | -0.158100 | [-0.198862, -0.119098] | 0.697541 | -3.101238 | -0.037977 | TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST |
| SMC_C_LONDON_OPENING_RANGE_V1 | 360 | -0.081108 | [-0.146490, -0.013442] | 0.707570 | -2.061177 | -0.062999 | TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST |
| SMC_C_NEWYORK_OPENING_RANGE_V1 | 753 | -0.031397 | [-0.087209, 0.023271] | 0.897514 | -0.683108 | 0.019275 | TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST |

The disjoint-window trade counts sum exactly to each combined count, and their
net-R totals reproduce each combined weighted mean. The four combined counts
sum to 3,991 and agree with the execution sample manifest. All aggregate
metrics, Holm-adjusted values, Tier assignments, and the null primary/secondary
selection agree exactly with the Gate P.0-R-DCR-A1A memo.

Status: `PASS`.
