from __future__ import annotations

import hashlib
import json
import lzma
import struct
from datetime import date, datetime, timezone

import pytest

from fx_smc_bot.data.dukascopy_bi5 import aggregate_bi5_payload


def _payload(records: list[tuple[int, int, int, int, int, bytes]]) -> bytes:
    raw = b"".join(
        struct.pack(">iiiii", second, open_raw, close_raw, low_raw, high_raw) + volume
        for second, open_raw, close_raw, low_raw, high_raw, volume in records
    )
    return lzma.compress(raw)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_raw_byte_aggregate_uses_declared_hash_contract() -> None:
    requested = date(2011, 3, 14)
    positive = struct.pack(">f", 1.5)
    negative_zero = b"\x80\x00\x00\x00"
    payload = _payload(
        [
            (0, 100, 102, 99, 103, positive),
            (86_399, 102, 101, 100, 104, positive),
            (60, 1, 1, 1, 1, negative_zero),
        ]
    )
    anchor = int(datetime(2011, 3, 14, tzinfo=timezone.utc).timestamp() * 1000)
    timestamps = [anchor, anchor + 86_399_000]
    ohlc = [[anchor, 100, 103, 99, 102], [anchor + 86_399_000, 102, 104, 100, 101]]

    result = aggregate_bi5_payload(payload, pair="EURUSD", requested_date=requested)

    assert result.raw_sha256 == _sha(payload)
    assert result.ordered_timestamp_sha256 == _sha(
        json.dumps(timestamps, separators=(",", ":")).encode()
    )
    assert result.integer_ohlc_sha256 == _sha(json.dumps(ohlc, separators=(",", ":")).encode())
    assert result.volume_bits_sha256 == _sha(positive + positive)
    assert result.zero_volume_excluded_count == 1
    assert result.negative_zero_excluded_count == 1
    assert result.ohlc_invariants_pass


def test_raw_byte_aggregate_rejects_non_finite_volume() -> None:
    payload = _payload([(0, 1, 1, 1, 1, b"\x7f\x80\x00\x00")])

    with pytest.raises(ValueError, match="A0R2_BI5_NON_FINITE_VOLUME"):
        aggregate_bi5_payload(payload, pair="USDJPY", requested_date=date(2010, 1, 4))
