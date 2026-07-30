from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from fx_smc_bot.data import daily_checkpoint, dukascopy_bi5
from fx_smc_bot.data.daily_checkpoint import DayStatus, MonthManifest
from fx_smc_bot.data.dukascopy_bi5 import NativeFetchResult
from fx_smc_bot.research.strategy_alpha_data import RecoveryPartition

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_gate_p0rdcra1a.py"


@pytest.fixture(scope="module")
def gate_module():
    spec = importlib.util.spec_from_file_location(
        "run_gate_p0rdcra1a_fallback_tests",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(instrument: str, side: str, year: int) -> MonthManifest:
    return MonthManifest(
        pair=instrument,
        side=side,
        year=year,
        month=1,
        days=[
            DayStatus(
                pair=instrument,
                side=side,
                year=year,
                month=1,
                day=4,
                status="complete",
                rows=1,
                checksum="primary-success",
                file_size=100,
            ),
            DayStatus(
                pair=instrument,
                side=side,
                year=year,
                month=1,
                day=5,
                status="market_closed",
                failure_category="MARKET_CLOSED_HOLIDAY",
            ),
            DayStatus(
                pair=instrument,
                side=side,
                year=year,
                month=1,
                day=6,
                status="failed",
                failure_category="TRANSIENT_NETWORK_ERROR",
                error="synthetic primary failure",
                attempts=5,
            ),
            DayStatus(
                pair=instrument,
                side=side,
                year=year,
                month=1,
                day=7,
                status="complete",
                rows=0,
                failure_category="NO_PROVIDER_DATA",
                checksum="empty-primary",
                file_size=2,
            ),
        ],
    )


def _synthetic_row(day: date) -> dict[str, int | float]:
    timestamp = int(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
        * 1000
    )
    return {
        "timestamp": timestamp,
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "volume": 10.0,
        "open_raw": 110000,
        "high_raw": 120000,
        "low_raw": 100000,
        "close_raw": 115000,
    }


@pytest.mark.parametrize(
    ("instrument", "side", "year"),
    [("EURUSD", "BID", 2015), ("GBPUSD", "ASK", 2022)],
)
def test_native_fallback_repairs_only_failed_or_zero_row_authorized_days(
    gate_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    instrument: str,
    side: str,
    year: int,
) -> None:
    raw_root = tmp_path / "synthetic-raw"
    manifest = _manifest(instrument, side, year)
    primary_calls: list[tuple[str, str, int, int]] = []
    url_calls: list[tuple[str, date, str]] = []
    fetch_calls: list[tuple[str, Path]] = []
    parse_calls: list[date] = []

    def fake_primary(
        pair: str,
        requested_side: str,
        requested_year: int,
        month: int,
        raw_dir: Path,
        **_kwargs,
    ) -> MonthManifest:
        assert raw_dir == raw_root
        primary_calls.append((pair, requested_side, requested_year, month))
        return manifest

    def fake_url(pair: str, requested_day: date, requested_side: str) -> str:
        url_calls.append((pair, requested_day, requested_side))
        return f"mock://{pair}/{requested_day.isoformat()}/{requested_side}"

    def fake_fetch(url: str, out_file: Path, **_kwargs) -> NativeFetchResult:
        fetch_calls.append((url, out_file))
        out_file.parent.mkdir(parents=True, exist_ok=True)
        payload = f"synthetic-bi5:{url}".encode()
        out_file.write_bytes(payload)
        return NativeFetchResult(
            url=url,
            status="PASS",
            http_status=200,
            content_length=len(payload),
            elapsed_seconds=0.001,
            attempts=1,
            raw_path=str(out_file),
            checksum=dukascopy_bi5.sha256_bytes(payload),
        )

    def fake_parse(
        _payload: bytes,
        requested_day: date,
        **_kwargs,
    ) -> list[dict[str, int | float]]:
        parse_calls.append(requested_day)
        return [_synthetic_row(requested_day)]

    def fake_validate(
        rows: list[dict[str, int | float]],
        requested_day: date,
    ) -> dict[str, int | bool | None]:
        assert rows == [_synthetic_row(requested_day)]
        return {
            "row_count": 1,
            "first_timestamp": rows[0]["timestamp"],
            "last_timestamp": rows[0]["timestamp"],
            "monotonic_timestamps": True,
            "timestamps_in_requested_day": True,
            "ohlc_valid": True,
        }

    monkeypatch.setattr(gate_module, "RAW_ROOTS", (tmp_path, tmp_path, raw_root))
    monkeypatch.setattr(daily_checkpoint, "acquire_month_bulk", fake_primary)
    monkeypatch.setattr(dukascopy_bi5, "dukascopy_candle_url", fake_url)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", fake_fetch)
    monkeypatch.setattr(dukascopy_bi5, "parse_bi5_m1_candles", fake_parse)
    monkeypatch.setattr(dukascopy_bi5, "validate_m1_rows", fake_validate)
    # Keep the test effective if the integration imports these symbols at module scope.
    monkeypatch.setattr(gate_module, "dukascopy_candle_url", fake_url, raising=False)
    monkeypatch.setattr(gate_module, "fetch_bi5_day", fake_fetch, raising=False)
    monkeypatch.setattr(gate_module, "parse_bi5_m1_candles", fake_parse, raising=False)
    monkeypatch.setattr(gate_module, "validate_m1_rows", fake_validate, raising=False)

    partition = RecoveryPartition(instrument, year, 1, side)
    gate_module._acquire_repair_unit(
        instrument,
        side,
        year,
        1,
        {partition.partition_id},
    )

    expected_days = [date(year, 1, 6), date(year, 1, 7)]
    assert [item[1] for item in url_calls] == expected_days
    assert parse_calls == expected_days
    assert len(fetch_calls) == 2
    assert all(item[0] == instrument for item in url_calls)
    assert all(item[2].upper() == side for item in url_calls)

    persisted = daily_checkpoint.load_month_manifest(
        raw_root,
        instrument,
        side,
        year,
        1,
    )
    assert persisted is not None
    days = {item.day: item for item in persisted.days}
    assert days[4].checksum == "primary-success"
    assert days[5].status == "market_closed"
    for day_number in (6, 7):
        repaired = days[day_number]
        assert repaired.status == "complete"
        assert repaired.rows == 1
        assert repaired.checksum
        assert repaired.file_size > 2
        assert repaired.failure_category == ""
        assert repaired.error == ""
        assert repaired.completed_at
        day_file = daily_checkpoint._day_dir(
            raw_root,
            instrument,
            side,
            year,
            1,
            day_number,
        ) / "data.json"
        assert json.loads(day_file.read_text(encoding="utf-8")) == [
            _synthetic_row(date(year, 1, day_number))
        ]

    tracked_files = sorted(
        path for path in raw_root.rglob("*") if path.is_file()
    )
    first_snapshot = {path.relative_to(raw_root): path.read_bytes() for path in tracked_files}
    assert not list(raw_root.rglob("*.tmp"))

    gate_module._acquire_repair_unit(
        instrument,
        side,
        year,
        1,
        {partition.partition_id},
    )

    second_snapshot = {
        path.relative_to(raw_root): path.read_bytes()
        for path in sorted(raw_root.rglob("*"))
        if path.is_file()
    }
    assert len(primary_calls) == 2
    assert len(fetch_calls) == 2
    assert first_snapshot == second_snapshot
    assert not list(raw_root.rglob("*.tmp"))


@pytest.mark.parametrize(
    ("instrument", "year", "error"),
    [
        ("EURUSD", 2014, "precedes the permitted"),
        ("GBPUSD", 2023, "sealed holdout"),
        ("USDJPY", 2021, "instrument is not"),
    ],
)
def test_acquisition_guard_rejects_before_any_provider_access(
    gate_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    instrument: str,
    year: int,
    error: str,
) -> None:
    provider_calls: list[str] = []

    def forbidden_provider(*_args, **_kwargs):
        provider_calls.append("called")
        raise AssertionError("provider access occurred before the amended guard")

    monkeypatch.setattr(gate_module, "RAW_ROOTS", (tmp_path, tmp_path, tmp_path))
    monkeypatch.setattr(daily_checkpoint, "acquire_month_bulk", forbidden_provider)
    monkeypatch.setattr(dukascopy_bi5, "dukascopy_candle_url", forbidden_provider)
    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", forbidden_provider)
    monkeypatch.setattr(
        gate_module,
        "dukascopy_candle_url",
        forbidden_provider,
        raising=False,
    )
    monkeypatch.setattr(gate_module, "fetch_bi5_day", forbidden_provider, raising=False)

    partition = RecoveryPartition(instrument, year, 1, "BID")
    with pytest.raises(ValueError, match=error):
        gate_module._acquire_repair_unit(
            instrument,
            "BID",
            year,
            1,
            {partition.partition_id},
        )

    assert provider_calls == []
    assert list(tmp_path.iterdir()) == []


def test_full_closed_saturday_is_normalized_but_sunday_open_is_repaired(
    gate_module,
) -> None:
    saturday = DayStatus(
        pair="EURUSD",
        side="ASK",
        year=2017,
        month=11,
        day=18,
        status="failed",
    )
    sunday = DayStatus(
        pair="EURUSD",
        side="ASK",
        year=2017,
        month=11,
        day=19,
        status="failed",
    )

    assert gate_module._is_closed_saturday_repair_candidate(saturday) is True
    assert gate_module._requires_native_fallback(saturday) is False
    assert gate_module._is_closed_saturday_repair_candidate(sunday) is False
    assert gate_module._requires_native_fallback(sunday) is True


def test_legacy_native_checkpoint_categories_are_migrated(gate_module) -> None:
    manifest = MonthManifest(
        pair="EURUSD",
        side="ASK",
        year=2017,
        month=11,
        days=[
            DayStatus(
                pair="EURUSD",
                side="ASK",
                year=2017,
                month=11,
                day=17,
                status="failed",
                failure_category="NATIVE_BI5_FETCH_FAILURE",
            ),
            DayStatus(
                pair="EURUSD",
                side="ASK",
                year=2017,
                month=11,
                day=18,
                status="failed",
                failure_category="NATIVE_BI5_VALIDATION_FAILURE",
            ),
        ],
    )

    assert gate_module._normalize_native_checkpoint_categories(manifest) is True
    assert [item.failure_category for item in manifest.days] == [
        "UNKNOWN_ERROR",
        "PARSER_ERROR",
    ]
    assert gate_module._normalize_native_checkpoint_categories(manifest) is False


def test_valid_zero_volume_provider_payload_is_market_closed(
    gate_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = MonthManifest(
        pair="EURUSD",
        side="BID",
        year=2017,
        month=12,
        days=[
            DayStatus(
                pair="EURUSD",
                side="BID",
                year=2017,
                month=12,
                day=day_number,
                status="failed" if day_number == 31 else "market_closed",
            )
            for day_number in range(1, 32)
        ],
    )

    def fake_fetch(url: str, out_file: Path, **_kwargs) -> NativeFetchResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"synthetic-valid-zero-volume-bi5")
        return NativeFetchResult(
            url=url,
            status="PASS",
            http_status=200,
            content_length=31,
            elapsed_seconds=0.001,
            attempts=1,
            raw_path=str(out_file),
            checksum="synthetic",
        )

    monkeypatch.setattr(dukascopy_bi5, "fetch_bi5_day", fake_fetch)
    monkeypatch.setattr(dukascopy_bi5, "parse_bi5_m1_candles", lambda *_a, **_k: [])
    monkeypatch.setattr(
        dukascopy_bi5,
        "validate_m1_rows",
        lambda *_a, **_k: {
            "row_count": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "monotonic_timestamps": True,
            "timestamps_in_requested_day": True,
            "ohlc_valid": True,
        },
    )
    partition = RecoveryPartition("EURUSD", 2017, 12, "BID")

    attempts = gate_module._repair_manifest_with_native_bi5(
        manifest,
        raw_root=tmp_path,
        planned_ids={partition.partition_id},
    )

    assert len(attempts) == 1
    assert attempts[0]["status"] == "MARKET_CLOSED"
    assert attempts[0]["validation_status"] == "PROVIDER_CLOSED_ZERO_VOLUME"
    day_status = next(item for item in manifest.days if item.day == 31)
    assert day_status.status == "market_closed"
    assert day_status.failure_category == "MARKET_CLOSED_HOLIDAY"
    assert day_status.rows == 0
