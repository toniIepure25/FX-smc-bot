from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from fx_smc_bot.research.manifest_hashing import (
    CURRENT_WORKING_TREE,
    SHA256_OF_RAW_BYTES,
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    ManifestVerificationError,
    manifest_bytes_sha256,
    verify_manifest_hash,
    verify_manifest_sections,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    return tmp_path


def test_later_source_modification_does_not_invalidate_historical_manifest(
    git_repo: Path,
) -> None:
    source = git_repo / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    _git(git_repo, "add", "src/module.py")
    _git(git_repo, "commit", "-m", "freeze source")
    frozen_sha = _git(git_repo, "rev-parse", "HEAD")
    expected = manifest_bytes_sha256(
        b"value = 1\n",
        SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    )

    source.write_text("value = 2\n", encoding="utf-8")
    verified = verify_manifest_sections(
        {
            "implementation_sha_before_final_artifacts": frozen_sha,
            "hash_mode": SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            "source_sha256": {"src/module.py": expected},
        },
        repository_root=git_repo,
        sections=("source_sha256",),
    )

    assert verified["source_sha256"]["src/module.py"] == expected


def test_actual_mismatch_at_recorded_commit_fails(git_repo: Path) -> None:
    source = git_repo / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    _git(git_repo, "add", "src/module.py")
    _git(git_repo, "commit", "-m", "freeze source")
    frozen_sha = _git(git_repo, "rev-parse", "HEAD")

    with pytest.raises(ManifestVerificationError, match="hash mismatch"):
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="src/module.py",
            expected_sha256="0" * 64,
            hash_mode=SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            source_commit=frozen_sha,
        )


def test_missing_historical_path_fails(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("ready\n", encoding="utf-8")
    _git(git_repo, "add", "README.md")
    _git(git_repo, "commit", "-m", "freeze readme")
    frozen_sha = _git(git_repo, "rev-parse", "HEAD")

    with pytest.raises(ManifestVerificationError, match="not available"):
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="src/missing.py",
            expected_sha256="0" * 64,
            hash_mode=SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            source_commit=frozen_sha,
        )


def test_manifest_introduction_commit_can_verify_final_artifact_source(
    git_repo: Path,
) -> None:
    (git_repo / "README.md").write_text("ready\n", encoding="utf-8")
    _git(git_repo, "add", "README.md")
    _git(git_repo, "commit", "-m", "implementation")
    implementation_sha = _git(git_repo, "rev-parse", "HEAD")
    final_test = git_repo / "tests" / "test_final.py"
    final_test.parent.mkdir()
    final_test.write_text("assert True\n", encoding="utf-8")
    expected = manifest_bytes_sha256(
        b"assert True\n",
        SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    )
    manifest_path = git_repo / "results" / "gate" / "reproducibility_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    _git(git_repo, "add", "tests/test_final.py", "results/gate/reproducibility_manifest.json")
    _git(git_repo, "commit", "-m", "final artifacts")
    final_test.write_text("assert False\n", encoding="utf-8")

    verified = verify_manifest_sections(
        {
            "implementation_sha_before_final_artifacts": implementation_sha,
            "hash_mode": SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            "source_sha256": {"tests/test_final.py": expected},
        },
        repository_root=git_repo,
        sections=("source_sha256",),
        manifest_relative_path="results/gate/reproducibility_manifest.json",
    )

    assert verified["source_sha256"]["tests/test_final.py"] == expected


def test_lf_and_crlf_normalization_for_text_mode(git_repo: Path) -> None:
    text = git_repo / "notes.txt"
    text.write_bytes(b"alpha\r\nbeta\r\n")
    _git(git_repo, "add", "notes.txt")
    _git(git_repo, "commit", "-m", "freeze text")
    frozen_sha = _git(git_repo, "rev-parse", "HEAD")
    expected = hashlib.sha256(b"alpha\nbeta\n").hexdigest()

    assert (
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="notes.txt",
            expected_sha256=expected,
            hash_mode=SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            source_commit=frozen_sha,
        )
        == expected
    )


def test_raw_byte_mode_remains_byte_sensitive(git_repo: Path) -> None:
    text = git_repo / "notes.bin"
    text.write_bytes(b"\x00alpha\r\nbeta\r\n")
    _git(git_repo, "add", "notes.bin")
    _git(git_repo, "commit", "-m", "freeze raw")
    frozen_sha = _git(git_repo, "rev-parse", "HEAD")
    raw_expected = hashlib.sha256(b"\x00alpha\r\nbeta\r\n").hexdigest()
    normalized_expected = hashlib.sha256(b"\x00alpha\nbeta\n").hexdigest()

    assert (
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="notes.bin",
            expected_sha256=raw_expected,
            hash_mode=SHA256_OF_RAW_BYTES,
            source_commit=frozen_sha,
        )
        == raw_expected
    )
    with pytest.raises(ManifestVerificationError, match="hash mismatch"):
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="notes.bin",
            expected_sha256=normalized_expected,
            hash_mode=SHA256_OF_RAW_BYTES,
            source_commit=frozen_sha,
        )


def test_current_working_tree_mode_remains_supported(git_repo: Path) -> None:
    current = git_repo / "current.txt"
    current.write_text("current\n", encoding="utf-8")
    expected = manifest_bytes_sha256(
        b"current\n",
        SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    )

    assert (
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path="current.txt",
            expected_sha256=expected,
            hash_mode=SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            source_commit=CURRENT_WORKING_TREE,
        )
        == expected
    )


@pytest.mark.parametrize("relative_path", ["../outside.txt", "/absolute.txt", "C:/x.txt"])
def test_git_object_lookup_is_repository_relative_and_safe(
    git_repo: Path, relative_path: str
) -> None:
    with pytest.raises(ManifestVerificationError, match="repository"):
        verify_manifest_hash(
            repository_root=git_repo,
            relative_path=relative_path,
            expected_sha256="0" * 64,
            hash_mode=SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
            source_commit=CURRENT_WORKING_TREE,
        )
