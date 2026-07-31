from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fx_smc_bot.research import classical_fx_rates as rates
from fx_smc_bot.research.classical_factor_safe_io import (
    DataProvider,
    IOAuthorization,
    OperationType,
    ProviderRequest,
    RatePartition,
    SafeIOViolationError,
)


def _partition(currency: str = "USD", year: int = 2010) -> RatePartition:
    return RatePartition(currency, date(year, 1, 1), date(year, 12, 31))


def _raw(
    currency: str = "USD",
    observation: date = date(2010, 1, 4),
    *,
    value: float = 0.0012,
    publication: datetime | None = None,
    effective: datetime | None = None,
    payload_hash: str = "a" * 64,
    metadata_hash: str = "b" * 64,
) -> dict[str, object]:
    publication = publication or datetime.combine(
        observation + timedelta(days=1), datetime.min.time(), UTC
    ).replace(hour=9)
    effective = effective or datetime.combine(observation, datetime.min.time(), UTC)
    return {
        "source_series_identifier": rates.source_series_identifier(currency, observation),
        "observation_date": observation.isoformat(),
        "value": value,
        "original_publication_timestamp": publication.isoformat(),
        "original_publication_timestamp_proven": True,
        "effective_timestamp": effective.isoformat(),
        "effective_timestamp_proven": True,
        "source_payload_sha256": payload_hash,
        "source_metadata_sha256": metadata_hash,
    }


def _authorization(
    partition: RatePartition,
    *,
    operation: OperationType = OperationType.PROVIDER_REQUEST,
) -> IOAuthorization:
    entry = rates.RATE_REGISTRY[partition.currency]
    return IOAuthorization(
        clean_room_root=Path("C:/synthetic-f0-root"),
        authorized_instruments=frozenset({"EURUSD"}),
        authorized_currencies=frozenset({partition.currency}),
        authorized_start=partition.start,
        authorized_end=partition.end,
        authorized_partition_set=frozenset({partition}),
        authorized_provider=entry.provider,
        authorized_operation=operation,
        repository_root=Path("C:/synthetic-repository"),
        forbidden_roots=(),
    )


class RecordingAdapter:
    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[ProviderRequest, rates.RateRegistryEntry, str]] = []

    def fetch(
        self,
        request: ProviderRequest,
        registry_entry: rates.RateRegistryEntry,
        source_series_identifier: str,
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((request, registry_entry, source_series_identifier))
        return self.rows


def test_registry_has_exact_frozen_official_series_and_day_counts() -> None:
    assert {
        currency: entry.series_identifier for currency, entry in rates.RATE_REGISTRY.items()
    } == {
        "USD": "EFFR",
        "EUR": "EONIA_TO_ESTR",
        "GBP": "IUDSOIA",
        "AUD": "RBA_CASH_RATE",
        "NZD": "B2_OVERNIGHT_INTERBANK_CASH_RATE",
        "JPY": "FM01'STRDCLUCON",
        "CAD": "V39079",
        "CHF": "SRFXON3",
    }
    assert rates.RATE_REGISTRY["CAD"].provider is DataProvider.CAD_BANK_OF_CANADA_TARGET_OVERNIGHT
    assert rates.RATE_REGISTRY["NZD"].provider is DataProvider.NZD_RBNZ_OVERNIGHT_RATE
    assert rates.RATE_REGISTRY["USD"].day_count_convention == "ACT_360"
    assert rates.RATE_REGISTRY["GBP"].day_count_convention == "ACT_365_FIXED"


def test_development_plan_is_exactly_8_currencies_by_7_years() -> None:
    plan = rates.development_rate_plan()
    tasks = plan["tasks"]
    assert isinstance(tasks, list)
    assert plan["partition_count"] == 56
    assert len(tasks) == 56
    assert len({task["partition_id"] for task in tasks}) == 56
    assert tasks[0]["start"] == "2010-01-01"
    assert tasks[-1]["end"] == "2016-12-31"
    assert plan == rates.development_rate_plan()


def test_eur_transition_is_explicit_and_development_uses_eonia() -> None:
    assert rates.source_series_identifier("EUR", date(2019, 9, 30)) == "EONIA"
    assert rates.source_series_identifier("EUR", date(2019, 10, 1)) == "ESTR"
    tasks = rates.development_rate_plan()["tasks"]
    assert isinstance(tasks, list)
    eur_tasks = [task for task in tasks if task["currency"] == "EUR"]
    assert {task["source_series_identifier"] for task in eur_tasks} == {"EONIA"}


def test_normalized_schema_uses_max_timestamp_and_combined_source_hash() -> None:
    observation = date(2010, 1, 4)
    publication = datetime(2010, 1, 5, 9, tzinfo=UTC)
    effective = datetime(2010, 1, 6, tzinfo=UTC)
    normalized = rates.normalize_rate_rows(
        _partition(),
        [_raw(observation=observation, publication=publication, effective=effective)],
    )
    assert normalized.rejected == ()
    row = normalized.rows[0]
    assert row.available_timestamp == effective
    assert row.day_count_convention == "ACT_360"
    assert row.registry_series_identifier == "EFFR"
    assert row.as_record() == {
        "currency": "USD",
        "registry_series_identifier": "EFFR",
        "source_series_identifier": "EFFR",
        "observation_date": "2010-01-04",
        "value": 0.0012,
        "original_publication_timestamp": "2010-01-05T09:00:00Z",
        "effective_timestamp": "2010-01-06T00:00:00Z",
        "available_timestamp": "2010-01-06T00:00:00Z",
        "day_count_convention": "ACT_360",
        "source_hash": row.source_hash,
    }
    assert len(row.source_hash) == 64


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("original_publication_timestamp_proven", False, "UNPROVEN_ORIGINAL"),
        ("effective_timestamp_proven", False, "UNPROVEN_EFFECTIVE"),
        ("original_publication_timestamp", "2010-01-05T09:00:00", "TIMEZONE"),
        ("effective_timestamp", None, "TIMESTAMP_REQUIRED"),
        ("source_metadata_sha256", None, "SOURCE_METADATA"),
    ],
)
def test_unproven_availability_or_source_evidence_fails_closed(
    field: str,
    value: object,
    reason: str,
) -> None:
    raw = _raw()
    raw[field] = value
    normalized = rates.normalize_rate_rows(_partition(), [raw])
    assert normalized.rows == ()
    assert normalized.rejected[0].row_index == 0
    assert reason in normalized.rejected[0].reason


def test_wrong_series_and_out_of_partition_rows_are_missing_not_reinterpreted() -> None:
    wrong_series = _raw()
    wrong_series["source_series_identifier"] = "UNOFFICIAL_RECONSTRUCTION"
    escaped = _raw(observation=date(2017, 1, 3))
    normalized = rates.normalize_rate_rows(_partition(), [wrong_series, escaped])
    assert normalized.rows == ()
    assert {item.reason for item in normalized.rejected} == {
        "SOURCE_SERIES_IDENTIFIER_MISMATCH",
        "OBSERVATION_OUTSIDE_AUTHORIZED_PARTITION",
    }


def test_point_in_time_join_does_not_interpolate_or_use_future_publication() -> None:
    rows = rates.normalize_rate_rows(
        _partition(),
        [
            _raw(
                observation=date(2010, 1, 4),
                value=0.01,
                publication=datetime(2010, 1, 5, 9, tzinfo=UTC),
            ),
            _raw(
                observation=date(2010, 1, 6),
                value=0.03,
                publication=datetime(2010, 1, 7, 9, tzinfo=UTC),
                payload_hash="c" * 64,
            ),
        ],
    ).rows
    missing = rates.point_in_time_rate(rows, "USD", datetime(2010, 1, 5, 8, tzinfo=UTC))
    carried = rates.point_in_time_rate(rows, "USD", datetime(2010, 1, 6, 12, tzinfo=UTC))
    current = rates.point_in_time_rate(rows, "USD", datetime(2010, 1, 7, 9, tzinfo=UTC))
    assert missing.status == "MISSING"
    assert missing.value is None
    assert carried.value == 0.01
    assert carried.status == "AVAILABLE_CARRIED_WITHOUT_INTERPOLATION"
    assert current.value == 0.03


def test_revision_is_not_backfilled_before_its_publication() -> None:
    observation = date(2010, 1, 4)
    original = _raw(
        observation=observation,
        value=0.01,
        publication=datetime(2010, 1, 5, 9, tzinfo=UTC),
    )
    revision = _raw(
        observation=observation,
        value=0.011,
        publication=datetime(2010, 1, 5, 14, 30, tzinfo=UTC),
        payload_hash="c" * 64,
        metadata_hash="d" * 64,
    )
    rows = rates.normalize_rate_rows(_partition(), [revision, original]).rows
    before = rates.point_in_time_rate(rows, "USD", datetime(2010, 1, 5, 10, tzinfo=UTC))
    after = rates.point_in_time_rate(rows, "USD", datetime(2010, 1, 5, 15, tzinfo=UTC))
    assert before.value == 0.01
    assert after.value == 0.011


def test_same_timestamp_conflicting_revision_blocks_certification() -> None:
    first = _raw(value=0.01)
    second = _raw(value=0.02, payload_hash="c" * 64)
    certification = rates.certify_rate_partition(_partition(), [first, second])
    assert certification.status == "BLOCKED_BY_RATE_DATA_PROVENANCE"
    assert certification.rejected_count == 1
    assert "AMBIGUOUS_SAME_TIMESTAMP_REVISION" in certification.reasons[0]


def test_three_run_certification_is_deterministic_and_commits_no_rows() -> None:
    certification = rates.certify_rate_partition(_partition(), [_raw()])
    assert certification.status == "F0_RATE_PARTITION_CERTIFIED"
    assert certification.three_run_parity
    assert len(set(certification.replay_sha256)) == 1
    assert certification.content_sha256 == certification.replay_sha256[0]
    assert certification.summary()["row_level_rate_commit_allowed"] is False


def test_empty_or_rejected_partition_cannot_be_certified() -> None:
    empty = rates.certify_rate_partition(_partition(), [])
    invalid = _raw()
    invalid["effective_timestamp_proven"] = False
    rejected = rates.certify_rate_partition(_partition(), [invalid])
    assert empty.status == "BLOCKED_BY_RATE_DATA_PROVENANCE"
    assert empty.reasons == ("NO_PROVEN_OFFICIAL_OBSERVATIONS",)
    assert rejected.status == "BLOCKED_BY_RATE_DATA_PROVENANCE"


def test_day_count_conventions_use_actual_calendar_days() -> None:
    start = date(2012, 2, 28)
    end = date(2012, 3, 1)
    assert rates.day_count_fraction(start, end, "ACT_360") == pytest.approx(2 / 360)
    assert rates.day_count_fraction(start, end, "ACT_365_FIXED") == pytest.approx(2 / 365)
    with pytest.raises(ValueError, match="Unsupported"):
        rates.day_count_fraction(start, end, "ACT_ACT")


def test_default_recovery_is_dry_run_and_crosses_no_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rates,
        "development_rate_authorization",
        lambda *_args, **_kwargs: pytest.fail("dry-run touched the clean root"),
    )
    result = rates.recover_development_rates(tmp_path, tmp_path / "repository")
    assert result["status"] == "DRY_RUN_NO_PROVIDER_ACCESS"
    assert result["provider_requests_sent"] == 0
    assert result["planned_partitions"] == 56


def test_explicit_execution_requires_injected_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Explicit RateProviderAdapter"):
        rates.recover_development_rates(
            tmp_path,
            tmp_path / "repository",
            execute_provider=True,
        )


def test_safe_io_guard_rejection_prevents_adapter_callback() -> None:
    partition = _partition()
    adapter = RecordingAdapter([_raw()])
    authorization = _authorization(partition, operation=OperationType.READ)
    with pytest.raises(SafeIOViolationError, match="PROVIDER_REQUEST"):
        rates._recover_partition(authorization, partition, adapter)
    assert adapter.calls == []


def test_safe_provider_callback_receives_exact_registry_identity() -> None:
    partition = _partition("CAD")
    adapter = RecordingAdapter([_raw("CAD")])
    certification = rates._recover_partition(_authorization(partition), partition, adapter)
    assert certification.status == "F0_RATE_PARTITION_CERTIFIED"
    request, entry, source_identifier = adapter.calls[0]
    assert request.partition == partition
    assert request.provider is DataProvider.CAD_BANK_OF_CANADA_TARGET_OVERNIGHT
    assert request.resource_name == "f0-rate-cad-2010.json"
    assert entry.series_identifier == "V39079"
    assert source_identifier == "V39079"


def test_full_injected_recovery_certifies_exactly_56_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[ProviderRequest] = []

    class SyntheticOfficialAdapter:
        def fetch(
            self,
            request: ProviderRequest,
            registry_entry: rates.RateRegistryEntry,
            source_identifier: str,
        ) -> Sequence[Mapping[str, object]]:
            calls.append(request)
            return [_raw(registry_entry.currency, request.partition.start)]

    monkeypatch.setattr(
        rates,
        "development_rate_authorization",
        lambda _root, _repository, currency: _authorization(_partition(currency)),
    )

    def guarded(
        _authorization_value: IOAuthorization,
        request: ProviderRequest,
        callback: Any,
    ) -> Sequence[Mapping[str, object]]:
        return callback(request)

    monkeypatch.setattr(rates, "safe_provider_request", guarded)
    result = rates.recover_development_rates(
        tmp_path,
        tmp_path / "repository",
        adapter=SyntheticOfficialAdapter(),
        execute_provider=True,
        workers=4,
    )
    assert result["status"] == "F0_DEVELOPMENT_RATES_CERTIFIED"
    assert result["certified_partitions"] == 56
    assert result["normalized_rows_committed"] == 0
    assert len(calls) == 56


@pytest.mark.parametrize("workers", [0, 5, -1])
def test_worker_count_is_bounded(workers: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 4"):
        rates.recover_development_rates(tmp_path, tmp_path / "repository", workers=workers)


def test_module_uses_no_broad_discovery_network_or_row_write_api() -> None:
    path = Path(rates.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_attributes = {
        "glob",
        "rglob",
        "walk",
        "scandir",
        "urlopen",
        "request",
        "post",
        "put",
    }
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    assert used == set()
    source = path.read_text(encoding="utf-8")
    assert "safe_atomic_write" not in source
    imported_roots = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported_roots.isdisjoint({"httpx", "requests", "urllib"})


def test_static_status_is_nonempirical_and_noninspecting() -> None:
    status = rates.static_status()
    assert status["provider_requests_sent"] == 0
    assert status["filesystem_inspected"] is False
    assert status["network_accessed"] is False
    assert status["row_level_rate_commit_allowed"] is False
