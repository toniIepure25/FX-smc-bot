# Strategy-Alpha Results

| Candidate | Trades | Mean net R | Day-cluster 95% CI | PF | Sharpe | 1.5x cost | 2.0x cost | Matched alpha | Tier |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Sweep reversal | 202 | 0.0106 | [-0.0747, 0.0995] | 1.0485 | 0.2803 | -0.0066 | -0.0237 | -0.0051 | C |
| Acceptance continuation | 2,676 | -0.1581 | [-0.1989, -0.1191] | 0.6975 | -3.1012 | -0.2031 | -0.2482 | -0.0380 | C |
| London opening range | 360 | -0.0811 | [-0.1465, -0.0134] | 0.7076 | -2.0612 | -0.1063 | -0.1316 | -0.0630 | C |
| New York opening range | 753 | -0.0314 | [-0.0872, 0.0233] | 0.8975 | -0.6831 | -0.0545 | -0.0776 | 0.0193 | C |

All Holm-adjusted p-values were 1.0. Direction flips were positive but are
outcome-informed controls, not validated strategies. One- and two-bar delays
were strongly negative. No candidate passed leave-one-year-out positivity; PBO
was 0.86. No candidate was selected for a forward test.
