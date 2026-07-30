# Strategy-Alpha Final Claim Matrix

| ID | Claim | Status |
|---|---|---|
| A | The repository contains a certified deterministic bid/ask strategy-level execution and economic-evaluation pipeline for the permitted 2015-2022 data. | `SUPPORTED` |
| B | Sweep reversal generated positive historical mean net expectancy. | `DESCRIPTIVELY_SUPPORTED_BUT_NOT_ROBUST` |
| C | Acceptance continuation was historically profitable as a standalone strategy. | `REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY` |
| D | London opening-range continuation was historically profitable. | `REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY` |
| E | New York opening-range continuation was historically profitable. | `NOT_SUPPORTED` |
| F | Any frozen candidate demonstrated benchmark-relative alpha. | `NOT_SUPPORTED` |
| G | Any frozen candidate justified prospective paper trading. | `NOT_SUPPORTED` |
| H | Positive direction-flip controls establish that inverted versions are profitable strategies. | `EXPLORATORY_OUTCOME_INFORMED_ONLY` |
| I | The current results authorize live-capital deployment. | `NOT_TESTED_AND_NOT_AUTHORIZED` |

Claim B is descriptive only: its `+0.0106R` mean had a confidence interval
crossing zero, negative matched alpha, negative expectancy at 1.5x and 2.0x
cost, and failed leave-one-year-out positivity. Claim H cannot be confirmed on
the current sample; inversion requires a separate lineage and preregistered
hypothesis with independent instruments or genuinely future data.
