"""Hash files according to an explicitly declared reproducibility mode."""

from __future__ import annotations

import hashlib
from pathlib import Path

SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS = (
    "SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS"
)
SHA256_OF_RAW_BYTES = "SHA256_OF_RAW_BYTES"


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
