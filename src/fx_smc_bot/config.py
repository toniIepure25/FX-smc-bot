"""Typed configuration for the FX SMC research framework."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class RiskConfig(BaseModel):
    base_risk_per_trade: float = Field(default=0.005, ge=0.0, le=0.05)
    max_portfolio_risk: float = Field(default=0.015, ge=0.0, le=0.20)
    max_daily_drawdown: float = Field(default=0.03, ge=0.0, le=0.20)
    max_weekly_drawdown: float = Field(default=0.06, ge=0.0, le=0.30)
    max_concurrent_positions: int = Field(default=3, ge=1, le=10)
    max_usd_directional_exposure: float = Field(default=1.0, ge=0.0, le=5.0)


class ExecutionConfig(BaseModel):
    model_spread: bool = True
    model_slippage: bool = True
    latency_ms: int = Field(default=150, ge=0, le=10_000)
    allow_limit_orders: bool = True
    fill_on_touch: bool = False


class MlConfig(BaseModel):
    enable_regime_filter: bool = False
    enable_trade_quality_model: bool = False
    enable_meta_labeling: bool = False


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FX_SMC_", extra="ignore")

    environment: str = "dev"
    data: DataConfig = DataConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    ml: MlConfig = MlConfig()


__all__ = [
    "AppConfig",
    "DataConfig",
    "ExecutionConfig",
    "MlConfig",
    "RiskConfig",
    "Timeframe",
    "TradingPair",
]
