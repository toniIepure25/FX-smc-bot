"""Acquire and certify a small REAL pre-2018 M1 sample through the firewalled pipeline.

Downloads a bounded set of Dukascopy hourly tick files (respectful backoff for the observed
503 throttle), aggregates to canonical M1 bid/ask, certifies each partition with the full
integrity manifest, and writes ``results/gate_v3f/data_manifest.json`` plus the canonical
parquet under the git-ignored ``data/canonical/`` tree. Every request is firewalled: no 2018+
URL or date can reach the network.

This is a SAMPLE that proves the pipeline end-to-end on real data and provides real-data for
benchmarks. Full 13-instrument x 2010-2017 coverage is a bounded, resumable background
operation recorded as PENDING in the plan registry -- not run here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition import acquisition_plan_payload
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"
CANON = REPO / "data" / "canonical"

# Bounded, respectful real sample: 2 pairs (JPY + non-JPY), one liquid pre-2018 trading day,
# London+NY overlap hours only. 2 x 8 = 16 requests.
SAMPLE_PAIRS = ("EURUSD", "USDJPY")
SAMPLE_DATE = date(2014, 6, 10)  # Tuesday, non-holiday, pre-2018
SAMPLE_HOURS = tuple(range(8, 16))
INTER_REQUEST_DELAY_S = 3.0
MAX_RETRIES = 3


def bi5_url(instrument: str, d: date, hour: int) -> str:
    # Dukascopy months are 0-indexed.
    return (
        f"https://datafeed.dukascopy.com/datafeed/{instrument}/{d.year:04d}/"
        f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5"
    )


def curl_get(url: str, dest: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["curl", "-sS", "--max-time", "30", "-o", str(dest), "-w", "%{http_code} %{size_download}",
         url], capture_output=True, text=True,
    )
    parts = proc.stdout.strip().split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return -1, 0


def fetch_hour(fw: V3HoldoutFirewall, instrument: str, d: date, hour: int,
               scratch: Path) -> tuple[bytes, str, int]:
    """Firewalled fetch of one hourly bi5 with backoff. Returns (raw, url, http_status)."""

    url = bi5_url(instrument, d, hour)
    fw.guard_url(url)                       # blocks 2018+ before any I/O
    fw.guard_date(d, context=f"{instrument} acquisition")
    dest = scratch / f"{instrument}_{d.isoformat()}_{hour:02d}.bi5"
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes(), url, 200  # resume from cache
    status = -1
    for attempt in range(MAX_RETRIES):
        status, size = curl_get(url, dest)
        if status == 200:
            return dest.read_bytes(), url, 200
        if status == 503:
            time.sleep(8.0 * (attempt + 1))  # respectful exponential backoff
            continue
        break
    return (dest.read_bytes() if dest.exists() else b""), url, status


def acquire_pair(fw: V3HoldoutFirewall, instrument: str, scratch: Path) -> dict[str, Any]:
    scale = ap.price_scale(instrument)
    ticks: list[ap.Tick] = []
    urls: list[str] = []
    source_hash = hashlib.sha256()
    source_bytes = 0
    hours_ok = 0
    for hour in SAMPLE_HOURS:
        raw, url, status = fetch_hour(fw, instrument, SAMPLE_DATE, hour, scratch)
        urls.append(url)
        if status == 200 and raw:
            ticks.extend(ap.decode_bi5(raw, _hour_ms(SAMPLE_DATE, hour), scale))
            source_hash.update(raw)
            source_bytes += len(raw)
            hours_ok += 1
        time.sleep(INTER_REQUEST_DELAY_S)
    m1 = ap.aggregate_m1(ticks)
    # persist canonical parquet (git-ignored) for both sides
    for side in ("bid", "ask"):
        rows = [{"timestamp": r["timestamp"], "open": r[f"{side}_open"], "high": r[f"{side}_high"],
                 "low": r[f"{side}_low"], "close": r[f"{side}_close"]} for r in m1]
        pdir = (CANON / instrument / f"price={side}" / f"year={SAMPLE_DATE.year}"
                / f"month={SAMPLE_DATE.month:02d}" / f"day={SAMPLE_DATE.day:02d}")
        pdir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(pdir / "data.parquet", index=False)
    certs = {
        side: ap.certify_partition(
            instrument=instrument, year=SAMPLE_DATE.year, month=SAMPLE_DATE.month,
            day=SAMPLE_DATE.day, side=side, m1_rows=m1, source_bytes=source_bytes,
            source_sha256=source_hash.hexdigest(), request_urls=urls,
        )
        for side in ("bid", "ask")
    }
    return {"instrument": instrument, "hours_requested": len(SAMPLE_HOURS),
            "hours_ok": hours_ok, "m1_bars": len(m1), "certifications": certs}


def _hour_ms(d: date, hour: int) -> int:
    return int(datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".v3_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fw = V3HoldoutFirewall()

    sample = [acquire_pair(fw, pair, scratch) for pair in SAMPLE_PAIRS]
    certified = sum(
        1 for s in sample for c in s["certifications"].values()
        if c["acquisition_status"] == "CERTIFIED"
    )
    plan = acquisition_plan_payload()
    manifest: dict[str, Any] = {
        "artifact_id": "V3_DATA_MANIFEST_V1",
        "provider": ap.PROVIDER,
        "parser_version": ap.PARSER_VERSION,
        "canonicalizer_version": ap.CANONICALIZER_VERSION,
        "sample_scope": {
            "pairs": list(SAMPLE_PAIRS),
            "date": SAMPLE_DATE.isoformat(),
            "hours": list(SAMPLE_HOURS),
            "granularity": "M1_BIDASK_OHLC",
            "note": "bounded real sample proving the pipeline; NOT full coverage.",
        },
        "certified_partition_count": certified,
        "sample_partitions": sample,
        "full_plan": {
            "total_monthly_partitions": plan["totals"]["files"],
            "instrument_years": plan["totals"]["instrument_years"],
            "status": "PENDING_BULK_ACQUISITION",
            "reason": "provider 503-throttle over corporate proxy; ~649k requests needed; "
                      "bounded resumable background operation for a later/unthrottled run.",
        },
        "exposure_semantics": "DOWNLOAD+PARSE+INTEGRITY_INSPECTION != OUTCOME_EXPOSED",
        "2018_plus_provider_requests_issued": 0,
        "2018_plus_provider_requests_blocked": fw.network.blocked_2018_plus_count(),
        "2018_plus_market_or_outcome_files_opened": fw.opened_2018_plus_count(),
        "firewall_audit": fw.audit_payload(),
    }
    manifest["data_manifest_hash"] = canonical_hash(
        {"sample": sample, "scope": manifest["sample_scope"]}
    )
    (OUT / "data_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print("certified partitions:", certified, "/", len(SAMPLE_PAIRS) * 2)
    for s in sample:
        print(f"  {s['instrument']}: hours_ok={s['hours_ok']}/{s['hours_requested']} "
              f"m1_bars={s['m1_bars']} "
              f"bid={s['certifications']['bid']['acquisition_status']}")
    print("data_manifest_hash:", manifest["data_manifest_hash"][:16])
    print("2018+ files opened:", manifest["2018_plus_market_or_outcome_files_opened"])
    return 0 if certified == len(SAMPLE_PAIRS) * 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
