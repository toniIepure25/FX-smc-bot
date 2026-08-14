"""Tests for the tick->M1 acquisition/certification pipeline and the terminal data gate."""

from __future__ import annotations

import lzma
import struct

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3.data_gate import (
    VERDICT_CERTIFIED,
    VERDICT_PENDING,
    build_gate,
)

_REC = struct.Struct(">IIIff")


def _synth_bi5(ticks: list[tuple[int, int, int]]) -> bytes:
    """(time_ms, ask_i, bid_i) records -> lzma-compressed .bi5-style payload."""

    raw = b"".join(_REC.pack(t, ask, bid, 1.0, 1.0) for t, ask, bid in ticks)
    return lzma.compress(raw)


def test_price_scale_jpy_vs_nonjpy() -> None:
    assert ap.price_scale("EURUSD") == 100000
    assert ap.price_scale("USDJPY") == 1000
    assert ap.price_scale("EURJPY") == 1000
    assert ap.is_jpy("GBPJPY") and not ap.is_jpy("GBPUSD")


def test_decode_aggregate_certify_roundtrip() -> None:
    hour_ms = 1_402_394_400_000  # arbitrary hour start
    payload = _synth_bi5([
        (0, 135430, 135427), (30_000, 135435, 135432), (61_000, 135420, 135417),
    ])
    ticks = ap.decode_bi5(payload, hour_ms, ap.price_scale("EURUSD"))
    assert len(ticks) == 3
    assert abs(ticks[0].ask - 1.35430) < 1e-9 and abs(ticks[0].bid - 1.35427) < 1e-9
    m1 = ap.aggregate_m1(ticks)
    assert len(m1) == 2  # minute 0 (two ticks) + minute 1 (one tick)
    cert = ap.certify_partition(
        instrument="EURUSD", year=2014, month=6, day=10, side="bid", m1_rows=m1,
        source_bytes=len(payload), source_sha256="x", request_urls=["u"],
    )
    assert cert["row_count"] == 2
    assert cert["integrity_audit"]["bid_ask_valid"]
    assert cert["integrity_audit"]["duplicate_timestamps"] == 0
    assert cert["acquisition_status"] == "CERTIFIED"
    assert "NOT OUTCOME_EXPOSED" in cert["exposure_note"]


def test_certify_is_deterministic() -> None:
    hour_ms = 1_402_394_400_000
    ticks = ap.decode_bi5(_synth_bi5([(0, 135430, 135427)]), hour_ms, 100000)
    m1 = ap.aggregate_m1(ticks)
    c1 = ap.certify_partition(instrument="EURUSD", year=2014, month=6, day=10, side="ask",
                              m1_rows=m1, source_bytes=1, source_sha256="x", request_urls=[])
    c2 = ap.certify_partition(instrument="EURUSD", year=2014, month=6, day=10, side="ask",
                              m1_rows=m1, source_bytes=1, source_sha256="x", request_urls=[])
    assert c1["canonical_checksum"] == c2["canonical_checksum"]


def test_empty_bi5_is_valid_empty() -> None:
    assert ap.decode_bi5(b"", 0, 100000) == []


_ALL_TRUE = {
    "dependencies_satisfiable_in_plan": True, "denominator_unambiguous": True,
    "freeze_identities_correct": True, "readiness_evidence_derived": True,
    "no_2018_requests": True, "no_2018_reads": True, "no_outcome_computed": True,
    "manifests_reproduce": True, "quality_gates_pass": True, "no_orphan_processes": True,
}


def test_gate_certified_only_with_full_coverage() -> None:
    gate = build_gate(certified_units=2496, required_units=2496,
                      prospectively_excluded_units=0, evidence=_ALL_TRUE)
    assert gate["verdict"] == VERDICT_CERTIFIED
    assert gate["next_gate"] == "V3_ALPHA_DISCOVERY_RUN"


def test_gate_pending_when_coverage_incomplete() -> None:
    gate = build_gate(certified_units=0, required_units=2496,
                      prospectively_excluded_units=0, evidence=_ALL_TRUE)
    assert gate["verdict"] == VERDICT_PENDING
    assert gate["remaining_external_step"] is not None
    assert gate["2018_plus_market_or_outcome_files_opened"] == 0
