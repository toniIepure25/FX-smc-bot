"""Testable core for bounded-parallel native-M1 acquisition.

Operations-only helpers for the durable runner's HTTP/2 parallel path: adaptive concurrency
control, per-unit transport classification (BID+ASK atomicity), source-cache reuse, target
planning with firewall-before-scheduling, and retry-amplification accounting. No scientific
semantics, no freeze component, no market data touched here (transport is injected).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from fx_smc_bot.research.v3.provider_scheduler import Outcome

# result of a day-unit's native BID+ASK transport
NATIVE = "native"       # both sides 200 -> canonicalize + certify native
FALLBACK = "fallback"   # a side genuinely 404 -> deterministic tick fallback
RETRY = "retry"         # a side throttled/timed-out -> RETRYABLE (keep succeeded side cached)

CACHE_MIN_BYTES = 200   # a valid .bi5 candle is >~10 KB; 404/503 bodies are tiny/HTML


def cache_valid(path: Path) -> bool:
    """A cached source payload is reusable iff it is a non-trivial, non-HTML file."""

    if not path.exists() or path.stat().st_size < CACHE_MIN_BYTES:
        return False
    return path.read_bytes()[:6] != b"<html>"


def classify_unit_transport(bid: Outcome, ask: Outcome) -> str:
    """Decide a day-unit's native transport result from both sides (frozen fallback policy).

    A genuine 404 on EITHER side means native is unavailable for the day -> tick fallback.
    Both 200 -> native. Anything else (throttle/timeout on a side) -> retry, never closure.
    """

    if bid is Outcome.MISSING or ask is Outcome.MISSING:
        return FALLBACK
    if bid is Outcome.OK and ask is Outcome.OK:
        return NATIVE
    return RETRY


@dataclass(slots=True)
class RetryAccounting:
    """Honest effective-throughput bookkeeping: HTTP attempts vs certified source files."""

    total_http_attempts: int = 0
    certified_source_files: int = 0

    def record_attempts(self, n: int) -> None:
        self.total_http_attempts += n

    def record_certified_files(self, n: int) -> None:
        self.certified_source_files += n

    def amplification(self) -> float:
        if self.certified_source_files == 0:
            return 0.0
        return round(self.total_http_attempts / self.certified_source_files, 3)


@dataclass(slots=True)
class ConcurrencyController:
    """Adaptive HTTP/2 concurrency over a rolling health window (mandate policy).

    UPGRADE one level only when the recent 429/503/timeout rate is <= up_thresh over a full
    window, the breaker is closed, and we are past the post-downgrade cooldown. DOWNGRADE
    immediately when the throttle rate reaches down_thresh or the breaker opens, and start a
    cooldown before probing higher again. Bounded to [1, max_level].
    """

    initial: int = 2
    max_level: int = 4
    window: int = 40
    up_thresh: float = 0.02
    down_thresh: float = 0.10
    cooldown_s: float = 45.0
    clock: Callable[[], float] = field(default=lambda: 0.0)
    _events: deque[int] = field(init=False)
    level: int = field(init=False)
    _cooldown_until: float = field(default=0.0)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=self.window)
        self.level = max(1, min(self.initial, self.max_level))

    def observe(self, is_throttle: bool) -> None:
        self._events.append(1 if is_throttle else 0)

    def throttle_rate(self) -> float:
        return sum(self._events) / len(self._events) if self._events else 0.0

    def update(self, *, breaker_open: bool) -> int:
        now = self.clock()
        tr = self.throttle_rate()
        if breaker_open or tr >= self.down_thresh:
            if self.level > 1:
                self.level -= 1
            self._cooldown_until = now + self.cooldown_s
            self._events.clear()          # fresh window after a change
        elif (len(self._events) >= self.window and tr <= self.up_thresh
              and now >= self._cooldown_until and self.level < self.max_level):
            self.level += 1
            self._events.clear()
        return self.level


@dataclass(frozen=True, slots=True)
class FetchTarget:
    url: str
    dest: Path
    key: str      # unit key "INSTR:ISODATE"
    side: str     # "bid" | "ask"


def plan_targets(
    units: list[tuple[str, date]],
    scratch: Path,
    url_fn: Callable[[str, date, str], str],
    guard: Callable[[str, date], None],
) -> list[FetchTarget]:
    """Build the fetch targets for a batch, skipping valid cached sides (reuse) and firewalling
    every URL BEFORE it is scheduled for transport. ``guard`` must raise on a 2018+ URL/date.
    """

    targets: list[FetchTarget] = []
    for inst, d in units:
        key = f"{inst}:{d.isoformat()}"
        for side in ("bid", "ask"):
            dest = scratch / f"{inst}_{d.isoformat()}_{side}.bi5"
            if cache_valid(dest):
                continue  # reuse the already-succeeded side; do not redownload
            url = url_fn(inst, d, side.upper())
            guard(url, d)  # firewall-before-scheduling; raises on 2018+
            targets.append(FetchTarget(url=url, dest=dest, key=key, side=side))
    return targets
