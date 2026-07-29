# Gate C.3F Worker And Chunk Benchmark

Status: `DEFERRED_PENDING_FULL_DEVELOPMENT_COMPLETION`.

The corrected runner has automated proof that `workers=2` produces real bounded concurrency and that `workers=1` remains sequential. The prior benchmark artifact is preserved as preliminary only: it selected 2 workers based on observed CDN behavior and heartbeat proof, but a formal uncached day/week/month chunk comparison has not yet been completed.
