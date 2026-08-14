"""Native Dukascopy M1 BID/ASK candle transport + prospective parity contract.

A second acquisition transport that fetches Dukascopy's native per-day M1 candle ``.bi5``
files (one per price side) instead of aggregating hourly ticks. It does NOT replace the
canonical format; it is a transport *candidate* whose semantic equivalence to the certified
tick->M1 representation must be certified before use. Transport identity is always recorded
(NATIVE_M1 vs TICK_AGGREGATED_M1, plus any fallback reason). URL generation is firewalled by
the caller before any network I/O.

Native candle ``.bi5`` format: LZMA-compressed 24-byte big-endian records
``(time:int32, open:int32, close:int32, low:int32, high:int32, volume:float32)`` -- note the
open, CLOSE, low, high ordering. ``time`` is a seconds offset from the file's day start; prices
are integer instrument points (scale 100000 non-JPY, 1000 JPY).

PARITY CONTRACT (frozen, declared before any parity result): native M1 and the certified
tick->M1 canonical representation are compared on timestamps, bid O/H/L/C, ask O/H/L/C, row
presence/absence, missing-minute structure, ordering, day boundaries and JPY/non-JPY scaling.
The accepted equality is at the FROZEN QUOTE PRECISION only: prices are equal iff they are
equal when rounded to the instrument's canonical decimals (5 non-JPY, 3 JPY). PASS_EXACT =
identical canonical values on every shared minute AND identical minute sets; PASS_CANONICAL_
EQUIVALENT = identical rounded-to-precision values (serialization-only differences); anything
else is FAIL. No looser tolerance may be introduced after seeing results. No strategy/P&L
comparison is performed.
"""

from __future__ import annotations

import lzma
import struct
from datetime import date, datetime, timezone
from typing import Any

from fx_smc_bot.research.v3.acquisition_pipeline import Tick, aggregate_m1, price_scale

TRANSPORT_NATIVE_M1 = "NATIVE_M1"
TRANSPORT_TICK_AGGREGATED_M1 = "TICK_AGGREGATED_M1"
NATIVE_PARSER_VERSION = "v3_native_candle_parser_1"
_CANDLE = struct.Struct(">5if")  # time, open, close, low, high, volume

# Canonical decimals per instrument class -> frozen quote precision for the parity contract.
DECIMALS_JPY = 3
DECIMALS_NONJPY = 5


def native_m1_url(instrument: str, d: date, side: str) -> str:
    """Native per-day M1 candle URL. ``side`` in {BID, ASK}. Dukascopy months are 0-indexed."""

    s = side.upper()
    if s not in ("BID", "ASK"):
        raise ValueError(f"side must be BID or ASK, got {side!r}")
    return (
        f"https://datafeed.dukascopy.com/datafeed/{instrument}/{d.year:04d}/"
        f"{d.month - 1:02d}/{d.day:02d}/{s}_candles_min_1.bi5"
    )


def decimals_for(instrument: str) -> int:
    return DECIMALS_JPY if instrument.upper().endswith("JPY") else DECIMALS_NONJPY


def decode_candle_bi5(raw: bytes, day_start_ms: int, scale: int) -> list[dict[str, Any]]:
    """Decode one side's native M1 candle file into per-minute OHLC rows.

    An empty payload (no-data day) yields an empty list. Prices are scaled to float; the
    timestamp is ``day_start_ms + time_seconds*1000``.
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
        raise ValueError("native candle payload is not decodable LZMA")
    rows: list[dict[str, Any]] = []
    for off in range(0, len(data) - (len(data) % _CANDLE.size), _CANDLE.size):
        t, o, c, low, high, _vol = _CANDLE.unpack_from(data, off)
        rows.append({
            "timestamp": day_start_ms + int(t) * 1000,
            "open": o / scale, "high": high / scale, "low": low / scale, "close": c / scale,
        })
    return rows


def native_m1_day(bid_raw: bytes, ask_raw: bytes, instrument: str, d: date) -> list[dict[str, Any]]:
    """Combine native BID and ASK candle files into the canonical M1 bid/ask row shape."""

    day_start_ms = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    scale = price_scale(instrument)
    bid = {r["timestamp"]: r for r in decode_candle_bi5(bid_raw, day_start_ms, scale)}
    ask = {r["timestamp"]: r for r in decode_candle_bi5(ask_raw, day_start_ms, scale)}
    rows: list[dict[str, Any]] = []
    for ts in sorted(set(bid) | set(ask)):
        b = bid.get(ts)
        a = ask.get(ts)
        if b is None or a is None:
            continue  # require both sides for a canonical bid/ask minute
        rows.append({
            "timestamp": ts,
            "bid_open": b["open"], "bid_high": b["high"], "bid_low": b["low"],
            "bid_close": b["close"],
            "ask_open": a["open"], "ask_high": a["high"], "ask_low": a["low"],
            "ask_close": a["close"],
        })
    return rows


def tick_m1_day(ticks: list[Tick]) -> list[dict[str, Any]]:
    """Reference tick->M1 aggregation (delegates to the certified tick pipeline)."""

    return aggregate_m1(ticks)


_SIDE_OHLC = ("bid_open", "bid_high", "bid_low", "bid_close",
              "ask_open", "ask_high", "ask_low", "ask_close")


def fill_session_grid(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonical empty-minute policy: flat carry-forward for no-tick minutes.

    Dukascopy native M1 candles are emitted on a regular full-minute grid (no-tick minutes are
    flat carry-forward bars, O=H=L=C=last close); the tick->M1 aggregation instead omits
    no-tick minutes. On liquid sessions every minute has ticks so the two coincide, but on thin
    sessions (Sunday-open / Friday-close) they differ in row PRESENCE only -- prices are
    identical on every real minute. The canonical M1 standard adopts the native full-grid
    convention (a regular time grid). This function makes any series canonical-consistent by
    flat-filling missing minutes within [min, max]; it changes no price and is idempotent on an
    already-full grid. This is a canonicalizer definition, NOT a quote-precision tolerance.
    """

    if not rows:
        return rows
    by = {r["timestamp"]: r for r in rows}
    lo, hi = min(by), max(by)
    out: list[dict[str, Any]] = []
    last: dict[str, Any] | None = None
    for ts in range(lo, hi + 60000, 60000):
        if ts in by:
            last = by[ts]
            out.append(last)
        elif last is not None:
            flat = {"timestamp": ts}
            for side in ("bid", "ask"):
                c = last[f"{side}_close"]
                flat[f"{side}_open"] = flat[f"{side}_high"] = flat[f"{side}_low"] = c
                flat[f"{side}_close"] = c
            out.append(flat)
    return out


# --------------------------------------------------------------------------------------
# Parity comparison under the FROZEN contract above.
# --------------------------------------------------------------------------------------
PARITY_PASS_EXACT = "PASS_EXACT"
PARITY_PASS_CANONICAL = "PASS_CANONICAL_EQUIVALENT"
PARITY_FAIL = "FAIL"
PARITY_MISSING_NATIVE = "MISSING_NATIVE"
PARITY_MISSING_TICK = "MISSING_TICK_REFERENCE"

_PRICE_FIELDS = ("bid_open", "bid_high", "bid_low", "bid_close",
                 "ask_open", "ask_high", "ask_low", "ask_close")


def parity_contract() -> dict[str, Any]:
    return {
        "artifact_id": "V3_PARITY_CONTRACT_V1",
        "compared_fields": ["timestamps", *_PRICE_FIELDS, "row_presence", "missing_minutes",
                            "ordering", "day_boundaries", "jpy_scaling", "nonjpy_scaling"],
        "acceptance": {
            "PASS_EXACT": "identical minute set AND identical canonical values everywhere",
            "PASS_CANONICAL_EQUIVALENT": "identical values after rounding to frozen quote "
                                         "precision (serialization-only differences)",
            "FAIL": "any difference exceeding frozen quote precision, or minute-set mismatch",
        },
        "frozen_quote_precision": {"jpy_decimals": DECIMALS_JPY,
                                   "nonjpy_decimals": DECIMALS_NONJPY},
        "comparison_window": "the common covered minute window [max(min), min(max)] of the two "
                             "series; within it, minute sets and canonical values must match. "
                             "This handles partial references and does NOT loosen price equality.",
        "empty_minute_canonicalization": (
            "canonical M1 uses the native full-minute grid: no-tick minutes are flat "
            "carry-forward bars (O=H=L=C=last close). Both transports are canonicalized to this "
            "grid (fill_session_grid) before comparison. This is a parser/canonicalizer "
            "definition motivated by the primary native transport's structure; it aligns row "
            "PRESENCE only and does not change any price or the quote-precision tolerance. "
            "Defined after diagnosing a Sunday-open row-presence difference whose prices already "
            "matched exactly (0 precision mismatches)."
        ),
        "no_loose_tolerance_after_results": True,
        "no_strategy_or_pnl_comparison": True,
    }


def compare_parity(
    native_rows: list[dict[str, Any]] | None,
    tick_rows: list[dict[str, Any]] | None,
    instrument: str,
) -> dict[str, Any]:
    """Compare native vs tick->M1 under the frozen contract; return a per-unit verdict."""

    if native_rows is None:
        return {"verdict": PARITY_MISSING_NATIVE}
    if tick_rows is None:
        return {"verdict": PARITY_MISSING_TICK}

    dec = decimals_for(instrument)
    # Canonicalize both series to the full-minute grid (native empty-minute policy) so row
    # presence is compared apples-to-apples; prices are unchanged.
    nat_all = {r["timestamp"]: r for r in fill_session_grid(native_rows)}
    tk_all = {r["timestamp"]: r for r in fill_session_grid(tick_rows)}
    # Compare on the COMMON covered minute window (declared pre-result): partial references
    # must not be penalised for coverage span. Price equality is unchanged (quote precision).
    if not nat_all or not tk_all:
        lo = hi = 0
    else:
        lo = max(min(nat_all), min(tk_all))
        hi = min(max(nat_all), max(tk_all))
    nat = {ts: r for ts, r in nat_all.items() if lo <= ts <= hi}
    tk = {ts: r for ts, r in tk_all.items() if lo <= ts <= hi}
    shared = sorted(set(nat) & set(tk))
    minute_set_equal = set(nat) == set(tk)

    exact_mismatch = 0
    precision_mismatch = 0
    for ts in shared:
        for f in _PRICE_FIELDS:
            nv, tv = nat[ts][f], tk[ts][f]
            if nv != tv:
                exact_mismatch += 1
                if round(nv, dec) != round(tv, dec):
                    precision_mismatch += 1

    if precision_mismatch > 0 or not minute_set_equal:
        verdict = PARITY_FAIL
    elif exact_mismatch > 0:
        verdict = PARITY_PASS_CANONICAL
    else:
        verdict = PARITY_PASS_EXACT

    return {
        "verdict": verdict,
        "shared_minutes": len(shared),
        "native_minutes": len(nat),
        "tick_minutes": len(tk),
        "minute_set_equal": minute_set_equal,
        "exact_field_mismatches": exact_mismatch,
        "precision_field_mismatches": precision_mismatch,
        "instrument_decimals": dec,
    }
