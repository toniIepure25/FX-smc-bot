# Gate C.3F — 2019 Certification Report

## Status: PENDING — Acquisition In Progress

The 2019 development year acquisition has been started using the new daily
checkpoint system. Certification cannot proceed until all three pairs
(EURUSD, GBPUSD, USDJPY) have complete bid and ask M1 data for all 12
months of 2019.

## Certification Requirements

For each pair-year (2019) to pass:
- At least 11 structurally validated months
- Timestamp alignment ≥ 80%
- Zero negative spreads
- Unpaired-row ratio ≤ 20%
- Session coverage ≥ 70%

## Acquisition Method

Using Gate C.3F daily checkpoint system:
- Day-by-day download with atomic persistence
- Manifest tracking per day
- Monthly compaction after all days terminal
- Failure categories: weekend/holiday distinguished from errors
- Resume from last completed day on restart

## Command

```bash
python scripts/run_persistent_acquisition.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2019-01-01 --end 2019-12-31 \
  --workers 2 --resume \
  --log-dir logs/acquisition --state-dir data/acquisition_state
```

## Pending Steps

1. Complete 2019 acquisition for all pairs
2. Run structural validation on each partition
3. Run pair-year certification gate
4. Execute 2019 tick audit windows
5. Only then may event funnels run on certified 2019 data
