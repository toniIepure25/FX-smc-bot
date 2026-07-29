# Gate C.3F-R — Worker Benchmark

## Status: DEFERRED_PENDING_ACQUISITION_COMPLETION

The formal benchmark comparing 1, 2, and 3 workers requires the same uncached daily units to be downloaded under each configuration. Since the 2019 acquisition is in progress and cached responses would invalidate the comparison, the benchmark will be executed after the full development dataset is acquired.

## Preliminary observations

From the corrected runner's initial 2019 acquisition run:

- **Workers configured**: 2
- **max_observed_concurrent_tasks**: 2 (confirmed via heartbeat)
- **Concurrent pairs processing**: EURUSD/ask/2019-01 + EURUSD/bid/2019-02 running simultaneously
- **Cached days**: ~200ms per day (loaded from prior C.3F runs)
- **Network days**: 1-5 seconds per day (CDN dependent)
- **Transient failures**: ~20% of network requests need 1-2 retries

## Benchmark plan

When executed, the benchmark will use 12 fresh uncached daily units:
- 4 units for 1-worker configuration
- 4 units for 2-worker configuration
- 4 units for 3-worker configuration

All configurations use the same rate limiter settings to ensure fair comparison.

## Default selection rationale

Based on Dukascopy CDN behavior observed across Gates C.3R and C.3F:
- The CDN rate-limits aggressively above 2-3 concurrent requests
- 2 workers provides ~1.8x throughput vs 1 worker for cached/fast operations
- 3 workers may increase transient failure rate

**Preliminary default: 2 workers**
