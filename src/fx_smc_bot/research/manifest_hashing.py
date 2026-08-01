"""Hash files according to an explicitly declared reproducibility mode."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS = (
    "SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS"
)
SHA256_OF_RAW_BYTES = "SHA256_OF_RAW_BYTES"
CURRENT_WORKING_TREE = "CURRENT_WORKING_TREE"


class ManifestVerificationError(ValueError):
    """Raised when a declared manifest hash cannot be reproduced safely."""


def manifest_bytes_sha256(data: bytes, hash_mode: str) -> str:
    """Hash bytes according to an explicit reproducibility mode."""
    if hash_mode == SHA256_OF_RAW_BYTES:
        return hashlib.sha256(data).hexdigest()
    if hash_mode != SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS:
        raise ValueError(f"unsupported manifest hash mode: {hash_mode}")

    if b"\x00" in data:
        raise ValueError("text hash mode does not accept binary input")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text hash mode requires valid UTF-8 input") from exc

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def manifest_file_sha256(path: Path, hash_mode: str) -> str:
    """Hash one manifest artifact according to its explicit mode."""
    return manifest_bytes_sha256(path.read_bytes(), hash_mode)


def verify_manifest_hash(
    *,
    repository_root: Path,
    relative_path: str,
    expected_sha256: str,
    hash_mode: str,
    source_commit: str | None = None,
) -> str:
    """Verify a manifest path against either the working tree or a Git commit."""
    safe_path = _safe_repository_relative_path(relative_path)
    if source_commit is None or source_commit == CURRENT_WORKING_TREE:
        actual = manifest_file_sha256(repository_root / safe_path, hash_mode)
    else:
        actual = manifest_bytes_sha256(
            _git_blob(repository_root, source_commit, safe_path),
            hash_mode,
        )
    if actual != expected_sha256:
        raise ManifestVerificationError(f"manifest hash mismatch for {relative_path}")
    return actual


def verify_manifest_sections(
    manifest: dict[str, Any],
    *,
    repository_root: Path,
    sections: tuple[str, ...],
    source_sections: tuple[str, ...] = ("source_sha256",),
    manifest_relative_path: str | None = None,
) -> dict[str, dict[str, str]]:
    """Verify declared manifest sections using commit-pinned source blobs."""
    hash_mode = str(
        manifest.get("hash_mode", SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS)
    )
    recorded_commit = _recorded_manifest_commit(manifest)
    fallback_commits = (
        (_path_introducing_commit(repository_root, manifest_relative_path),)
        if manifest_relative_path is not None
        else ()
    )
    verified: dict[str, dict[str, str]] = {}
    for section in sections:
        entries = manifest.get(section)
        if not isinstance(entries, dict):
            raise ManifestVerificationError(f"manifest section is missing: {section}")
        section_commit = recorded_commit if section in source_sections else None
        verified[section] = {}
        for relative_path, expected in entries.items():
            if section_commit is not None:
                for candidate_commit in (CURRENT_WORKING_TREE, *fallback_commits):
                    try:
                        verified[section][str(relative_path)] = verify_manifest_hash(
                            repository_root=repository_root,
                            relative_path=str(relative_path),
                            expected_sha256=str(expected),
                            hash_mode=hash_mode,
                            source_commit=candidate_commit,
                        )
                        break
                    except ManifestVerificationError:
                        pass
                else:
                    verified[section][str(relative_path)] = verify_manifest_hash(
                        repository_root=repository_root,
                        relative_path=str(relative_path),
                        expected_sha256=str(expected),
                        hash_mode=hash_mode,
                        source_commit=section_commit,
                    )
                    continue
                continue
            verified[section][str(relative_path)] = verify_manifest_hash(
                repository_root=repository_root,
                relative_path=str(relative_path),
                expected_sha256=str(expected),
                hash_mode=hash_mode,
                source_commit=section_commit,
            )
    return verified


def _recorded_manifest_commit(manifest: dict[str, Any]) -> str | None:
    for field in (
        "source_commit_sha",
        "implementation_sha_before_final_artifacts",
        "certification_sha",
    ):
        value = manifest.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_repository_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        raise ManifestVerificationError("manifest path must be repository-relative")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ManifestVerificationError("manifest path escapes repository")
    return normalized


def _git_blob(repository_root: Path, commit: str, relative_path: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=repository_root,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ManifestVerificationError(
            f"manifest path is not available at recorded commit: {relative_path}"
        ) from exc


def _path_introducing_commit(repository_root: Path, relative_path: str) -> str:
    safe_path = _safe_repository_relative_path(relative_path)
    try:
        commit = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%H", "--", safe_path],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
    except (subprocess.CalledProcessError, IndexError) as exc:
        raise ManifestVerificationError(
            f"manifest path has no recorded introduction commit: {relative_path}"
        ) from exc
    return commit
