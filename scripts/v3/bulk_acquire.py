"""Durable, resumable bulk pre-2018 M1 acquisition runner (native primary, tick fallback).

A long-running, safely-resumable, user-controlled process. Native per-day M1 candles are the
primary transport; tick->M1 aggregation is a per-day deterministic fallback used ONLY when a
day's native artifact is genuinely unavailable. Every request is firewalled before I/O, the
adaptive scheduler paces/backs-off/circuit-breaks, and unit state is persisted atomically
after each transition so a killed process resumes without repeating certified work.

Usage:
  python scripts/v3/bulk_acquire.py status  --state PATH
  python scripts/v3/bulk_acquire.py run     --state PATH --canonical DIR --scratch DIR \\
                                            [--limit N] [--instruments EURUSD,USDJPY] \\
                                            [--rate 0.5] [--log PATH]

SIGINT/SIGTERM: finish the current unit, persist, exit 0. Re-run the same command to resume.
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


def _acquire_native_day(sched: AdaptiveScheduler, fw: V3HoldoutFirewall, inst: str, d: date,
                        scratch: Path) -> tuple[str, list[dict[str, Any]], str]:
    """Return (result, rows, source_sha). result in {'native','missing','retry'}."""

    o_bid, bid_raw = _fetch(sched, fw, nt.native_m1_url(inst, d, "BID"), d,
                            scratch / f"{inst}_{d.isoformat()}_bid.bi5")
    o_ask, ask_raw = _fetch(sched, fw, nt.native_m1_url(inst, d, "ASK"), d,
                            scratch / f"{inst}_{d.isoformat()}_ask.bi5")
    if o_bid is Outcome.MISSING or o_ask is Outcome.MISSING:
        return "missing", [], ""
    if o_bid is not Outcome.OK or o_ask is not Outcome.OK:
        return "retry", [], ""
    rows = nt.native_m1_day(bid_raw, ask_raw, inst, d)
    src = hashlib.sha256(bid_raw + ask_raw).hexdigest()
    return "native", rows, src


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


def run(args: argparse.Namespace) -> int:
    _install_signals()
    fw = V3HoldoutFirewall()
    canon = Path(args.canonical)
    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    store = StateStore(Path(args.state))
    store.load()

    only = set(args.instruments.split(",")) if args.instruments else None
    # plan (idempotent): enumerate units; weekends auto TERMINAL_DATA_ABSENT
    for inst, d in iter_units():
        if only and inst not in only:
            continue
        store.plan(inst, d)
    store._persist()

    sched = AdaptiveScheduler(rate_per_sec=args.rate, clock=time.monotonic, seed=7)
    log = open(args.log, "a") if args.log else None
    processed = 0
    for key in store.pending_keys():
        if _STOP["flag"] or (args.limit and processed >= args.limit):
            break
        inst, iso = key.split(":")
        d = date.fromisoformat(iso)
        store.transition(inst, d, UnitStatus.IN_PROGRESS)
        result, rows, src = _acquire_native_day(sched, fw, inst, d, scratch)
        if result == "native" and rows:
            canon_rows = cm.canonicalize_native_day(rows, d)
            cert = ap.certify_partition(instrument=inst, year=d.year, month=d.month, day=d.day,
                                        side="bid", m1_rows=canon_rows, source_bytes=0,
                                        source_sha256=src, request_urls=[])
            if cert["integrity_audit"]["bid_ask_valid"] and cert["integrity_audit"][
                    "scaling_plausibility_ok"]:
                canon_hash = _write_canonical(canon, inst, d, canon_rows)
                store.transition(inst, d, UnitStatus.CERTIFIED_NATIVE,
                                 transport=Transport.NATIVE_M1.value, source_checksum=src,
                                 canonical_checksum=canon_hash, canonical_rows=len(rows))
            else:
                store.transition(inst, d, UnitStatus.INTEGRITY_FAILURE)
        elif result == "missing":
            # native genuinely 404 -> attempt the per-day tick->M1 fallback (never infer
            # closure from provider silence).
            tresult, trows, tsrc = _acquire_tick_fallback_day(sched, fw, inst, d, scratch)
            if tresult == "tick" and trows:
                canon_trows = cm.canonicalize_tick_day(trows, d)
                tcert = ap.certify_partition(instrument=inst, year=d.year, month=d.month,
                                             day=d.day, side="bid", m1_rows=canon_trows,
                                             source_bytes=0, source_sha256=tsrc, request_urls=[])
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
                # both transports genuinely 404 on a calendar trading date -> exceptional
                # closure, preserved explicitly (deterministic; not transient silence).
                store.transition(inst, d, UnitStatus.TERMINAL_DATA_ABSENT,
                                 fallback_reason="exceptional_closure_native_and_tick_404")
            else:
                store.transition(inst, d, UnitStatus.RETRYABLE,
                                 fallback_reason="throttle_or_timeout")
        else:
            store.transition(inst, d, UnitStatus.RETRYABLE, fallback_reason="throttle_or_timeout")
        processed += 1
        snap = sched.health_snapshot()
        line = (f"{datetime.now(timezone.utc).isoformat()} {key} -> "
                f"{store.units[key].status} health={snap}")
        print(line, flush=True)
        if log:
            log.write(line + "\n")
            log.flush()
    if log:
        log.close()
    s = store.summary()
    print(f"[done] processed={processed} certified={s['certified_units']} "
          f"pending={s['pending_units']} stop={_STOP['flag']}", flush=True)
    return 0


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
    r.set_defaults(func=run)
    s = sub.add_parser("status")
    s.add_argument("--state", required=True)
    s.set_defaults(func=status)
    args = ap_.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
