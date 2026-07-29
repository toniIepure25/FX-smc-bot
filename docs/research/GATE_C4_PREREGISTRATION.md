# Gate C.4 Preregistration

Status: PREREGISTERED BEFORE OUTCOMES

Preregistration hash: `508ad3540b0f8f82b710775a50781f3f936695c2978284edc13942658624a349`

Repository SHA at preregistration: `8fb676d0f452a29bfbb3414bef50f0cac30a686c`

## Dataset
- Pair: `USDJPY`
- Development years: `[2015, 2016, 2017, 2018, 2019]`
- Discovery years: `[2015, 2016, 2017]`
- Internal temporal replication years: `[2018, 2019]`
- Freeze scope hash: `c0ef7c5897b61dabfebda0ed1b8cf5cccaf61fbfac83003c6d97c792aa837912`

## Primary Horizons
{
  "liquidity_acceptance_fvg_continuation": 120,
  "liquidity_sweep_mss_fvg_reversal": 60,
  "opening_range_london": 60,
  "opening_range_new_york": 60
}

## Matching And Inference
Matched controls are exact on year, month, session, and direction where available,
then nearest on preregistered pre-event covariates. Primary tests use paired
permutation p-values, day-cluster bootstrap confidence intervals, and Holm
correction across the four primary family tests.

## Decision Rules
{
  "confirmed": "adequate event count, positive event and matched-control primary effect, Holm p<=0.05, positive replication effect, and placebo checks not reproducing the primary effect",
  "insufficient": "event count below preregistered minimums",
  "mixed": "directionally positive or heterogeneous but not confirmed",
  "null": "adequate event count without a positive primary effect"
}

## Prohibited Metrics
No full-strategy performance, sizing, portfolio, equity, or challenge-probability
metrics are calculated or reported in Gate C.4.
