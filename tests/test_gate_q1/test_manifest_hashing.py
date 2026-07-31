from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fx_smc_bot.research.manifest_hashing import (
    SHA256_OF_RAW_BYTES,
    SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS,
    manifest_file_sha256,
)

TEXT_MODE = SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS


@pytest.mark.parametrize(
    ("contents", "canonical"),
    [
        (b"alpha\nbeta\n", b"alpha\nbeta\n"),
        (b"alpha\r\nbeta\r\n", b"alpha\nbeta\n"),
        (b"alpha\r\nbeta\ngamma\rdelta\n", b"alpha\nbeta\ngamma\ndelta\n"),
        (b"terminal-newline\n", b"terminal-newline\n"),
        (b"no-terminal-newline", b"no-terminal-newline"),
    ],
    ids=("lf", "crlf", "mixed", "terminal-newline", "no-terminal-newline"),
)
def test_text_mode_hashes_canonical_utf8_text(
    tmp_path: Path, contents: bytes, canonical: bytes
) -> None:
    path = tmp_path / "artifact.txt"
    path.write_bytes(contents)

    assert manifest_file_sha256(path, TEXT_MODE) == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize("contents", [b"text\x00payload", b"text\xffpayload"])
def test_text_mode_rejects_binary_files(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(contents)

    with pytest.raises(ValueError, match="text hash mode"):
        manifest_file_sha256(path, TEXT_MODE)


def test_raw_byte_mode_remains_line_ending_sensitive(tmp_path: Path) -> None:
    lf_path = tmp_path / "lf.txt"
    crlf_path = tmp_path / "crlf.txt"
    lf_path.write_bytes(b"alpha\nbeta\n")
    crlf_path.write_bytes(b"alpha\r\nbeta\r\n")

    assert manifest_file_sha256(lf_path, SHA256_OF_RAW_BYTES) != manifest_file_sha256(
        crlf_path, SHA256_OF_RAW_BYTES
    )


def test_unknown_hash_mode_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "artifact.txt"
    path.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported manifest hash mode"):
        manifest_file_sha256(path, "UNDECLARED_MODE")
