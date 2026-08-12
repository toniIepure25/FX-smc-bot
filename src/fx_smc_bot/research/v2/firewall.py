"""Holdout firewall for the 2018+ market/outcome region.

The scientific value of an unopened holdout is preserved by making it *structurally*
impossible to read 2018+ market or outcome files during readiness. Any attempt raises
:class:`HoldoutFirewallError` before a byte of content is decoded. File-path metadata may be
inspected (to enforce the firewall) but market content of the holdout is never read.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import read_json, sha256_file

HOLDOUT_YEAR_FLOOR = 2018
_YEAR_RE = re.compile(r"year=(\d{4})")


class HoldoutFirewallError(RuntimeError):
    """Raised when readiness code attempts to open a 2018+ market/outcome file."""


def classify_year(path: str | Path) -> int | None:
    """Extract the market year encoded in a raw-data path, or ``None`` if not applicable."""

    match = _YEAR_RE.search(str(path).replace("\\", "/"))
    return int(match.group(1)) if match else None


def is_forbidden_market_path(path: str | Path) -> bool:
    year = classify_year(path)
    return year is not None and year >= HOLDOUT_YEAR_FLOOR


@dataclass(frozen=True, slots=True)
class MarketRead:
    path: str
    year: int
    bytes: int
    sha256: str


@dataclass(slots=True)
class HoldoutFirewall:
    """Records permitted development-region reads and blocks holdout reads."""

    reads: list[MarketRead] = field(default_factory=list)
    blocked_attempts: list[str] = field(default_factory=list)

    def guard_path(self, path: str | Path) -> None:
        if is_forbidden_market_path(path):
            self.blocked_attempts.append(str(path))
            raise HoldoutFirewallError(
                f"V2_HOLDOUT_FIREWALL: refusing to open 2018+ market/outcome file: {path}"
            )

    def read_market_json(self, path: str | Path) -> Any:
        """Read a permitted (pre-2018) market JSON file, recording provenance."""

        self.guard_path(path)
        p = Path(path)
        payload = read_json(p)
        year = classify_year(p) or 0
        self.reads.append(
            MarketRead(path=str(p), year=year, bytes=p.stat().st_size, sha256=sha256_file(p))
        )
        return payload

    def opened_2018_plus_count(self) -> int:
        return sum(1 for r in self.reads if r.year >= HOLDOUT_YEAR_FLOOR)

    def audit_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": "A0R4_HOLDOUT_FIREWALL_AUDIT_V1",
            "holdout_year_floor": HOLDOUT_YEAR_FLOOR,
            "opened_file_count": len(self.reads),
            "opened_bytes": sum(r.bytes for r in self.reads),
            "opened_files": [asdict(r) for r in self.reads],
            "blocked_attempt_count": len(self.blocked_attempts),
            "blocked_attempts": list(self.blocked_attempts),
            "opened_2018_plus_market_or_outcome_files": [
                r.path for r in self.reads if r.year >= HOLDOUT_YEAR_FLOOR
            ],
            "2018_plus_market_or_outcome_files_opened": self.opened_2018_plus_count(),
        }


def frame_is_pre_holdout(frame: pd.DataFrame) -> bool:
    """Sanity guard: assert a loaded frame contains no 2018+ timestamps."""

    if frame.empty or "timestamp" not in frame:
        return True
    years = pd.to_datetime(frame["timestamp"], utc=True).dt.year
    return bool((years < HOLDOUT_YEAR_FLOOR).all())
