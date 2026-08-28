"""V3 synchronized-tick quote-validity contract (V3_SYNCHRONIZED_TICK_QUOTE_VALIDITY_V1).

This is a FROZEN, pre-outcome *data-quality* contract that fixes -- BEFORE any additional tick
outcome is inspected -- the rule for which synchronized Dukascopy ticks are VALID market quotes.
It is a data-quality correction only: it changes no candidate definition, no statistic, no
execution hypothesis, and computes no V3 P&L or candidate outcome.

The scientific rule (ZERO-TOLERANCE at the QUOTE level):

A synchronized tick is a VALID market quote only if ALL of the following hold:

  1. its timestamp decodes correctly (guaranteed by the bi5 record layout);
  2. ``bid`` and ``ask`` are finite;
  3. ``bid > 0``;
  4. ``ask > 0``;
  5. the quote is scaling-plausible under the frozen instrument scale (mid within the
     instrument price envelope);
  6. ``ask >= bid``.

A tick with ``ask < bid`` is an INVALID MARKET QUOTE (a crossed quote). It MUST NOT be repaired,
clamped, have ``ask`` replaced by ``bid``, be swapped, contribute to OHLC, count as observed,
count as executable, or update stateful market features. It is preserved in provenance/audit
counts only.

Zero-tolerance is applied at the QUOTE level, NOT the DAY level: a day is not rejected merely
because one or more raw invalid ticks existed. A minute with >=1 valid tick is observed (OHLC
from valid ticks only); a minute with zero valid ticks is unobserved/non-executable under the
existing frozen imputation/staleness semantics. An invalid tick is never treated as a zero
return and no quote is fabricated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

QUOTE_VALIDITY_CONTRACT_ID = "V3_SYNCHRONIZED_TICK_QUOTE_VALIDITY_V1"

# Plausible mid-price envelopes per instrument class, matching the frozen M1 scaling audit.
# JPY-quoted pairs trade around 50-200; all other pairs around 0.3-3.0. A tick whose mid falls
# outside its envelope is scaling-implausible (wrong instrument scale) and is INVALID.
QUOTE_PRICE_ENVELOPE: dict[str, tuple[float, float]] = {
    "JPY": (50.0, 200.0),
    "NONJPY": (0.3, 3.0),
}

# The six frozen quote-validity conditions (machine-readable; hashed into the contract).
QUOTE_VALIDITY_CONDITIONS = (
    "timestamp decodes correctly",
    "bid and ask are finite",
    "bid > 0",
    "ask > 0",
    "scaling plausible under the frozen instrument scale (mid within instrument envelope)",
    "ask >= bid",
)


def _is_jpy(instrument: str) -> bool:
    return instrument.upper().endswith("JPY")


def is_valid_quote(bid: float, ask: float, instrument: str) -> bool:
    """Return True iff the synchronized tick ``(bid, ask)`` is a VALID market quote.

    Implements the six frozen conditions. A crossed quote (``ask < bid``) is INVALID. No repair,
    clamp, swap or imputation is performed here -- this is a pure predicate.
    """

    if not (math.isfinite(bid) and math.isfinite(ask)):
        return False
    if bid <= 0.0 or ask <= 0.0:
        return False
    if ask < bid:  # crossed quote -> INVALID (zero-tolerance at the quote level)
        return False
    lo, hi = QUOTE_PRICE_ENVELOPE["JPY" if _is_jpy(instrument) else "NONJPY"]
    mid = (bid + ask) / 2.0
    return lo <= mid <= hi


@dataclass(frozen=True, slots=True)
class TickValidityStats:
    """Provenance-only counts for a decoded tick session (never used as alpha features)."""

    raw_tick_count: int
    valid_tick_count: int
    invalid_crossed_tick_count: int      # ask < bid (the primary source defect)
    invalid_other_tick_count: int        # non-finite, <=0, or scaling-implausible
    minutes_affected: int                # minutes containing >=1 invalid tick
    minutes_with_no_valid_tick: int      # minutes with ticks but ZERO valid ticks
    max_invalid_negative_spread: float   # max(bid - ask) over crossed ticks (points)


def classify_ticks(ticks: list[Any], instrument: str) -> tuple[list[Any], TickValidityStats]:
    """Partition decoded ticks into VALID quotes and provenance stats.

    ``ticks`` is a sequence of objects exposing ``.bid``, ``.ask`` and ``.ts_ms`` (the
    :class:`acquisition_pipeline.Tick` dataclass). Returns ``(valid_ticks, stats)`` where
    ``valid_ticks`` preserves input order and ``stats`` records the invalid-quote provenance.
    """

    valid: list[Any] = []
    invalid_crossed = 0
    invalid_other = 0
    max_neg_spread = 0.0
    minutes_with_invalid: set[int] = set()
    for t in ticks:
        if is_valid_quote(t.bid, t.ask, instrument):
            valid.append(t)
            continue
        minutes_with_invalid.add((t.ts_ms // 60000) * 60000)
        if (math.isfinite(t.bid) and math.isfinite(t.ask)
                and t.bid > 0.0 and t.ask > 0.0 and t.ask < t.bid):
            invalid_crossed += 1
            max_neg_spread = max(max_neg_spread, t.bid - t.ask)
        else:
            invalid_other += 1
    valid_minutes = {(t.ts_ms // 60000) * 60000 for t in valid}
    minutes_with_no_valid = len(minutes_with_invalid - valid_minutes)
    return valid, TickValidityStats(
        raw_tick_count=len(ticks),
        valid_tick_count=len(valid),
        invalid_crossed_tick_count=invalid_crossed,
        invalid_other_tick_count=invalid_other,
        minutes_affected=len(minutes_with_invalid),
        minutes_with_no_valid_tick=minutes_with_no_valid,
        max_invalid_negative_spread=max_neg_spread,
    )


def quote_validity_contract_payload() -> dict[str, Any]:
    """The machine-readable, hashable pre-outcome quote-validity contract."""

    return {
        "artifact_id": QUOTE_VALIDITY_CONTRACT_ID,
        "class": "PRE_OUTCOME_DATA_QUALITY_CORRECTION",
        "no_v3_pnl_used": True,
        "no_candidate_outcomes_used": True,
        "no_candidate_definition_changes": True,
        "no_statistic_changes": True,
        "no_execution_hypothesis_changes": True,
        "zero_tolerance_level": "QUOTE",
        "day_level_zero_tolerance": False,
        "quote_validity_conditions": list(QUOTE_VALIDITY_CONDITIONS),
        "invalid_quote_policy": {
            "repaired": False,
            "clamped": False,
            "ask_replaced_with_bid": False,
            "swapped": False,
            "contributes_to_ohlc": False,
            "counts_as_observed": False,
            "counts_as_executable": False,
            "updates_stateful_market_features": False,
            "preserved_in_provenance_audit_counts": True,
        },
        "price_envelope": {k: list(v) for k, v in QUOTE_PRICE_ENVELOPE.items()},
        "minute_semantics": {
            "one_or_more_valid_ticks": "observed=true; bid/ask OHLC computed from valid ticks only",
            "zero_valid_ticks": "observed=false; executable=false; existing frozen "
                                "imputation/staleness semantics apply",
            "invalid_tick_as_zero_return": False,
            "fabricated_quote": False,
        },
        "day_validity": {
            "rejected_for_isolated_invalid_ticks": False,
            "certify_if": [
                "contains genuine valid observations",
                "zero bid/ask ordering violations after quote-validity filtering",
                "passes scaling/timestamp/duplicate/session checks",
                "satisfies the existing frozen observation/canonical semantics",
            ],
            "provenance_counts": [
                "raw_tick_count", "valid_tick_count", "invalid_crossed_tick_count",
                "minutes_affected", "minutes_with_no_valid_tick",
                "maximum_invalid_negative_spread",
            ],
            "provenance_used_as_alpha_features": False,
        },
        "zero_observation_day_rule": (
            "preserved: native zero observation + complete tick session with zero VALID "
            "synchronized market observations + no unresolved transport failure => "
            "TERMINAL_DATA_ABSENT; no external holiday labels used to force the result"
        ),
    }


def quote_validity_contract_hash() -> str:
    """Deterministic hash of the pre-outcome quote-validity contract (fixed before tick results)."""

    return canonical_hash(quote_validity_contract_payload())
