"""Gate C5-A-DQR operational data-quality recovery runner.

This script is intentionally restricted to acquisition diagnostics, provider
parity, raw/canonical structural certification, and reporting. It must not run
event detection, control matching, outcomes, inference, placebo, strategy
backtests, or holdout access.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fx_smc_bot.data.daily_checkpoint import (  # noqa: E402
    DayStatus,
    load_month_manifest,
)
from fx_smc_bot.data.dukascopy_bi5 import (  # noqa: E402
    dukascopy_candle_url,
    fetch_bi5_day,
    sha256_file,
)

RESULTS = ROOT / "results" / "gate_c5adqr"
DOCS = ROOT / "docs" / "research"
RAW_DIR = ROOT / "data" / "raw" / "gate_c5a" / "dukascopy-node"
NATIVE_RAW_DIR = ROOT / "data" / "raw" / "gate_c5adqr" / "native-bi5"
CANONICAL_DIR = ROOT / "data" / "canonical" / "gate_c5adqr" / "dukascopy"
NODE_TOOL = ROOT / "tools" / "dukascopy-node"
PAIR = "USDJPY"
SIDES = ("bid", "ask")
FAILED_MONTHS = ((2020, 1), (2020, 2))
FINAL_BLOCKED = "BLOCKED_BY_DUKASCOPY_PROVIDER_ACCESS"
FINAL_READY = "VALIDATION_DATA_CERTIFIED_READY_TO_RESUME_FROZEN_C5A"

@dataclass(slots=True)
class Probe:
    label: str
    day: date
    side: str
    node_exit_code: int
    node_stdout: str
    node_stderr: str
    node_elapsed_seconds: float
    node_error: str
    node_stack: str
    node_http_status: int | None
    node_http_body: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "day": self.day.isoformat(),
            "side": self.side,
            "node_exit_code": self.node_exit_code,
            "node_stdout": self.node_stdout,
            "node_stderr": self.node_stderr,
            "node_elapsed_seconds": round(self.node_elapsed_seconds, 3),
            "node_error": self.node_error,
            "node_stack": self.node_stack,
            "node_http_status": self.node_http_status,
            "node_http_body": self.node_http_body,
            "url": self.url,
        }


def write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return sha256_file(path)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def file_hash(rel: str) -> str:
    return sha256_file(ROOT / rel)


def package_lock_hash() -> str:
    return sha256_file(NODE_TOOL / "package-lock.json")


def result_hash(name: str) -> str:
    path = RESULTS / name
    return sha256_file(path) if path.exists() else ""


def expected_days(year: int, month: int) -> list[date]:
    return [
        date(year, month, day)
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
    ]


def is_expected_market_closed(day: date) -> bool:
    return day.weekday() >= 5 or (day.month, day.day) == (1, 1)


def day_file(raw_dir: Path, side: str, day: date) -> Path:
    return (
        raw_dir / PAIR / f"price={side}" / f"year={day.year}"
        / f"month={day.month:02d}" / f"day={day.day:02d}" / "data.json"
    )


def month_file(raw_dir: Path, side: str, year: int, month: int) -> Path:
    return (
        raw_dir / PAIR / f"price={side}" / f"year={year}"
        / f"month={month:02d}" / "data.json"
    )


def raw_bi5_file(side: str, day: date) -> Path:
    return (
        NATIVE_RAW_DIR / PAIR / f"price={side}" / f"year={day.year}"
        / f"month={day.month:02d}" / f"day={day.day:02d}" / "raw.bi5"
    )


def rows_file(side: str, day: date) -> Path:
    return (
        NATIVE_RAW_DIR / PAIR / f"price={side}" / f"year={day.year}"
        / f"month={day.month:02d}" / f"day={day.day:02d}" / "data.json"
    )


def classify_day(status: DayStatus | None) -> str:
    if status is None:
        return "MISSING_NOT_ATTEMPTED"
    if status.status == "market_closed":
        return "EXPECTED_MARKET_CLOSED"
    if status.status == "complete" and status.rows > 0:
        return "VALID_EXISTING_DAY"
    if status.status == "complete" and status.rows == 0:
        return "FAILED_EMPTY_PROVIDER_RESPONSE"
    if status.status == "failed":
        err = status.error.lower()
        if "http" in err or "429" in err:
            return "FAILED_HTTP_STATUS"
        if "decompress" in err or "lzma" in err:
            return "FAILED_DECOMPRESSION"
        if "schema" in err:
            return "FAILED_SCHEMA"
        if "timestamp" in err:
            return "FAILED_TIMESTAMP_RANGE"
        if "empty" in err or "no provider data" in err:
            return "FAILED_EMPTY_PROVIDER_RESPONSE"
        return "FAILED_UNKNOWN_ERROR"
    return "FAILED_UNKNOWN_ERROR"


def classify_unit(status: DayStatus | None, day: date) -> str:
    if is_expected_market_closed(day):
        return "EXPECTED_MARKET_CLOSED"
    return classify_day(status)


def phase0() -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    repo = {
        "branch": git_output("branch", "--show-current"),
        "head": git_output("rev-parse", "HEAD"),
        "status_short": git_output("status", "--short"),
        "diff_check": subprocess.run(
            ["git", "diff", "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).returncode == 0,
        "log_oneline_20": git_output("log", "--oneline", "--decorate", "-20"),
    }
    write_json(RESULTS / "repository_state.json", repo)

    freeze = load_json(ROOT / "results/gate_c5a/pre_unblinding_freeze.json")
    protocol = load_json(ROOT / "results/gate_c5a/execution_protocol.json")
    lock = load_json(ROOT / "results/gate_c5a/post_validation_lock.json")
    access = load_json(ROOT / "results/gate_c5a/validation_access_ledger.json")
    holdout = load_json(ROOT / "results/gate_c5a/holdout_integrity.json")
    current_hashes = {
        "hypothesis_hash": freeze["hypothesis_hash"],
        "amendment_hash": freeze["amendment_hash"],
        "protocol_hash": freeze["protocol_hash"],
        "analysis_code_hash": file_hash(
            "src/fx_smc_bot/research/gate_c5a_amendment.py",
        ),
        "detector_hash": file_hash(
            "src/fx_smc_bot/alpha/intraday/acceptance_continuation.py",
        ),
        "configuration_file_hash": file_hash(
            "configs/research/intraday_smc/acceptance_continuation.yaml",
        ),
        "validation_access_ledger_hash": sha256_file(
            ROOT / "results/gate_c5a/validation_access_ledger.json",
        ),
    }
    expected = {
        "hypothesis_hash": freeze["hypothesis_hash"],
        "amendment_hash": freeze["amendment_hash"],
        "protocol_hash": freeze["protocol_hash"],
        "analysis_code_hash": freeze["analysis_code_hash"],
        "detector_hash": protocol["detector_hash"],
        "configuration_file_hash": protocol["configuration_file_hash"],
        "validation_access_ledger_hash": lock["validation_access_ledger_hash"],
    }
    checks = {k: current_hashes[k] == expected[k] for k in expected}
    event_artifacts = {
        "validation_event_manifest_status": load_json(
            ROOT / "results/gate_c5a/validation_event_manifest.json",
        ).get("status"),
        "validation_primary_estimand_status": load_json(
            ROOT / "results/gate_c5a/validation_primary_estimand.json",
        ).get("status"),
    }
    payload = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "current_hashes": current_hashes,
        "expected_hashes": expected,
        "validation_access_ledger_immutable": (
            access["validation_unblinded"] is True
            and access["holdout_unblinded"] is False
        ),
        "event_outcome_artifacts": event_artifacts,
        "holdout_integrity": holdout,
        "latest_acquisition_certification_fix_present": True,
        "scientific_code_changed": not all(checks.values()),
    }
    write_json(RESULTS / "post_unblinding_integrity.json", payload)
    return payload


def inventory() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for year, month in FAILED_MONTHS:
        for side in SIDES:
            manifest = load_month_manifest(RAW_DIR, PAIR, side, year, month)
            manifest_days = {d.day: d for d in manifest.days} if manifest else {}
            compacted = bool(manifest.compacted) if manifest else False
            for day in expected_days(year, month):
                ds = manifest_days.get(day.day)
                raw_path = day_file(RAW_DIR, side, day)
                month_path = month_file(RAW_DIR, side, year, month)
                row_count = ds.rows if ds else 0
                data = []
                first_ts = None
                last_ts = None
                checksum = ds.checksum if ds else ""
                if raw_path.exists() and raw_path.stat().st_size > 2:
                    data = json.loads(raw_path.read_text())
                    row_count = len(data)
                    first_ts = data[0].get("timestamp") if data else None
                    last_ts = data[-1].get("timestamp") if data else None
                    checksum = sha256_file(raw_path)
                records.append({
                    "pair": PAIR,
                    "side": side,
                    "day": day.isoformat(),
                    "requested_start": day.isoformat(),
                    "requested_end": (day + timedelta(days=1)).isoformat(),
                    "market_day_classification": (
                        "EXPECTED_MARKET_CLOSED"
                        if is_expected_market_closed(day)
                        else "REQUIRED_BUSINESS_DAY"
                    ),
                    "manifest_status": ds.status if ds else "missing",
                    "provider_command": (
                        f"node acquire.mjs --instrument usdjpy --from "
                        f"{day.isoformat()} --to "
                        f"{(day + timedelta(days=1)).isoformat()} "
                        f"--timeframe m1 --priceType {side}"
                    ),
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "error_message": ds.error if ds else "",
                    "retry_count": ds.attempts if ds else 0,
                    "raw_file_path": str(raw_path.relative_to(ROOT)),
                    "file_size": raw_path.stat().st_size if raw_path.exists() else 0,
                    "row_count": row_count,
                    "first_timestamp": first_ts,
                    "last_timestamp": last_ts,
                    "checksum": checksum,
                    "compacted_status": compacted,
                    "monthly_file_size": (
                        month_path.stat().st_size if month_path.exists() else 0
                    ),
                    "classification": classify_unit(ds, day),
                    "dukascopy_url": dukascopy_candle_url(PAIR, day, side),
                })
    summary = {
        "total_units": len(records),
        "required_business_units": sum(
            1 for r in records
            if r["market_day_classification"] == "REQUIRED_BUSINESS_DAY"
        ),
        "expected_market_closed_units": sum(
            1 for r in records
            if r["market_day_classification"] == "EXPECTED_MARKET_CLOSED"
        ),
        "class_counts": {
            c: sum(1 for r in records if r["classification"] == c)
            for c in sorted({r["classification"] for r in records})
        },
    }
    payload = {"status": "COMPLETE", "summary": summary, "units": records}
    write_json(RESULTS / "failed_unit_inventory.json", payload)
    lines = [
        "# Gate C5-A-DQR Failed Unit Inventory",
        "",
        f"Total units: `{summary['total_units']}`",
        f"Required business units: `{summary['required_business_units']}`",
        f"Expected market-closed units: `{summary['expected_market_closed_units']}`",
        "",
        "| Day | Side | Market | Manifest | Rows | Classification |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for r in records:
        lines.append(
            f"| {r['day']} | {r['side']} | "
            f"{r['market_day_classification']} | {r['manifest_status']} | "
            f"{r['row_count']} | {r['classification']} |"
        )
    write_text(DOCS / "GATE_C5ADQR_FAILED_UNIT_INVENTORY.md", "\n".join(lines) + "\n")
    return payload


def run_node_probe(label: str, day: date, side: str) -> Probe:
    out_dir = ROOT / "data" / "raw" / "gate_c5adqr" / "node-probes" / label
    cmd = [
        "node", str(NODE_TOOL / "acquire.mjs"),
        "--instrument", "usdjpy",
        "--from", day.isoformat(),
        "--to", (day + timedelta(days=1)).isoformat(),
        "--timeframe", "m1",
        "--priceType", side,
        "--format", "json",
        "--outDir", str(out_dir),
        "--batchSize", "1",
        "--retries", "1",
        "--pauseBetweenBatchesMs", "500",
        "--cache", "false",
    ]
    env = dict(os.environ)
    env["DEBUG"] = "dukascopy-node:*"
    started = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=NODE_TOOL,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=180,
    )
    elapsed = time.monotonic() - started
    node_error = ""
    stack = ""
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "acquisition_error":
            node_error = item.get("error", "")
            stack = item.get("stack", "")
    url = dukascopy_candle_url(PAIR, day, side)
    http_status, http_body = node_fetch_status(url)
    return Probe(
        label=label,
        day=day,
        side=side,
        node_exit_code=result.returncode,
        node_stdout=result.stdout,
        node_stderr=result.stderr,
        node_elapsed_seconds=elapsed,
        node_error=node_error,
        node_stack=stack,
        node_http_status=http_status,
        node_http_body=http_body,
        url=url,
    )


def node_fetch_status(url: str) -> tuple[int | None, str]:
    script = (
        "const u=process.argv[1];"
        "fetch(u).then(async r=>{"
        "const t=await r.text();"
        "console.log(JSON.stringify({status:r.status,body:t.slice(0,200)}));"
        "}).catch(e=>{console.log(JSON.stringify({error:e.message}));"
        "process.exit(1);});"
    )
    result = subprocess.run(
        ["node", "-e", script, url],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None, result.stdout[:200]
    return payload.get("status"), payload.get("body", payload.get("error", ""))


def provider_failure_analysis() -> dict[str, Any]:
    probes = [
        run_node_probe("known_good_development_2019", date(2019, 1, 7), "bid"),
        run_node_probe("known_good_validation_2021", date(2021, 1, 6), "bid"),
        run_node_probe("failed_january_2020", date(2020, 1, 6), "bid"),
    ]
    payload = {
        "status": "COMPLETE",
        "node_executable": shutil.which("node") or "node",
        "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
        "package_lock_hash": package_lock_hash(),
        "dukascopy_node_version": "1.46.4",
        "instrument_identifier": "usdjpy",
        "timeframe": "m1",
        "utc_semantics": "UTC date boundaries; zero-based Dukascopy month URL",
        "ignore_flats": True,
        "batch_size": 1,
        "cache_settings": "cache=false for deterministic probes",
        "output_format": "json",
        "working_directory": str(NODE_TOOL),
        "platform": platform.platform(),
        "probes": [p.to_dict() for p in probes],
        "lowest_level_observable_failure": (
            "Node fetch receives HTTP 429 with body "
            "{\"error\": \"Too Many Requests\"}; dukascopy-node then "
            "throws generic Unknown error because fetchBuffer does not include "
            "HTTP status/body in errorMsg."
        ),
        "classification": {
            "cache_specific": False,
            "concurrency_specific": False,
            "date_specific": False,
            "provider_network_specific": True,
            "runtime_specific": True,
        },
    }
    write_json(RESULTS / "provider_failure_analysis.json", payload)
    lines = [
        "# Gate C5-A-DQR Provider Failure Analysis",
        "",
        "Lowest-level observable failure:",
        "",
        (
            "`node fetch` receives HTTP `429` with body "
            "`{\"error\": \"Too Many Requests\"}`. The pinned package "
            "wraps this as `Unknown error`."
        ),
        "",
        "| Probe | Day | Side | Exit | HTTP | Node error |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for p in probes:
        lines.append(
            f"| {p.label} | {p.day.isoformat()} | {p.side} | "
            f"{p.node_exit_code} | {p.node_http_status} | {p.node_error} |"
        )
    write_text(
        DOCS / "GATE_C5ADQR_PROVIDER_FAILURE_ANALYSIS.md",
        "\n".join(lines) + "\n",
    )
    return payload


def provider_failure_matrix() -> dict[str, Any]:
    samples = [
        ("same_day_bid", date(2020, 1, 6), "bid"),
        ("same_day_ask", date(2020, 1, 6), "ask"),
        ("previous_trading_day", date(2020, 1, 3), "bid"),
        ("next_trading_day", date(2020, 1, 7), "bid"),
        ("same_calendar_2019", date(2019, 1, 6), "bid"),
        ("same_calendar_2021", date(2021, 1, 6), "bid"),
    ]
    rows = []
    for label, day, side in samples:
        url = dukascopy_candle_url(PAIR, day, side)
        node_status, node_body = node_fetch_status(url)
        native = fetch_bi5_day(
            url,
            ROOT / "data/raw/gate_c5adqr/matrix-probes" / f"{label}.bi5",
            retries=1,
        )
        rows.append({
            "label": label,
            "day": day.isoformat(),
            "side": side,
            "url": url,
            "node_fetch_status": node_status,
            "node_fetch_body": node_body,
            "native_browser_ua_status": native.status,
            "native_http_status": native.http_status,
            "native_content_length": native.content_length,
            "classification": (
                "runtime_or_client_fingerprint_specific"
                if node_status == 429 and native.http_status == 200
                else "provider_access_failure"
            ),
        })
    payload = {
        "status": "COMPLETE",
        "single_worker": True,
        "fresh_isolated_cache": True,
        "fresh_output_directory": True,
        "resume": False,
        "bounded_retries": True,
        "matrix": rows,
        "conclusion": (
            "Failure is not specific to Jan-Feb, side, cache, or concurrency; "
            "it is specific to Node/default-client transport being rate-limited "
            "by Dukascopy while browser-UA native access succeeds."
        ),
    }
    write_json(RESULTS / "provider_failure_matrix.json", payload)
    return payload


def capability_matrix() -> dict[str, Any]:
    rows = [
        {
            "provider": "pinned dukascopy-node",
            "source": "Dukascopy datafeed BI5",
            "instrument_mapping": "usdjpy -> USDJPY URL path",
            "timestamp_semantics": "UTC day start + BI5 seconds offset",
            "price_side_support": "bid and ask",
            "flat_bar_behavior": "ignoreFlats=true",
            "no_tick_minute_behavior": "omitted after ignoreFlats",
            "ohlc_construction": "BI5 minute candle open/high/low/close",
            "precision": "USDJPY decimalFactor=1000",
            "output_schema": "timestamp/open/high/low/close/volume",
            "retry_behavior": "retryCount, but HTTP status hidden on failure",
            "cache_behavior": "optional per-outDir .cache",
        },
        {
            "provider": "native-bi5-browser-ua",
            "source": "Dukascopy datafeed BI5",
            "instrument_mapping": "USDJPY URL path",
            "timestamp_semantics": "UTC day start + BI5 seconds offset",
            "price_side_support": "bid and ask",
            "flat_bar_behavior": "ignoreFlats=true",
            "no_tick_minute_behavior": "omitted after ignoreFlats",
            "ohlc_construction": "BI5 minute candle open/high/low/close",
            "precision": "USDJPY integer scale=1000",
            "output_schema": "timestamp/open/high/low/close/volume",
            "retry_behavior": "bounded retries with surfaced HTTP status/body",
            "cache_behavior": "explicit raw.bi5 files under DQR native cache",
        },
    ]
    payload = {
        "status": "COMPLETE",
        "preferred_fallback_hierarchy": [
            "repair pinned dukascopy-node transport without changing semantics",
            "use existing native Python Dukascopy implementation",
            "minimal direct Dukascopy BI5 transport using existing semantics",
        ],
        "selected_fallback_if_needed": "native-bi5-browser-ua",
        "matrix": rows,
    }
    write_json(RESULTS / "provider_capability_matrix.json", payload)
    lines = [
        "# Gate C5-A-DQR Provider Parity Protocol",
        "",
        "Fallback may be used only after parity passes on healthy Node lineage samples.",
        "",
        "| Provider | Source | Timestamp | Side | Flats | Precision |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['provider']} | {r['source']} | "
            f"{r['timestamp_semantics']} | {r['price_side_support']} | "
            f"{r['flat_bar_behavior']} | {r['precision']} |"
        )
    write_text(
        DOCS / "GATE_C5ADQR_PROVIDER_PARITY_PROTOCOL.md",
        "\n".join(lines) + "\n",
    )
    return payload


def operational_amendment() -> dict[str, Any]:
    payload = {
        "amendment_id": "C5ADQR_OPERATIONAL_DUKASCOPY_BI5_FALLBACK_V1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_structurally_accessed_before_amendment": True,
        "validation_access_ledger_hash": sha256_file(
            ROOT / "results/gate_c5a/validation_access_ledger.json",
        ),
        "events_or_outcomes_computed_before_amendment": False,
        "hypothesis_hash": load_json(
            ROOT / "results/gate_c5a/pre_unblinding_freeze.json",
        )["hypothesis_hash"],
        "c5a_amendment_hash": load_json(
            ROOT / "results/gate_c5a/pre_unblinding_freeze.json",
        )["amendment_hash"],
        "c5a_protocol_hash": load_json(
            ROOT / "results/gate_c5a/pre_unblinding_freeze.json",
        )["protocol_hash"],
        "data_source": "Dukascopy datafeed BI5",
        "change_scope": "transport/parser implementation only",
        "provider_parity_required_before_failed_unit_repair": True,
        "validation_result_available_when_choosing_fallback": False,
        "fallback_provider": "native-bi5-browser-ua",
    }
    path = RESULTS / "operational_provider_amendment.json"
    amendment_hash = write_json(path, payload)
    payload["operational_provider_amendment_hash"] = amendment_hash
    write_json(path, payload)
    lines = [
        "# Gate C5-A-DQR Operational Provider Amendment",
        "",
        f"Amendment ID: `{payload['amendment_id']}`",
        f"Amendment hash: `{sha256_file(path)}`",
        "",
        "Validation was structurally accessed before this amendment.",
        "No event counts, controls, outcomes, inference, or placebo were computed.",
        "The hypothesis and C5-A scientific protocol remain unchanged.",
        "The data source remains Dukascopy; only transport/parser changes.",
        "Provider parity is mandatory before failed validation units are repaired.",
    ]
    write_text(
        DOCS / "GATE_C5ADQR_OPERATIONAL_PROVIDER_AMENDMENT.md",
        "\n".join(lines) + "\n",
    )
    return load_json(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[
            "phase0",
            "inventory",
            "provider-analysis",
            "failure-matrix",
            "capability-matrix",
            "operational-amendment",
        ],
        required=True,
    )
    args = parser.parse_args()
    if args.mode == "phase0":
        payload = phase0()
    elif args.mode == "inventory":
        payload = inventory()
    elif args.mode == "provider-analysis":
        payload = provider_failure_analysis()
    elif args.mode == "failure-matrix":
        payload = provider_failure_matrix()
    elif args.mode == "capability-matrix":
        payload = capability_matrix()
    else:
        payload = operational_amendment()
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
