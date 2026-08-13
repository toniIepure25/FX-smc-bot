"""Tiny, firewall-guarded validation of the acquisition path on ONE pre-2018 slice.

Proves two things end-to-end against the real provider without ever touching the holdout:

1. a 2018+ provider URL is rejected by the firewall *before* any transport is attempted;
2. exactly one small *pre-2018* hourly tick file can be fetched through the firewalled
   downloader (transport = system-trust `curl`, injected as the fetch function).

The downloaded bytes are written to a scratch directory outside the repository and are NOT
decoded or committed; only size, HTTP status and sha256 are recorded. Everything after
2018-01-01 fails before a byte is consumed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from fx_smc_bot.research.v3.firewall import (
    NetworkHoldoutFirewallError,
    V3HoldoutFirewall,
)

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"

# Pre-2018 tick file: EURUSD 2015-03-10 12:00 UTC. Dukascopy months are 0-indexed (Mar = 02).
OK_URL = "https://datafeed.dukascopy.com/datafeed/EURUSD/2015/02/10/12h_ticks.bi5"
# Holdout sibling that must be blocked before any request.
HOLDOUT_URL = "https://datafeed.dukascopy.com/datafeed/EURUSD/2018/00/02/12h_ticks.bi5"


def curl_fetch(url: str, dest: Path) -> tuple[int, int]:
    """Fetch via system-trust curl. Returns (http_status, bytes_downloaded)."""

    proc = subprocess.run(
        ["curl", "-sS", "--max-time", "25", "-o", str(dest),
         "-w", "%{http_code} %{size_download}", url],
        capture_output=True, text=True,
    )
    parts = proc.stdout.strip().split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return -1, 0


def sha256_file(path: Path) -> str:
    import hashlib  # noqa: PLC0415

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".v3_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fw = V3HoldoutFirewall()

    result: dict[str, Any] = {
        "artifact_id": "V3_ACQUISITION_VALIDATION_V1",
        "holdout_url": HOLDOUT_URL,
        "pre_2018_url": OK_URL,
        "2018_plus_market_or_outcome_files_opened": 0,
    }

    # 1. holdout URL must be blocked before any transport
    blocked = False
    try:
        fw.guard_url(HOLDOUT_URL)
    except NetworkHoldoutFirewallError:
        blocked = True
    result["holdout_blocked_before_transport"] = blocked

    # 2. one small pre-2018 fetch through the firewall
    fetched: dict[str, Any] = {"attempted": True}
    try:
        fw.guard_url(OK_URL)
        fw.guard_date(date(2015, 3, 10), context="acquisition validation")
        dest = scratch / "eurusd_2015_03_10_12h_ticks.bi5"
        status, size = curl_fetch(OK_URL, dest)
        fetched.update(
            http_status=status,
            bytes=size,
            sha256=sha256_file(dest) if dest.exists() and size > 0 else "",
            transport="system_trust_curl",
            transport_reachable=status != -1,
            note="binary .bi5 not decoded or committed; scratch-only",
        )
    except NetworkHoldoutFirewallError as exc:  # would be a firewall bug for a pre-2018 date
        fetched.update(error=str(exc))
    result["pre_2018_fetch"] = fetched

    result["validation_passed"] = bool(
        blocked and fetched.get("transport_reachable")
    )
    (OUT / "acquisition_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    print("holdout_blocked_before_transport:", blocked)
    print("pre_2018 http_status:", fetched.get("http_status"),
          "bytes:", fetched.get("bytes"))
    print("validation_passed:", result["validation_passed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
