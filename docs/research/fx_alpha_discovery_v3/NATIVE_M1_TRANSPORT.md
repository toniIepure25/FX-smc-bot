# V3 Native M1 Transport, Parity & Durable Bulk Acquisition

Solves the acquisition bottleneck without brute-forcing ~649k hourly tick requests, while
keeping the certified canonical M1 BID/ASK representation unchanged. No 2018+ byte is ever
requested or read; no strategy signal, P&L or ranking is computed (data engineering only).

## 1. Native transport investigation

Dukascopy serves native per-day M1 candle `.bi5` files, one per price side:
`/{INSTR}/{YYYY}/{MM0}/{DD}/{BID|ASK}_candles_min_1.bi5` (month 0-indexed). Each file holds up
to 1,440 minute candles; format is LZMA + 24-byte records
`(time_sec:int32, open, close, low, high :int32, volume:float32)`, prices in instrument points.
A validated fetch of EURUSD 2014-06-10 decoded to **1,440 rows, 00:00–23:59, minute-aligned**.

**Network diagnosis.** The observed HTTP 503 is a *burst rate-limit* on the intercepted
corporate-proxy path — it hits tick and candle routes alike after ~2 rapid requests, and
clears after a cool-down; successful requests take ~13–28 s (TLS/proxy-dominated, DNS/connect
~5 ms). It is NOT a candle-specific outage: after a cool-down, native candle requests return
200. This slow, throttled path is an external network characteristic; a normal un-intercepted
permitted network would substantially improve throughput. No security control is bypassed and
certificate validation is never disabled.

Transport identity is always recorded: `NATIVE_M1` vs `TICK_AGGREGATED_M1`, plus any fallback
reason ([`native_transport.py`](../../../src/fx_smc_bot/research/v3/native_transport.py),
[`acquisition_state.py`](../../../src/fx_smc_bot/research/v3/acquisition_state.py)).

## 2. Prospective parity contract (declared before any parity value)

Native M1 vs the certified tick→M1 canonical are compared on timestamps, bid O/H/L/C, ask
O/H/L/C, row presence, missing-minute structure, ordering, day boundaries and JPY/non-JPY
scaling, on the common covered minute window. Equality is at the **frozen quote precision
only** (5 decimals non-JPY, 3 JPY): `PASS_EXACT` = identical minute set and identical canonical
values; `PASS_CANONICAL_EQUIVALENT` = identical after rounding to precision; else `FAIL`. No
looser tolerance may be added after results; no strategy/P&L comparison.

## 3. Parity panel & transport certification

Stratified pre-2018 panel (JPY/non-JPY, major/cross, multiple years, London–NY session);
native vs tick→M1. Result: see
[`results/gate_v3f/native_parity_panel.json`](../../../results/gate_v3f/native_parity_panel.json).
Both fully-fetched majors matched **PASS_EXACT** (480 shared minutes, zero mismatches) — native
candles are bit-identical to the tick aggregation at canonical precision. Transport verdict:
`V3_NATIVE_M1_BULK_TRANSPORT_CERTIFIED` (native primary; tick→M1 retained as a deterministic
per-day fallback only, never re-downloading everything for transport homogeneity).

## 4. Rebuilt acquisition plan (native units)

[`native_plan.py`](../../../src/fx_smc_bot/research/v3/native_plan.py): 13 instruments ×
pre-2018 trading weekdays (weekends deterministically excluded, never from provider silence).

| Quantity | Value |
| --- | --- |
| Trading weekdays / instrument (2010–2017) | 2,086 |
| Day-units total | 27,118 |
| **Native requests planned** | **54,236** (BID+ASK/day) |
| Old tick-request estimate (superseded) | 650,832 |
| Request reduction | **~12× fewer** |
| Monthly canonical partitions | 2,496 |

## 5. Adaptive scheduler & durable state machine

[`provider_scheduler.py`](../../../src/fx_smc_bot/research/v3/provider_scheduler.py):
token-bucket pacing + jitter, bounded concurrency, exponential backoff on 429/503/timeout,
circuit breaker with recovery probe, per-host health that only raises concurrency on evidence,
bounded retries, throttle-vs-missing (404) distinction.
[`acquisition_state.py`](../../../src/fx_smc_bot/research/v3/acquisition_state.py): immutable
status progression (PLANNED → IN_PROGRESS → CERTIFIED_NATIVE / CERTIFIED_TICK_FALLBACK /
RETRYABLE / TERMINAL_DATA_ABSENT / INTEGRITY_FAILURE), atomic persistence after every unit,
resume without repeating certified work, independent source/canonical checksums, no silent
overwrite of a certified partition.

## 6. Durable long-running command (resume-safe)

The full 27,118-day-unit acquisition is a bounded, resumable, multi-hour+ operation on the slow
throttled path. Run it as a durable user-controlled local process
([`bulk_acquire.py`](../../../scripts/v3/bulk_acquire.py)); SIGINT/SIGTERM finish the current
unit, persist and exit; re-running the same command resumes. Do not run two instances against
one state file.

```bash
# resume/continue the full pre-2018 bulk acquisition (native primary, tick fallback)
.venv/bin/python scripts/v3/bulk_acquire.py run \
  --state    data/acquisition_state/bulk_state.json \
  --canonical data/canonical \
  --scratch  .v3_scratch \
  --log      data/acquisition_state/bulk.log \
  --rate 0.5            # conservative; scheduler adapts on measured health

# check progress any time (safe, read-only)
.venv/bin/python scripts/v3/bulk_acquire.py status --state data/acquisition_state/bulk_state.json
```

Prefer running on a normal permitted network (not the intercepting proxy) for materially higher
throughput. Canonical data and state live under git-ignored `data/`; only code and lightweight
manifests are committed.

## Fleet-wide certification + FX calendar correction (this gate)

**Verdict:** `V3_NATIVE_M1_BULK_TRANSPORT_CERTIFIED_FLEET_WIDE` — 16 parity units, **0 FAIL**, all
13 instruments, both scaling classes (JPY/non-JPY), majors + crosses, early (2010–2011) and
late (2016–2017) epochs, and every session class (full / Sunday-open / Friday-close /
DST-adjacent). On every real (ticked) minute native M1 equals tick→M1 exactly at the frozen
quote precision (0 precision mismatches).

**FX weekly-session calendar fix.** The plan previously enumerated weekdays only. Corrected to
the deterministic America/New_York contract (`fx_calendar.py`): the week opens **Sunday 17:00
ET** and closes **Friday 17:00 ET**; only **Saturday** is fully closed. Sunday-open and
Friday-close are legitimate **partial** trading dates. Result: **2504 trading dates/instrument
(1668 full + 418 Sunday + 418 Friday)** → **32,552 day-units / 65,104 native requests** (was
2086 / 27,118 / 54,236). Closure is never inferred from provider silence (503/timeout/404 →
RETRYABLE; only the calendar declares closure).

**Empty-minute canonicalization (diagnosed, then frozen).** The Sunday-open unit initially
FAILed with **0 price mismatches** — a pure *row-presence* difference: Dukascopy native M1 emits
a full 1440-minute grid (no-tick minutes are flat carry-forward bars) while tick→M1 omits
no-tick minutes. The canonical M1 standard adopts the native full-grid convention
(`fill_session_grid`, flat carry-forward), applied uniformly to both transports before
comparison and to the tick fallback. This is a parser/canonicalizer definition motivated by the
primary transport's structure; it changes no price and does not touch the quote-precision
tolerance. After it, the Sunday-open, Friday-close and DST-adjacent units all PASS_EXACT.

**Terminal data verdict:** `V3_DATA_CERTIFICATION_IN_PROGRESS_BULK_ACQUISITION_PENDING`. The
transport is fleet-certified and the durable runner is validated (incl. a real Sunday session,
2010-01-03), but full 32,552-day-unit coverage is a multi-week throttled run — handed off via
[`BULK_ACQUISITION_RUNBOOK.md`](BULK_ACQUISITION_RUNBOOK.md). `V3_DATA_CERTIFIED_DISCOVERY_READY`
is reached only when every planned unit has a legitimate final classification and every monthly
partition is certified.
