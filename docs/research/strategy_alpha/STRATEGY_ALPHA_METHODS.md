# Strategy-Alpha Methods

The candidate universe, estimands, benchmarks, costs, and Tier criteria were
frozen before the final outcomes. An outcome-blind amendment resolved source
resolution, warm-up, exit horizon, session calendar, and instrument roles before
market-data access.

Dukascopy bid and ask provenance was canonicalized to UTC M1 OHLC and then
aggregated deterministically to M5. Certification prohibited interpolation and
forward fill. Execution used 500 M5 warm-up bars, final-bar causal signals,
adverse-first intrabar semantics, candidate session exits, Friday safety exit,
actual bid/ask spread, fixed commission, and slippage. Tick ordering was not
used for favorable stop/target resolution.

Inference used day-cluster confidence intervals, week sensitivity, cost stress,
risk simulations, matched benchmarks, negative controls, leave-one-year-out
analysis, concentration diagnostics, Holm correction, FDR sensitivity, and
deflated Sharpe. Tier adjudication was mechanical with no manual override or
parameter search.
