"""Drift detection: compare forward paper performance against historical baseline.

Uses rolling-window statistics and lightweight statistical tests to
flag when live-forward behavior diverges from the validated historical
profile, triggering alerts for human review.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BaselineProfile:
    """Expected performance characteristics from the validated campaign."""
    win_rate: float = 0.57
    avg_rr: float = 1.5
    profit_factor: float = 1.8
    avg_trades_per_month: float = 50.0
    max_loss_streak: int = 8
    max_dd_pct: float = 0.10
    cb_fires_per_year: float = 7.0

    @classmethod
    def from_json(cls, path: Path | str) -> BaselineProfile:
        with open(path) as f:
            data = json.load(f)
        validation = data.get("validation_snapshot", data)
        return cls(
            win_rate=validation.get("win_rate", 0.57),
            avg_rr=validation.get("avg_rr", 1.5),
            profit_factor=validation.get("profit_factor", 1.8),
            avg_trades_per_month=validation.get("avg_trades_per_month", 50.0),
            max_loss_streak=validation.get("max_loss_streak", 8),
            max_dd_pct=validation.get("max_dd_pct", 0.10),
        )


@dataclass(slots=True, frozen=True)
class DriftResult:
    metric: str
    baseline_value: float
    observed_value: float
    z_score: float
    is_significant: bool
    message: str


class DriftDetector:
    """Rolling-window drift detection against a historical baseline."""

    def __init__(
        self,
        baseline: BaselineProfile,
        window_size: int = 20,
        z_threshold: float = 2.0,
    ) -> None:
        self._baseline = baseline
        self._window = window_size
        self._z_thresh = z_threshold

        self._trade_pnls: list[float] = []
        self._trade_rrs: list[float] = []
        self._trade_timestamps: list[datetime] = []

    @property
    def baseline(self) -> BaselineProfile:
        return self._baseline

    @property
    def trade_count(self) -> int:
        return len(self._trade_pnls)

    def record_trade(self, pnl: float, rr: float, timestamp: datetime) -> None:
        self._trade_pnls.append(pnl)
        self._trade_rrs.append(rr)
        self._trade_timestamps.append(timestamp)

    def check_drift(self) -> list[DriftResult]:
        """Run all drift tests on the latest rolling window."""
        results: list[DriftResult] = []
        if len(self._trade_pnls) < self._window:
            return results

        window_pnls = self._trade_pnls[-self._window:]
        window_rrs = self._trade_rrs[-self._window:]

        results.append(self._check_win_rate(window_pnls))
        results.append(self._check_avg_rr(window_rrs))
        results.append(self._check_profit_factor(window_pnls))

        return results

    def _check_win_rate(self, pnls: list[float]) -> DriftResult:
        n = len(pnls)
        wins = sum(1 for p in pnls if p >= 0)
        observed = wins / n
        p0 = self._baseline.win_rate
        # Binomial z-test
        se = math.sqrt(p0 * (1 - p0) / n) if 0 < p0 < 1 else 0.01
        z = (observed - p0) / se if se > 0 else 0.0
        sig = abs(z) > self._z_thresh
        return DriftResult(
            metric="win_rate",
            baseline_value=p0,
            observed_value=round(observed, 3),
            z_score=round(z, 2),
            is_significant=sig,
            message=f"Win rate {'DRIFT' if sig else 'OK'}: {observed:.1%} vs baseline {p0:.1%}",
        )

    def _check_avg_rr(self, rrs: list[float]) -> DriftResult:
        observed = sum(rrs) / len(rrs) if rrs else 0.0
        baseline = self._baseline.avg_rr
        # Simple z-score using estimated std
        std = _std(rrs) if len(rrs) > 1 else 1.0
        se = std / math.sqrt(len(rrs)) if len(rrs) > 0 else 1.0
        z = (observed - baseline) / se if se > 0 else 0.0
        sig = abs(z) > self._z_thresh
        return DriftResult(
            metric="avg_rr",
            baseline_value=baseline,
            observed_value=round(observed, 2),
            z_score=round(z, 2),
            is_significant=sig,
            message=f"Avg RR {'DRIFT' if sig else 'OK'}: {observed:.2f} vs baseline {baseline:.2f}",
        )

    def _check_profit_factor(self, pnls: list[float]) -> DriftResult:
        gross_profit = sum(p for p in pnls if p > 0) or 0.001
        gross_loss = abs(sum(p for p in pnls if p < 0)) or 0.001
        observed = gross_profit / gross_loss
        baseline = self._baseline.profit_factor
        # Log-ratio comparison (PF is ratio, z-score on log scale)
        log_obs = math.log(max(observed, 0.01))
        log_base = math.log(max(baseline, 0.01))
        se = 0.5  # rough standard error for log-PF
        z = (log_obs - log_base) / se
        sig = abs(z) > self._z_thresh
        return DriftResult(
            metric="profit_factor",
            baseline_value=baseline,
            observed_value=round(observed, 2),
            z_score=round(z, 2),
            is_significant=sig,
            message=f"PF {'DRIFT' if sig else 'OK'}: {observed:.2f} vs baseline {baseline:.2f}",
        )

    def summary(self) -> dict[str, Any]:
        results = self.check_drift()
        return {
            "trade_count": self.trade_count,
            "window_size": self._window,
            "tests": [
                {
                    "metric": r.metric,
                    "baseline": r.baseline_value,
                    "observed": r.observed_value,
                    "z_score": r.z_score,
                    "significant": r.is_significant,
                    "message": r.message,
                }
                for r in results
            ],
            "any_drift_detected": any(r.is_significant for r in results),
        }


def _std(values: list[float]) -> float:
    """Sample standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)
