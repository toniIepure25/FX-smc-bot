"""Dedicated, fast, resumable RAW TICK DOWNLOAD phase for the V3 integrity remediation.

This is a TRANSPORT-ONLY phase: it fetches the exact tick-hour files enumerated by the FROZEN
targeted manifest (``V3_TARGETED_TICK_MANIFEST_V1``) and records each file's terminal transport
state. It performs NO decoding, NO aggregation, NO certification and NO remediation -- those are
the separate, fully-OFFLINE remediation phase (``remediate_integrity.py``).

Engineering pattern (same as the native-M1 durable runner, adapted because this curl build has no
HTTP/2): bounded-parallel ``curl --parallel`` batches with connection reuse, explicit request-start
pacing between batches, a resumable source cache (the tick scratch dir + the fetch log), SHA256,
and a transport status log. Already-legitimate files (a genuine 200 of any size, including a
0-byte no-data hour, or a genuine 404) are reused and never redownloaded.

Terminal transport states per tick-hour file:
  DOWNLOADED_VALID  -- a genuine HTTP 200 (any size, including 0 bytes = no-data hour);
  SOURCE_404        -- a genuine HTTP 404 (the hour is legitimately absent);
  RETRYABLE         -- 429/502/503/504/timeout/connection failure (NOT a terminal state; retried).

Never use IP rotation, proxy evasion, multiple workers, or TLS bypass. Concurrency is calibrated
over c1/c2/c4 only (no aggressive c8/c16).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

from fx_smc_bot.research.v3._hashing import canonical_hash  # noqa: E402
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall  # noqa: E402

_STOP = {"flag": False}

# Terminal transport states for a tick-hour file.
DOWNLOADED_VALID = "DOWNLOADED_VALID"
SOURCE_404 = "SOURCE_404"
RETRYABLE = "RETRYABLE"


@dataclass(frozen=True, slots=True)
class TickTarget:
    key: str          # "{inst}_{isodate}_{hh}h"
    url: str
    inst: str
    day: date
    hour: int
    dest: Path


def _install_signals() -> None:
    def handler(signum: int, _frame: object) -> None:
        _STOP["flag"] = True
        print(f"[signal {signum}] finishing current batch then exiting...", flush=True)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


def _file_key(inst: str, d: date, hour: int) -> str:
    return f"{inst}_{d.isoformat()}_{hour:02d}h"


class FetchLog:
    """Persistent, resumable record of which tick-hours reached a legitimate transport state.

    A tick-hour is terminal once it is ``DOWNLOADED_VALID`` (a genuine 200 of any size, including
    a 0-byte no-data hour) or ``SOURCE_404`` (a genuine 404). Transient failures (429/502/503/504/
    timeout/connection failure) are NOT recorded as terminal, so they are retried on the next run.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            self.entries = json.loads(path.read_text())

    def get(self, key: str) -> dict[str, Any] | None:
        return self.entries.get(key)

    def is_terminal(self, key: str) -> bool:
        # Backward-compatible: the prior remediation runner recorded "ok" (== DOWNLOADED_VALID)
        # and "missing" (== SOURCE_404). Both are legitimate terminal transport states.
        e = self.entries.get(key)
        return e is not None and e.get("status") in (DOWNLOADED_VALID, SOURCE_404, "ok", "missing")

    def mark(self, key: str, status: str, sha256: str = "", nbytes: int = 0) -> None:
        self.entries[key] = {"status": status, "sha256": sha256, "bytes": nbytes}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, sort_keys=True))
        tmp.replace(self.path)


def _load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    m = json.loads(manifest_path.read_text())
    if canonical_hash(m["units"]) != m["manifest_hash"]:
        raise SystemExit("manifest hash mismatch -- refusing to run on a tampered manifest")
    return m["units"]


def _all_targets(units: list[dict[str, Any]], tick_scratch: Path) -> list[TickTarget]:
    """Enumerate the exact frozen tick-hour universe (435 units / 9,007 files) with dest paths."""

    out: list[TickTarget] = []
    for u in units:
        inst = u["instrument"]
        d = date.fromisoformat(u["day"])
        for h in u["session_hours"]:
            key = _file_key(inst, d, h)
            out.append(TickTarget(
                key=key, url=_tick_url(inst, d, h), inst=inst, day=d, hour=h,
                dest=tick_scratch / f"{key}_ticks.bi5",
            ))
    return out


def _curl_batch(targets: list[TickTarget], parallel_max: int) -> dict[str, tuple[int, float]]:
    """Bounded-parallel fetch of a batch (connection reuse). Returns {url: (code, time_total)}.

    Uses ``-o <dest> <url>`` per target (NOT a ``--config`` file): curl 8.x on Windows/Schannel
    silently drops the ``output =`` directive in a parallel config, so files would be fetched
    but never written. Per-URL ``-o`` is verified to write the files.
    """

    if not targets:
        return {}
    cmd: list[str] = ["curl", "-sS", "--parallel", "--parallel-max", str(parallel_max),
                      "-w", "%{url_effective} %{http_code} %{time_total}\n",
                      "--max-time", "90", "--retry", "0"]
    for t in targets:
        cmd.extend(["-o", str(t.dest), t.url])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out: dict[str, tuple[int, float]] = {}
    for line in proc.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-2].isdigit():
            out[" ".join(parts[:-2])] = (int(parts[-2]), float(parts[-1]))
    return out


def _classify_http(code: int) -> str:
    if code == 200:
        return DOWNLOADED_VALID
    if code == 404:
        return SOURCE_404
    return RETRYABLE  # 429/502/503/504/other/-1 (timeout/conn failure)


def _download_batch(fw: V3HoldoutFirewall, batch: list[TickTarget], flog: FetchLog,
                    parallel_max: int) -> dict[str, int]:
    """Fetch one batch of pending tick-hours; update the fetch log. Returns status counts."""

    counts: dict[str, int] = {}
    if not batch:
        return counts
    for t in batch:  # firewall BEFORE scheduling any transport (a 2018+ URL would raise)
        fw.guard_url(t.url)
        fw.guard_date(t.day, context="raw tick download")
    results = _curl_batch(batch, parallel_max)
    for t in batch:
        code, _t = results.get(t.url, (-1, 0.0))
        status = _classify_http(code)
        if status == DOWNLOADED_VALID:
            raw = t.dest.read_bytes() if t.dest.exists() else b""
            flog.mark(t.key, status, hashlib.sha256(raw).hexdigest(), len(raw))
        elif status == SOURCE_404:
            flog.mark(t.key, status)
        # RETRYABLE: not recorded as terminal -> retried next batch/run.
        counts[status] = counts.get(status, 0) + 1
    return counts


def _progress(flog: FetchLog, total: int) -> dict[str, int]:
    # Backward-compatible: count the prior runner's "ok"/"missing" as valid/404.
    dv = sum(1 for e in flog.entries.values()
             if e.get("status") in (DOWNLOADED_VALID, "ok"))
    s404 = sum(1 for e in flog.entries.values()
               if e.get("status") in (SOURCE_404, "missing"))
    return {"total": total, "downloaded_valid": dv, "source_404": s404,
            "pending": total - dv - s404}


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Run a small calibration batch at c1/c2/c4 and report sustained terminal files/sec."""

    _install_signals()
    units = _load_manifest(Path(args.manifest))
    tick_scratch = Path(args.tick_scratch)
    tick_scratch.mkdir(parents=True, exist_ok=True)
    flog = FetchLog(tick_scratch / "tick_fetch_log.json")
    fw = V3HoldoutFirewall()
    all_targets = _all_targets(units, tick_scratch)
    pending = [t for t in all_targets if not flog.is_terminal(t.key)]
    per = args.calibrate_size
    report: dict[str, Any] = {}
    for c in (1, 2, 4):
        if _STOP["flag"]:
            break
        batch, pending = pending[:per], pending[per:]
        t0 = time.monotonic()
        counts = _download_batch(fw, batch, flog, c)
        flog.save()
        dt = time.monotonic() - t0
        ok = counts.get(DOWNLOADED_VALID, 0) + counts.get(SOURCE_404, 0)
        report[f"c{c}"] = {
            "files_attempted": len(batch),
            "downloaded_valid": counts.get(DOWNLOADED_VALID, 0),
            "source_404": counts.get(SOURCE_404, 0),
            "retryable": counts.get(RETRYABLE, 0),
            "wall_s": round(dt, 1),
            "terminal_files_per_sec": round(ok / dt, 3) if dt > 0 else 0.0,
        }
        print(f"c{c}: {json.dumps(report[f'c{c}'])}", flush=True)
    out = tick_scratch / "tick_calibration.json"
    out.write_text(json.dumps({"artifact_id": "V3_TICK_DOWNLOAD_CALIBRATION_V1",
                               "calibrate_size": per, "profiles": report},
                              indent=2, sort_keys=True))
    print(json.dumps(report, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Download every pending tick-hour at the chosen concurrency (resumable)."""

    _install_signals()
    units = _load_manifest(Path(args.manifest))
    tick_scratch = Path(args.tick_scratch)
    tick_scratch.mkdir(parents=True, exist_ok=True)
    flog = FetchLog(tick_scratch / "tick_fetch_log.json")
    fw = V3HoldoutFirewall()
    all_targets = _all_targets(units, tick_scratch)
    total = len(all_targets)
    log = open(args.log, "a") if args.log else None
    t_start = time.monotonic()
    batch_no = 0
    while not _STOP["flag"]:
        pending = [t for t in all_targets if not flog.is_terminal(t.key)]
        if not pending:
            break
        if args.limit and batch_no * args.batch_size >= args.limit:
            break
        batch = pending[:args.batch_size]
        batch_no += 1
        counts = _download_batch(fw, batch, flog, args.concurrency)
        flog.save()
        prog = _progress(flog, total)
        elapsed = time.monotonic() - t_start
        line = (f"{datetime.now(timezone.utc).isoformat()} batch={batch_no} "
                f"conc={args.concurrency} {json.dumps(counts)} "
                f"valid={prog['downloaded_valid']} 404={prog['source_404']} "
                f"pending={prog['pending']} elapsed_s={round(elapsed, 1)}")
        print(line, flush=True)
        if log:
            log.write(line + "\n")
            log.flush()
        time.sleep(args.pace_s)  # explicit request-start pacing between batches
    if log:
        log.close()
    prog = _progress(flog, total)
    elapsed = time.monotonic() - t_start
    terminal = prog["downloaded_valid"] + prog["source_404"]
    summary = {
        "artifact_id": "V3_TICK_DOWNLOAD_RUN_V1",
        "total_expected": total,
        "downloaded_valid": prog["downloaded_valid"],
        "source_404": prog["source_404"],
        "retryable_pending": prog["pending"],
        "elapsed_s": round(elapsed, 1),
        "terminal_files_per_sec": round(terminal / elapsed, 3) if elapsed > 0 else 0.0,
        "stop": _STOP["flag"],
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    units = _load_manifest(Path(args.manifest))
    tick_scratch = Path(args.tick_scratch)
    flog = FetchLog(tick_scratch / "tick_fetch_log.json")
    total = len(_all_targets(units, tick_scratch))
    print(json.dumps(_progress(flog, total), indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Dedicated fast resumable raw tick download")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("calibrate", "run", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--manifest", required=True)
        sp.add_argument("--tick-scratch", required=True, dest="tick_scratch")
    sub.choices["calibrate"].add_argument("--calibrate-size", type=int, default=30,
                                          dest="calibrate_size")
    sub.choices["run"].add_argument("--concurrency", type=int, default=4)
    sub.choices["run"].add_argument("--batch-size", type=int, default=40, dest="batch_size")
    sub.choices["run"].add_argument("--pace-s", type=float, default=1.0, dest="pace_s")
    sub.choices["run"].add_argument("--limit", type=int, default=0)
    sub.choices["run"].add_argument("--log", default="")
    sub.choices["calibrate"].set_defaults(func=cmd_calibrate)
    sub.choices["run"].set_defaults(func=cmd_run)
    sub.choices["status"].set_defaults(func=cmd_status)
    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
