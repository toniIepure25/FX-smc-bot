"""Deterministic canonical hashing shared by every V3 frozen artifact.

Byte-identical scientific identity depends on a single canonicalisation rule: JSON with
sorted keys and no insignificant whitespace, hashed with SHA-256. This is the same rule
used across V1/V2, reproduced here so V3 artifacts hash identically on any machine or CPU
architecture (the hash is a pure function of the logical payload, not of float layout).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    """Return the canonical JSON string used for hashing (stable across machines)."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def canonical_hash(payload: Any) -> str:
    """SHA-256 of the canonical JSON encoding of ``payload``."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
