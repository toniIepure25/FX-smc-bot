"""Benchmark: optimized day download (batchSize=10, pause=200ms)."""
import sys
import time
sys.path.insert(0, "src")
from fx_smc_bot.data.dukascopy_node_provider import _download_single_day

instrument = "eurusd"

# Day that's NOT cached yet (2019-07-01)
print("=== NEW settings: batchSize=10, pause=200ms ===")
t0 = time.time()
data, err = _download_single_day(
    instrument, "2019-07-01", "2019-07-02", "bid",
    batch_size=10, retries=3, pause_between_batches_ms=200,
)
t1 = time.time()
print(f"  Result: {len(data)} rows, err={err!r}, time={t1-t0:.1f}s")

# Another uncached day with old settings for comparison
print("\n=== OLD settings: batchSize=5, pause=1000ms ===")
t0 = time.time()
data2, err2 = _download_single_day(
    instrument, "2019-07-02", "2019-07-03", "bid",
    batch_size=5, retries=3, pause_between_batches_ms=1000,
)
t1 = time.time()
print(f"  Result: {len(data2)} rows, err={err2!r}, time={t1-t0:.1f}s")

# Cached re-download (should be fast)
print("\n=== CACHED re-download (new settings) ===")
t0 = time.time()
data3, err3 = _download_single_day(
    instrument, "2019-07-01", "2019-07-02", "bid",
    batch_size=10, retries=3, pause_between_batches_ms=200,
)
t1 = time.time()
print(f"  Result: {len(data3)} rows, err={err3!r}, time={t1-t0:.1f}s")
