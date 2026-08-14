"""Dukascopy tick -> canonical M1 bid/ask pipeline with per-partition certification.

Pure, testable acquisition logic: decode Dukascopy ``.bi5`` hourly tick files, aggregate to
M1 bid/ask OHLC, and certify each partition with the full integrity manifest the gate
requires. Transport is injected (see ``scripts/v3/run_acquisition.py`` for the firewalled
curl transport) so this module needs no network and can be unit-tested on bytes.

Hard boundaries: this module parses and validates data integrity only. It computes NO V3
signals, P&L, rankings or selection statistics. It never decodes a 2018+ file -- the caller's
firewall blocks those before a byte is fetched.

Dukascopy ``.bi5`` format: LZMA-compressed stream of 20-byte big-endian records
``(time_ms:uint32, ask:uint32, bid:uint32, ask_vol:float32, bid_vol:float32)`` where prices
are integers in instrument points. JPY-quoted pairs use 3-decimal points (scale 1000); all
other pairs use 5-decimal points (scale 100000). Verifying that scaling is a required
certification step.
"""

from __future__ import annotations

import hashlib
import lzma
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

PARSER_VERSION = "v3_bi5_parser_1"
CANONICALIZER_VERSION = "v3_m1_canonicalizer_1"
PROVIDER = "dukascopy_datafeed"
_REC = struct.Struct(">IIIff")  # time_ms, ask, bid, ask_vol, bid_vol

# Plausible price envelopes for the JPY/non-JPY scaling verification.
_PRICE_ENVELOPE = {
    "JPY": (50.0, 200.0),
    "NONJPY": (0.3, 3.0),
}


def price_scale(instrument: str) -> int:
    """3-decimal points (scale 1000) for JPY-quoted pairs; 5-decimal (100000) otherwise."""

    return 1000 if instrument.upper().endswith("JPY") else 100000


def is_jpy(instrument: str) -> bool:
    return instrument.upper().endswith("JPY")


@dataclass(frozen=True, slots=True)
class Tick:
    ts_ms: int
    bid: float
    ask: float


def decode_bi5(raw: bytes, hour_start_ms: int, scale: int) -> list[Tick]:
    """Decompress and parse one hourly ``.bi5`` payload into absolute-timestamped ticks.

    An empty payload (no-data hour) yields an empty list -- a valid, expected outcome.
    """

    if not raw:
        return []
    data = None
    for fmt in (lzma.FORMAT_AUTO, lzma.FORMAT_ALONE):
        try:
            data = lzma.decompress(raw, format=fmt)
            break
        except lzma.LZMAError:
            continue
    if data is None:
        raise ValueError("bi5 payload is not decodable LZMA")
    ticks: list[Tick] = []
    for off in range(0, len(data) - (len(data) % _REC.size), _REC.size):
        t_ms, ask_i, bid_i, _av, _bv = _REC.unpack_from(data, off)
        ticks.append(Tick(hour_start_ms + int(t_ms), bid_i / scale, ask_i / scale))
    return ticks


def aggregate_m1(ticks: list[Tick]) -> list[dict[str, Any]]:
    """Aggregate ticks into per-minute bid/ask OHLC rows (causal, closed minutes)."""

    buckets: dict[int, list[Tick]] = {}
    for t in ticks:
        minute = (t.ts_ms // 60000) * 60000
        buckets.setdefault(minute, []).append(t)
    rows: list[dict[str, Any]] = []
    for minute in sorted(buckets):
        group = buckets[minute]
        bids = [t.bid for t in group]
        asks = [t.ask for t in group]
        rows.append(
            {
                "timestamp": minute,
                "bid_open": bids[0], "bid_high": max(bids), "bid_low": min(bids),
                "bid_close": bids[-1],
                "ask_open": asks[0], "ask_high": max(asks), "ask_low": min(asks),
                "ask_close": asks[-1],
                "tick_count": len(group),
            }
        )
    return rows


def _side_rows(m1_rows: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    return [
        {"timestamp": r["timestamp"], "open": r[f"{side}_open"], "high": r[f"{side}_high"],
         "low": r[f"{side}_low"], "close": r[f"{side}_close"]}
        for r in m1_rows
    ]


def _integrity_audit(m1_rows: list[dict[str, Any]], instrument: str) -> dict[str, Any]:
    ts = [r["timestamp"] for r in m1_rows]
    duplicates = len(ts) - len(set(ts))
    # missing minutes within the covered span (natural low-liquidity gaps; reported not failed)
    missing = 0
    if len(ts) >= 2:
        span = list(range(min(ts), max(ts) + 60000, 60000))
        present = set(ts)
        missing = sum(1 for m in span if m not in present)
    bidask_violations = sum(1 for r in m1_rows if r["ask_close"] < r["bid_close"])
    lo, hi = _PRICE_ENVELOPE["JPY" if is_jpy(instrument) else "NONJPY"]
    closes = [(r["bid_close"] + r["ask_close"]) / 2 for r in m1_rows]
    scale_ok = bool(closes) and all(lo <= c <= hi for c in closes)
    return {
        "duplicate_timestamps": duplicates,
        "missing_minutes_in_span": missing,
        "bid_ask_ordering_violations": bidask_violations,
        "bid_ask_valid": bidask_violations == 0,
        "jpy_pair": is_jpy(instrument),
        "price_scale": price_scale(instrument),
        "scaling_plausibility_ok": scale_ok,
        "price_envelope": [lo, hi],
    }


def certify_partition(
    *,
    instrument: str,
    year: int,
    month: int,
    day: int | None,
    side: str,
    m1_rows: list[dict[str, Any]],
    source_bytes: int,
    source_sha256: str,
    request_urls: list[str],
) -> dict[str, Any]:
    """Build the full per-partition certification manifest for one side."""

    side_rows = _side_rows(m1_rows, side)
    canonical_bytes = len(canonical_hash(side_rows).encode()) if side_rows else 0
    ts = [r["timestamp"] for r in side_rows]

    def _iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

    audit = _integrity_audit(m1_rows, instrument)
    status = "CERTIFIED" if (side_rows and audit["bid_ask_valid"]
                             and audit["scaling_plausibility_ok"]) else "REJECTED_INTEGRITY"
    return {
        "artifact_id": "V3_PARTITION_CERT_V1",
        "instrument": instrument,
        "year": year,
        "month": month,
        "day": day,
        "side": side,
        "provider": PROVIDER,
        "request_identity": {
            "url_count": len(request_urls),
            "urls_sha256": hashlib.sha256("\n".join(request_urls).encode()).hexdigest(),
        },
        "source_checksum": source_sha256,
        "canonical_checksum": canonical_hash(side_rows),
        "source_bytes": source_bytes,
        "canonical_bytes": canonical_bytes,
        "row_count": len(side_rows),
        "timestamp_bounds": {
            "start": _iso(min(ts)) if ts else None,
            "end": _iso(max(ts)) if ts else None,
        },
        "integrity_audit": audit,
        "parser_version": PARSER_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "acquisition_status": status,
        "exposure_note": "DOWNLOAD+PARSE+INTEGRITY_INSPECTION only; NOT OUTCOME_EXPOSED.",
    }
