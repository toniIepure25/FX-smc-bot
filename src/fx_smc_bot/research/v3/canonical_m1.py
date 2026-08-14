"""Canonical M1 schema v2 with observation provenance (clock / observed / executable).

A canonical M1 row carries, alongside bid/ask OHLC, the provenance that keeps a clock-grid
row from masquerading as a real quote:

* ``session_valid``     -- inside the FX weekly session window for the date;
* ``bid_observed`` / ``ask_observed`` -- genuine underlying observation this minute
  (native: volume>0 per side; tick: the minute had ticks);
* ``executable_quote``  -- ``session_valid and bid_observed and ask_observed``;
* ``is_imputed``        -- True for a flat carry-forward (clock-alignment) row;
* ``staleness_minutes`` -- minutes since the last executable observation (0 when executable);
* ``transport``         -- NATIVE_M1 or TICK_AGGREGATED_M1.

Imputed rows exist only for clock alignment and are always marked. Execution and stateful
market features must consult these masks (see :mod:`observation_contract`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition_state import Transport
from fx_smc_bot.research.v3.fx_calendar import session_window_utc

CANONICALIZER_VERSION = "v3_m1_canonicalizer_2"

CANONICAL_FIELDS = (
    "timestamp",
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close",
    "session_valid", "bid_observed", "ask_observed", "executable_quote",
    "is_imputed", "staleness_minutes", "transport",
)


def _session_bounds_ms(d: date) -> tuple[int, int] | None:
    win = session_window_utc(d)
    if win is None:
        return None
    return (int(win[0].timestamp() * 1000), int(win[1].timestamp() * 1000))


def _flat(src: dict[str, Any], ts: int) -> dict[str, Any]:
    row: dict[str, Any] = {"timestamp": ts}
    for side in ("bid", "ask"):
        c = src[f"{side}_close"]
        row[f"{side}_open"] = row[f"{side}_high"] = row[f"{side}_low"] = row[f"{side}_close"] = c
    return row


def _canonicalize(rows: list[dict[str, Any]], d: date, transport: str,
                  bid_obs: dict[int, bool], ask_obs: dict[int, bool]) -> list[dict[str, Any]]:
    """Build the full-minute canonical grid with observation provenance."""

    if not rows:
        return []
    by = {r["timestamp"]: r for r in rows}
    lo, hi = min(by), max(by)
    bounds = _session_bounds_ms(d)
    out: list[dict[str, Any]] = []
    last_real: dict[str, Any] | None = None
    last_exec_ts: int | None = None
    for ts in range(lo, hi + 60000, 60000):
        r = by.get(ts)
        b_ok = bool(r) and bid_obs.get(ts, False)
        a_ok = bool(r) and ask_obs.get(ts, False)
        executable_obs = b_ok and a_ok
        if r is not None and (b_ok or a_ok):
            base = r
            last_real = r
            is_imputed = not executable_obs
        elif last_real is not None:
            base = last_real
            is_imputed = True
            b_ok = a_ok = False
        else:
            continue  # leading gap before any observation: no row to carry forward
        if executable_obs:
            last_exec_ts = ts
        session_valid = bounds is not None and bounds[0] <= ts < bounds[1]
        if executable_obs or last_exec_ts is None:
            staleness = 0
        else:
            staleness = (ts - last_exec_ts) // 60000
        row = base if not is_imputed else _flat(base, ts)
        out.append({
            "timestamp": ts,
            "bid_open": row["bid_open"], "bid_high": row["bid_high"],
            "bid_low": row["bid_low"], "bid_close": row["bid_close"],
            "ask_open": row["ask_open"], "ask_high": row["ask_high"],
            "ask_low": row["ask_low"], "ask_close": row["ask_close"],
            "session_valid": session_valid,
            "bid_observed": b_ok, "ask_observed": a_ok,
            "executable_quote": bool(session_valid and b_ok and a_ok),
            "is_imputed": is_imputed,
            "staleness_minutes": int(staleness),
            "transport": transport,
        })
    return out


def canonicalize_native_day(native_rows: list[dict[str, Any]], d: date) -> list[dict[str, Any]]:
    """Native rows carry bid_volume/ask_volume; observed := volume>0 (certified rule)."""

    bid_obs = {r["timestamp"]: float(r.get("bid_volume", 0.0)) > 0.0 for r in native_rows}
    ask_obs = {r["timestamp"]: float(r.get("ask_volume", 0.0)) > 0.0 for r in native_rows}
    return _canonicalize(native_rows, d, Transport.NATIVE_M1.value, bid_obs, ask_obs)


def canonicalize_tick_day(tick_rows: list[dict[str, Any]], d: date) -> list[dict[str, Any]]:
    """Tick->M1 rows are present only for observed minutes; observed := row present."""

    obs = {r["timestamp"]: True for r in tick_rows}
    return _canonicalize(tick_rows, d, Transport.TICK_AGGREGATED_M1.value, obs, obs)


# --------------------------------------------------------------------------------------
# Execution semantics: never fill on an imputed / non-observed minute.
# --------------------------------------------------------------------------------------
def next_executable_index(rows: list[dict[str, Any]], start: int) -> int | None:
    """First index >= start whose row is an EXECUTABLE quote, else None.

    Time advances across imputed/non-observed minutes; execution occurs only on an
    executable (session_valid, observed bid+ask) minute -- honouring no_synthetic_fill.
    """

    for i in range(max(0, start), len(rows)):
        if rows[i]["executable_quote"]:
            return i
    return None


def is_executable(rows: list[dict[str, Any]], i: int) -> bool:
    return 0 <= i < len(rows) and bool(rows[i]["executable_quote"])


# --------------------------------------------------------------------------------------
# Feature semantics: imputed rows are not zero-return market observations.
# --------------------------------------------------------------------------------------
def observed_mid_series(rows: list[dict[str, Any]]) -> list[float | None]:
    """Mid on observed minutes, None on imputed -- so stateful features skip imputed rows."""

    out: list[float | None] = []
    for r in rows:
        if r["is_imputed"] or not (r["bid_observed"] and r["ask_observed"]):
            out.append(None)
        else:
            out.append((r["bid_close"] + r["ask_close"]) / 2.0)
    return out


def observed_return_series(rows: list[dict[str, Any]]) -> list[float | None]:
    """Log returns computed only between consecutive OBSERVED mids; None otherwise.

    An imputed minute never contributes a (spurious zero) return, and the return after a gap
    is measured across the gap between real observations, not manufactured per clock minute.
    """

    import math  # noqa: PLC0415

    mids = observed_mid_series(rows)
    out: list[float | None] = []
    last: float | None = None
    for m in mids:
        if m is None or last is None:
            out.append(None)          # imputed minute, or no prior observation to diff against
        else:
            out.append(math.log(m / last))  # return measured across the gap between observations
        if m is not None:
            last = m
    return out


# --------------------------------------------------------------------------------------
# Cross-pair synchronization: require contemporaneous observation on every leg.
# --------------------------------------------------------------------------------------
def synchronized_observation(rows_by_instrument: dict[str, dict[int, dict[str, Any]]],
                             ts: int) -> bool:
    """True iff EVERY leg has an executable (freshly observed) quote at timestamp ``ts``.

    A stale/imputed leg breaks synchronization even though it occupies the same clock row.
    """

    for legrows in rows_by_instrument.values():
        r = legrows.get(ts)
        if r is None or not r.get("executable_quote"):
            return False
    return True


# --------------------------------------------------------------------------------------
# Multi-timeframe resampling with observation provenance.
# --------------------------------------------------------------------------------------
def resample_mtf(rows: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Aggregate canonical M1 into higher-TF bars carrying observation coverage provenance."""

    if minutes <= 1 or not rows:
        return rows
    step = minutes * 60000
    buckets: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault((r["timestamp"] // step) * step, []).append(r)
    out: list[dict[str, Any]] = []
    for bts in sorted(buckets):
        grp = buckets[bts]
        obs = [r for r in grp if r["executable_quote"]]
        src = obs if obs else grp
        observed_minutes = len(obs)
        out.append({
            "timestamp": bts,
            "bid_open": src[0]["bid_open"], "bid_high": max(r["bid_high"] for r in src),
            "bid_low": min(r["bid_low"] for r in src), "bid_close": src[-1]["bid_close"],
            "ask_open": src[0]["ask_open"], "ask_high": max(r["ask_high"] for r in src),
            "ask_low": min(r["ask_low"] for r in src), "ask_close": src[-1]["ask_close"],
            "observed_minutes": observed_minutes,
            "imputed_minutes": len(grp) - observed_minutes,
            "coverage_fraction": round(observed_minutes / len(grp), 4) if grp else 0.0,
            "executable_quote": observed_minutes > 0,
        })
    return out


_MASK_FIELDS = ("session_valid", "bid_observed", "ask_observed", "executable_quote", "is_imputed")


def observation_mask_parity(native_rows: list[dict[str, Any]], tick_rows: list[dict[str, Any]],
                            d: date) -> dict[str, Any]:
    """Compare observation/executable/imputed/session masks of native vs tick canonical rows.

    The OHLC/price parity is checked separately (native_transport.compare_parity). Here every
    shared clock minute must agree on all provenance masks; disagreement means the two
    transports would classify executability/imputation differently (a certification blocker).
    """

    nat = {r["timestamp"]: r for r in canonicalize_native_day(native_rows, d)}
    tk = {r["timestamp"]: r for r in canonicalize_tick_day(tick_rows, d)}
    if not nat or not tk:
        return {"verdict": "MISSING", "shared_minutes": 0}
    lo = max(min(nat), min(tk))
    hi = min(max(nat), max(tk))
    shared = [ts for ts in nat if lo <= ts <= hi and ts in tk]
    mismatches: dict[str, int] = {f: 0 for f in _MASK_FIELDS}
    for ts in shared:
        for f in _MASK_FIELDS:
            if bool(nat[ts][f]) != bool(tk[ts][f]):
                mismatches[f] += 1
    minute_set_equal = {ts for ts in nat if lo <= ts <= hi} == {ts for ts in tk if lo <= ts <= hi}
    total_mismatch = sum(mismatches.values())
    verdict = "PASS" if (total_mismatch == 0 and minute_set_equal) else "FAIL"
    return {
        "verdict": verdict,
        "shared_minutes": len(shared),
        "minute_set_equal": minute_set_equal,
        "mask_mismatches": mismatches,
        "native_executable": sum(1 for ts in shared if nat[ts]["executable_quote"]),
        "native_imputed": sum(1 for ts in shared if nat[ts]["is_imputed"]),
        "tick_executable": sum(1 for ts in shared if tk[ts]["executable_quote"]),
        "tick_imputed": sum(1 for ts in shared if tk[ts]["is_imputed"]),
    }


def canonical_schema_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_CANONICAL_M1_SCHEMA_V2",
        "canonicalizer_version": CANONICALIZER_VERSION,
        "fields": list(CANONICAL_FIELDS),
        "native_observed_rule": "bid_volume>0 / ask_volume>0 (certified vs tick)",
        "tick_observed_rule": "minute present in tick->M1 aggregation (tick_count>0)",
        "imputed_rows_marked": True,
        "mtf_provenance_fields": ["observed_minutes", "imputed_minutes", "coverage_fraction"],
    }


def canonical_schema_hash() -> str:
    return canonical_hash(canonical_schema_payload())
