"""Targeted tick remediation runner for the V3 pre-2018 data-integrity failures.

Implements the FROZEN V3_DATA_INTEGRITY_REMEDIATION_V1 contract (see
``fx_smc_bot.research.v3.remediation``): remediates ONLY the eligible native-integrity-failure
day-units via the existing synchronized Dukascopy tick fallback. It is a data-integrity
correction only -- it changes no candidate definition, statistic or execution hypothesis, and
computes no V3 P&L.

Subcommands:
  manifest  --state PATH --scratch PATH --manifest PATH
            Classify the INTEGRITY_FAILURE units, enumerate the exact frozen session hours,
            build the targeted pre-2018 tick manifest, firewall every URL, and hash it BEFORE
            acquisition.
  run       --state PATH --canonical DIR --scratch PATH --tick-scratch DIR --manifest PATH
            [--limit N] [--rate 0.5] [--concurrency 2] [--log PATH]
            Bounded, resumable tick download (concurrency 2, conservative pacing, adapt
            downward on 429/503), synchronized tick->M1 aggregation, strict certification,
            and the frozen remediation decision. Writes the audit trail.

Do NOT run two competing instances against the same --state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

from fx_smc_bot.research.v3 import acquisition_pipeline as ap  # noqa: E402
from fx_smc_bot.research.v3 import canonical_m1 as cm  # noqa: E402
from fx_smc_bot.research.v3 import native_transport as nt  # noqa: E402
from fx_smc_bot.research.v3._hashing import canonical_hash  # noqa: E402
from fx_smc_bot.research.v3.acquisition_state import (  # noqa: E402
    StateStore,
    Transport,
    UnitStatus,
)
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall  # noqa: E402
from fx_smc_bot.research.v3.fx_calendar import session_hours  # noqa: E402
from fx_smc_bot.research.v3.provider_scheduler import (  # noqa: E402
    AdaptiveScheduler,
    Outcome,
    classify,
)
from fx_smc_bot.research.v3.remediation import (  # noqa: E402
    ABSENT_REASON_CONFIRMED,
    CAT_BIDASK_ORDER,
    CAT_ZERO_OBS,
    FALLBACK_REASON_BIDASK,
    FALLBACK_REASON_ZERO_OBS,
    TICK_HAS_OBS,
    TICK_TRANSIENT,
    TICK_ZERO_OBS,
    decide_remediation_outcome,
    remediation_contract_hash,
)

_STOP = {"flag": False}

# States that mean a manifest unit is still in (or owed) the remediation pass.
_INFLIGHT = {UnitStatus.INTEGRITY_FAILURE.value, UnitStatus.IN_PROGRESS.value,
             UnitStatus.RETRYABLE.value}
# A unit left in INTEGRITY_FAILURE by a prior remediation pass (tick still failing) is terminal.
_REMEDIAL_FAILED = "remediation_tick_still_failing"


def _install_signals() -> None:
    def handler(signum: int, _frame: object) -> None:
        _STOP["flag"] = True
        print(f"[signal {signum}] finishing current unit then exiting...", flush=True)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


def _day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _curl(url: str, dest: Path) -> tuple[int, int, float]:
    t0 = time.perf_counter()
    p = subprocess.run(
        ["curl", "-sS", "--max-time", "45", "-o", str(dest),
         "-w", "%{http_code} %{size_download}", url],
        capture_output=True, text=True,
    )
    dt = time.perf_counter() - t0
    parts = p.stdout.strip().split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1]), dt
    return -1, 0, dt


# --------------------------------------------------------------------------------------
# Native classification (re-derives the frozen category from the local native source).
# --------------------------------------------------------------------------------------
def classify_native(inst: str, d: date, scratch: Path) -> dict[str, Any]:
    """Re-decode the native BID/ASK source and classify the integrity-failure category.

    Returns {category, native_source_checksum, native_bid_ask_violations,
    native_observed_minutes}. This is the SAME frozen logic the native runner used to reach
    INTEGRITY_FAILURE; it is re-derived here only to build the targeted manifest + audit trail.
    """

    bid_raw = (scratch / f"{inst}_{d.isoformat()}_bid.bi5").read_bytes()
    ask_raw = (scratch / f"{inst}_{d.isoformat()}_ask.bi5").read_bytes()
    src = hashlib.sha256(bid_raw + ask_raw).hexdigest()
    rows = nt.native_m1_day(bid_raw, ask_raw, inst, d)
    canon = cm.canonicalize_native_day(rows, d)
    observed = sum(1 for r in canon if r["bid_observed"] or r["ask_observed"])
    violations = sum(1 for r in canon if r["ask_close"] < r["bid_close"])
    if not canon or observed == 0:
        category = CAT_ZERO_OBS
    elif violations > 0:
        category = CAT_BIDASK_ORDER
    else:
        category = "OTHER_INTEGRITY_FAILURE"
    return {
        "category": category,
        "native_source_checksum": src,
        "native_bid_ask_violations": violations,
        "native_observed_minutes": observed,
    }


# --------------------------------------------------------------------------------------
# Phase 3: targeted tick manifest (hash BEFORE acquisition).
# --------------------------------------------------------------------------------------
def build_manifest(state_path: Path, scratch: Path, manifest_path: Path) -> int:
    store = StateStore(state_path)
    store.load()
    fw = V3HoldoutFirewall()
    units: list[dict[str, Any]] = []
    eligible = 0
    for key in sorted(store.units):
        rec = store.units[key]
        if rec.status != UnitStatus.INTEGRITY_FAILURE.value:
            continue
        inst, iso = key.split(":")
        d = date.fromisoformat(iso)
        cls = classify_native(inst, d, scratch)
        if cls["category"] not in (CAT_ZERO_OBS, CAT_BIDASK_ORDER):
            continue  # non-eligible: NOT remediated
        eligible += 1
        hours = session_hours(d)
        urls = [_tick_url(inst, d, h) for h in hours]
        # firewall BEFORE the manifest is finalized; a 2018+ URL would raise.
        for u in urls:
            fw.guard_url(u)
        fw.guard_date(d, context="integrity remediation manifest")
        units.append({
            "key": key,
            "instrument": inst,
            "day": iso,
            "category": cls["category"],
            "native_source_checksum": cls["native_source_checksum"],
            "native_bid_ask_violations": cls["native_bid_ask_violations"],
            "native_observed_minutes": cls["native_observed_minutes"],
            "session_hours": hours,
            "tick_urls": urls,
        })
    total_files = sum(len(u["tick_urls"]) for u in units)
    by_cat: dict[str, int] = {}
    for u in units:
        by_cat[u["category"]] = by_cat.get(u["category"], 0) + 1
    manifest = {
        "artifact_id": "V3_TARGETED_TICK_MANIFEST_V1",
        "remediation_contract_hash": remediation_contract_hash(),
        "unit_count": len(units),
        "total_tick_files": total_files,
        "by_category": by_cat,
        "2018_plus_tick_urls": 0,
        "firewall": {
            "permitted_request_count": len(fw.network.permitted_requests),
            "blocked_request_count": fw.network.blocked_2018_plus_count(),
        },
        "units": units,
    }
    manifest["manifest_hash"] = canonical_hash(units)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps({
        "unit_count": len(units),
        "total_tick_files": total_files,
        "by_category": by_cat,
        "manifest_hash": manifest["manifest_hash"],
        "2018_plus_tick_urls": 0,
        "firewall_blocked": fw.network.blocked_2018_plus_count(),
    }, indent=2))
    return 0


# --------------------------------------------------------------------------------------
# Phase 4/5/6: bounded tick download + synchronized aggregation + strict certification.
# --------------------------------------------------------------------------------------
class FetchLog:
    """Persistent, resumable record of which tick-hours reached a legitimate transport state.

    A tick-hour is 'done' once it is either a genuine 200 (any size, including a 0-byte
    no-data hour) or a genuine 404. Transient failures (429/502/503/504/timeout) are NOT
    recorded, so they are retried on the next run. This makes the download resumable and
    immune to the standard cache_valid >200-byte rule (which cannot see 0-byte no-data hours).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            self.entries = json.loads(path.read_text())

    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    def mark(self, key: str, status: str, sha256: str = "", nbytes: int = 0) -> None:
        self.entries[key] = {"status": status, "sha256": sha256, "bytes": nbytes}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, sort_keys=True))
        tmp.replace(self.path)


def _fetch(sched: AdaptiveScheduler, lock: Lock, fw: V3HoldoutFirewall, url: str, d: date,
           dest: Path) -> tuple[Outcome, bytes]:
    """Firewalled, scheduler-paced fetch of one tick-hour file with bounded retries."""

    fw.guard_url(url)
    fw.guard_date(d, context="integrity remediation")
    attempt = 0
    while True:
        attempt += 1
        with lock:
            wait = sched.next_wait()
        if wait > 0:
            time.sleep(min(wait, 120.0))
        status, _size, dt = _curl(url, dest)
        outcome = classify(status, timed_out=(status == -1))
        with lock:
            should_retry, delay = sched.record(outcome, dt, attempt)
        if outcome is Outcome.OK:
            return outcome, (dest.read_bytes() if dest.exists() else b"")
        if not should_retry:
            return outcome, b""
        time.sleep(min(delay, 120.0))


def acquire_tick_session(sched: AdaptiveScheduler, lock: Lock, fw: V3HoldoutFirewall,
                         inst: str, d: date, tick_scratch: Path, flog: FetchLog,
                         concurrency: int) -> dict[str, Any]:
    """Fetch the COMPLETE required session for (inst, d) at bounded concurrency.

    Returns a rich result: tick_state (has_observations / zero_observations_confirmed /
    unresolved_transient), the decoded ticks, per-hour source checksums, and the combined
    tick source sha256. Resumable via the FetchLog: done hours (200 of any size, or 404) are
    reused and never redownloaded; transient hours are retried.
    """

    scale = ap.price_scale(inst)
    tick_scratch.mkdir(parents=True, exist_ok=True)
    hours = session_hours(d)
    per_hour: dict[str, str] = {}
    per_hour_sha: dict[str, str] = {}
    combined = hashlib.sha256()
    ticks: list[ap.Tick] = []
    decoded = 0

    def _one(h: int) -> tuple[int, str, int]:
        key = f"{inst}_{d.isoformat()}_{h:02d}h"
        dest = tick_scratch / f"{key}_ticks.bi5"
        prev = flog.get(key)
        if prev is not None:
            if prev["status"] == "ok":
                raw = dest.read_bytes() if dest.exists() else b""
                ht = ap.decode_bi5(raw, _day_ms(d) + h * 3600_000, scale)
                return h, "ok", len(ht)
            return h, "missing", 0
        o, raw = _fetch(sched, lock, fw, _tick_url(inst, d, h), d, dest)
        if o is Outcome.OK:
            flog.mark(key, "ok", hashlib.sha256(raw).hexdigest(), len(raw))
            ht = ap.decode_bi5(raw, _day_ms(d) + h * 3600_000, scale)
            return h, "ok", len(ht)
        if o is Outcome.MISSING:
            flog.mark(key, "missing")
            return h, "missing", 0
        return h, "transient", 0

    results: list[tuple[int, str, int]] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        for res in ex.map(_one, hours):
            results.append(res)
            if _STOP["flag"]:
                break

    any_transient = False
    for h, state, _n in sorted(results):
        per_hour[str(h)] = state
        if state == "transient":
            any_transient = True
            continue
        if state == "ok":
            dest = tick_scratch / f"{inst}_{d.isoformat()}_{h:02d}h_ticks.bi5"
            raw = dest.read_bytes() if dest.exists() else b""
            combined.update(raw)
            per_hour_sha[str(h)] = hashlib.sha256(raw).hexdigest()
            ht = ap.decode_bi5(raw, _day_ms(d) + h * 3600_000, scale)
            if ht:
                decoded += len(ht)
                ticks.extend(ht)

    if any_transient or len(results) < len(hours):
        tick_state = TICK_TRANSIENT
    elif decoded > 0:
        tick_state = TICK_HAS_OBS
    else:
        tick_state = TICK_ZERO_OBS
    return {
        "tick_state": tick_state,
        "ticks": ticks,
        "decoded_tick_count": decoded,
        "tick_source_sha256": combined.hexdigest(),
        "tick_source_checksums": per_hour_sha,
        "hour_states": per_hour,
    }


def _write_canonical(canon: Path, inst: str, d: date,
                     canon_rows: list[dict[str, Any]]) -> str:
    """Persist canonical M1 v2 rows per side (frozen _write_canonical semantics)."""

    import pandas as pd  # noqa: PLC0415

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


def run(args: argparse.Namespace) -> int:
    _install_signals()
    store = StateStore(Path(args.state))
    store.load()
    manifest = json.loads(Path(args.manifest).read_text())
    if canonical_hash(manifest["units"]) != manifest["manifest_hash"]:
        raise SystemExit("manifest hash mismatch -- refusing to run on a tampered manifest")
    if manifest["remediation_contract_hash"] != remediation_contract_hash():
        raise SystemExit("remediation contract hash mismatch -- refusing to run")

    canon = Path(args.canonical)
    tick_scratch = Path(args.tick_scratch)
    fw = V3HoldoutFirewall()
    sched = AdaptiveScheduler(rate_per_sec=args.rate, max_concurrency=args.concurrency,
                              start_concurrency=args.concurrency, seed=7,
                              clock=time.monotonic, max_attempts=3)
    lock = Lock()
    flog = FetchLog(tick_scratch / "tick_fetch_log.json")

    audit_path = Path(args.audit)
    audit: dict[str, Any] = {}
    if audit_path.exists():
        audit = json.loads(audit_path.read_text()).get("units", {})

    units = manifest["units"]

    log = open(args.log, "a") if args.log else None
    t_start = time.monotonic()
    counts: dict[str, int] = {}
    processed = 0
    for u in units:
        if _STOP["flag"]:
            break
        if args.limit and processed >= args.limit:
            break  # bound the number of in-flight units processed this chunk
        key = u["key"]
        inst, iso = key.split(":")
        d = date.fromisoformat(iso)
        rec = store.units.get(key)
        if rec is None or rec.status not in _INFLIGHT:
            continue  # terminal (certified / absent / remediation-failed): skip (resumable)
        if rec.status == UnitStatus.INTEGRITY_FAILURE.value and \
                rec.fallback_reason == _REMEDIAL_FAILED:
            continue  # a prior remediation pass already left it a terminal integrity failure
        if rec.status == UnitStatus.INTEGRITY_FAILURE.value:
            store.begin_remediation(inst, d, u["category"])
        elif rec.status == UnitStatus.RETRYABLE.value:
            # a transient-retry unit must re-enter the pass via IN_PROGRESS (the state machine
            # does not allow RETRYABLE -> CERTIFIED_TICK_FALLBACK/TERMINAL_DATA_ABSENT directly).
            store.transition(inst, d, UnitStatus.IN_PROGRESS)
        # IN_PROGRESS (interrupted): already in the pass; re-process.

        sess = acquire_tick_session(sched, lock, fw, inst, d, tick_scratch, flog,
                                    args.concurrency)
        flog.save()
        if sess["tick_state"] == TICK_HAS_OBS:
            trows = ap.aggregate_m1(sess["ticks"])
            canon_trows = cm.canonicalize_tick_day(trows, d)
            tcert = ap.certify_partition(instrument=inst, year=d.year, month=d.month,
                                         day=d.day, side="bid", m1_rows=canon_trows,
                                         source_bytes=0,
                                         source_sha256=sess["tick_source_sha256"],
                                         request_urls=[])
            tick_audit = tcert["integrity_audit"]
        else:
            trows, canon_trows, tick_audit = [], [], None

        outcome = decide_remediation_outcome(category=u["category"],
                                             tick_state=sess["tick_state"],
                                             tick_audit=tick_audit)
        entry: dict[str, Any] = {
            "category": u["category"],
            "native_source_checksum": u["native_source_checksum"],
            "native_bid_ask_violations": u["native_bid_ask_violations"],
            "native_observed_minutes": u["native_observed_minutes"],
            "tick_state": sess["tick_state"],
            "decoded_tick_count": sess["decoded_tick_count"],
            "tick_source_sha256": sess["tick_source_sha256"],
            "tick_source_checksums": sess["tick_source_checksums"],
            "hour_states": sess["hour_states"],
        }
        if outcome == "CERTIFIED_TICK_FALLBACK":
            ch = _write_canonical(canon, inst, d, canon_trows)
            reason = (FALLBACK_REASON_BIDASK if u["category"] == CAT_BIDASK_ORDER
                      else FALLBACK_REASON_ZERO_OBS)
            store.transition(inst, d, UnitStatus.CERTIFIED_TICK_FALLBACK,
                             transport=Transport.TICK_AGGREGATED_M1.value,
                             fallback_reason=reason, source_checksum=sess["tick_source_sha256"],
                             canonical_checksum=ch, canonical_rows=len(trows))
            entry.update({"final_status": "CERTIFIED_TICK_FALLBACK",
                          "tick_canonical_checksum": ch,
                          "fallback_reason": reason,
                          "tick_bid_ask_violations": tick_audit["bid_ask_ordering_violations"]})
        elif outcome == "TERMINAL_DATA_ABSENT":
            store.transition(inst, d, UnitStatus.TERMINAL_DATA_ABSENT,
                             fallback_reason=ABSENT_REASON_CONFIRMED)
            entry.update({"final_status": "TERMINAL_DATA_ABSENT",
                          "fallback_reason": ABSENT_REASON_CONFIRMED})
        elif outcome == "RETRYABLE":
            store.transition(inst, d, UnitStatus.RETRYABLE,
                             fallback_reason="tick_transient_throttle_or_timeout")
            entry.update({"final_status": "RETRYABLE",
                          "fallback_reason": "tick_transient_throttle_or_timeout"})
        else:  # INTEGRITY_FAILURE
            store.transition(inst, d, UnitStatus.INTEGRITY_FAILURE,
                             fallback_reason="remediation_tick_still_failing")
            entry.update({"final_status": "INTEGRITY_FAILURE",
                          "fallback_reason": "remediation_tick_still_failing",
                          "tick_bid_ask_violations":
                              (tick_audit["bid_ask_ordering_violations"]
                               if tick_audit else None)})
        audit[key] = entry
        counts[outcome] = counts.get(outcome, 0) + 1
        processed += 1
        if log and (processed % 5 == 0 or processed == len(units)):
            line = (f"{datetime.now(timezone.utc).isoformat()} processed={processed} "
                    f"{json.dumps(counts)}")
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
        if processed % 5 == 0:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps(
                {"artifact_id": "V3_DATA_INTEGRITY_REMEDIATION_AUDIT_V1",
                 "remediation_contract_hash": remediation_contract_hash(),
                 "units": audit}, indent=0, sort_keys=True))

    if log:
        log.close()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(
        {"artifact_id": "V3_DATA_INTEGRITY_REMEDIATION_AUDIT_V1",
         "remediation_contract_hash": remediation_contract_hash(),
         "units": audit}, indent=2, sort_keys=True))
    s = store.summary()
    elapsed_h = (time.monotonic() - t_start) / 3600
    print(json.dumps({
        "processed": processed,
        "outcome_counts": counts,
        "state_summary": s,
        "elapsed_hours": round(elapsed_h, 4),
        "stop": _STOP["flag"],
    }, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="V3 targeted tick data-integrity remediation")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--state", required=True)
    m.add_argument("--scratch", required=True)
    m.add_argument("--manifest", required=True)
    m.set_defaults(func=lambda a: build_manifest(Path(a.state), Path(a.scratch),
                                                 Path(a.manifest)))
    r = sub.add_parser("run")
    r.add_argument("--state", required=True)
    r.add_argument("--canonical", required=True)
    r.add_argument("--scratch", required=True)
    r.add_argument("--tick-scratch", required=True, dest="tick_scratch")
    r.add_argument("--manifest", required=True)
    r.add_argument("--audit", required=True)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--rate", type=float, default=0.5)
    r.add_argument("--concurrency", type=int, default=2)
    r.add_argument("--log", default="")
    r.set_defaults(func=run)
    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
