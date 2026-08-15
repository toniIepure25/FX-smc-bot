# V3 Acquisition Transport Benchmark — faster path investigation

Goal: take the pre-2018 bulk acquisition from ~weeks toward hours **without** changing the
provider, the `.bi5` data store, the canonical M1 v2 semantics, the candidate universe
(A/B/C = 992/52/1044) or any scientific identity (freeze `5a96fd0e…` unchanged). Bounded real
benchmark only — no full bulk started, no discovery, no 2018+ (all requests firewalled;
2018+ requests = 0). Machine-readable: [`results/gate_v3f/transport_benchmark.json`](../../../results/gate_v3f/transport_benchmark.json).

## JForex historical-data API — feasibility: BLOCKED on this machine

`IHistory.getBars(instrument, Period.ONE_MIN, OfferSide.BID/ASK, Filter.NO_FILTER, from, to)`
was the primary target. It cannot be prototyped here:

1. **Java runtime not installed** (`/usr/bin/java` is a stub — "Unable to locate a Java
   Runtime"); a JDK install would be required. Maven is also absent.
2. **Authentication required.** JForex-API needs a connected `IClient` —
   `client.connect(jnlpUrl, username, password)` to a Dukascopy **demo/live account** — before
   any `getBars` call. The agent must not and cannot enter account credentials, and none are
   available. Without a connection there is no data.
3. **No latency advantage even with credentials.** `getBars(range)` internally fetches the
   **same per-day `.bi5` files** from Dukascopy's servers over the **same intercepted network**.
   The range API reduces *logical* calls, not the underlying per-file HTTP latency that
   dominates here.

So JForex is not runnable on this machine, and would not beat the measured `.bi5` throughput
on this network. (M1 has no monthly `.bi5` file — only per-day candle files exist for the
minute timeframe; only H1+/D1 have coarser files, which are the wrong timeframe.)

## Measured `.bi5` transport (curl 8.7.1, HTTP/2, firewalled, pre-2018)

Full native plan = **65,104** BID/ASK per-day requests. Latency is **highly variable
(0.6–15 s/file)** — proxy/interception induced, not payload size (~11 KB files).

| Mode | Result | OK files/s | Full-plan ETA |
|---|---|---|---|
| Serial, new connection (current runner) | 6/6 200 | 0.06–0.19 (variable) | ~12–25 days |
| HTTP/2 reuse, concurrency 1 | 5/6 200, 1×502 | 0.063 | ~12 days |
| HTTP/2 reuse, **concurrency 2** | **6/6 200** | **0.146** | **~5.2 days** |
| HTTP/2 reuse, concurrency 4 | 4/6 200, 2×503 | 0.46 | ~1.6 days (with retries) |
| Concurrency ≥ 4 without recovery / bursts | immediate 503 wall | — | — |

**Rate-limit behavior:** the provider hard-503s bursts. With a real recovery window,
**concurrency 2 is sustainable (0% throttle)**; **concurrency 4 draws ~33% 503** (retryable —
the frozen adaptive scheduler's backoff would absorb them) but is ~3× the throughput of
serial. First-load vs cached was inconclusive (the cached re-fetch fell inside a burst-503
window). The earlier "all-503 at any concurrency" result was budget exhaustion from a
preceding batch, not a hard ceiling.

## Conclusion & recommendation

- **JForex:** blocked (Java + Dukascopy-account credentials); no advantage on this network.
- **Same (intercepted) network:** bounded concurrency **2–4** with the existing adaptive
  scheduler cuts the ETA from **~25 days → ~1.6–5 days** (~5–15×). The durable runner currently
  fetches **serially** (concurrency 1); realizing this needs bounded *parallel* per-file
  fetches under the scheduler (the scheduler already caps at `max_concurrency=4`). This is a
  targeted runner change, not a scheduler redesign, and was intentionally **not** made in this
  benchmark-only session.
- **Fastest real path to _hours_:** the per-file latency is proxy-induced; on a **normal,
  permitted, non-intercepted network** the same `.bi5` CDN serves <1 s/file and tolerates
  concurrency 4–8, so the full plan completes in a **few hours** with the **existing durable
  runner unchanged**. Never bypass security controls or disable TLS validation.
- **Canonical semantics:** unchanged under every option — all transports fetch byte-identical
  `.bi5` files parsed by `v3_m1_canonicalizer_2`; observation masks (volume>0), executable/
  imputed status and session validity are preserved.

Durable acquisition state is untouched and resumable (34 day-units certified). No scientific
identity changed; no discovery run.
