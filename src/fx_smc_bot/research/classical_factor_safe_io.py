"""Capability-restricted I/O for the Gate F.0 classical-factor clean room."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final, TypeVar

EARLIEST_AUTHORIZED_DATE: Final = date(2010, 1, 1)
LATEST_AUTHORIZED_DATE: Final = date(2022, 12, 31)
FROZEN_INSTRUMENTS: Final = frozenset(
    {
        "EURUSD",
        "GBPUSD",
        "AUDUSD",
        "NZDUSD",
        "USDJPY",
        "USDCAD",
        "USDCHF",
        "EURJPY",
        "GBPJPY",
        "AUDJPY",
    }
)
FROZEN_CURRENCIES: Final = frozenset({"USD", "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF"})
AUTHORIZED_MARKET_SIDES: Final = frozenset({"bid", "ask"})

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=-]*$")
_WILDCARD_CHARACTERS: Final = frozenset("*?[]{}")
_QUARANTINED_YEAR_TOKENS: Final = ("2023", "2024", "2025")


class SafeIOViolationError(RuntimeError):
    """Raised before a forbidden filesystem or provider boundary is crossed."""


class OperationType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    STAT = "STAT"
    DELETE = "DELETE"
    PROVIDER_REQUEST = "PROVIDER_REQUEST"


class DataProvider(str, Enum):
    DUKASCOPY_BI5_BID_ASK = "Dukascopy BI5 bid and ask"
    USD_NY_FED_EFFR = "Federal Reserve Bank of New York EFFR"
    EUR_ECB_EONIA_ESTR = "European Central Bank EONIA and euro short-term rate"
    GBP_BOE_SONIA = "Bank of England SONIA"
    JPY_BOJ_OVERNIGHT_CALL_RATE = "Bank of Japan uncollateralized overnight call rate"
    AUD_RBA_CASH_RATE = "Reserve Bank of Australia cash rate"
    NZD_RBNZ_OVERNIGHT_RATE = "Reserve Bank of New Zealand overnight rate"
    CAD_BANK_OF_CANADA_TARGET_OVERNIGHT = "Bank of Canada target for the overnight rate V39079"
    CHF_SIX_SARON = "SIX Swiss Exchange SARON"


RATE_PROVIDER_CURRENCY: Final[dict[DataProvider, str]] = {
    DataProvider.USD_NY_FED_EFFR: "USD",
    DataProvider.EUR_ECB_EONIA_ESTR: "EUR",
    DataProvider.GBP_BOE_SONIA: "GBP",
    DataProvider.JPY_BOJ_OVERNIGHT_CALL_RATE: "JPY",
    DataProvider.AUD_RBA_CASH_RATE: "AUD",
    DataProvider.NZD_RBNZ_OVERNIGHT_RATE: "NZD",
    DataProvider.CAD_BANK_OF_CANADA_TARGET_OVERNIGHT: "CAD",
    DataProvider.CHF_SIX_SARON: "CHF",
}


@dataclass(frozen=True, order=True)
class MarketPartition:
    instrument: str
    side: str
    start: date
    end: date

    @property
    def partition_id(self) -> str:
        return (
            f"market:{self.instrument}:{self.side}:{self.start.isoformat()}:{self.end.isoformat()}"
        )


@dataclass(frozen=True, order=True)
class RatePartition:
    currency: str
    start: date
    end: date

    @property
    def partition_id(self) -> str:
        return f"rate:{self.currency}:{self.start.isoformat()}:{self.end.isoformat()}"


DataPartition = MarketPartition | RatePartition


@dataclass(frozen=True)
class IOAuthorization:
    clean_room_root: Path
    authorized_instruments: frozenset[str]
    authorized_currencies: frozenset[str]
    authorized_start: date
    authorized_end: date
    authorized_partition_set: frozenset[DataPartition]
    authorized_provider: DataProvider
    authorized_operation: OperationType
    repository_root: Path
    forbidden_roots: tuple[Path, ...]


@dataclass(frozen=True)
class ProviderRequest:
    provider: DataProvider
    partition: DataPartition
    start: date
    end: date
    resource_name: str


T = TypeVar("T")


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.fspath(path))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((os.fspath(path), os.fspath(root)))
    except ValueError:
        return False
    return os.path.normcase(common) == _path_key(root)


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_relative_to(first, second) or _is_relative_to(second, first)


def _is_reparse_point(path: Path, stat_result: os.stat_result | None = None) -> bool:
    result = stat_result
    if result is None:
        try:
            result = os.lstat(path)
        except FileNotFoundError:
            return False
    attributes = getattr(result, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_flag)


def _guard_root_relationships(
    root: Path,
    repository_root: Path,
    forbidden_roots: tuple[Path, ...],
) -> None:
    if root == repository_root or _paths_overlap(root, repository_root):
        raise SafeIOViolationError("Clean-room root overlaps the repository root")
    if root == repository_root.parent:
        raise SafeIOViolationError("Clean-room root cannot be the repository parent")
    for forbidden_root in forbidden_roots:
        if _paths_overlap(root, forbidden_root):
            raise SafeIOViolationError("Clean-room root overlaps an explicitly forbidden old root")


def _guard_existing_components(root: Path, target: Path) -> None:
    current = root
    components = (Path(), *target.relative_to(root).parents[::-1], target.relative_to(root))
    for relative in components:
        current = root / relative
        try:
            result = os.lstat(current)
        except FileNotFoundError:
            break
        if _is_reparse_point(current, result):
            raise SafeIOViolationError("Path crosses a symlink or junction")


def configured_f0_root(repository_root: Path) -> Path:
    configured = os.environ.get("FX_F0_DATA_ROOT")
    if configured:
        return _lexical_absolute(Path(configured))
    return _lexical_absolute(
        repository_root.parent / "FX-smc-bot-local-data" / "f0_classical_factors_v1"
    )


def validate_clean_root(
    root: Path,
    repository_root: Path,
    *,
    forbidden_roots: tuple[Path, ...],
    require_empty: bool = False,
) -> Path:
    """Validate only the exact root; no neighboring directory is enumerated."""
    candidate = _lexical_absolute(root)
    repository = _lexical_absolute(repository_root)
    forbidden = tuple(_lexical_absolute(path) for path in forbidden_roots)

    _guard_root_relationships(candidate, repository, forbidden)

    try:
        result = os.lstat(candidate)
    except FileNotFoundError as exc:
        raise SafeIOViolationError("Clean-room root must already exist") from exc
    if _is_reparse_point(candidate, result):
        raise SafeIOViolationError("Clean-room root cannot be a symlink or junction")
    if not stat.S_ISDIR(result.st_mode):
        raise SafeIOViolationError("Clean-room root must be a directory")
    if require_empty:
        with os.scandir(candidate) as entries:
            if next(entries, None) is not None:
                raise SafeIOViolationError("Clean-room root must be empty")
    return candidate


def authorize_date(value: date) -> None:
    if value < EARLIEST_AUTHORIZED_DATE or value > LATEST_AUTHORIZED_DATE:
        raise SafeIOViolationError("Date is outside the frozen 2010-2022 interval")


def _validate_interval(start: date, end: date) -> None:
    authorize_date(start)
    authorize_date(end)
    if end < start:
        raise SafeIOViolationError("Date interval end precedes start")


def _validate_universe(
    instruments: frozenset[str],
    currencies: frozenset[str],
) -> None:
    if not instruments or not instruments.issubset(FROZEN_INSTRUMENTS):
        raise SafeIOViolationError("Authorization contains an unknown instrument")
    if not currencies or not currencies.issubset(FROZEN_CURRENCIES):
        raise SafeIOViolationError("Authorization contains an unknown currency")


def _validate_partition(partition: DataPartition) -> None:
    _validate_interval(partition.start, partition.end)
    if isinstance(partition, MarketPartition):
        if partition.instrument not in FROZEN_INSTRUMENTS:
            raise SafeIOViolationError("Partition instrument is outside the frozen universe")
        if partition.side not in AUTHORIZED_MARKET_SIDES:
            raise SafeIOViolationError("Partition side is outside the bid/ask contract")
        return
    if isinstance(partition, RatePartition):
        if partition.currency not in FROZEN_CURRENCIES:
            raise SafeIOViolationError("Partition currency is outside the frozen universe")
        return
    raise SafeIOViolationError("Unknown partition type")


def _validate_provider_partition(provider: DataProvider, partition: DataPartition) -> None:
    if provider is DataProvider.DUKASCOPY_BI5_BID_ASK:
        if not isinstance(partition, MarketPartition):
            raise SafeIOViolationError("Dukascopy capability may contain only market partitions")
        return
    expected_currency = RATE_PROVIDER_CURRENCY.get(provider)
    if expected_currency is None:
        raise SafeIOViolationError("Provider is not an approved market or rate authority")
    if not isinstance(partition, RatePartition) or partition.currency != expected_currency:
        raise SafeIOViolationError("Rate authority does not match the partition currency")


def create_authorization(
    *,
    root: Path,
    repository_root: Path,
    instruments: frozenset[str],
    currencies: frozenset[str],
    start: date,
    end: date,
    partitions: frozenset[DataPartition],
    provider: DataProvider,
    operation: OperationType,
    forbidden_roots: tuple[Path, ...],
    require_empty_root: bool = False,
) -> IOAuthorization:
    """Create a least-privilege capability after all non-I/O checks pass."""
    _validate_interval(start, end)
    _validate_universe(instruments, currencies)
    if not isinstance(provider, DataProvider):
        raise SafeIOViolationError("Provider must be an explicitly approved provider")
    if not isinstance(operation, OperationType):
        raise SafeIOViolationError("Operation must be explicit")
    if not partitions:
        raise SafeIOViolationError("Authorization must contain planned partitions")

    for partition in partitions:
        _validate_partition(partition)
        _validate_provider_partition(provider, partition)
        if partition.start < start or partition.end > end:
            raise SafeIOViolationError("Partition is outside authorization dates")
        if isinstance(partition, MarketPartition):
            if partition.instrument not in instruments:
                raise SafeIOViolationError("Partition instrument is not authorized")
        elif partition.currency not in currencies:
            raise SafeIOViolationError("Partition currency is not authorized")

    validated_root = validate_clean_root(
        root,
        repository_root,
        forbidden_roots=forbidden_roots,
        require_empty=require_empty_root,
    )
    return IOAuthorization(
        clean_room_root=validated_root,
        authorized_instruments=instruments,
        authorized_currencies=currencies,
        authorized_start=start,
        authorized_end=end,
        authorized_partition_set=partitions,
        authorized_provider=provider,
        authorized_operation=operation,
        repository_root=_lexical_absolute(repository_root),
        forbidden_roots=tuple(_lexical_absolute(path) for path in forbidden_roots),
    )


def _require_operation(authorization: IOAuthorization, expected: OperationType) -> None:
    if authorization.authorized_operation is not expected:
        raise SafeIOViolationError(f"Capability does not authorize {expected.value}")


def _require_planned_partition(
    authorization: IOAuthorization,
    partition: DataPartition,
) -> None:
    _validate_partition(partition)
    _validate_provider_partition(authorization.authorized_provider, partition)
    if partition not in authorization.authorized_partition_set:
        raise SafeIOViolationError("Partition is not in the immutable authorization set")
    if partition.start < authorization.authorized_start:
        raise SafeIOViolationError("Partition starts before the capability interval")
    if partition.end > authorization.authorized_end:
        raise SafeIOViolationError("Partition ends after the capability interval")
    if isinstance(partition, MarketPartition):
        if partition.instrument not in authorization.authorized_instruments:
            raise SafeIOViolationError("Partition instrument is not authorized")
    elif partition.currency not in authorization.authorized_currencies:
        raise SafeIOViolationError("Partition currency is not authorized")


def _validate_resource_name(resource_name: str) -> None:
    if any(character in resource_name for character in _WILDCARD_CHARACTERS):
        raise SafeIOViolationError("Wildcard and recursive patterns are forbidden")
    if any(token in resource_name for token in _QUARANTINED_YEAR_TOKENS):
        raise SafeIOViolationError("Resource name queries the quarantined interval")
    if (
        not _SAFE_COMPONENT.fullmatch(resource_name)
        or resource_name in {".", ".."}
        or "/" in resource_name
        or "\\" in resource_name
    ):
        raise SafeIOViolationError("Resource name must be one safe path component")


def _partition_components(partition: DataPartition) -> tuple[str, ...]:
    if isinstance(partition, MarketPartition):
        return (
            "market",
            "provider=dukascopy-bi5-bid-ask",
            f"instrument={partition.instrument}",
            f"side={partition.side}",
            f"start={partition.start.isoformat()}",
            f"end={partition.end.isoformat()}",
        )
    return (
        "rates",
        f"currency={partition.currency}",
        f"start={partition.start.isoformat()}",
        f"end={partition.end.isoformat()}",
    )


def partition_path(
    authorization: IOAuthorization,
    partition: DataPartition,
    resource_name: str,
) -> Path:
    """Construct one exact planned path without discovery or pattern expansion."""
    _require_planned_partition(authorization, partition)
    _validate_resource_name(resource_name)
    _guard_root_relationships(
        authorization.clean_room_root,
        authorization.repository_root,
        authorization.forbidden_roots,
    )
    target = _lexical_absolute(
        authorization.clean_room_root.joinpath(
            *_partition_components(partition),
            resource_name,
        )
    )
    if not _is_relative_to(target, authorization.clean_room_root):
        raise SafeIOViolationError("Path escapes the clean-room root")
    _guard_existing_components(authorization.clean_room_root, target)
    return target


def validate_provider_request(
    authorization: IOAuthorization,
    request: ProviderRequest,
) -> None:
    """Validate a request completely before a provider callback can run."""
    _require_operation(authorization, OperationType.PROVIDER_REQUEST)
    if request.provider is not authorization.authorized_provider:
        raise SafeIOViolationError("Request provider is not authorized")
    _validate_interval(request.start, request.end)
    _validate_resource_name(request.resource_name)
    _require_planned_partition(authorization, request.partition)
    if request.start < request.partition.start or request.end > request.partition.end:
        raise SafeIOViolationError("Request is outside its planned partition")


def safe_provider_request(
    authorization: IOAuthorization,
    request: ProviderRequest,
    callback: Callable[[ProviderRequest], T],
) -> T:
    validate_provider_request(authorization, request)
    return callback(request)


def safe_stat(
    authorization: IOAuthorization,
    partition: DataPartition,
    resource_name: str,
) -> os.stat_result | None:
    _require_operation(authorization, OperationType.STAT)
    path = partition_path(authorization, partition, resource_name)
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def safe_read_bytes(
    authorization: IOAuthorization,
    partition: DataPartition,
    resource_name: str,
) -> bytes:
    _require_operation(authorization, OperationType.READ)
    return partition_path(authorization, partition, resource_name).read_bytes()


def safe_prepare_partition_directory(
    authorization: IOAuthorization,
    partition: DataPartition,
) -> Path:
    _require_operation(authorization, OperationType.WRITE)
    probe = partition_path(authorization, partition, "directory-guard")
    probe.parent.mkdir(parents=True, exist_ok=True)
    _guard_existing_components(authorization.clean_room_root, probe)
    return probe.parent


def safe_atomic_write(
    authorization: IOAuthorization,
    partition: DataPartition,
    resource_name: str,
    payload: bytes,
) -> str:
    _require_operation(authorization, OperationType.WRITE)
    path = partition_path(authorization, partition, resource_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _guard_existing_components(authorization.clean_room_root, path)
    temporary = path.with_name(f"{path.name}.f0-tmp")
    _guard_existing_components(authorization.clean_room_root, temporary)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        digest = hashlib.sha256(payload).hexdigest()
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise SafeIOViolationError("Atomic-write hash verification failed")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return digest


def safe_unlink(
    authorization: IOAuthorization,
    partition: DataPartition,
    resource_name: str,
) -> None:
    _require_operation(authorization, OperationType.DELETE)
    partition_path(authorization, partition, resource_name).unlink(missing_ok=True)
