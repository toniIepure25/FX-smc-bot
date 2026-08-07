from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from fx_smc_bot.data import dukascopy_bi5
from fx_smc_bot.data.dukascopy_bi5 import (
    BI5_INSTRUMENTS,
    NativeFetchResult,
    dukascopy_candle_url,
    instrument_metadata,
    sha256_bytes,
)


def test_all_authorized_a0r2_pairs_have_frozen_native_metadata() -> None:
    assert set(BI5_INSTRUMENTS) == {
        "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDCHF",
        "EURJPY", "GBPJPY", "AUDJPY",
    }
    assert all(item.candle_record_size == 24 for item in BI5_INSTRUMENTS.values())
    assert all(item.endianness == "big" for item in BI5_INSTRUMENTS.values())
    assert all(item.timezone == "UTC" for item in BI5_INSTRUMENTS.values())


@pytest.mark.parametrize("pair", sorted(BI5_INSTRUMENTS))
def test_native_urls_preserve_frozen_pair_and_side_contract(pair: str) -> None:
    metadata = instrument_metadata(pair)
    bid = dukascopy_candle_url(pair, date(2010, 1, 4), "bid")
    ask = dukascopy_candle_url(pair, date(2010, 1, 4), "ask")

    assert f"/{metadata.instrument_code}/2010/00/04/" in bid
    assert bid.endswith("/BID_candles_min_1.bi5")
    assert ask.endswith("/ASK_candles_min_1.bi5")


def test_unauthorized_native_pair_is_rejected() -> None:
    with pytest.raises(ValueError, match="A0R2_UNAUTHORIZED_NATIVE_BI5_INSTRUMENT"):
        instrument_metadata("NZDUSD")


def test_http_transport_v2_uses_urllib_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"primary-bi5"

    def fake_primary(url: str, out_file: Path, **_kwargs: object) -> NativeFetchResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(payload)
        return NativeFetchResult(
            url=url,
            status="PASS",
            http_status=200,
            content_length=len(payload),
            elapsed_seconds=0.001,
            attempts=1,
            raw_path=str(out_file),
            checksum=sha256_bytes(payload),
            client_id="python_urllib",
        )

    def forbidden_curl(*_args: object, **_kwargs: object) -> NativeFetchResult:
        raise AssertionError("curl fallback should not run after primary success")

    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", fake_primary)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day_curl", forbidden_curl)

    result = dukascopy_bi5.fetch_bi5_day_http_v2("mock://primary", tmp_path / "x.bi5")

    assert result.status == "PASS"
    assert result.client_id == "python_urllib"
    assert result.primary_status == "PASS"
    assert result.checksum == sha256_bytes(payload)


def test_http_transport_v2_falls_back_to_curl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"fallback-bi5"

    def failed_primary(url: str, _out_file: Path, **_kwargs: object) -> NativeFetchResult:
        return NativeFetchResult(
            url=url,
            status="FAIL",
            http_status=503,
            content_length=0,
            elapsed_seconds=0.001,
            attempts=1,
            error="HTTP 503",
            client_id="python_urllib",
        )

    def fake_curl(url: str, out_file: Path, **_kwargs: object) -> NativeFetchResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(payload)
        return NativeFetchResult(
            url=url,
            status="PASS",
            http_status=200,
            content_length=len(payload),
            elapsed_seconds=0.001,
            attempts=1,
            raw_path=str(out_file),
            checksum=sha256_bytes(payload),
            client_id="curl.exe",
        )

    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", failed_primary)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day_curl", fake_curl)

    result = dukascopy_bi5.fetch_bi5_day_http_v2("mock://fallback", tmp_path / "x.bi5")

    assert result.status == "PASS"
    assert result.client_id == "curl.exe"
    assert result.primary_status == "FAIL"
    assert result.attempts == 2
    assert result.checksum == sha256_bytes(payload)
