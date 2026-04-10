"""Typed configuration for the FX SMC research framework.

Uses Pydantic v2 BaseModel for validated, serialisable configuration.
AppConfig aggregates all sub-configs and can be loaded from env vars or YAML.
"""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Core enums (used across the whole package)
# ---------------------------------------------------------------------------

class TradingPair(str, Enum):
    EURUSD = "EURUSD"
    GBPUSD = "GBPUSD"
    USDJPY = "USDJPY"
    GBPJPY = "GBPJPY"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


# Mapping from Timeframe enum to minutes for resampling arithmetic.
TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}


# ---------------------------------------------------------------------------
# Pip metadata per pair (used by sizing, metrics, and display logic)
# ---------------------------------------------------------------------------

PAIR_PIP_INFO: dict[TradingPair, tuple[float, int]] = {
    TradingPair.EURUSD: (0.0001, 4),
    TradingPair.GBPUSD: (0.0001, 4),
    TradingPair.USDJPY: (0.01, 2),
    TradingPair.GBPJPY: (0.01, 2),
}

# Base and quote currency for each pair.
PAIR_CURRENCIES: dict[TradingPair, tuple[str, str]] = {
    TradingPair.EURUSD: ("EUR", "USD"),
    TradingPair.GBPUSD: ("GBP", "USD"),
    TradingPair.USDJPY: ("USD", "JPY"),
    TradingPair.GBPJPY: ("GBP", "JPY"),
}


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

class DataConfig(BaseModel):
    root_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw")
    interim_dir: Path = Path("data/interim")
    processed_dir: Path = Path("data/processed")
    primary_pairs: list[TradingPair] = Field(
        default_factory=lambda: [
            TradingPair.EURUSD,
            TradingPair.GBPUSD,
            TradingPair.USDJPY,
        ]
    )
    context_timeframes: list[Timeframe] = Field(
        default_factory=lambda: [Timeframe.H4, Timeframe.H1]
    )
    execution_timeframes: list[Timeframe] = Field(
        default_factory=lambda: [Timeframe.M15, Timeframe.M5]
    )
    timezone: str = "UTC"


class StructureConfig(BaseModel):
    """Parameters controlling swing detection and structure analysis."""
    swing_lookback: int = Field(default=5, ge=2, le=50,
                                description="Bars each side for fractal swing detection")
    min_swing_atr_multiple: float = Field(default=0.3, ge=0.0,
                                          description="Minimum swing size as ATR multiple")
    atr_period: int = Field(default=14, ge=5, le=100)
    fvg_min_atr_multiple: float = Field(default=0.5, ge=0.0,
                                        description="Min FVG size as ATR multiple")
    fvg_max_fill_pct: float = Field(default=0.5, ge=0.0, le=1.0,
                                    description="FVG considered filled above this %")
    displacement_atr_multiple: float = Field(default=1.5, ge=0.5,
                                             description="Min body size for displacement candle")
    displacement_body_efficiency: float = Field(default=0.6, ge=0.0, le=1.0,
                                                description="Min body/range ratio for displacement")
    ob_require_displacement: bool = True
    equal_level_tolerance_pips: float = Field(default=3.0, ge=0.0,
                                              description="Pip tolerance for equal high/low clustering")
    equal_level_min_touches: int = Field(default=2, ge=2)


class SessionTimeConfig(BaseModel):
    """UTC time boundaries for a single session."""
    start: time = time(0, 0)
    end: time = time(0, 0)


class SessionConfig(BaseModel):
    """FX session time windows (UTC)."""
    asian: SessionTimeConfig = SessionTimeConfig(start=time(0, 0), end=time(8, 0))
    london: SessionTimeConfig = SessionTimeConfig(start=time(7, 0), end=time(16, 0))
    new_york: SessionTimeConfig = SessionTimeConfig(start=time(12, 0), end=time(21, 0))
    london_ny_overlap: SessionTimeConfig = SessionTimeConfig(start=time(12, 0), end=time(16, 0))


class RiskConfig(BaseModel):
    base_risk_per_trade: float = Field(default=0.005, ge=0.0, le=0.05)
    max_portfolio_risk: float = Field(default=0.015, ge=0.0, le=0.20)
    max_daily_drawdown: float = Field(default=0.03, ge=0.0, le=0.20)
    max_weekly_drawdown: float = Field(default=0.06, ge=0.0, le=0.30)
    max_concurrent_positions: int = Field(default=3, ge=1, le=10)
    max_per_pair_positions: int = Field(default=1, ge=1, le=5)
    max_usd_directional_exposure: float = Field(default=1.0, ge=0.0, le=5.0)
    min_reward_risk_ratio: float = Field(default=1.5, ge=0.0)
    score_risk_modulation: float = Field(default=0.5, ge=0.0, le=1.0,
                                         description="How much signal score modulates risk (0=none, 1=full)")
    volatility_risk_scaling: bool = True
    max_currency_exposure: float = Field(default=2.0, ge=0.0, le=10.0,
                                          description="Max net exposure per currency factor (lot-units)")
    max_directional_concentration: float = Field(default=0.8, ge=0.0, le=1.0,
                                                   description="Max fraction of positions in one direction")
    max_trades_per_day: int = Field(default=10, ge=1, le=100)
    max_trades_per_session: int = Field(default=5, ge=1, le=50)
    daily_loss_lockout: float = Field(default=0.025, ge=0.0, le=0.10,
                                       description="Daily loss % that triggers LOCKED state")
    consecutive_loss_dampen_after: int = Field(default=3, ge=1, le=20,
                                                description="Consecutive losses before dampening")
    consecutive_loss_dampen_factor: float = Field(default=0.5, ge=0.0, le=1.0)
    allocation_strategy: str = Field(
        default="equal_risk",
        description="Budget allocation: equal_risk, score_weighted, volatility_adjusted, capped_conviction",
    )


class FillPolicy(str, Enum):
    """How to resolve intrabar SL/TP ambiguity when both levels are within range."""
    CONSERVATIVE = "conservative"  # SL checked first (worst-case assumption)
    OPTIMISTIC = "optimistic"      # TP checked first
    RANDOM = "random"              # randomize which hits first


class ExecutionConfig(BaseModel):
    model_spread: bool = True
    model_slippage: bool = True
    default_spread_pips: float = Field(default=1.5, ge=0.0)
    slippage_pips: float = Field(default=0.3, ge=0.0)
    latency_ms: int = Field(default=150, ge=0, le=10_000)
    allow_limit_orders: bool = True
    fill_on_touch: bool = False
    fill_policy: FillPolicy = FillPolicy.CONSERVATIVE
    volatility_slippage_factor: float = Field(
        default=0.1, ge=0.0, le=1.0,
        description="Slippage as fraction of current ATR (for VolatilitySlippage)")
    volatility_spread_factor: float = Field(
        default=0.3, ge=0.0, le=2.0,
        description="Spread as fraction of current ATR (for VolatilitySlippage)")


class BacktestConfig(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    initial_capital: float = Field(default=100_000.0, ge=1_000.0)
    commission_per_lot: float = Field(default=3.5, ge=0.0,
                                      description="Round-turn commission per standard lot")
    lot_size: float = Field(default=100_000.0, ge=1.0)


class AlphaConfig(BaseModel):
    """Controls which setup families are active and scoring parameters."""
    enabled_families: list[str] = Field(
        default_factory=lambda: [
            "sweep_reversal", "bos_continuation", "fvg_retrace",
        ],
        description="Family names to activate (supports SMC and baseline names)",
    )
    scoring_weights: tuple[float, float, float] = Field(
        default=(0.5, 0.3, 0.2),
        description="Weights for (structure, liquidity, session) scoring",
    )
    min_signal_score: float = Field(default=0.15, ge=0.0, le=1.0)
    slippage_model: str = Field(
        default="fixed",
        description="Slippage model: fixed, volatility, spread_from_data",
    )
    sizer_model: str = Field(
        default="stop_based",
        description="Sizer: stop_based, volatility_adjusted, score_aware, composite",
    )


class MlConfig(BaseModel):
    enable_regime_filter: bool = False
    enable_regime_tagging: bool = True
    enable_trade_quality_model: bool = False
    enable_meta_labeling: bool = False


class OperationalState(str, Enum):
    """Operational risk state machine for the trading engine."""
    ACTIVE = "active"
    THROTTLED = "throttled"
    LOCKED = "locked"
    STOPPED = "stopped"


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class DeploymentGateConfig(BaseModel):
    """Configurable thresholds for deployment readiness gate."""
    min_sharpe: float = Field(default=0.3, description="Minimum Sharpe ratio")
    min_profit_factor: float = Field(default=1.1, description="Minimum profit factor")
    max_drawdown_pct: float = Field(default=0.20, description="Maximum drawdown percentage")
    min_trade_count: int = Field(default=30, description="Minimum number of trades")
    min_win_rate: float = Field(default=0.35, description="Minimum win rate")
    max_cost_degradation_pct: float = Field(default=0.50, description="Max PnL loss under cost stress")
    min_stability: float = Field(default=0.3, description="Minimum stability score (0-1)")
    min_robustness: float = Field(default=0.3, description="Minimum robustness score (0-1)")
    min_oos_consistency: float = Field(default=0.5, description="Minimum OOS consistency (0-1)")
    min_diversification: float = Field(default=0.2, description="Minimum pair diversification (0-1)")


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FX_SMC_", extra="ignore")

    environment: str = "dev"
    data: DataConfig = DataConfig()
    structure: StructureConfig = StructureConfig()
    sessions: SessionConfig = SessionConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    backtest: BacktestConfig = BacktestConfig()
    alpha: AlphaConfig = AlphaConfig()
    ml: MlConfig = MlConfig()
    deployment_gate: DeploymentGateConfig = DeploymentGateConfig()


__all__ = [
    "AlphaConfig",
    "AppConfig",
    "BacktestConfig",
    "DataConfig",
    "DeploymentGateConfig",
    "ExecutionConfig",
    "FillPolicy",
    "MlConfig",
    "OperationalState",
    "PAIR_CURRENCIES",
    "PAIR_PIP_INFO",
    "RiskConfig",
    "SessionConfig",
    "SessionTimeConfig",
    "StructureConfig",
    "TIMEFRAME_MINUTES",
    "Timeframe",
    "TradingPair",
]
