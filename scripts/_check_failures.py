"""Check 2019 partition status."""
import sys
sys.path.insert(0, "src")
from pathlib import Path
from fx_smc_bot.data.daily_checkpoint import load_month_manifest

raw = Path("data/raw/dukascopy-node")
pairs = ["EURUSD", "GBPUSD", "USDJPY"]

complete = 0
partial = 0
missing = 0
total_rows = 0
for pair in pairs:
    for side in ["bid", "ask"]:
        for month in range(1, 13):
            m = load_month_manifest(raw, pair, side, 2019, month)
            if m and m.compacted:
                complete += 1
                total_rows += m.compacted_rows
                print(f"  OK   {pair}/{side}/2019-{month:02d}: {m.compacted_rows:>6} rows")
            elif m:
                done = sum(1 for d in m.days if d.status in ("complete", "market_closed"))
                failed = sum(1 for d in m.days if d.status == "failed")
                rows = sum(d.rows for d in m.days)
                partial += 1
                print(f"  ... {pair}/{side}/2019-{month:02d}: {done} done, {failed} fail ({rows} rows)")
            else:
                missing += 1

print(f"\nTotal: {complete} complete, {partial} partial, {missing} missing (of 72)")
print(f"Rows so far: {total_rows:,}")
