# V3 Durable Bulk Pre-2018 Acquisition — Runbook

The full pre-2018 acquisition is a **multi-week, resumable** operation (see ETA below). It
runs as a single durable, user-controlled local process. This runbook is the exact
status/start/resume contract; **no code change is needed to resume**.

## Scale (corrected FX calendar)

| Quantity | Value |
| --- | --- |
| Instruments | 13 |
| Trading dates / instrument (2010–2017) | 2504 (1668 full + 418 Sunday-open + 418 Friday-close) |
| Day-units | 32,552 |
| Native requests (BID+ASK/day) | 65,104 |
| Monthly canonical partitions | 2,496 |

Only Saturday is deterministically closed. Sunday/Friday partial sessions are legitimate
trading dates (do not expect 1440 rows). Closure is never inferred from provider silence.

## Network reality (ETA)

`datafeed.dukascopy.com` over the current intercepted corporate path is burst-rate-limited
(HTTP 503 after ~2 rapid requests) with ~13–20 s per successful request. At the safe paced
throughput this is a **multi-week** run. **Prefer running it on a faster PERMITTED normal
network** (do NOT bypass security controls or disable TLS verification); the acquisition
system is correct on the slow path regardless.

## Commands

Status (safe, read-only):
```bash
.venv/bin/python scripts/v3/bulk_acquire.py status --state data/acquisition_state/bulk_state.json
```

Start / resume the durable run (same command resumes; certified units are never re-fetched):
```bash
OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
UV_SYSTEM_CERTS=1 \
.venv/bin/python scripts/v3/bulk_acquire.py run \
  --state data/acquisition_state/bulk_state.json \
  --canonical data/canonical \
  --scratch data/acquisition_state/scratch \
  --rate 0.4 \
  --log data/acquisition_state/bulk.log
```

* `--rate` is the token-bucket requests/sec (start conservative; the adaptive scheduler
  lowers concurrency on throttle and only raises it from measured health).
* `--limit N` processes at most N units then exits cleanly (useful for bounded chunks).
* `--instruments EURUSD,USDJPY` restricts to a subset.
* **SIGINT/SIGTERM**: the process finishes the current unit, persists state atomically, and
  exits 0. Re-run the identical command to resume. **Do not run two instances against the
  same `--state`.**

## Mac resource policy (M5, 16 GiB)

Network-bound, not compute-bound: bounded parser/network concurrency, BLAS threads = 1, no
swap-dependent design. Canonical storage is day-partitioned Parquet (lazy-loadable); it is
git-ignored (`data/canonical/`), never committed.

## After daily acquisition completes

Materialize + certify monthly canonical partitions and the global data-freeze digest
(session-aware coverage), then rebuild the data gate. The gate reaches
`V3_DATA_CERTIFIED_DISCOVERY_READY` (next gate `V3_ALPHA_DISCOVERY_RUN`) **only** when every
planned unit has a scientifically legitimate final classification and every required monthly
partition is certified. No coverage is ever fabricated; transient 503/timeouts are not valid
no-data exclusions.
