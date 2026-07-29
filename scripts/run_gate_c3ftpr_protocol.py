"""Freeze Gate C.3F-TPR tick-to-M1 protocol before audit execution."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results" / "gate_c3ftpr"
DOCS_DIR = ROOT / "docs" / "research"
DOCUMENTED_PLAN_HASH = "bbcebd0b6cc0"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return sha256_file(path)


def write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def git_one(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip().splitlines()[0]


def build_protocol() -> dict[str, Any]:
    amended = json.loads((RESULTS_DIR / "amended_frozen_tick_audit_plan.json").read_text())
    if amended["status"] != "PROSPECTIVELY_FROZEN":
        raise RuntimeError("amended plan is not prospectively frozen")
    if amended["generated_candidate_hash"] != DOCUMENTED_PLAN_HASH:
        raise RuntimeError("amended plan hash mismatch")

    protocol = {
        "status": "FROZEN_BEFORE_AUDIT_EXECUTION",
        "created_at": datetime.now(UTC).isoformat(),
        "amendment_commit_sha": git_one("rev-parse", "HEAD"),
        "amended_plan_hash": amended["generated_candidate_hash"],
        "amended_plan_file_sha256": sha256_file(
            RESULTS_DIR / "amended_frozen_tick_audit_plan.json",
        ),
        "utc_policy": {
            "timezone": "UTC only",
            "dst": "not applicable after UTC normalization",
            "sunday_open": "classified by UTC timestamp; no local-time conversion",
            "friday_close": "classified by UTC timestamp; no local-time conversion",
        },
        "intervals": {
            "audit_window": "[window_start_utc, window_end_utc)",
            "minute": "[minute_start_utc, minute_start_utc + 60s)",
            "tick_on_minute_boundary": "belongs to minute starting at that timestamp",
            "partial_first_last_minutes": "excluded from equality summary, reported separately",
        },
        "ordering": {
            "primary": "provider timestamp ascending",
            "duplicate_timestamp": "stable provider/input order",
            "equal_timestamp_tie_break": "stable provider/input order",
            "out_of_order_ticks": "count and sort stably before aggregation",
        },
        "aggregation": {
            "open": "first tick in minute and side",
            "high": "maximum tick in minute and side",
            "low": "minimum tick in minute and side",
            "close": "last tick in minute and side",
        },
        "quantization": {
            "EURUSD": 100000,
            "GBPUSD": 100000,
            "USDJPY": 1000,
            "method": "round(price * scale) to integer raw points before comparison",
            "float_equality": "not used",
        },
        "flat_tick_policy": "preserve flat ticks; canonical ignoreFlats interaction reported",
        "zero_volume": "preserve if present; not used for OHLC equality",
        "missing_side": "side-specific generated bar missing; classify separately",
        "no_tick_minutes": "do not forward fill; classify missing tick-derived bars",
        "comparison_mask": {
            "timestamps": "exact common UTC minute timestamps after boundary exclusions",
            "bid_ohlc": "integer raw-point exact comparison",
            "ask_ohlc": "integer raw-point exact comparison",
            "canonical_m1_ignoreFlats": (
                "canonical provider notes indicate ignoreFlats=false for M1 acquisition; "
                "audit preserves flats and reports no-tick minutes separately"
            ),
        },
        "immutability": {
            "protocol_frozen_before_tick_download": True,
            "windows_frozen_before_tick_download": True,
            "tolerances_frozen_before_tick_download": True,
        },
    }
    protocol["protocol_hash"] = sha256_obj(protocol)
    return protocol


def main() -> None:
    amendment_commit = git_one("rev-parse", "HEAD")
    record_path = RESULTS_DIR / "amendment_record.json"
    record = json.loads(record_path.read_text())
    record["amendment_commit_sha"] = amendment_commit
    record["amendment_commit_recorded_at"] = datetime.now(UTC).isoformat()
    write_json(record_path, record)

    protocol = build_protocol()
    protocol_hash = write_json(RESULTS_DIR / "tick_to_m1_protocol.json", protocol)
    write_doc(
        DOCS_DIR / "GATE_C3FTPR_TICK_TO_M1_PROTOCOL.md",
        f"""# Gate C.3F-TPR Tick-To-M1 Protocol

Status: `{protocol['status']}`

Protocol hash: `{protocol_hash}`

For each UTC minute and side:

- open = first tick
- high = maximum tick
- low = minimum tick
- close = last tick

Minute and audit windows are left-closed/right-open. Ticks exactly on a
minute boundary belong to the minute starting at that timestamp. Duplicate
timestamps preserve provider/input order. EURUSD and GBPUSD use scale
`100000`; USDJPY uses scale `1000`. No-tick minutes are not forward-filled.

This protocol is frozen before any C3F-TPR tick-window download or comparison.
""",
    )
    print(json.dumps({
        "status": protocol["status"],
        "amendment_commit_sha": amendment_commit,
        "protocol_hash": protocol["protocol_hash"],
        "protocol_file_hash": protocol_hash,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
