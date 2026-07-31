from __future__ import annotations

import ast
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fx_smc_bot.research import classical_factor_safe_io as safe_io
from fx_smc_bot.research.classical_factor_safe_io import (
    FROZEN_CURRENCIES,
    FROZEN_INSTRUMENTS,
    DataProvider,
    IOAuthorization,
    MarketPartition,
    OperationType,
    ProviderRequest,
    RatePartition,
    SafeIOViolationError,
    authorize_date,
    create_authorization,
    partition_path,
    safe_atomic_write,
    safe_provider_request,
    safe_read_bytes,
    safe_stat,
    safe_unlink,
    validate_clean_root,
)


def _roots(tmp_path: Path) -> tuple[Path, Path, tuple[Path, ...]]:
    repository = tmp_path / "repository"
    repository.mkdir()
    root = tmp_path / "clean"
    root.mkdir()
    return repository, root, (tmp_path / "explicit-old-root",)


def _market_authorization(
    tmp_path: Path,
    *,
    operation: OperationType = OperationType.PROVIDER_REQUEST,
) -> tuple[IOAuthorization, MarketPartition]:
    repository, root, forbidden = _roots(tmp_path)
    partition = MarketPartition(
        instrument="EURUSD",
        side="bid",
        start=date(2022, 1, 1),
        end=date(2022, 1, 31),
    )
    authorization = create_authorization(
        root=root,
        repository_root=repository,
        instruments=frozenset({"EURUSD"}),
        currencies=frozenset({"EUR", "USD"}),
        start=partition.start,
        end=partition.end,
        partitions=frozenset({partition}),
        provider=DataProvider.DUKASCOPY_BI5_BID_ASK,
        operation=operation,
        forbidden_roots=forbidden,
    )
    return authorization, partition


def _rate_authorization(
    tmp_path: Path,
    *,
    operation: OperationType = OperationType.PROVIDER_REQUEST,
) -> tuple[IOAuthorization, RatePartition]:
    repository, root, forbidden = _roots(tmp_path)
    partition = RatePartition(
        currency="GBP",
        start=date(2011, 1, 1),
        end=date(2011, 1, 31),
    )
    authorization = create_authorization(
        root=root,
        repository_root=repository,
        instruments=frozenset({"GBPUSD"}),
        currencies=frozenset({"GBP", "USD"}),
        start=partition.start,
        end=partition.end,
        partitions=frozenset({partition}),
        provider=DataProvider.GBP_BOE_SONIA,
        operation=operation,
        forbidden_roots=forbidden,
    )
    return authorization, partition


def _request(
    authorization: IOAuthorization,
    partition: MarketPartition | RatePartition,
) -> ProviderRequest:
    return ProviderRequest(
        provider=authorization.authorized_provider,
        partition=partition,
        start=partition.start,
        end=partition.end,
        resource_name="partition-2022-01.bi5"
        if isinstance(partition, MarketPartition)
        else "sonia-2011-01.csv",
    )


def test_frozen_universe_is_exact() -> None:
    assert FROZEN_INSTRUMENTS == frozenset(
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
    assert FROZEN_CURRENCIES == frozenset({"USD", "EUR", "GBP", "AUD", "NZD", "JPY", "CAD", "CHF"})


def test_authorization_contains_every_required_capability_field(tmp_path: Path) -> None:
    authorization, partition = _market_authorization(tmp_path)
    assert authorization.clean_room_root == tmp_path / "clean"
    assert authorization.authorized_instruments == frozenset({"EURUSD"})
    assert authorization.authorized_currencies == frozenset({"EUR", "USD"})
    assert authorization.authorized_start == partition.start
    assert authorization.authorized_end == partition.end
    assert authorization.authorized_partition_set == frozenset({partition})
    assert authorization.authorized_provider is DataProvider.DUKASCOPY_BI5_BID_ASK
    assert authorization.authorized_operation is OperationType.PROVIDER_REQUEST


@pytest.mark.parametrize("value", [date(2010, 1, 1), date(2022, 12, 31)])
def test_frozen_date_boundaries_are_accepted(value: date) -> None:
    authorize_date(value)


@pytest.mark.parametrize(
    "value",
    [
        date(2009, 12, 31),
        date(2023, 1, 1),
        date(2024, 6, 1),
        date(2025, 12, 31),
        date(2026, 1, 1),
    ],
)
def test_dates_outside_frozen_interval_are_rejected(value: date) -> None:
    with pytest.raises(SafeIOViolationError, match="outside"):
        authorize_date(value)


@pytest.mark.parametrize(
    ("instruments", "currencies", "message"),
    [
        (frozenset({"EURUSD", "EURCHF"}), frozenset({"EUR", "USD"}), "instrument"),
        (frozenset({"EURUSD"}), frozenset({"EUR", "USD", "SEK"}), "currency"),
    ],
)
def test_unknown_universe_member_is_rejected_before_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    instruments: frozenset[str],
    currencies: frozenset[str],
    message: str,
) -> None:
    repository, root, forbidden = _roots(tmp_path)
    partition = MarketPartition("EURUSD", "bid", date(2022, 1, 1), date(2022, 1, 31))
    touched = False

    def fail_lstat(_path: Path) -> os.stat_result:
        nonlocal touched
        touched = True
        raise AssertionError("filesystem must not be touched")

    monkeypatch.setattr(safe_io.os, "lstat", fail_lstat)
    with pytest.raises(SafeIOViolationError, match=message):
        create_authorization(
            root=root,
            repository_root=repository,
            instruments=instruments,
            currencies=currencies,
            start=partition.start,
            end=partition.end,
            partitions=frozenset({partition}),
            provider=DataProvider.DUKASCOPY_BI5_BID_ASK,
            operation=OperationType.READ,
            forbidden_roots=forbidden,
        )
    assert not touched


@pytest.mark.parametrize("side", ["mid", "BID", ""])
def test_non_bid_ask_market_side_is_rejected(tmp_path: Path, side: str) -> None:
    repository, root, forbidden = _roots(tmp_path)
    partition = MarketPartition("EURUSD", side, date(2022, 1, 1), date(2022, 1, 31))
    with pytest.raises(SafeIOViolationError, match="bid/ask"):
        create_authorization(
            root=root,
            repository_root=repository,
            instruments=frozenset({"EURUSD"}),
            currencies=frozenset({"EUR", "USD"}),
            start=partition.start,
            end=partition.end,
            partitions=frozenset({partition}),
            provider=DataProvider.DUKASCOPY_BI5_BID_ASK,
            operation=OperationType.READ,
            forbidden_roots=forbidden,
        )


def test_market_capability_requires_exact_dukascopy_provider(tmp_path: Path) -> None:
    repository, root, forbidden = _roots(tmp_path)
    partition = MarketPartition("EURUSD", "ask", date(2022, 1, 1), date(2022, 1, 31))
    with pytest.raises(SafeIOViolationError, match="Rate authority"):
        create_authorization(
            root=root,
            repository_root=repository,
            instruments=frozenset({"EURUSD"}),
            currencies=frozenset({"EUR", "USD"}),
            start=partition.start,
            end=partition.end,
            partitions=frozenset({partition}),
            provider=DataProvider.GBP_BOE_SONIA,
            operation=OperationType.PROVIDER_REQUEST,
            forbidden_roots=forbidden,
        )


def test_rate_authority_is_explicit_and_currency_scoped(tmp_path: Path) -> None:
    authorization, partition = _rate_authorization(tmp_path)
    assert authorization.authorized_provider is DataProvider.GBP_BOE_SONIA
    assert partition.currency == "GBP"

    wrong_partition = RatePartition("CHF", partition.start, partition.end)
    repository = authorization.repository_root
    with pytest.raises(SafeIOViolationError, match="does not match"):
        create_authorization(
            root=authorization.clean_room_root,
            repository_root=repository,
            instruments=frozenset({"GBPUSD", "USDCHF"}),
            currencies=frozenset({"GBP", "USD", "CHF"}),
            start=partition.start,
            end=partition.end,
            partitions=frozenset({wrong_partition}),
            provider=DataProvider.GBP_BOE_SONIA,
            operation=OperationType.PROVIDER_REQUEST,
            forbidden_roots=authorization.forbidden_roots,
        )


def test_cad_rate_authority_uses_frozen_v39079_target_series() -> None:
    provider = DataProvider.CAD_BANK_OF_CANADA_TARGET_OVERNIGHT
    assert provider.value == "Bank of Canada target for the overnight rate V39079"
    assert safe_io.RATE_PROVIDER_CURRENCY[provider] == "CAD"


@pytest.mark.parametrize("root_kind", ["repository", "parent", "inside"])
def test_repository_and_parent_roots_are_rejected_before_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_kind: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    candidate = {
        "repository": repository,
        "parent": repository.parent,
        "inside": repository / "data",
    }[root_kind]
    touched = False

    def fail_lstat(_path: Path) -> os.stat_result:
        nonlocal touched
        touched = True
        raise AssertionError("filesystem must not be touched")

    monkeypatch.setattr(safe_io.os, "lstat", fail_lstat)
    with pytest.raises(SafeIOViolationError, match="repository"):
        validate_clean_root(candidate, repository, forbidden_roots=())
    assert not touched


@pytest.mark.parametrize("relationship", ["same", "child", "parent"])
def test_explicit_old_root_overlap_is_rejected_without_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relationship: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    old_root = tmp_path / "storage" / "old"
    candidate = {
        "same": old_root,
        "child": old_root / "new",
        "parent": old_root.parent,
    }[relationship]
    touched = False

    def fail_lstat(_path: Path) -> os.stat_result:
        nonlocal touched
        touched = True
        raise AssertionError("old roots must not be inspected")

    monkeypatch.setattr(safe_io.os, "lstat", fail_lstat)
    with pytest.raises(SafeIOViolationError, match="old root"):
        validate_clean_root(candidate, repository, forbidden_roots=(old_root,))
    assert not touched


@pytest.mark.parametrize(
    "resource_name",
    [
        "*",
        "**",
        "*.bi5",
        "pair?.bi5",
        "[ab].bi5",
        "../escape.bi5",
        "nested/data.bi5",
        r"nested\data.bi5",
        "/absolute.bi5",
        "quotes-2023-01.bi5",
        "quotes_20240101.bi5",
        "2025.csv",
    ],
)
def test_wildcard_exterior_and_quarantined_resource_names_are_rejected_before_path_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource_name: str,
) -> None:
    authorization, partition = _market_authorization(tmp_path)
    touched = False

    def fail_guard(_root: Path, _target: Path) -> None:
        nonlocal touched
        touched = True
        raise AssertionError("path guard must not run")

    monkeypatch.setattr(safe_io, "_guard_existing_components", fail_guard)
    with pytest.raises(SafeIOViolationError):
        partition_path(authorization, partition, resource_name)
    assert not touched


def test_unplanned_partition_is_rejected_before_path_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, partition = _market_authorization(tmp_path)
    unplanned = replace(partition, side="ask")
    touched = False

    def fail_guard(_root: Path, _target: Path) -> None:
        nonlocal touched
        touched = True
        raise AssertionError("path guard must not run")

    monkeypatch.setattr(safe_io, "_guard_existing_components", fail_guard)
    with pytest.raises(SafeIOViolationError, match="immutable"):
        partition_path(authorization, unplanned, "partition-2022-01.bi5")
    assert not touched


def test_symlink_or_junction_component_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, partition = _market_authorization(tmp_path)
    monkeypatch.setattr(
        safe_io,
        "_is_reparse_point",
        lambda path, _result=None: path.name == "market",
    )
    (authorization.clean_room_root / "market").mkdir()
    with pytest.raises(SafeIOViolationError, match="symlink or junction"):
        partition_path(authorization, partition, "partition-2022-01.bi5")


def test_valid_market_provider_callback_runs_once(tmp_path: Path) -> None:
    authorization, partition = _market_authorization(tmp_path)
    request = _request(authorization, partition)
    calls: list[ProviderRequest] = []

    def callback(validated: ProviderRequest) -> str:
        calls.append(validated)
        return "market-ok"

    assert safe_provider_request(authorization, request, callback) == "market-ok"
    assert calls == [request]


def test_valid_rate_authority_callback_runs_once(tmp_path: Path) -> None:
    authorization, partition = _rate_authorization(tmp_path)
    request = _request(authorization, partition)
    calls: list[ProviderRequest] = []

    def callback(validated: ProviderRequest) -> str:
        calls.append(validated)
        return "rate-ok"

    assert safe_provider_request(authorization, request, callback) == "rate-ok"
    assert calls == [request]


def test_rate_callback_is_not_called_for_wrong_currency(tmp_path: Path) -> None:
    authorization, partition = _rate_authorization(tmp_path)
    request = replace(
        _request(authorization, partition),
        partition=replace(partition, currency="CHF"),
    )
    called = False

    def callback(_validated: ProviderRequest) -> None:
        nonlocal called
        called = True

    with pytest.raises(SafeIOViolationError, match="does not match"):
        safe_provider_request(authorization, request, callback)
    assert not called


def _invalid_request_cases(
    authorization: IOAuthorization,
    partition: MarketPartition,
) -> tuple[ProviderRequest, ...]:
    valid = _request(authorization, partition)
    return (
        replace(valid, start=date(2009, 12, 31)),
        replace(valid, end=date(2023, 1, 1)),
        replace(valid, provider=DataProvider.GBP_BOE_SONIA),
        replace(valid, partition=replace(partition, instrument="EURCHF")),
        replace(valid, partition=replace(partition, side="ask")),
        replace(valid, resource_name="*.bi5"),
        replace(valid, resource_name="quotes-2024-01.bi5"),
    )


@pytest.mark.parametrize("case_index", range(7))
def test_provider_callback_is_never_called_when_guard_rejects(
    tmp_path: Path,
    case_index: int,
) -> None:
    authorization, partition = _market_authorization(tmp_path)
    request = _invalid_request_cases(authorization, partition)[case_index]
    called = False

    def callback(_validated: ProviderRequest) -> None:
        nonlocal called
        called = True

    with pytest.raises(SafeIOViolationError):
        safe_provider_request(authorization, request, callback)
    assert not called


def test_wrong_operation_rejects_before_provider_callback(tmp_path: Path) -> None:
    authorization, partition = _market_authorization(tmp_path, operation=OperationType.READ)
    called = False

    def callback(_validated: ProviderRequest) -> None:
        nonlocal called
        called = True

    with pytest.raises(SafeIOViolationError, match="PROVIDER_REQUEST"):
        safe_provider_request(authorization, _request(authorization, partition), callback)
    assert not called


def test_file_operations_require_separate_capabilities_and_preserve_payload(
    tmp_path: Path,
) -> None:
    write_authorization, partition = _market_authorization(
        tmp_path,
        operation=OperationType.WRITE,
    )
    payload = b"synthetic-test-payload"
    digest = safe_atomic_write(
        write_authorization,
        partition,
        "partition-2022-01.bi5",
        payload,
    )
    assert digest == "ff4dd832d6618eb36248875eb831f816b49a27107c9305d3cc53a847d39f681e"

    def capability(operation: OperationType) -> IOAuthorization:
        return create_authorization(
            root=write_authorization.clean_room_root,
            repository_root=write_authorization.repository_root,
            instruments=write_authorization.authorized_instruments,
            currencies=write_authorization.authorized_currencies,
            start=write_authorization.authorized_start,
            end=write_authorization.authorized_end,
            partitions=write_authorization.authorized_partition_set,
            provider=write_authorization.authorized_provider,
            operation=operation,
            forbidden_roots=write_authorization.forbidden_roots,
        )

    read_authorization = capability(OperationType.READ)
    stat_authorization = capability(OperationType.STAT)
    delete_authorization = capability(OperationType.DELETE)

    assert safe_read_bytes(read_authorization, partition, "partition-2022-01.bi5") == payload
    assert safe_stat(stat_authorization, partition, "partition-2022-01.bi5") is not None
    with pytest.raises(SafeIOViolationError, match="WRITE"):
        safe_atomic_write(
            read_authorization,
            partition,
            "forbidden-write.bi5",
            b"must-not-write",
        )
    safe_unlink(delete_authorization, partition, "partition-2022-01.bi5")
    assert safe_stat(stat_authorization, partition, "partition-2022-01.bi5") is None


def test_module_uses_no_recursive_or_broad_discovery_api() -> None:
    tree = ast.parse(Path(safe_io.__file__).read_text(encoding="utf-8"))
    forbidden_attributes = {"walk", "rglob", "glob"}
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    assert used == set()


def test_callback_type_accepts_non_none_results(tmp_path: Path) -> None:
    authorization, partition = _market_authorization(tmp_path)

    def callback(request: ProviderRequest) -> dict[str, Any]:
        return {"resource": request.resource_name}

    typed_callback: Callable[[ProviderRequest], dict[str, Any]] = callback
    assert safe_provider_request(authorization, _request(authorization, partition), callback) == {
        "resource": "partition-2022-01.bi5"
    }
    assert typed_callback is callback
