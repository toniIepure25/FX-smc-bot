# Gate Q1 Aggregate Result Reproduction

Gate Q1 read only committed aggregate JSON and the committed Q0-R decision
memo. It did not load market data or row-level features, predictions, signals,
orders, benchmarks, or trades.

| Candidate | Trades | Mean net R | PF | 1.5x cost | Matched alpha |
|---|---:|---:|---:|---:|---:|
| Inverse Sweep | 364 | -0.321805 | 0.297522 | -0.356640 | -0.255439 |
| Inverse Acceptance | 6,932 | -0.762445 | 0.107293 | -0.858735 | -0.527579 |
| Inverse London OR | 930 | -0.410300 | 0.160778 | -0.471346 | -0.215112 |
| Inverse New York OR | 1,488 | -0.421101 | 0.233314 | -0.473285 | -0.284062 |
| Elastic-net meta | 6 | -0.121867 | 0.077613 | -0.133150 | -0.128247 |

Checks performed: `111`.
Mismatches: `0`.
Maximum numeric difference: `0.0`.
Q0-R manifest hash agreement: `True`.

White Reality Check, Hansen SPA, Romano-Wolf, Holm, FDR, PSR, DSR, PBO,
year and instrument stability, development ineligibility, empty shortlist,
absence of replication access, and absence of a future freeze all reproduced.

Status: `PASS`.
