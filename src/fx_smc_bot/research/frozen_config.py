"""Parameter freezing and holdout discipline for candidate configs.

Enforces a clear separation between exploratory research and locked
candidate evaluation. Frozen configs get a deterministic hash that
must not change -- any mutation is detected by validate_frozen().
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries

logger = logging.getLogger(__name__)


class ConfigStatus(str, Enum):
    EXPLORATORY = "exploratory"
    LOCKED = "locked"
    BASELINE = "baseline"


@dataclass(frozen=True, slots=True)
class DataSplitPolicy:
    """Defines train/validation/holdout percentages and embargo."""
    train_end_pct: float = 0.60
    validation_end_pct: float = 0.80
    embargo_bars: int = 10

    def __post_init__(self) -> None:
        if not (0.0 < self.train_end_pct < self.validation_end_pct <= 1.0):
            raise ValueError(
                f"Invalid split: train_end={self.train_end_pct}, "
                f"val_end={self.validation_end_pct}; need 0 < train < val <= 1"
            )


@dataclass(slots=True)
class FrozenCandidate:
    config: AppConfig
    config_hash: str
    status: ConfigStatus
    label: str
    data_split: DataSplitPolicy = field(default_factory=DataSplitPolicy)
    locked_at: str = ""
    assumptions: dict[str, Any] = field(default_factory=dict)
    lineage_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "config_hash": self.config_hash,
            "status": self.status.value,
            "locked_at": self.locked_at,
            "assumptions": self.assumptions,
            "lineage_notes": self.lineage_notes,
            "data_split": {
                "train_end_pct": self.data_split.train_end_pct,
                "validation_end_pct": self.data_split.validation_end_pct,
                "embargo_bars": self.data_split.embargo_bars,
            },
        }


def _config_hash(config: AppConfig) -> str:
    serialized = json.dumps(config.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def freeze_config(
    config: AppConfig,
    label: str,
    status: ConfigStatus = ConfigStatus.LOCKED,
    assumptions: dict[str, Any] | None = None,
    lineage_notes: list[str] | None = None,
    data_split: DataSplitPolicy | None = None,
) -> FrozenCandidate:
    """Create an immutable candidate from a config snapshot."""
    return FrozenCandidate(
        config=config.model_copy(deep=True),
        config_hash=_config_hash(config),
        status=status,
        label=label,
        data_split=data_split or DataSplitPolicy(),
        locked_at=datetime.utcnow().isoformat(),
        assumptions=assumptions or {},
        lineage_notes=lineage_notes or [],
    )


def validate_frozen(candidate: FrozenCandidate) -> bool:
    """Re-hash the config and verify it matches the stored hash."""
    return _config_hash(candidate.config) == candidate.config_hash


def split_data(
    data: dict[TradingPair, BarSeries],
    policy: DataSplitPolicy,
) -> tuple[dict[TradingPair, BarSeries], dict[TradingPair, BarSeries], dict[TradingPair, BarSeries]]:
    """Split data into train / validation / holdout according to policy."""
    train: dict[TradingPair, BarSeries] = {}
    validation: dict[TradingPair, BarSeries] = {}
    holdout: dict[TradingPair, BarSeries] = {}

    for pair, series in data.items():
        n = len(series)
        train_end = int(n * policy.train_end_pct)
        val_end = int(n * policy.validation_end_pct)

        train[pair] = series.slice(0, train_end)
        val_start = min(train_end + policy.embargo_bars, val_end)
        validation[pair] = series.slice(val_start, val_end)
        holdout_start = min(val_end + policy.embargo_bars, n)
        holdout[pair] = series.slice(holdout_start, n)

    return train, validation, holdout


class OverfittingGuard:
    """Warns when the number of variants explored exceeds what
    the evidence (trade count, data size) can support."""

    def __init__(self, max_variants_per_100_trades: int = 5) -> None:
        self._ratio = max_variants_per_100_trades

    def warn_if_overfitting(
        self,
        n_variants_tried: int,
        total_trades: int,
        n_pairs: int = 1,
    ) -> list[str]:
        warnings: list[str] = []
        allowance = max(1, (total_trades // 100) * self._ratio)

        if n_variants_tried > allowance:
            warnings.append(
                f"OVERFIT_RISK: {n_variants_tried} variants tried vs "
                f"~{total_trades} trades ({allowance} variants supportable). "
                f"Risk of overfitting to noise."
            )

        if n_variants_tried > 20 and n_pairs < 2:
            warnings.append(
                "SINGLE_PAIR_OVERFIT: many variants explored on a single pair. "
                "Results may not generalize."
            )

        if total_trades < 30:
            warnings.append(
                f"INSUFFICIENT_EVIDENCE: only {total_trades} trades. "
                f"No variant selection is statistically meaningful."
            )

        return warnings
