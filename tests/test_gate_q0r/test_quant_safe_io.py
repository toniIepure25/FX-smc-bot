from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from fx_smc_bot.research import quant_safe_io
from fx_smc_bot.research.quant_safe_io import (
    MarketPartition,
    OperationType,
    SafeIOViolationError,
    authorize_date,
    create_authorization,
    partition_path,
    validate_clean_root,
)


def _authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    root = tmp_path / "clean"
    root.mkdir()
    partition = MarketPartition("AUDUSD", "bid", 2022, 12)
    authorization = create_authorization(
        root=root,
        repository_root=repository,
        instruments=frozenset({"AUDUSD"}),
        start=date(2022, 12, 1),
        end=date(2022, 12, 31),
        partitions=frozenset({partition}),
        operation=OperationType.READ,
    )
    monkeypatch.setattr(quant_safe_io, "_is_reparse_point", lambda _path: False)
    return authorization, partition


def test_latest_permitted_day_is_accepted() -> None:
    authorize_date(date(2022, 12, 31))


@pytest.mark.parametrize("value", [date(2023, 1, 1), date(2024, 6, 1), date(2025, 12, 31)])
def test_quarantined_dates_are_rejected(value: date) -> None:
    with pytest.raises(SafeIOViolationError, match="outside"):
        authorize_date(value)


def test_pre_window_date_is_rejected() -> None:
    with pytest.raises(SafeIOViolationError, match="outside"):
        authorize_date(date(2014, 12, 31))


def test_unknown_instrument_is_rejected_before_path_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization, _partition = _authorization(tmp_path, monkeypatch)
    touched = False

    def path_guard(_root: Path, _target: Path) -> None:
        nonlocal touched
        touched = True

    monkeypatch.setattr(quant_safe_io, "_guard_existing_components", path_guard)
    unknown = MarketPartition("EURUSD", "bid", 2022, 12)
    with pytest.raises(SafeIOViolationError, match="Instrument"):
        partition_path(authorization, unknown, "data.bin")
    assert not touched


def test_repository_and_ancestor_roots_are_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    with pytest.raises(SafeIOViolationError, match="inside"):
        validate_clean_root(repository, repository)
    with pytest.raises(SafeIOViolationError, match="ancestor"):
        validate_clean_root(tmp_path, repository)


def test_old_q0_root_is_rejected_without_inspection(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    old_root = tmp_path / "old-q0"
    old_root.mkdir()
    with pytest.raises(SafeIOViolationError, match="predecessor"):
        validate_clean_root(old_root, repository, forbidden_roots=(old_root,))


def test_nonempty_configured_root_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "unrelated.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SafeIOViolationError, match="must initially be empty"):
        validate_clean_root(root, repository)


@pytest.mark.parametrize("leaf", ["**", "*.bin", "../data.bin", "nested/data.bin"])
def test_recursive_wildcard_and_multicomponent_paths_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leaf: str
) -> None:
    authorization, partition = _authorization(tmp_path, monkeypatch)
    with pytest.raises(SafeIOViolationError):
        partition_path(authorization, partition, leaf)


def test_symlink_or_junction_escape_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization, partition = _authorization(tmp_path, monkeypatch)
    monkeypatch.setattr(
        quant_safe_io,
        "_is_reparse_point",
        lambda path: path.name == "AUDUSD",
    )
    (authorization.authorized_root / "AUDUSD").mkdir()
    with pytest.raises(SafeIOViolationError, match="symlink or junction"):
        partition_path(authorization, partition, "data.bin")


def test_market_io_module_contains_no_recursive_discovery_api() -> None:
    tree = ast.parse(Path(quant_safe_io.__file__).read_text(encoding="utf-8"))
    forbidden_attributes = {"walk", "rglob"}
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    assert used == set()
