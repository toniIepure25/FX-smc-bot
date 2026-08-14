"""Adaptive provider scheduler for firewalled bulk acquisition.

The measured failure mode is HTTP 503 *rate-limiting* triggered by request bursts (it hits
tick and candle paths alike), on top of a slow intercepted network path (~13-20 s per
successful request). This module replaces the previous fixed rapid-request pattern with an
adaptive, conservative controller:

* token-bucket pacing (bounded average rate) with small randomized jitter;
* bounded concurrency;
* exponential backoff on 429/503/timeout;
* a circuit breaker that opens after clustered failures and requires a recovery probe;
* per-host health metrics that only *increase* concurrency when evidence supports it;
* a durable retry queue with bounded (never unbounded) retries;
* an explicit distinction between provider throttle (retryable) and genuine missing data.

Everything is deterministic given an injected clock and seeded jitter, so it is unit-testable
without any network.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class Outcome(str, Enum):
    OK = "ok"
    THROTTLE = "throttle"          # 429 / 503 -> retryable, back off
    TIMEOUT = "timeout"            # network timeout -> retryable, back off
    MISSING = "missing"           # 404 -> genuine data-absent candidate (NOT throttle)
    ERROR = "error"               # other 4xx/5xx -> retryable up to the cap


def classify(http_status: int, *, timed_out: bool = False) -> Outcome:
    if timed_out:
        return Outcome.TIMEOUT
    if http_status == 200:
        return Outcome.OK
    if http_status in (429, 503):
        return Outcome.THROTTLE
    if http_status == 404:
        return Outcome.MISSING
    return Outcome.ERROR


@dataclass(slots=True)
class TokenBucket:
    rate_per_sec: float
    capacity: float
    _tokens: float = field(default=0.0)
    _last: float = field(default=0.0)

    def __post_init__(self) -> None:
        self._tokens = self.capacity

    def take(self, now: float) -> float:
        """Return seconds to wait before a token is available (0 if immediate)."""

        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_sec)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        deficit = 1.0 - self._tokens
        self._tokens = 0.0
        return deficit / self.rate_per_sec


class BreakerState(str, Enum):
    CLOSED = "closed"        # normal
    OPEN = "open"            # tripped; refuse until cooldown
    HALF_OPEN = "half_open"  # allow a single recovery probe


@dataclass(slots=True)
class CircuitBreaker:
    trip_threshold: int = 5          # consecutive throttle/timeout failures to trip
    cooldown_s: float = 60.0
    _state: BreakerState = BreakerState.CLOSED
    _consecutive_failures: int = 0
    _opened_at: float = 0.0

    @property
    def state(self) -> BreakerState:
        return self._state

    def allow(self, now: float) -> bool:
        if self._state is BreakerState.OPEN:
            if now - self._opened_at >= self.cooldown_s:
                self._state = BreakerState.HALF_OPEN
                return True          # allow one recovery probe
            return False
        return True

    def record(self, outcome: Outcome, now: float) -> None:
        if outcome is Outcome.OK or outcome is Outcome.MISSING:
            self._consecutive_failures = 0
            self._state = BreakerState.CLOSED
            return
        # a failure
        self._consecutive_failures += 1
        if self._state is BreakerState.HALF_OPEN:
            self._state = BreakerState.OPEN     # recovery probe failed; re-open
            self._opened_at = now
            return
        if self._consecutive_failures >= self.trip_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = now


def backoff_delay(attempt: int, *, base_s: float = 4.0, cap_s: float = 120.0,
                  rng: random.Random | None = None) -> float:
    """Exponential backoff with full jitter; deterministic when ``rng`` is seeded."""

    ceiling = min(cap_s, base_s * (2 ** max(0, attempt - 1)))
    r = rng if rng is not None else random
    return round(r.uniform(0.0, ceiling), 3)


@dataclass(slots=True)
class HostHealth:
    window: int = 50
    _events: deque[Outcome] = field(default_factory=lambda: deque(maxlen=50))
    _latencies: deque[float] = field(default_factory=lambda: deque(maxlen=50))

    def observe(self, outcome: Outcome, latency_s: float) -> None:
        self._events.append(outcome)
        if outcome is Outcome.OK:
            self._latencies.append(latency_s)

    def throttle_rate(self) -> float:
        if not self._events:
            return 0.0
        n_throttle = sum(1 for e in self._events if e in (Outcome.THROTTLE, Outcome.TIMEOUT))
        return n_throttle / len(self._events)

    def median_latency(self) -> float:
        if not self._latencies:
            return 0.0
        s = sorted(self._latencies)
        return s[len(s) // 2]

    def recommend_concurrency(self, current: int, *, max_workers: int) -> int:
        """Only raise concurrency when the recent throttle rate is low; drop fast if high."""

        tr = self.throttle_rate()
        if tr >= 0.25:
            return max(1, current - 1)
        if tr == 0.0 and len(self._events) >= self.window and current < max_workers:
            return current + 1
        return current


@dataclass(slots=True)
class AdaptiveScheduler:
    """Combines pacing, breaker, health and a bounded retry queue over one host."""

    rate_per_sec: float = 0.5           # conservative start: 1 request / 2 s
    burst_capacity: float = 2.0
    max_concurrency: int = 4
    start_concurrency: int = 1
    max_attempts: int = 6
    clock: Callable[[], float] = field(default=lambda: 0.0)
    seed: int = 0
    _bucket: TokenBucket = field(init=False)
    _breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    _health: HostHealth = field(default_factory=HostHealth)
    _rng: random.Random = field(init=False)
    concurrency: int = field(init=False)

    def __post_init__(self) -> None:
        self._bucket = TokenBucket(self.rate_per_sec, self.burst_capacity)
        self._rng = random.Random(self.seed)
        self.concurrency = self.start_concurrency

    def next_wait(self) -> float:
        now = self.clock()
        if not self._breaker.allow(now):
            return self._breaker.cooldown_s
        pace = self._bucket.take(now)
        jitter = self._rng.uniform(0.0, 0.5)
        return round(pace + jitter, 3)

    def record(self, outcome: Outcome, latency_s: float, attempt: int) -> tuple[bool, float]:
        """Record an outcome. Returns (should_retry, retry_delay_s)."""

        now = self.clock()
        self._breaker.record(outcome, now)
        self._health.observe(outcome, latency_s)
        self.concurrency = self._health.recommend_concurrency(
            self.concurrency, max_workers=self.max_concurrency
        )
        if outcome in (Outcome.OK, Outcome.MISSING):
            return (False, 0.0)
        if attempt >= self.max_attempts:
            return (False, 0.0)          # bounded: give up -> RETRYABLE persisted for later
        return (True, backoff_delay(attempt, rng=self._rng))

    def health_snapshot(self) -> dict[str, float | str | int]:
        return {
            "breaker_state": self._breaker.state.value,
            "throttle_rate": round(self._health.throttle_rate(), 3),
            "median_ok_latency_s": round(self._health.median_latency(), 3),
            "concurrency": self.concurrency,
        }
