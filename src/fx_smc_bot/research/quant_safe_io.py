"""Capability-based market I/O for the Gate Q.0-R clean room."""

from __future__ import annotations

import calendar
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final

EARLIEST_AUTHORIZED_DATE: Final = date(2015, 1, 1)
LATEST_AUTHORIZED_DATE: Final = date(2022, 12, 31)
FROZEN_INSTRUMENTS: Final = frozenset(
    {"AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURJPY", "GBPJPY"}
)
AUTHORIZED_SIDES: Final = frozenset({"bid", "ask"})
_SAFE_LEAF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_WILDCARD_CHARACTERS: Final = frozenset("*?[]{}")


class SafeIOViolationError(RuntimeError):
    """Raised before a market-data boundary can be crossed."""


class OperationType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    STAT = "STAT"
    DELETE = "DELETE"
    PROVIDER_REQUEST = "PROVIDER_REQUEST"


@dataclass(frozen=True, order=True)
class MarketPartition:
    instrument: str
    side: str
    year: int
    month: int

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def partition_id(self) -> str:
        return f"{self.instrument}:{self.side}:{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class MarketIOAuthorization:
    authorized_root: Path
    authorized_instruments: frozenset[str]
    authorized_start: date
    authorized_end: date
    authorized_partitions: frozenset[MarketPartition]
    authorized_operation: OperationType


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(root))) == os.fspath(root)
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _guard_existing_components(root: Path, target: Path) -> None:
    current = root
    if _is_reparse_point(current):
        raise SafeIOViolationError("Authorized root is a symlink or junction")
    relative = target.relative_to(root)
    for part in relative.parts[:-1]:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise SafeIOViolationError("Path crosses a symlink or junction")


def configured_q0r_root(repository_root: Path) -> Path:
    configured = os.environ.get("FX_Q0R_DATA_ROOT")
    if configured:
        return _lexical_absolute(Path(configured))
    return _lexical_absolute(repository_root.parent / "FX-smc-bot-local-data" / "q0r_v2")


def validate_clean_root(
    root: Path,
    repository_root: Path,
    *,
    forbidden_roots: tuple[Path, ...] = (),
    require_empty: bool = True,
) -> Path:
    """Validate an exact configured root without exploring any neighboring storage."""
    candidate = _lexical_absolute(root)
    repository = _lexical_absolute(repository_root)
    forbidden = {_lexical_absolute(path) for path in forbidden_roots}
    if candidate == repository or _is_relative_to(candidate, repository):
        raise SafeIOViolationError("Clean-room root cannot be inside the repository")
    if _is_relative_to(repository, candidate):
        raise SafeIOViolationError("Clean-room root cannot be an ancestor of the repository")
    if candidate in forbidden:
        raise SafeIOViolationError("Configured root is a forbidden predecessor root")
    if not candidate.is_dir():
        raise SafeIOViolationError("Clean-room root must already exist as a directory")
    if _is_reparse_point(candidate):
        raise SafeIOViolationError("Clean-room root cannot be a symlink or junction")
    if require_empty:
        try:
            next(candidate.iterdir())
        except StopIteration:
            pass
        else:
            raise SafeIOViolationError("Clean-room root must initially be empty")
    return candidate


def authorize_date(value: date) -> None:
    if value < EARLIEST_AUTHORIZED_DATE or value > LATEST_AUTHORIZED_DATE:
        raise SafeIOViolationError("Date is outside the frozen Q.0-R authorization window")


def _validate_partition_fields(partition: MarketPartition) -> None:
    if partition.instrument not in FROZEN_INSTRUMENTS:
        raise SafeIOViolationError("Instrument is outside the frozen Q.0-R universe")
    if partition.side not in AUTHORIZED_SIDES:
        raise SafeIOViolationError("Market side is outside the frozen bid/ask contract")
    authorize_date(partition.first_day)
    authorize_date(partition.last_day)


def create_authorization(
    *,
    root: Path,
    repository_root: Path,
    instruments: frozenset[str],
    start: date,
    end: date,
    partitions: frozenset[MarketPartition],
    operation: OperationType,
    forbidden_roots: tuple[Path, ...] = (),
    require_empty_root: bool = False,
) -> MarketIOAuthorization:
    authorize_date(start)
    authorize_date(end)
    if end < start:
        raise SafeIOViolationError("Authorization end precedes start")
    if not instruments or not instruments.issubset(FROZEN_INSTRUMENTS):
        raise SafeIOViolationError("Authorization contains an unknown instrument")
    for partition in partitions:
        _validate_partition_fields(partition)
        if partition.instrument not in instruments:
            raise SafeIOViolationError("Partition instrument is not authorized")
        if partition.first_day < start or partition.last_day > end:
            raise SafeIOViolationError("Partition is outside authorization dates")
    validated_root = validate_clean_root(
        root,
        repository_root,
        forbidden_roots=forbidden_roots,
        require_empty=require_empty_root,
    )
    return MarketIOAuthorization(
        authorized_root=validated_root,
        authorized_instruments=instruments,
        authorized_start=start,
        authorized_end=end,
        authorized_partitions=partitions,
        authorized_operation=operation,
    )


def _require_operation(
    authorization: MarketIOAuthorization, expected: OperationType
) -> None:
    if authorization.authorized_operation is not expected:
        raise SafeIOViolationError(f"Capability does not authorize {expected.value}")


def authorize_provider_request(
    authorization: MarketIOAuthorization,
    instrument: str,
    start: date,
    end: date,
) -> tuple[MarketPartition, ...]:
    """Authorize transport before any provider client or path is constructed."""
    authorize_date(start)
    authorize_date(end)
    if end < start:
        raise SafeIOViolationError("Provider request end precedes start")
    if instrument not in authorization.authorized_instruments:
        raise SafeIOViolationError("Provider request instrument is not authorized")
    if start < authorization.authorized_start or end > authorization.authorized_end:
        raise SafeIOViolationError("Provider request is outside capability dates")
    _require_operation(authorization, OperationType.PROVIDER_REQUEST)
    required = tuple(
        sorted(
            partition
            for partition in authorization.authorized_partitions
            if partition.instrument == instrument
            and partition.last_day >= start
            and partition.first_day <= end
        )
    )
    if not required:
        raise SafeIOViolationError("Provider request has no planned partition")
    return required


def partition_path(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
    leaf_name: str,
) -> Path:
    """Build one planned path without directory discovery or wildcard expansion."""
    _validate_partition_fields(partition)
    if partition not in authorization.authorized_partitions:
        raise SafeIOViolationError("Partition is not in the immutable authorization set")
    if partition.instrument not in authorization.authorized_instruments:
        raise SafeIOViolationError("Partition instrument is not authorized")
    if any(character in leaf_name for character in _WILDCARD_CHARACTERS):
        raise SafeIOViolationError("Wildcards are forbidden in market-data paths")
    if not _SAFE_LEAF.fullmatch(leaf_name) or leaf_name in {".", ".."}:
        raise SafeIOViolationError("Leaf name is not a single safe path component")
    target = _lexical_absolute(
        authorization.authorized_root
        / partition.instrument
        / f"price={partition.side}"
        / f"year={partition.year:04d}"
        / f"month={partition.month:02d}"
        / leaf_name
    )
    if not _is_relative_to(target, authorization.authorized_root):
        raise SafeIOViolationError("Market-data path escapes the clean-room root")
    _guard_existing_components(authorization.authorized_root, target)
    return target


def safe_stat(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
    leaf_name: str,
) -> os.stat_result | None:
    _require_operation(authorization, OperationType.STAT)
    path = partition_path(authorization, partition, leaf_name)
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def safe_read_bytes(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
    leaf_name: str,
) -> bytes:
    _require_operation(authorization, OperationType.READ)
    path = partition_path(authorization, partition, leaf_name)
    return path.read_bytes()


def safe_atomic_write(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
    leaf_name: str,
    payload: bytes,
) -> str:
    _require_operation(authorization, OperationType.WRITE)
    path = partition_path(authorization, partition, leaf_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _guard_existing_components(authorization.authorized_root, path)
    temporary = path.with_name(f"{path.name}.q0r-tmp")
    temporary.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
        temporary.unlink(missing_ok=True)
        raise SafeIOViolationError("Atomic-write hash verification failed")
    os.replace(temporary, path)
    return digest


def safe_prepare_partition_directory(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
) -> Path:
    _require_operation(authorization, OperationType.WRITE)
    probe = partition_path(authorization, partition, "directory-guard")
    probe.parent.mkdir(parents=True, exist_ok=True)
    _guard_existing_components(authorization.authorized_root, probe)
    return probe.parent


def safe_unlink(
    authorization: MarketIOAuthorization,
    partition: MarketPartition,
    leaf_name: str,
) -> None:
    _require_operation(authorization, OperationType.DELETE)
    path = partition_path(authorization, partition, leaf_name)
    path.unlink(missing_ok=True)
