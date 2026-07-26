"""Gate C6-R-CI-PDA content-role prohibited-data classifier."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SAFE_CLASSIFICATIONS = {
    "POLICY_DOCUMENTATION",
    "DECISION_DOCUMENTATION",
    "INTEGRITY_METADATA",
    "FREEZE_OR_PROVENANCE_METADATA",
    "DATA_QUALITY_SUMMARY",
    "ACCESS_CONTROL_CODE",
    "ACCESS_CONTROL_TEST",
    "RESEARCH_RESULT_SUMMARY",
}

PROHIBITED_CLASSIFICATIONS = {
    "RAW_MARKET_DATA",
    "CANONICAL_MARKET_DATA",
    "ROW_LEVEL_EVENT_DATA",
    "ROW_LEVEL_CONTROL_DATA",
    "HOLDOUT_PAYLOAD",
    "CREDENTIAL_OR_SECRET",
    "GENERATED_CACHE",
    "UNEXPLAINED_BINARY",
}

MARKET_ROW_KEYS = {
    "timestamp",
    "time",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "bid",
    "ask",
    "event_id",
    "control_id",
    "outcome",
    "markout",
}

CREDENTIAL_KEYS = {"password", "secret", "token", "api_key", "private_key"}
RAW_EXTENSIONS = {".bi5"}
CANONICAL_EXTENSIONS = {".parquet", ".feather", ".arrow", ".h5", ".hdf5"}
ROW_TABLE_EXTENSIONS = {".csv", ".tsv", ".jsonl", ".json.gz", ".csv.gz"}
GENERATED_CACHE_TOKENS = {"node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True, slots=True)
class JsonShape:
    """Aggregate JSON schema signals without exposing row values."""

    row_array_presence: bool = False
    row_array_count_sampled: int = 0
    maximum_nested_list_length: int = 0
    numeric_or_time_series_array_signal: bool = False
    market_key_dict_count_sampled: int = 0
    credential_key_signal: bool = False


@dataclass(frozen=True, slots=True)
class PathClassification:
    """Content-role classification for a committed or candidate path."""

    path: str
    classification: str
    evidence: str
    extension: str
    size_bytes: int
    raw_sha256: str
    json_shape: JsonShape | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_prohibited(self) -> bool:
        return self.classification in PROHIBITED_CLASSIFICATIONS

    @property
    def is_ambiguous(self) -> bool:
        return self.classification == "AMBIGUOUS"

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["is_prohibited"] = self.is_prohibited
        record["is_ambiguous"] = self.is_ambiguous
        return record


def raw_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _path_text(path: Path) -> str:
    return path.as_posix().lower()


def _is_generated_cache(path: Path) -> bool:
    parts = {_path_text(Path(part)) for part in path.parts}
    return bool(parts & GENERATED_CACHE_TOKENS)


def _looks_like_credential(path: Path, data: bytes) -> bool:
    lower_path = _path_text(path)
    if path.name.lower().startswith(".env") or "credential" in lower_path:
        return True
    text = data[:4096].decode("utf-8", errors="ignore").lower()
    return any(f"{key}=" in text or f"{key}:" in text for key in CREDENTIAL_KEYS)


def json_shape(payload: Any) -> JsonShape:
    max_list = 0
    row_arrays = 0
    vector_signal = False
    market_dicts = 0
    credential_signal = False

    def walk(value: Any) -> None:
        nonlocal max_list, row_arrays, vector_signal, market_dicts, credential_signal
        if isinstance(value, dict):
            keys = {str(key).lower() for key in value}
            if keys & CREDENTIAL_KEYS:
                credential_signal = True
            if len(keys & MARKET_ROW_KEYS) >= 3:
                market_dicts += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            max_list = max(max_list, len(value))
            sample = value[:10]
            if sample and all(isinstance(item, dict) for item in sample):
                if any(
                    len({str(k).lower() for k in item} & MARKET_ROW_KEYS) >= 3
                    for item in sample
                ):
                    row_arrays += 1
            if (
                len(value) > 20
                and sample
                and all(isinstance(item, int | float | str) for item in sample)
            ):
                vector_signal = True
            if len(value) > 20 and sample and all(isinstance(item, list) for item in sample):
                nested_sample = [child for item in sample for child in item[:5]]
                if nested_sample and all(
                    isinstance(item, int | float | str) for item in nested_sample
                ):
                    vector_signal = True
            for child in value[:50]:
                walk(child)

    walk(payload)
    return JsonShape(
        row_array_presence=row_arrays > 0,
        row_array_count_sampled=row_arrays,
        maximum_nested_list_length=max_list,
        numeric_or_time_series_array_signal=vector_signal,
        market_key_dict_count_sampled=market_dicts,
        credential_key_signal=credential_signal,
    )


def _classify_markdown(path: Path, data: bytes) -> PathClassification:
    text = data.decode("utf-8", errors="replace")
    lower = _path_text(path)
    has_payload_signal = "base64," in text.lower() or len(data) > 250_000
    classification = "POLICY_DOCUMENTATION" if "policy" in lower else "DECISION_DOCUMENTATION"
    if has_payload_signal:
        classification = "AMBIGUOUS"
    return PathClassification(
        path=path.as_posix(),
        classification=classification,
        evidence="Markdown reviewed as documentation; no encoded payload signal."
        if not has_payload_signal
        else "Markdown contains a large table or encoded payload signal.",
        extension=path.suffix.lower(),
        size_bytes=len(data),
        raw_sha256=raw_sha256_bytes(data),
        details={"embedded_large_table_or_payload": has_payload_signal},
    )


def _classify_python(path: Path, data: bytes) -> PathClassification:
    lower = _path_text(path)
    classification = (
        "ACCESS_CONTROL_TEST"
        if "/test" in lower or lower.startswith("tests/")
        else "ACCESS_CONTROL_CODE"
    )
    try:
        tree = ast.parse(data.decode("utf-8"))
        large_literal = any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) > 1000
            for node in ast.walk(tree)
        )
    except SyntaxError:
        large_literal = True
    if large_literal:
        classification = "AMBIGUOUS"
    return PathClassification(
        path=path.as_posix(),
        classification=classification,
        evidence="Python source reviewed as access-control code/test; no embedded data.",
        extension=path.suffix.lower(),
        size_bytes=len(data),
        raw_sha256=raw_sha256_bytes(data),
        details={"large_string_literal_signal": large_literal},
    )


def _classify_json(path: Path, data: bytes) -> PathClassification:
    lower = _path_text(path)
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return PathClassification(
            path=path.as_posix(),
            classification="AMBIGUOUS",
            evidence="JSON extension but parsing failed.",
            extension=path.suffix.lower(),
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    shape = json_shape(payload)
    if shape.credential_key_signal:
        classification = "CREDENTIAL_OR_SECRET"
    elif "holdout" in lower and shape.row_array_presence:
        classification = "HOLDOUT_PAYLOAD"
    elif shape.row_array_presence:
        classification = "ROW_LEVEL_EVENT_DATA"
    elif shape.numeric_or_time_series_array_signal and "manifest" not in lower:
        classification = "AMBIGUOUS"
    elif lower.endswith("/holdout_integrity.json"):
        classification = "INTEGRITY_METADATA"
    elif "data_quality" in lower:
        classification = "DATA_QUALITY_SUMMARY"
    elif "freeze" in lower or "manifest" in lower or "provenance" in lower:
        classification = "FREEZE_OR_PROVENANCE_METADATA"
    else:
        classification = "RESEARCH_RESULT_SUMMARY"
    return PathClassification(
        path=path.as_posix(),
        classification=classification,
        evidence="JSON inspected by schema signals without printing values.",
        extension=path.suffix.lower(),
        size_bytes=len(data),
        raw_sha256=raw_sha256_bytes(data),
        json_shape=shape,
    )


def _classify_row_table(path: Path, data: bytes) -> PathClassification:
    lower = _path_text(path)
    header = data[:512].decode("utf-8", errors="ignore").lower()
    if "control" in lower or "control_id" in header:
        classification = "ROW_LEVEL_CONTROL_DATA"
    elif any(key in header for key in ["event_id", "timestamp", "markout", "open,high,low,close"]):
        classification = "ROW_LEVEL_EVENT_DATA"
    else:
        classification = "AMBIGUOUS"
    return PathClassification(
        path=path.as_posix(),
        classification=classification,
        evidence="Row-table extension reviewed by header tokens.",
        extension=path.suffix.lower(),
        size_bytes=len(data),
        raw_sha256=raw_sha256_bytes(data),
    )


def classify_content(path: Path, data: bytes) -> PathClassification:
    lower = _path_text(path)
    extension = path.suffix.lower()
    if _is_generated_cache(path):
        return PathClassification(
            path=path.as_posix(),
            classification="GENERATED_CACHE",
            evidence="Path is inside a generated cache directory.",
            extension=extension,
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    if _looks_like_credential(path, data):
        return PathClassification(
            path=path.as_posix(),
            classification="CREDENTIAL_OR_SECRET",
            evidence="Credential filename or secret-like key detected.",
            extension=extension,
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    if extension in RAW_EXTENSIONS or "data/raw/" in lower:
        return PathClassification(
            path=path.as_posix(),
            classification="RAW_MARKET_DATA",
            evidence="Raw market-data extension or raw-data path.",
            extension=extension,
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    if extension in CANONICAL_EXTENSIONS or "data/canonical/" in lower:
        return PathClassification(
            path=path.as_posix(),
            classification="CANONICAL_MARKET_DATA",
            evidence="Canonical market-data extension or canonical-data path.",
            extension=extension,
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    if len(data) > 2_000_000 and extension not in {".json", ".md", ".py", ".yaml", ".yml"}:
        return PathClassification(
            path=path.as_posix(),
            classification="UNEXPLAINED_BINARY",
            evidence="Large non-text payload without approved metadata extension.",
            extension=extension,
            size_bytes=len(data),
            raw_sha256=raw_sha256_bytes(data),
        )
    if extension == ".md":
        return _classify_markdown(path, data)
    if extension == ".py":
        return _classify_python(path, data)
    if extension == ".json":
        return _classify_json(path, data)
    if extension in ROW_TABLE_EXTENSIONS:
        return _classify_row_table(path, data)
    return PathClassification(
        path=path.as_posix(),
        classification="RESEARCH_RESULT_SUMMARY",
        evidence="Non-payload text/config/source artifact.",
        extension=extension,
        size_bytes=len(data),
        raw_sha256=raw_sha256_bytes(data),
    )


def classify_committed_path(path: Path) -> PathClassification:
    return classify_content(Path(path.as_posix()), path.read_bytes())


def corrected_prohibited_data_audit(repo: Path, paths: list[str]) -> dict[str, Any]:
    records = [classify_committed_path(repo / path).to_record() for path in paths]
    prohibited = [record for record in records if record["is_prohibited"]]
    ambiguous = [record for record in records if record["is_ambiguous"]]
    safe = [
        record
        for record in records
        if not record["is_prohibited"] and not record["is_ambiguous"]
    ]
    return {
        "changed_paths": paths,
        "reviewed_safe_control_paths": safe,
        "prohibited_payload_paths": prohibited,
        "ambiguous_paths": ambiguous,
        "status": "PASS" if not prohibited and not ambiguous else "FAIL",
    }
