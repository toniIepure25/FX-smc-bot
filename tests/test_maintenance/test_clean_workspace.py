"""Tests for the local workspace cleanup helpers."""

from __future__ import annotations

from pathlib import Path

from scripts.maintenance.clean_workspace import (
    is_protected,
    is_temp_candidate,
    iter_temp_dirs,
    quarantine_bi5,
)


def test_temp_candidate_matches_known_patterns() -> None:
    assert is_temp_candidate(".pytest_tmp_a0r1")
    assert is_temp_candidate(".tmp-gate-f0")
    assert is_temp_candidate("pytest-gate-f0-tmp")
    assert not is_temp_candidate("results")
    assert not is_temp_candidate("src")


def test_project_directories_are_protected(tmp_path: Path) -> None:
    assert is_protected(tmp_path / "results", tmp_path)
    assert is_protected(tmp_path / "src", tmp_path)
    assert is_protected(tmp_path, tmp_path)
    assert not is_protected(tmp_path / ".pytest_tmp_x", tmp_path)


def test_iter_temp_dirs_skips_protected_names(tmp_path: Path) -> None:
    (tmp_path / ".pytest_tmp_a0r1").mkdir()
    (tmp_path / "pytest-gate-f0-tmp").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "src").mkdir()

    found = {path.name for path in iter_temp_dirs(tmp_path)}

    assert found == {".pytest_tmp_a0r1", "pytest-gate-f0-tmp"}


def test_quarantine_bi5_moves_files_and_writes_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.bi5").write_bytes(b"a")
    (tmp_path / "b.bi5").write_bytes(b"bb")

    moved = quarantine_bi5(tmp_path, apply=True)

    assert moved == 2
    assert not list(tmp_path.glob("*.bi5"))
    destination = next((tmp_path / "var" / "quarantine").glob("root-bi5-*"))
    assert (destination / "a.bi5").exists()
    assert (destination / "MANIFEST.txt").exists()
