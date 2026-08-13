"""V3 holdout firewall: blocks 2018+ file reads *and* 2018+ provider/network requests.

The single most valuable scientific asset of this program is an *unopened* 2018+ holdout
(``2018_plus_market_or_outcome_files_opened == 0``). The V2 firewall
(:mod:`fx_smc_bot.research.v2.firewall`) makes it structurally impossible to *read* a 2018+
market/outcome file. V3 widens the firewall to also cover the acquisition surface: any
provider request (URL, instrument+date-range, or bare date) whose date falls on or after
``2018-01-01`` is rejected *before a single byte of network I/O is issued*.

Both guards raise before content is consumed, so a leak cannot happen and then be detected
after the fact -- it is prevented at the call site. File-path metadata and requested dates
may be inspected (that is how the firewall enforces itself); holdout *content* is never
read or fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fx_smc_bot.research.v2.firewall import (
    HOLDOUT_YEAR_FLOOR,
    HoldoutFirewall,
    HoldoutFirewallError,
    classify_year,
    is_forbidden_market_path,
)

HOLDOUT_DATE_FLOOR = date(HOLDOUT_YEAR_FLOOR, 1, 1)

# ISO date anywhere in a string, e.g. 2017-12-31.
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Dukascopy datafeed path segment: /INSTRUMENT/YYYY/MM/DD/... (MM is 0-indexed at source,
# but only the 4-digit year is needed to gate the holdout).
_DUKAS_PATH_RE = re.compile(r"/[A-Z]{6}/(\d{4})/(\d{2})/(\d{2})/")
# Bare 4-digit year token, used as a last-resort scan.
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


class NetworkHoldoutFirewallError(RuntimeError):
    """Raised when acquisition code attempts a provider request dated 2018+."""


def _year_is_holdout(year: int) -> bool:
    return year >= HOLDOUT_YEAR_FLOOR


def parse_request_years(target: str) -> list[int]:
    """Extract every plausible market year referenced by a request string.

    Recognises ISO dates, Dukascopy ``/PAIR/YYYY/MM/DD/`` paths and, failing those, any
    4-digit year token in a plausible market range. Returns all found years so a request
    that mixes pre- and post-holdout dates is still blocked.
    """

    years: set[int] = set()
    for m in _ISO_DATE_RE.finditer(target):
        years.add(int(m.group(1)))
    for m in _DUKAS_PATH_RE.finditer(target):
        years.add(int(m.group(1)))
    if not years:
        for m in _YEAR_TOKEN_RE.finditer(target):
            y = int(m.group(1))
            if 1990 <= y <= 2100:
                years.add(y)
    return sorted(years)


def _coerce_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = _ISO_DATE_RE.search(value)
    if not m:
        raise ValueError(f"V3_HOLDOUT_FIREWALL: cannot parse a date from {value!r}")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


@dataclass(slots=True)
class NetworkFirewall:
    """Records permitted (pre-2018) provider requests and blocks holdout requests."""

    permitted_requests: list[dict[str, Any]] = field(default_factory=list)
    blocked_requests: list[dict[str, Any]] = field(default_factory=list)

    def guard_date(self, value: str | date | datetime, *, context: str = "") -> date:
        """Reject a single requested date if it is on/after the holdout floor."""

        d = _coerce_date(value)
        if d >= HOLDOUT_DATE_FLOOR:
            entry = {"kind": "date", "date": d.isoformat(), "context": context}
            self.blocked_requests.append(entry)
            raise NetworkHoldoutFirewallError(
                f"V3_HOLDOUT_FIREWALL: refusing provider request dated {d.isoformat()} "
                f">= {HOLDOUT_DATE_FLOOR.isoformat()} (context={context or 'n/a'})"
            )
        return d

    def guard_provider_request(
        self,
        instrument: str,
        start: str | date | datetime,
        end: str | date | datetime,
    ) -> None:
        """Reject an instrument request whose window touches the holdout at any point."""

        s = _coerce_date(start)
        e = _coerce_date(end)
        if e >= HOLDOUT_DATE_FLOOR:
            entry = {
                "kind": "window",
                "instrument": instrument,
                "start": s.isoformat(),
                "end": e.isoformat(),
            }
            self.blocked_requests.append(entry)
            raise NetworkHoldoutFirewallError(
                f"V3_HOLDOUT_FIREWALL: refusing {instrument} window "
                f"{s.isoformat()}..{e.isoformat()} touching holdout "
                f">= {HOLDOUT_DATE_FLOOR.isoformat()}"
            )
        self.permitted_requests.append(
            {"instrument": instrument, "start": s.isoformat(), "end": e.isoformat()}
        )

    def guard_url(self, url: str) -> None:
        """Reject a provider URL that references any 2018+ market year, before fetching."""

        years = parse_request_years(url)
        holdout_years = [y for y in years if _year_is_holdout(y)]
        if holdout_years:
            self.blocked_requests.append({"kind": "url", "url": url, "years": holdout_years})
            raise NetworkHoldoutFirewallError(
                f"V3_HOLDOUT_FIREWALL: refusing provider URL referencing holdout years "
                f"{holdout_years}: {url}"
            )
        self.permitted_requests.append({"kind": "url", "url": url, "years": years})

    def blocked_2018_plus_count(self) -> int:
        return len(self.blocked_requests)

    def audit_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": "V3_NETWORK_FIREWALL_AUDIT_V1",
            "holdout_date_floor": HOLDOUT_DATE_FLOOR.isoformat(),
            "permitted_request_count": len(self.permitted_requests),
            "blocked_request_count": len(self.blocked_requests),
            "blocked_requests": list(self.blocked_requests),
            "2018_plus_provider_requests_issued": 0,
        }


@dataclass(slots=True)
class V3HoldoutFirewall:
    """Unified firewall: file reads (V2 semantics) plus provider/network requests."""

    files: HoldoutFirewall = field(default_factory=HoldoutFirewall)
    network: NetworkFirewall = field(default_factory=NetworkFirewall)

    # --- file surface (delegates to the proven V2 firewall) ---
    def guard_path(self, path: str) -> None:
        self.files.guard_path(path)

    def read_market_json(self, path: str) -> Any:
        return self.files.read_market_json(path)

    def opened_2018_plus_count(self) -> int:
        return self.files.opened_2018_plus_count()

    # --- network surface (V3 extension) ---
    def guard_date(self, value: str | date | datetime, *, context: str = "") -> date:
        return self.network.guard_date(value, context=context)

    def guard_provider_request(
        self, instrument: str, start: str | date | datetime, end: str | date | datetime
    ) -> None:
        self.network.guard_provider_request(instrument, start, end)

    def guard_url(self, url: str) -> None:
        self.network.guard_url(url)

    def audit_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": "V3_HOLDOUT_FIREWALL_AUDIT_V1",
            "holdout_year_floor": HOLDOUT_YEAR_FLOOR,
            "holdout_date_floor": HOLDOUT_DATE_FLOOR.isoformat(),
            "covers": ["file_reads", "provider_network_requests"],
            "2018_plus_market_or_outcome_files_opened": self.opened_2018_plus_count(),
            "2018_plus_provider_requests_issued": 0,
            "file_audit": self.files.audit_payload(),
            "network_audit": self.network.audit_payload(),
        }


__all__ = [
    "HOLDOUT_DATE_FLOOR",
    "HOLDOUT_YEAR_FLOOR",
    "HoldoutFirewall",
    "HoldoutFirewallError",
    "NetworkFirewall",
    "NetworkHoldoutFirewallError",
    "V3HoldoutFirewall",
    "classify_year",
    "is_forbidden_market_path",
    "parse_request_years",
]
