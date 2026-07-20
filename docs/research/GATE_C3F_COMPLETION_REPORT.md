# Gate C.3F Completion Report

Generated: 2026-07-20T11:12:53.173695+00:00

Acquisition runner status: `RUNNING_HEALTHY` with PID `20532`. Heartbeat shows `active_worker_count=2`, `max_observed_concurrent_tasks=2`, and Git SHA `c23a6b2323869761f172e685ac291d76e20ff25e`.

Coverage snapshot: 2015 EURUSD is complete for all bid/ask months; 2019 is complete and certified for EURUSD, GBPUSD, and USDJPY. EURUSD 2016-2018 plus GBPUSD/USDJPY 2015-2018 remain pending. No holdout event or strategy access occurred.

Final status for this continuation: `PARTIAL_RUNNING_ACQUISITION`.

The real detached acquisition was started with:

```powershell
.\scripts\start_acquisition.ps1 -Pairs EURUSD,GBPUSD,USDJPY -Start 2015-01-01 -End 2018-12-31 -Workers 2
```

It is writing stdout/stderr under `logs/acquisition/` and operational state under `data/acquisition_state/`. The main historical acquisition is active, so the 2019 tick audit was not run concurrently to avoid adding CDN load.
