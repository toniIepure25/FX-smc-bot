"""Point-in-time rate recovery and certification for Gate F.0.

The module is deliberately provider-agnostic.  Planning and dry-run status never
cross an I/O boundary; an explicitly injected adapter is required for recovery.
Raw rate rows remain in memory and are never written by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Protocol

from fx_smc_bot.research.classical_factor_safe_io import (
    FROZEN_INSTRUMENTS,
    DataProvider,
    IOAuthorization,
    OperationType,
    ProviderRequest,
    RatePartition,
    create_authorization,
    safe_provider_request,
)

PROGRAM_ID: Final = "FX_CLASSICAL_RISK_PREMIA_V1"
LINEAGE_ID: Final = "FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1"
DEVELOPMENT_START: Final = date(2010, 1, 1)
DEVELOPMENT_END: Final = date(2016, 12, 31)
DEVELOPMENT_YEARS: Final = tuple(range(2010, 2017))
MAXIMUM_WORKERS: Final = 4
EXPECTED_PARTITIONS: Final = 56

CURRENCY_ORDER: Final = ("USD", "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF")


@dataclass(frozen=True)
class RateRegistryEntry:
    """Frozen official-series identity and accounting convention."""

    currency: str
    series_identifier: str
    provider: DataProvider
    day_count_convention: str


RATE_REGISTRY: Final[dict[str, RateRegistryEntry]] = {
    "USD": RateRegistryEntry("USD", "EFFR", DataProvider.USD_NY_FED_EFFR, "ACT_360"),
    "EUR": RateRegistryEntry("EUR", "EONIA_TO_ESTR", DataProvider.EUR_ECB_EONIA_ESTR, "ACT_360"),
    "GBP": RateRegistryEntry("GBP", "IUDSOIA", DataProvider.GBP_BOE_SONIA, "ACT_365_FIXED"),
    "AUD": RateRegistryEntry(
        "AUD", "RBA_CASH_RATE", DataProvider.AUD_RBA_CASH_RATE, "ACT_365_FIXED"
    ),
    "NZD": RateRegistryEntry(
        "NZD",
        "B2_OVERNIGHT_INTERBANK_CASH_RATE",
        DataProvider.NZD_RBNZ_OVERNIGHT_RATE,
        "ACT_365_FIXED",
    ),
    "JPY": RateRegistryEntry(
        "JPY",
        "FM01'STRDCLUCON",
        DataProvider.JPY_BOJ_OVERNIGHT_CALL_RATE,
        "ACT_365_FIXED",
    ),
    "CAD": RateRegistryEntry(
        "CAD", "V39079", DataProvider.CAD_BANK_OF_CANADA_TARGET_OVERNIGHT, "ACT_365_FIXED"
    ),
    "CHF": RateRegistryEntry("CHF", "SRFXON3", DataProvider.CHF_SIX_SARON, "ACT_360"),
}


@dataclass(frozen=True)
class NormalizedRateRow:
    currency: str
    registry_series_identifier: str
    source_series_identifier: str
    observation_date: date
    value: float
    original_publication_timestamp: datetime
    effective_timestamp: datetime
    available_timestamp: datetime
    day_count_convention: str
    source_hash: str

    def as_record(self) -> dict[str, str | float]:
        return {
            "currency": self.currency,
            "registry_series_identifier": self.registry_series_identifier,
            "source_series_identifier": self.source_series_identifier,
            "observation_date": self.observation_date.isoformat(),
            "value": self.value,
            "original_publication_timestamp": _format_timestamp(
                self.original_publication_timestamp
            ),
            "effective_timestamp": _format_timestamp(self.effective_timestamp),
            "available_timestamp": _format_timestamp(self.available_timestamp),
            "day_count_convention": self.day_count_convention,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True)
class RejectedRateRow:
    row_index: int
    reason: str


@dataclass(frozen=True)
class RateNormalization:
    partition: RatePartition
    rows: tuple[NormalizedRateRow, ...]
    rejected: tuple[RejectedRateRow, ...]


@dataclass(frozen=True)
class RateCertification:
    partition: RatePartition
    rows: tuple[NormalizedRateRow, ...]
    row_count: int
    rejected_count: int
    content_sha256: str | None
    replay_sha256: tuple[str, str, str]
    three_run_parity: bool
    source_hashes: tuple[str, ...]
    status: str
    reasons: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {
            "partition_id": self.partition.partition_id,
            "row_count": self.row_count,
            "rejected_count": self.rejected_count,
            "content_sha256": self.content_sha256,
            "replay_sha256": list(self.replay_sha256),
            "three_run_parity": self.three_run_parity,
            "source_hashes": list(self.source_hashes),
            "row_level_rate_commit_allowed": False,
            "status": self.status,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PointInTimeRate:
    currency: str
    as_of: datetime
    value: float | None
    observation_date: date | None
    available_timestamp: datetime | None
    day_count_convention: str | None
    status: str
    reason: str | None


class RateProviderAdapter(Protocol):
    """Injectable official-source adapter; implementations own network details."""

    def fetch(
        self,
        request: ProviderRequest,
        registry_entry: RateRegistryEntry,
        source_series_identifier: str,
    ) -> Sequence[Mapping[str, object]]: ...


def source_series_identifier(currency: str, observation_date: date) -> str:
    """Resolve a frozen registry identity to the actual official source series."""
    entry = _registry_entry(currency)
    if currency != "EUR":
        return entry.series_identifier
    if observation_date <= date(2019, 9, 30):
        return "EONIA"
    return "ESTR"


def development_rate_partitions() -> tuple[RatePartition, ...]:
    partitions = tuple(
        RatePartition(currency, date(year, 1, 1), date(year, 12, 31))
        for currency in CURRENCY_ORDER
        for year in DEVELOPMENT_YEARS
    )
    if len(partitions) != EXPECTED_PARTITIONS or len(set(partitions)) != EXPECTED_PARTITIONS:
        raise RuntimeError("Gate F.0 rate plan is not exactly 56 unique partitions")
    return partitions


def development_rate_plan() -> dict[str, object]:
    tasks = [
        {
            "partition_id": partition.partition_id,
            "currency": partition.currency,
            "registry_series_identifier": RATE_REGISTRY[partition.currency].series_identifier,
            "source_series_identifier": source_series_identifier(
                partition.currency, partition.start
            ),
            "provider": RATE_REGISTRY[partition.currency].provider.value,
            "start": partition.start.isoformat(),
            "end": partition.end.isoformat(),
        }
        for partition in development_rate_partitions()
    ]
    plan_hash = _canonical_sha256(tasks)
    return {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "partition_granularity": "SERIES_BY_CALENDAR_YEAR",
        "partition_count": len(tasks),
        "maximum_workers": MAXIMUM_WORKERS,
        "tasks": tasks,
        "plan_sha256": plan_hash,
        "row_level_rate_commit_allowed": False,
    }


def development_rate_authorization(
    root: Path,
    repository_root: Path,
    currency: str,
) -> IOAuthorization:
    """Create one provider-scoped capability for the currency's seven partitions."""
    entry = _registry_entry(currency)
    partitions = frozenset(
        partition for partition in development_rate_partitions() if partition.currency == currency
    )
    return create_authorization(
        root=root,
        repository_root=repository_root,
        instruments=FROZEN_INSTRUMENTS,
        currencies=frozenset({currency}),
        start=DEVELOPMENT_START,
        end=DEVELOPMENT_END,
        partitions=partitions,
        provider=entry.provider,
        operation=OperationType.PROVIDER_REQUEST,
        forbidden_roots=(repository_root / "data",),
    )


def normalize_rate_rows(
    partition: RatePartition,
    raw_rows: Sequence[Mapping[str, object]],
) -> RateNormalization:
    """Normalize official rows and reject any row whose availability is unproven."""
    entry = _registry_entry(partition.currency)
    accepted: list[NormalizedRateRow] = []
    rejected: list[RejectedRateRow] = []
    for row_index, raw in enumerate(raw_rows):
        try:
            accepted.append(_normalize_row(entry, partition, raw))
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append(RejectedRateRow(row_index, str(exc)))

    accepted.sort(
        key=lambda row: (
            row.observation_date,
            row.available_timestamp,
            row.original_publication_timestamp,
            row.source_hash,
        )
    )
    conflicts = _conflicting_versions(accepted)
    if conflicts:
        rejected.extend(
            RejectedRateRow(-1, f"AMBIGUOUS_SAME_TIMESTAMP_REVISION:{key}")
            for key in sorted(conflicts)
        )
    return RateNormalization(partition, tuple(accepted), tuple(rejected))


def certify_rate_partition(
    partition: RatePartition,
    raw_rows: Sequence[Mapping[str, object]],
) -> RateCertification:
    """Replay deterministic normalization three times and certify provenance."""
    snapshots = tuple(dict(row) for row in raw_rows)
    runs = tuple(normalize_rate_rows(partition, snapshots) for _ in range(3))
    hashes = tuple(_normalization_sha256(run) for run in runs)
    replay_hashes = (hashes[0], hashes[1], hashes[2])
    parity = len(set(hashes)) == 1
    first = runs[0]
    reasons = tuple(sorted({item.reason for item in first.rejected}))
    if not parity:
        status = "BLOCKED_BY_NONDETERMINISM"
        reasons = (*reasons, "THREE_RUN_CONTENT_HASH_MISMATCH")
    elif first.rejected:
        status = "BLOCKED_BY_RATE_DATA_PROVENANCE"
    elif not first.rows:
        status = "BLOCKED_BY_RATE_DATA_PROVENANCE"
        reasons = ("NO_PROVEN_OFFICIAL_OBSERVATIONS",)
    else:
        status = "F0_RATE_PARTITION_CERTIFIED"
    return RateCertification(
        partition=partition,
        rows=first.rows,
        row_count=len(first.rows),
        rejected_count=len(first.rejected),
        content_sha256=hashes[0] if parity else None,
        replay_sha256=replay_hashes,
        three_run_parity=parity,
        source_hashes=tuple(sorted({row.source_hash for row in first.rows})),
        status=status,
        reasons=reasons,
    )


def point_in_time_rate(
    rows: Sequence[NormalizedRateRow],
    currency: str,
    as_of: datetime,
) -> PointInTimeRate:
    """Return the last official observation actually available at ``as_of``."""
    _registry_entry(currency)
    timestamp = _aware_utc(as_of, "as_of")
    eligible = [
        row for row in rows if row.currency == currency and row.available_timestamp <= timestamp
    ]
    if not eligible:
        return PointInTimeRate(
            currency,
            timestamp,
            None,
            None,
            None,
            None,
            "MISSING",
            "NO_PROVEN_RATE_AVAILABLE_AS_OF_TIMESTAMP",
        )
    selected = max(
        eligible,
        key=lambda row: (
            row.observation_date,
            row.available_timestamp,
            row.original_publication_timestamp,
            row.source_hash,
        ),
    )
    return PointInTimeRate(
        currency,
        timestamp,
        selected.value,
        selected.observation_date,
        selected.available_timestamp,
        selected.day_count_convention,
        "AVAILABLE_CARRIED_WITHOUT_INTERPOLATION",
        None,
    )


def day_count_fraction(start: date, end: date, convention: str) -> float:
    if end < start:
        raise ValueError("Day-count end precedes start")
    denominator = {"ACT_360": 360.0, "ACT_365_FIXED": 365.0}.get(convention)
    if denominator is None:
        raise ValueError("Unsupported frozen day-count convention")
    return (end - start).days / denominator


def recover_development_rates(
    root: Path,
    repository_root: Path,
    *,
    adapter: RateProviderAdapter | None = None,
    execute_provider: bool = False,
    workers: int = MAXIMUM_WORKERS,
) -> dict[str, object]:
    """Recover and certify all 56 partitions, or return a no-I/O dry run."""
    _validate_workers(workers)
    plan = development_rate_plan()
    if not execute_provider:
        return {
            "program_id": PROGRAM_ID,
            "stage": "recover-development-rates",
            "dry_run": True,
            "provider_requests_sent": 0,
            "planned_partitions": EXPECTED_PARTITIONS,
            "plan_sha256": plan["plan_sha256"],
            "row_level_rate_commit_allowed": False,
            "status": "DRY_RUN_NO_PROVIDER_ACCESS",
        }
    if adapter is None:
        raise ValueError("Explicit RateProviderAdapter required for provider execution")

    authorizations = {
        currency: development_rate_authorization(root, repository_root, currency)
        for currency in CURRENCY_ORDER
    }
    certifications: list[RateCertification] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="f0-rates") as pool:
        futures = {
            pool.submit(
                _recover_partition,
                authorizations[partition.currency],
                partition,
                adapter,
            ): partition
            for partition in development_rate_partitions()
        }
        for future in as_completed(futures):
            certifications.append(future.result())
    certifications.sort(key=lambda item: item.partition)
    certified = sum(item.status == "F0_RATE_PARTITION_CERTIFIED" for item in certifications)
    if certified == EXPECTED_PARTITIONS:
        status = "F0_DEVELOPMENT_RATES_CERTIFIED"
    elif any(item.status == "BLOCKED_BY_NONDETERMINISM" for item in certifications):
        status = "BLOCKED_BY_NONDETERMINISM"
    else:
        status = "BLOCKED_BY_RATE_DATA_PROVENANCE"
    return {
        "program_id": PROGRAM_ID,
        "stage": "recover-development-rates",
        "dry_run": False,
        "provider_requests_sent": EXPECTED_PARTITIONS,
        "planned_partitions": EXPECTED_PARTITIONS,
        "certified_partitions": certified,
        "plan_sha256": plan["plan_sha256"],
        "certifications": [item.summary() for item in certifications],
        "normalized_rows_committed": 0,
        "row_level_rate_commit_allowed": False,
        "status": status,
    }


def static_status() -> dict[str, object]:
    return {
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "development_interval": "2010-01-01..2016-12-31",
        "currencies": list(CURRENCY_ORDER),
        "planned_partitions": EXPECTED_PARTITIONS,
        "maximum_workers": MAXIMUM_WORKERS,
        "default_mode": "DRY_RUN",
        "provider_requests_sent": 0,
        "filesystem_inspected": False,
        "network_accessed": False,
        "row_level_rate_commit_allowed": False,
        "status": "READY_FOR_EXPLICIT_OFFICIAL_PROVIDER_ADAPTER",
    }


def _recover_partition(
    authorization: IOAuthorization,
    partition: RatePartition,
    adapter: RateProviderAdapter,
) -> RateCertification:
    entry = _registry_entry(partition.currency)
    source_identifier = source_series_identifier(partition.currency, partition.start)
    request = ProviderRequest(
        provider=entry.provider,
        partition=partition,
        start=partition.start,
        end=partition.end,
        resource_name=f"f0-rate-{partition.currency.lower()}-{partition.start.year}.json",
    )

    def fetch_after_guard(validated: ProviderRequest) -> Sequence[Mapping[str, object]]:
        if validated != request:
            raise RuntimeError("Validated Gate F.0 rate request changed unexpectedly")
        return adapter.fetch(validated, entry, source_identifier)

    raw_rows = safe_provider_request(authorization, request, fetch_after_guard)
    return certify_rate_partition(partition, raw_rows)


def _normalize_row(
    entry: RateRegistryEntry,
    partition: RatePartition,
    raw: Mapping[str, object],
) -> NormalizedRateRow:
    if raw.get("original_publication_timestamp_proven") is not True:
        raise ValueError("UNPROVEN_ORIGINAL_PUBLICATION_TIMESTAMP")
    if raw.get("effective_timestamp_proven") is not True:
        raise ValueError("UNPROVEN_EFFECTIVE_TIMESTAMP")
    observation = _parse_date(raw["observation_date"])
    if observation < partition.start or observation > partition.end:
        raise ValueError("OBSERVATION_OUTSIDE_AUTHORIZED_PARTITION")
    expected_source = source_series_identifier(entry.currency, observation)
    actual_source = raw.get("source_series_identifier")
    if actual_source != expected_source:
        raise ValueError("SOURCE_SERIES_IDENTIFIER_MISMATCH")
    value = _finite_float(raw["value"])
    publication = _parse_timestamp(raw["original_publication_timestamp"])
    effective = _parse_timestamp(raw["effective_timestamp"])
    source_hash = _combined_source_hash(raw)
    return NormalizedRateRow(
        currency=entry.currency,
        registry_series_identifier=entry.series_identifier,
        source_series_identifier=expected_source,
        observation_date=observation,
        value=value,
        original_publication_timestamp=publication,
        effective_timestamp=effective,
        available_timestamp=max(publication, effective),
        day_count_convention=entry.day_count_convention,
        source_hash=source_hash,
    )


def _combined_source_hash(raw: Mapping[str, object]) -> str:
    payload = _sha256(raw.get("source_payload_sha256"), "source payload")
    metadata = _sha256(raw.get("source_metadata_sha256"), "source metadata")
    return hashlib.sha256(f"{payload}:{metadata}".encode("ascii")).hexdigest()


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"INVALID_{label.upper().replace(' ', '_')}_SHA256")
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        raise ValueError(f"INVALID_{label.upper().replace(' ', '_')}_SHA256")
    return lowered


def _parse_date(value: object) -> date:
    if isinstance(value, datetime):
        raise TypeError("OBSERVATION_DATE_MUST_NOT_BE_DATETIME")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError("OBSERVATION_DATE_REQUIRED")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("INVALID_OBSERVATION_DATE") from exc


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return _aware_utc(value, "timestamp")
    if not isinstance(value, str):
        raise TypeError("TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    return _aware_utc(parsed, "timestamp")


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label.upper()}_MUST_HAVE_PROVEN_TIMEZONE_OFFSET")
    return value.astimezone(UTC)


def _finite_float(value: object) -> float:
    if isinstance(value, bool):
        raise TypeError("RATE_VALUE_MUST_BE_NUMERIC")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("RATE_VALUE_MUST_BE_NUMERIC") from exc
    if not math.isfinite(result):
        raise ValueError("RATE_VALUE_MUST_BE_FINITE")
    return result


def _conflicting_versions(rows: Sequence[NormalizedRateRow]) -> set[str]:
    seen: dict[tuple[date, datetime], tuple[float, str]] = {}
    conflicts: set[str] = set()
    for row in rows:
        key = (row.observation_date, row.available_timestamp)
        content = (row.value, row.source_hash)
        prior = seen.setdefault(key, content)
        if prior != content:
            conflicts.add(
                f"{row.observation_date.isoformat()}@{_format_timestamp(row.available_timestamp)}"
            )
    return conflicts


def _normalization_sha256(normalization: RateNormalization) -> str:
    payload = {
        "partition_id": normalization.partition.partition_id,
        "rows": [row.as_record() for row in normalization.rows],
        "rejected": [
            {"row_index": item.row_index, "reason": item.reason} for item in normalization.rejected
        ],
    }
    return _canonical_sha256(payload)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _registry_entry(currency: str) -> RateRegistryEntry:
    try:
        return RATE_REGISTRY[currency]
    except KeyError as exc:
        raise ValueError("Currency is outside the frozen Gate F.0 registry") from exc


def _validate_workers(workers: int) -> None:
    if not 1 <= workers <= MAXIMUM_WORKERS:
        raise ValueError("Gate F.0 rate workers must be between 1 and 4")


assert tuple(RATE_REGISTRY) == CURRENCY_ORDER
assert len(development_rate_partitions()) == EXPECTED_PARTITIONS
