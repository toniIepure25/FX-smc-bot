"""Durable, resumable bulk pre-2018 M1 acquisition runner (native primary, tick fallback).

A long-running, safely-resumable, user-controlled process. Native per-day M1 candles are the
primary transport, fetched in **bounded HTTP/2 parallel batches** (connection reuse via
``curl --http2 --parallel``); tick->M1 aggregation is a per-day deterministic fallback used
ONLY when a day's native artifact is genuinely 404. Every URL is firewalled BEFORE it is
scheduled for transport. A day-unit certifies only after BOTH bid and ask sides have valid
terminal results; a succeeded side is cached and reused (never redownloaded) if its sibling
fails; certified units are never fetched again. Concurrency adapts (1..max) on a rolling
health window. State is persisted atomically per unit, so SIGINT/SIGTERM leaves a clean
resumable state (interrupted IN_PROGRESS units are re-attempted).

Usage:
  python scripts/v3/bulk_acquire.py status  --state PATH
  python scripts/v3/bulk_acquire.py run     --state PATH --canonical DIR --scratch DIR \\
        [--initial-concurrency 2] [--max-concurrency 4] [--adaptive-concurrency] \\
        [--batch-size 8] [--limit N] [--instruments EURUSD,USDJPY] [--rate 0.5] [--log PATH]

Do NOT run two competing instances against the same --state.
"""

from __future__ import annotations

import argparse
import hashlib
import signal
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3 import canonical_m1 as cm
from fx_smc_bot.research.v3 import native_transport as nt
from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition_state import StateStore, Transport, UnitStatus
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall
from fx_smc_bot.research.v3.fx_calendar import session_hours
from fx_smc_bot.research.v3.native_plan import iter_units
from fx_smc_bot.research.v3.parallel_acquire import (
    FALLBACK,
    NATIVE,
    ConcurrencyController,
    FetchTarget,
    RetryAccounting,
    cache_valid,
    classify_unit_transport,
    plan_targets,
)
from fx_smc_bot.research.v3.provider_scheduler import AdaptiveScheduler, Outcome, classify

_STOP = {"flag": False}


def _install_signals() -> None:
    def handler(signum: int, _frame: Any) -> None:
        _STOP["flag"] = True
        print(f"[signal {signum}] finishing current unit then exiting...", flush=True)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


def _curl(url: str, dest: Path) -> tuple[int, int, float]:
    t0 = time.perf_counter()
    p = subprocess.run(
        ["curl", "-sS", "--max-time", "45", "-o", str(dest), "-w", "%{http_code} %{size_download}",
         url], capture_output=True, text=True,
    )
    dt = time.perf_counter() - t0
    parts = p.stdout.strip().split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1]), dt
    return -1, 0, dt


def _curl_parallel(targets: list[FetchTarget], parallel_max: int,
                   scratch: Path) -> dict[str, tuple[int, float]]:
    """HTTP/2 multiplexed parallel fetch of a batch (connection reuse). {url: (code, time)}.

    URLs are already firewalled by plan_targets before reaching here. Files land at each
    target's dest; per-side success is judged by cache_valid(dest), so URL->result mapping is
    only advisory for status accounting.
    """

    if not targets:
        return {}
    cfg = scratch / "_batch.cfg"
    cfg.write_text("\n".join(f'url = "{t.url}"\noutput = "{t.dest}"' for t in targets))
    proc = subprocess.run(
        ["curl", "-sS", "--http2", "--parallel", "--parallel-max", str(parallel_max),
         "--config", str(cfg), "-w", "%{url_effective} %{http_code} %{time_total}\\n",
         "--max-time", "60"],
        capture_output=True, text=True,
    )
    out: dict[str, tuple[int, float]] = {}
    for line in proc.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-2].isdigit():
            out[" ".join(parts[:-2])] = (int(parts[-2]), float(parts[-1]))
    return out


def _side_outcome(dest: Path, url: str, results: dict[str, tuple[int, float]]) -> Outcome:
    """A side is OK iff its cached payload is valid (freshly-200 or reused); else classify."""

    if cache_valid(dest):
        return Outcome.OK
    code = results.get(url, (-1, 0.0))[0]
    return classify(code, timed_out=(code == -1))


def _fetch(sched: AdaptiveScheduler, fw: V3HoldoutFirewall, url: str, d: date,
           dest: Path) -> tuple[Outcome, bytes]:
    """Firewalled, scheduler-paced fetch of one file with bounded retries."""

    fw.guard_url(url)
    fw.guard_date(d, context="bulk acquisition")
    attempt = 0
    while True:
        attempt += 1
        wait = sched.next_wait()
        if wait > 0:
            time.sleep(min(wait, 120.0))
        status, size, dt = _curl(url, dest)
        outcome = classify(status, timed_out=(status == -1))
        should_retry, delay = sched.record(outcome, dt, attempt)
        if outcome is Outcome.OK:
            return outcome, dest.read_bytes()
        if not should_retry:
            return outcome, b""
        time.sleep(min(delay, 120.0))


def _day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _write_canonical(canon: Path, inst: str, d: date, canon_rows: list[dict[str, Any]]) -> str:
    """Persist canonical M1 v2 rows per side, INCLUDING observation provenance masks."""

    digest_input: list[dict[str, Any]] = []
    for side in ("bid", "ask"):
        side_rows = [{"timestamp": r["timestamp"], "open": r[f"{side}_open"],
                      "high": r[f"{side}_high"], "low": r[f"{side}_low"],
                      "close": r[f"{side}_close"], "observed": bool(r[f"{side}_observed"]),
                      "executable_quote": bool(r["executable_quote"]),
                      "is_imputed": bool(r["is_imputed"]),
                      "staleness_minutes": int(r["staleness_minutes"]),
                      "session_valid": bool(r["session_valid"]),
                      "transport": r["transport"]} for r in canon_rows]
        digest_input.append({"side": side, "rows": side_rows})
        pdir = (canon / inst / f"price={side}" / f"year={d.year}" / f"month={d.month:02d}"
                / f"day={d.day:02d}")
        pdir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(side_rows).to_parquet(pdir / "data.parquet", index=False)
    return canonical_hash(digest_input)


def _acquire_tick_fallback_day(sched: AdaptiveScheduler, fw: V3HoldoutFirewall, inst: str,
                               d: date, scratch: Path) -> tuple[str, list[dict[str, Any]], str]:
    """Per-day tick->M1 fallback (only for genuine native unavailability).

    Returns ('tick', rows, src) if any hour has data; ('missing', [], '') iff EVERY expected
    session hour returns a genuine 404 (both transports absent -> exceptional closure); ('retry',
    [], '') on any throttle/timeout (never classify closure from transient silence).
    """

    scale = ap.price_scale(inst)
    ticks: list[ap.Tick] = []
    hasher = hashlib.sha256()
    any_data = False
    all_missing = True
    for h in session_hours(d):
        o, raw = _fetch(sched, fw, _tick_url(inst, d, h), d,
                        scratch / f"{inst}_{d.isoformat()}_{h:02d}h.bi5")
        if o is Outcome.OK:
            all_missing = False
            hasher.update(raw)
            hour_ticks = ap.decode_bi5(raw, _day_ms(d) + h * 3600_000, scale)
            if hour_ticks:
                any_data = True
                ticks.extend(hour_ticks)
        elif o is Outcome.MISSING:
            continue  # this hour genuinely absent (natural gap); keep checking
        else:
            return "retry", [], ""  # throttle/timeout -> never infer closure
    if any_data:
        return "tick", ap.aggregate_m1(ticks), hasher.hexdigest()  # canonicalized by caller
    if all_missing:
        return "missing", [], ""  # every session hour genuinely 404 -> exceptional closure
    return "retry", [], ""


def _certify_native_unit(store: StateStore, canon: Path, inst: str, d: date,
                         bid_bytes: bytes, ask_bytes: bytes) -> bool:
    """Canonicalize + certify a native day-unit from its two cached sides. Atomic transition."""

    rows = nt.native_m1_day(bid_bytes, ask_bytes, inst, d)
    if not rows:
        store.transition(inst, d, UnitStatus.RETRYABLE, fallback_reason="empty_native")
        return False
    canon_rows = cm.canonicalize_native_day(rows, d)
    src = hashlib.sha256(bid_bytes + ask_bytes).hexdigest()
    cert = ap.certify_partition(instrument=inst, year=d.year, month=d.month, day=d.day,
                                side="bid", m1_rows=canon_rows,
                                source_bytes=len(bid_bytes) + len(ask_bytes),
                                source_sha256=src, request_urls=[])
    if cert["integrity_audit"]["bid_ask_valid"] and cert["integrity_audit"][
            "scaling_plausibility_ok"]:
        ch = _write_canonical(canon, inst, d, canon_rows)
        store.transition(inst, d, UnitStatus.CERTIFIED_NATIVE,
                         transport=Transport.NATIVE_M1.value, source_checksum=src,
                         canonical_checksum=ch, canonical_rows=len(rows))
        return True
    store.transition(inst, d, UnitStatus.INTEGRITY_FAILURE)
    return False


def _fallback_unit(store: StateStore, sched: AdaptiveScheduler, fw: V3HoldoutFirewall,
                   canon: Path, inst: str, d: date, scratch: Path) -> None:
    """Native genuinely 404 -> deterministic tick->M1 fallback (never closure from silence)."""

    tresult, trows, tsrc = _acquire_tick_fallback_day(sched, fw, inst, d, scratch)
    if tresult == "tick" and trows:
        canon_trows = cm.canonicalize_tick_day(trows, d)
        tcert = ap.certify_partition(instrument=inst, year=d.year, month=d.month, day=d.day,
                                     side="bid", m1_rows=canon_trows, source_bytes=0,
                                     source_sha256=tsrc, request_urls=[])
        if tcert["integrity_audit"]["bid_ask_valid"] and tcert["integrity_audit"][
                "scaling_plausibility_ok"]:
            ch = _write_canonical(canon, inst, d, canon_trows)
            store.transition(inst, d, UnitStatus.CERTIFIED_TICK_FALLBACK,
                             transport=Transport.TICK_AGGREGATED_M1.value,
                             fallback_reason="native_unavailable_tick_fallback",
                             source_checksum=tsrc, canonical_checksum=ch,
                             canonical_rows=len(trows))
        else:
            store.transition(inst, d, UnitStatus.INTEGRITY_FAILURE)
    elif tresult == "missing":
        store.transition(inst, d, UnitStatus.TERMINAL_DATA_ABSENT,
                         fallback_reason="exceptional_closure_native_and_tick_404")
    else:
        store.transition(inst, d, UnitStatus.RETRYABLE, fallback_reason="throttle_or_timeout")


def run(args: argparse.Namespace) -> int:
    _install_signals()
    fw = V3HoldoutFirewall()
    canon = Path(args.canonical)
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    store = StateStore(Path(args.state))
    store.load()

    only = set(args.instruments.split(",")) if args.instruments else None
    for inst, d in iter_units():
        if only and inst not in only:
            continue
        store.plan(inst, d)
    store._persist()

    sched = AdaptiveScheduler(rate_per_sec=args.rate, clock=time.monotonic, seed=7)
    max_level = args.max_concurrency if args.adaptive_concurrency else args.initial_concurrency
    controller = ConcurrencyController(initial=args.initial_concurrency, max_level=max_level,
                                       clock=time.monotonic)
    retry = RetryAccounting()

    def _guard(url: str, d: date) -> None:
        fw.guard_url(url)                      # firewall-before-scheduling; raises on 2018+
        fw.guard_date(d, context="bulk acquisition")

    pending = store.pending_keys()
    log = open(args.log, "a") if args.log else None
    processed = 0
    t_start = time.monotonic()
    idx = 0
    req_metrics: list[tuple[int, float]] = []   # (http_code, time_total) per HTTP attempt
    while idx < len(pending) and not _STOP["flag"]:
        if args.limit and processed >= args.limit:
            break
        remaining = (args.limit - processed) if args.limit else args.batch_size
        batch = pending[idx: idx + min(args.batch_size, max(1, remaining))]
        idx += len(batch)
        units = [(k.split(":")[0], date.fromisoformat(k.split(":")[1])) for k in batch]
        for inst, d in units:
            store.transition(inst, d, UnitStatus.IN_PROGRESS)

        # firewall-before-scheduling happens inside plan_targets; cached sides are reused.
        targets = plan_targets(units, scratch, nt.native_m1_url, _guard)
        k_level = controller.level
        results = _curl_parallel(targets, k_level, scratch)
        for t in targets:
            outcome = _side_outcome(t.dest, t.url, results)
            code, rtime = results.get(t.url, (-1, 0.0))
            req_metrics.append((code, rtime))
            retry.record_attempts(1)
            controller.observe(outcome in (Outcome.THROTTLE, Outcome.TIMEOUT))
            sched.record(outcome, rtime, attempt=1)
        breaker_open = sched.health_snapshot()["breaker_state"] == "open"
        controller.update(breaker_open=breaker_open)

        for inst, d in units:
            bid_dest = scratch / f"{inst}_{d.isoformat()}_bid.bi5"
            ask_dest = scratch / f"{inst}_{d.isoformat()}_ask.bi5"
            bid_o = _side_outcome(bid_dest, nt.native_m1_url(inst, d, "BID"), results)
            ask_o = _side_outcome(ask_dest, nt.native_m1_url(inst, d, "ASK"), results)
            decision = classify_unit_transport(bid_o, ask_o)
            if decision == NATIVE:
                if _certify_native_unit(store, canon, inst, d,
                                        bid_dest.read_bytes(), ask_dest.read_bytes()):
                    retry.record_certified_files(2)
            elif decision == FALLBACK:
                _fallback_unit(store, sched, fw, canon, inst, d, scratch)
            else:
                # a side throttled/timed-out: keep the succeeded side cached for reuse.
                store.transition(inst, d, UnitStatus.RETRYABLE,
                                 fallback_reason="throttle_or_timeout")
            processed += 1

        elapsed_h = (time.monotonic() - t_start) / 3600
        s = store.summary()
        rate = round(s["certified_units"] / elapsed_h, 1) if elapsed_h > 0 else 0.0
        line = (f"{datetime.now(timezone.utc).isoformat()} batch={len(batch)} "
                f"concurrency={k_level} certified={s['certified_units']} "
                f"pending={s['pending_units']} throttle={round(controller.throttle_rate(), 3)} "
                f"amplification={retry.amplification()} breaker={breaker_open} "
                f"cert_units_per_hr={rate}")
        print(line, flush=True)
        if log:
            log.write(line + "\n")
            log.flush()
    if log:
        log.close()
    s = store.summary()
    elapsed_h = (time.monotonic() - t_start) / 3600
    cph = round(processed / elapsed_h, 1) if elapsed_h > 0 else 0.0
    print(f"[done] processed={processed} certified={s['certified_units']} "
          f"pending={s['pending_units']} attempts={retry.total_http_attempts} "
          f"amplification={retry.amplification()} "
          f"processed_units_per_hr={cph} stop={_STOP['flag']}", flush=True)
    if args.metrics:
        _write_metrics(Path(args.metrics), req_metrics, retry, processed, elapsed_h,
                       controller.level)
    return 0


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p * len(s)))], 3)


def _write_metrics(path: Path, req_metrics: list[tuple[int, float]], retry: RetryAccounting,
                   processed: int, elapsed_h: float, final_concurrency: int) -> None:
    import json  # noqa: PLC0415

    status: dict[str, int] = {}
    for code, _ in req_metrics:
        status[str(code)] = status.get(str(code), 0) + 1
    ok_lat = [t for c, t in req_metrics if c == 200]
    throttle = status.get("429", 0) + status.get("503", 0)
    total = len(req_metrics)
    path.write_text(json.dumps({
        "artifact_id": "V3_PARALLEL_SOAK_RUN_V1",
        "http_attempts": total,
        "status_counts": status,
        "throttle_rate": round(throttle / total, 4) if total else 0.0,
        "timeout_or_conn_error": status.get("-1", 0),
        "p50_ok_latency_s": _pct(ok_lat, 0.50),
        "p90_ok_latency_s": _pct(ok_lat, 0.90),
        "p99_ok_latency_s": _pct(ok_lat, 0.99),
        "retry_amplification": retry.amplification(),
        "processed_units": processed,
        "certified_source_files": retry.certified_source_files,
        "elapsed_hours": round(elapsed_h, 4),
        "effective_certified_units_per_hour": round(
            (retry.certified_source_files / 2) / elapsed_h, 1) if elapsed_h > 0 else 0.0,
        "processed_units_per_hour": round(processed / elapsed_h, 1) if elapsed_h > 0 else 0.0,
        "final_concurrency": final_concurrency,
    }, indent=2, sort_keys=True))


def status(args: argparse.Namespace) -> int:
    store = StateStore(Path(args.state))
    store.load()
    import json  # noqa: PLC0415
    print(json.dumps(store.summary(), indent=2, sort_keys=True))
    return 0


def main() -> int:
    ap_ = argparse.ArgumentParser(description="Durable bulk pre-2018 M1 acquisition")
    sub = ap_.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--state", required=True)
    r.add_argument("--canonical", required=True)
    r.add_argument("--scratch", required=True)
    r.add_argument("--log", default="")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--instruments", default="")
    r.add_argument("--rate", type=float, default=0.5)
    r.add_argument("--initial-concurrency", type=int, default=2, dest="initial_concurrency")
    r.add_argument("--max-concurrency", type=int, default=4, dest="max_concurrency")
    r.add_argument("--adaptive-concurrency", action="store_true", dest="adaptive_concurrency")
    r.add_argument("--batch-size", type=int, default=8, dest="batch_size")
    r.add_argument("--metrics", default="", help="write a soak-metrics JSON summary to this path")
    r.set_defaults(func=run)
    s = sub.add_parser("status")
    s.add_argument("--state", required=True)
    s.set_defaults(func=status)
    args = ap_.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
