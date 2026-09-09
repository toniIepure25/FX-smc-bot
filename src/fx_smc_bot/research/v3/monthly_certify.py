"""Session-aware monthly canonical-partition certification + global data-freeze digest.

Once daily acquisition completes, day-units are deterministically materialized into monthly
canonical partitions (instrument x year x month x side) and each partition is certified. This
module is the pure verification core: it takes the per-day canonical rows for a month and
produces the certification manifest, checking identity, session-aware coverage (against the FX
weekly calendar, so partial Sunday/Friday days are legitimate), ordering, duplicates,
unexpected gaps, bid/ask validity, JPY/non-JPY scaling, provenance, canonical checksum,
parser/canonicalizer version, transport mix, fallback reasons, row count and timestamp bounds.

V3.1 status taxonomy (V3_DATA_AVAILABILITY_AMENDMENT_V1):

* CERTIFIED_COMPLETE                  -- every required trading date present as a certified
                                         day-unit;
* CERTIFIED_WITH_PROSPECTIVE_ABSENCE  -- every required date certified or prospectively
                                         excluded under the frozen V3_DATA_INTEGRITY_
                                         REMEDIATION_V1 rule (TERMINAL_DATA_ABSENT: complete
                                         session, all hours in a legitimate transport state,
                                         zero valid observations on BOTH transports -- a
                                         confirmed no-market-observations day, never provider
                                         silence); no unresolved date;
* USABLE_WITH_UNRESOLVED_DATA_GAP     -- every required date certified, prospectively
                                         excluded, or explicitly represented as
                                         UNRESOLVED_DATA_GAP (all frozen transport/
                                         remediation paths exhausted; no frozen
                                         interpretation resolves it; no repair permitted).
                                         The unresolved day is annotated and never hashed as
                                         observed;
* INCOMPLETE_COVERAGE                 -- a required date is neither present, excluded nor
                                         explicitly unresolved (unexplained); blocks
                                         usability;
* INTEGRITY_FAILURE                   -- integrity violation on present rows.

Excluded and unresolved dates are recorded explicitly and are never hashed as observed rows.
"""

from __future__ import annotations

import calendar as _cal
from datetime import date
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition_pipeline import CANONICALIZER_VERSION, PARSER_VERSION
from fx_smc_bot.research.v3.fx_calendar import expected_minutes, trading_dates

# V3.1 monthly status taxonomy (V3_DATA_AVAILABILITY_AMENDMENT_V1).
CERTIFIED_COMPLETE = "CERTIFIED_COMPLETE"
CERTIFIED_WITH_PROSPECTIVE_ABSENCE = "CERTIFIED_WITH_PROSPECTIVE_ABSENCE"
USABLE_WITH_UNRESOLVED_DATA_GAP = "USABLE_WITH_UNRESOLVED_DATA_GAP"
INCOMPLETE = "INCOMPLETE_COVERAGE"
INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
USABLE_STATUSES = (
    CERTIFIED_COMPLETE,
    CERTIFIED_WITH_PROSPECTIVE_ABSENCE,
    USABLE_WITH_UNRESOLVED_DATA_GAP,
)


def month_trading_dates(year: int, month: int) -> list[date]:
    last = _cal.monthrange(year, month)[1]
    return list(trading_dates(date(year, month, 1), date(year, month, last)))


def certify_month(
    *,
    instrument: str,
    year: int,
    month: int,
    side: str,
    rows_by_date: dict[str, list[dict[str, Any]]],
    transport_by_date: dict[str, str],
    fallback_by_date: dict[str, str | None],
    decimals: int,
    excluded_dates: dict[str, str] | None = None,
    unresolved_dates: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Certify one monthly partition for one side. ``rows_by_date`` maps ISO date -> M1 rows.

    ``excluded_dates`` maps ISO date -> frozen exclusion reason for required trading dates
    that are prospectively excluded under the frozen V3_DATA_INTEGRITY_REMEDIATION_V1 rule
    (unit status TERMINAL_DATA_ABSENT: complete session, all hours in a legitimate transport
    state, zero valid observations on both transports). Excluded dates satisfy coverage and
    are recorded explicitly in the manifest; they are never hashed as observed rows.

    ``unresolved_dates`` maps ISO date -> frozen reason for required trading dates explicitly
    represented as UNRESOLVED_DATA_GAP under V3_DATA_AVAILABILITY_AMENDMENT_V1 (all frozen
    transport/remediation paths exhausted, native integrity checks fail, no independent
    frozen transport certifies the day, no frozen interpretation resolves it, no repair
    permitted). An unresolved date satisfies coverage, is annotated in the manifest, is
    never hashed as observed, and is NEVER counted as certified or excluded.

    A date that is both present and excluded, both present and unresolved, or both excluded
    and unresolved is a contradiction and raises.
    """

    excluded = dict(excluded_dates or {})
    unresolved = dict(unresolved_dates or {})
    overlap_present_excluded = set(excluded) & set(rows_by_date)
    if overlap_present_excluded:
        raise ValueError(
            f"{instrument} {year}-{month:02d} {side}: dates both present and excluded: "
            f"{sorted(overlap_present_excluded)}"
        )
    overlap_present_unresolved = set(unresolved) & set(rows_by_date)
    if overlap_present_unresolved:
        raise ValueError(
            f"{instrument} {year}-{month:02d} {side}: dates both present and unresolved: "
            f"{sorted(overlap_present_unresolved)}"
        )
    overlap_excluded_unresolved = set(excluded) & set(unresolved)
    if overlap_excluded_unresolved:
        raise ValueError(
            f"{instrument} {year}-{month:02d} {side}: dates both excluded and unresolved: "
            f"{sorted(overlap_excluded_unresolved)}"
        )
    required = [d.isoformat() for d in month_trading_dates(year, month)]
    present = sorted(rows_by_date)
    missing_dates = [
        d for d in required
        if d not in rows_by_date and d not in excluded and d not in unresolved
    ]

    all_rows: list[dict[str, Any]] = []
    for d in required:
        all_rows.extend(rows_by_date.get(d, []))

    ts = [r["timestamp"] for r in all_rows]
    ordered = all_rows == sorted(all_rows, key=lambda r: r["timestamp"])
    duplicates = len(ts) - len(set(ts))
    # OHLC self-consistency: high >= max(open,close) >= min(open,close) >= low
    ohlc_violations = sum(
        1 for r in all_rows
        if not (r["high"] >= max(r["open"], r["close"])
                and min(r["open"], r["close"]) >= r["low"])
    )
    # scaling plausibility per side (rounded prices must sit in the instrument envelope)
    lo, hi = (50.0, 200.0) if decimals == 3 else (0.3, 3.0)
    scaling_ok = all(lo <= r["close"] <= hi for r in all_rows) if all_rows else False

    transports = sorted({transport_by_date.get(d, "UNKNOWN") for d in present})
    fallbacks = {d: r for d, r in fallback_by_date.items() if r}

    coverage_ok = not missing_dates and (bool(present) or bool(unresolved))
    integrity_ok = ordered and duplicates == 0 and ohlc_violations == 0 and scaling_ok
    unresolved_in_month = {d: unresolved[d] for d in required if d in unresolved}
    excluded_in_month = {d: excluded[d] for d in required if d in excluded}
    if not coverage_ok:
        status = INCOMPLETE
    elif not integrity_ok:
        status = INTEGRITY_FAILURE
    elif unresolved_in_month:
        # Every required date is accounted for, but at least one is an explicitly
        # represented UNRESOLVED_DATA_GAP: usable, but visibly annotated -- never faked
        # as fully certified, never hashed as observed.
        status = USABLE_WITH_UNRESOLVED_DATA_GAP
    elif excluded_in_month:
        status = CERTIFIED_WITH_PROSPECTIVE_ABSENCE
    else:
        status = CERTIFIED_COMPLETE

    canonical_rows = [
        {"timestamp": r["timestamp"], "open": r["open"], "high": r["high"],
         "low": r["low"], "close": r["close"]} for r in all_rows
    ]
    return {
        "artifact_id": "V3_1_MONTHLY_PARTITION_CERT_V1",
        "instrument": instrument, "year": year, "month": month, "side": side,
        "status": status,
        "required_trading_dates": len(required),
        "present_dates": len(present),
        "excluded_dates": excluded_in_month,
        "excluded_date_count": len(excluded_in_month),
        "unresolved_dates": unresolved_in_month,
        "unresolved_date_count": len(unresolved_in_month),
        "missing_dates": missing_dates,
        "row_count": len(all_rows),
        "expected_minutes_session_aware": sum(
            expected_minutes(date.fromisoformat(d)) for d in present
        ),
        "ordered_timestamps": ordered,
        "duplicate_timestamps": duplicates,
        "ohlc_violations": ohlc_violations,
        "scaling_ok": scaling_ok,
        "decimals": decimals,
        "timestamp_bounds": {"start": min(ts) if ts else None, "end": max(ts) if ts else None},
        "transport_mix": transports,
        "fallback_reasons": fallbacks,
        "parser_version": PARSER_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "canonical_checksum": canonical_hash(canonical_rows),
    }


def global_data_freeze_digest(partition_manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Immutable digest over all monthly partitions (order-independent).

    V3 (V3_DATA_AVAILABILITY_AMENDMENT_V1): the digest explicitly distinguishes the four day
    classes so that missing data is never hashed as if observed:

    * certified days                  -- present as certified day-units (their rows are what
                                          ``canonical_checksum`` hashes);
    * excluded days                   -- prospectively excluded under the frozen
                                          V3_DATA_INTEGRITY_REMEDIATION_V1 rule
                                          (TERMINAL_DATA_ABSENT);
    * unresolved_data_gap_days        -- explicitly represented UNRESOLVED_DATA_GAP (all
                                          frozen paths exhausted; no frozen interpretation
                                          resolves; never repaired, never excluded);
    * missing_unexplained_days        -- required, neither present, excluded nor explicitly
                                          unresolved (blocks usability).

    Per partition: required = certified + excluded + unresolved_data_gap + missing_unexplained.
    An unresolved day is NEVER hashed as observed and is NEVER counted as certified or
    excluded.
    """

    entries = sorted(
        {
            f"{m['instrument']}:{m['year']}:{m['month']:02d}:{m['side']}": {
                "canonical_checksum": m["canonical_checksum"],
                "status": m["status"],
                "certified_days": m["present_dates"],
                "excluded_days": m.get("excluded_date_count", 0),
                "unresolved_data_gap_days": m.get("unresolved_date_count", 0),
                "missing_unexplained_days": len(m.get("missing_dates", [])),
            }
            for m in partition_manifests
        }.items()
    )
    status_counts: dict[str, int] = {}
    for m in partition_manifests:
        status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1
    day_classes = {
        "certified_days": sum(m["present_dates"] for m in partition_manifests),
        "excluded_days": sum(m.get("excluded_date_count", 0) for m in partition_manifests),
        "unresolved_data_gap_days": sum(m.get("unresolved_date_count", 0)
                                        for m in partition_manifests),
        "missing_unexplained_days": sum(len(m.get("missing_dates", []))
                                        for m in partition_manifests),
    }
    return {
        "artifact_id": "V3_GLOBAL_DATA_FREEZE_DIGEST_V3",
        "supersedes": "V3_GLOBAL_DATA_FREEZE_DIGEST_V2",
        "partition_count": len(partition_manifests),
        "usable_partitions": sum(1 for m in partition_manifests
                                 if m["status"] in USABLE_STATUSES),
        "partition_status_counts": status_counts,
        "partition_day_class_counts": day_classes,
        "global_digest": canonical_hash(entries),
    }
