# Q.0-R Development Results

The frozen 2015-2019 development run completed 20 candidate-year execution units
with 13,129 source signals. Original execution completed 5,066 trades and inverse
execution completed 9,714 trades. No runtime or reconciliation error occurred.

All five candidates failed the inherited development criteria. Trade counts were
364 for inverse sweep, 6,932 for inverse acceptance, 930 for inverse London
opening range, 1,488 for inverse New York opening range, and 6 for the elastic-net
meta candidate. Mean net R was negative for every candidate, as were all
matched-random alpha estimates.

White Reality Check returned 0.9898, Hansen SPA returned 1.0, and PBO was 1.0.
The final log-loss-selected hyperparameters were `C=0.01` and `l1_ratio=0.0`.
The 2,680-minute purge and five-FX-day embargo remained active.

The elastic-net solver emitted max-iteration convergence warnings. This remains a
numerical limitation of the frozen model implementation, but it cannot promote a
candidate: every candidate, including all deterministic inversions, failed the
mechanical eligibility rules. No replication outcome was accessed.
