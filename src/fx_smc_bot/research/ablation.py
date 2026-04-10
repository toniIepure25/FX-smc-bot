"""Strategy decomposition and ablation analysis.

Systematically evaluates contribution of each setup family, scoring
component, and filter threshold to overall strategy performance.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AlphaConfig, AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AblationVariant:
    name: str
    description: str
    config_override: dict[str, Any]
    metrics: PerformanceSummary | None = None
    trade_count: int = 0


@dataclass(slots=True)
class AblationResult:
    campaign_name: str
    baseline_metrics: PerformanceSummary | None = None
    variants: list[AblationVariant] = field(default_factory=list)

    def summary_table(self) -> str:
        lines = [
            f"{'Variant':<30s}  {'Trades':>7s}  {'Sharpe':>8s}  "
            f"{'PF':>7s}  {'WinRate':>8s}  {'PnL':>12s}",
            "-" * 78,
        ]
        for v in self.variants:
            m = v.metrics
            if m:
                lines.append(
                    f"{v.name:<30s}  {m.total_trades:>7d}  {m.sharpe_ratio:>8.3f}  "
                    f"{m.profit_factor:>7.2f}  {m.win_rate:>8.1%}  {m.total_pnl:>12,.2f}"
                )
            else:
                lines.append(f"{v.name:<30s}  {'FAILED':>7s}")
        return "\n".join(lines)


def _run_variant(
    base_config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
    variant: AblationVariant,
) -> None:
    cfg = base_config.model_copy(deep=True)
    for dotted_key, value in variant.config_override.items():
        parts = dotted_key.split(".")
        obj = cfg
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], value)
    try:
        engine = BacktestEngine(cfg)
        result = engine.run(data, htf_data)
        variant.metrics = engine.metrics(result)
        variant.trade_count = variant.metrics.total_trades
    except Exception as e:
        logger.warning("Variant %s failed: %s", variant.name, e)


def run_family_ablation(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> AblationResult:
    """Run ablation: each family alone, each family removed, all families."""
    all_families = list(config.alpha.enabled_families)
    result = AblationResult(campaign_name="family_ablation")

    # Baseline: all families
    baseline = AblationVariant(
        name="all_families",
        description="Full strategy with all enabled families",
        config_override={},
    )
    _run_variant(config, data, htf_data, baseline)
    result.baseline_metrics = baseline.metrics
    result.variants.append(baseline)

    # Each family in isolation
    for fam in all_families:
        v = AblationVariant(
            name=f"only_{fam}",
            description=f"Only {fam} detector active",
            config_override={"alpha.enabled_families": [fam]},
        )
        _run_variant(config, data, htf_data, v)
        result.variants.append(v)

    # Each family removed (leave-one-out)
    for fam in all_families:
        remaining = [f for f in all_families if f != fam]
        if not remaining:
            continue
        v = AblationVariant(
            name=f"without_{fam}",
            description=f"All families except {fam}",
            config_override={"alpha.enabled_families": remaining},
        )
        _run_variant(config, data, htf_data, v)
        result.variants.append(v)

    return result


def run_scoring_ablation(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> AblationResult:
    """Vary scoring weights to measure component contributions."""
    result = AblationResult(campaign_name="scoring_ablation")

    weight_sets = [
        ("equal_weights", (1.0, 1.0, 1.0)),
        ("structure_only", (1.0, 0.0, 0.0)),
        ("liquidity_only", (0.0, 1.0, 0.0)),
        ("session_only", (0.0, 0.0, 1.0)),
        ("no_session", (0.5, 0.5, 0.0)),
        ("no_liquidity", (0.7, 0.0, 0.3)),
        ("default", config.alpha.scoring_weights),
    ]

    for name, weights in weight_sets:
        v = AblationVariant(
            name=name,
            description=f"Scoring weights: {weights}",
            config_override={"alpha.scoring_weights": weights},
        )
        _run_variant(config, data, htf_data, v)
        if name == "default":
            result.baseline_metrics = v.metrics
        result.variants.append(v)

    return result


def run_filter_ablation(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None = None,
) -> AblationResult:
    """Sweep min_signal_score and min_reward_risk_ratio thresholds."""
    result = AblationResult(campaign_name="filter_ablation")

    for min_score in [0.0, 0.10, 0.15, 0.25, 0.35, 0.50]:
        v = AblationVariant(
            name=f"min_score_{min_score:.2f}",
            description=f"min_signal_score={min_score}",
            config_override={"alpha.min_signal_score": min_score},
        )
        _run_variant(config, data, htf_data, v)
        result.variants.append(v)

    for min_rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
        v = AblationVariant(
            name=f"min_rr_{min_rr:.1f}",
            description=f"min_reward_risk_ratio={min_rr}",
            config_override={"risk.min_reward_risk_ratio": min_rr},
        )
        _run_variant(config, data, htf_data, v)
        result.variants.append(v)

    if result.variants:
        result.baseline_metrics = result.variants[0].metrics

    return result
