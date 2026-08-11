from __future__ import annotations

import subprocess
import time
from datetime import date
from pathlib import Path

import pytest

from fx_smc_bot.data import daily_checkpoint, dukascopy_bi5
from fx_smc_bot.data.dukascopy_bi5 import (
    BI5_INSTRUMENTS,
    RUNNER_DEADLINE_RESERVE_SECONDS,
    RUNTIME_BUDGET_EXHAUSTED,
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


def test_http_transport_v2_preserves_url_for_curl_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[str] = []

    def failed_primary(url: str, _out_file: Path, **_kwargs: object) -> NativeFetchResult:
        seen.append(f"primary:{url}")
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

    def failed_curl(url: str, _out_file: Path, **_kwargs: object) -> NativeFetchResult:
        seen.append(f"curl:{url}")
        return NativeFetchResult(
            url=url,
            status="FAIL",
            http_status=503,
            content_length=0,
            elapsed_seconds=0.001,
            attempts=1,
            error="HTTP 503",
            client_id="curl.exe",
        )

    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", failed_primary)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day_curl", failed_curl)

    result = dukascopy_bi5.fetch_bi5_day_http_v2("mock://same-url", tmp_path / "x.bi5")

    assert result.status == "FAIL"
    assert result.client_id == "curl.exe"
    assert result.primary_status == "FAIL"
    assert result.http_status == 503
    assert seen == ["primary:mock://same-url", "curl:mock://same-url"]


def test_http_transport_v2_stops_retry_chain_at_runner_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    timeouts: list[float] = []

    def fake_urlopen(_request: object, *, timeout: float):
        timeouts.append(timeout)
        raise TimeoutError("synthetic slow provider")

    def forbidden_curl(*_args: object, **_kwargs: object) -> NativeFetchResult:
        raise AssertionError("curl fallback must not start after runner budget is exhausted")

    monkeypatch.setattr(dukascopy_bi5, "urlopen", fake_urlopen)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day_curl", forbidden_curl)

    result = dukascopy_bi5.fetch_bi5_day_http_v2(
        "mock://deadline",
        tmp_path / "x.bi5",
        runner_deadline_monotonic=time.monotonic() + RUNNER_DEADLINE_RESERVE_SECONDS + 1.0,
    )

    assert result.status == "FAIL"
    assert result.failure_category == RUNTIME_BUDGET_EXHAUSTED
    assert result.error == RUNTIME_BUDGET_EXHAUSTED
    assert len(timeouts) == 1
    assert 0 < timeouts[0] < 30


def test_curl_subprocess_has_hard_runner_deadline_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(dukascopy_bi5.shutil, "which", lambda _name: "curl.exe")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="503", stderr="")

    monkeypatch.setattr(dukascopy_bi5.subprocess, "run", fake_run)

    result = dukascopy_bi5.fetch_bi5_day_curl(
        "mock://curl-deadline",
        tmp_path / "x.bi5",
        retries=1,
        timeout_seconds=45,
        runner_deadline_monotonic=time.monotonic() + RUNNER_DEADLINE_RESERVE_SECONDS + 2.0,
    )

    assert result.status == "FAIL"
    assert len(calls) == 1
    timeout = calls[0]["timeout"]
    assert isinstance(timeout, float)
    assert 0 < timeout < 45
    args = calls[0]["args"]
    assert isinstance(args, list)
    max_time = float(args[args.index("--max-time") + 1])
    assert 0 < max_time < 45
    assert max_time == pytest.approx(timeout, abs=0.01)


def test_native_checkpoint_records_http_v2_day_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"synthetic-bi5"
    requested = date(2010, 1, 4)
    row = {
        "timestamp": 1262563200000,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 1.0,
        "open_raw": 100000,
        "high_raw": 110000,
        "low_raw": 90000,
        "close_raw": 105000,
    }

    def fake_fetch(url: str, out_file: Path, **_kwargs: object) -> NativeFetchResult:
        assert url.endswith("/EURUSD/2010/00/04/BID_candles_min_1.bi5")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(payload)
        return NativeFetchResult(
            url=url,
            status="PASS",
            http_status=200,
            content_length=len(payload),
            elapsed_seconds=0.001,
            attempts=2,
            raw_path=str(out_file),
            checksum=sha256_bytes(payload),
            client_id="curl.exe",
            primary_status="FAIL",
        )

    monkeypatch.setattr(daily_checkpoint, "fetch_bi5_day_http_v2", fake_fetch)
    monkeypatch.setattr(
        daily_checkpoint,
        "parse_bi5_m1_candles",
        lambda _payload, day, **_kwargs: [row] if day == requested else [],
    )
    monkeypatch.setattr(
        daily_checkpoint,
        "validate_m1_rows",
        lambda _rows, _day: {
            "row_count": 1,
            "first_timestamp": row["timestamp"],
            "last_timestamp": row["timestamp"],
            "monotonic_timestamps": True,
            "timestamps_in_requested_day": True,
            "ohlc_valid": True,
        },
    )

    status = daily_checkpoint.download_native_day_with_checkpoint(
        "EURUSD",
        "bid",
        2010,
        1,
        4,
        tmp_path / "raw",
        tmp_path / "native",
    )

    assert status.status == "complete"
    assert status.attempts == 1
    assert status.transport_id == dukascopy_bi5.HTTP_TRANSPORT_V2_ID
    assert status.effective_http_client == "curl.exe"
    assert status.native_primary_status == "FAIL"
    assert status.native_http_status == 200
    assert status.native_content_length == len(payload)
    assert status.native_http_attempts == 2
    assert status.raw_hash == sha256_bytes(payload)
