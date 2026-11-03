"""Data and result preparation for the local research dashboard.

The dashboard is intentionally a thin layer over the existing backtest engine:
it loads bars, runs one backtest and converts the result into small pandas
frames. Keeping this logic here (instead of inside the Streamlit page) makes it
testable without the optional UI dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.config import TIMEFRAME_MINUTES, AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult, MarketBar
from fx_smc_bot.research.experiments import load_config


@dataclass(frozen=True)
class DashboardSnapshot:
    """A completed backtest and its market data, ready for display."""

    config: AppConfig
    data: dict[TradingPair, BarSeries]
    result: BacktestResult
    metrics: PerformanceSummary
    source_label: str


_SYNTHETIC_SPECS: dict[TradingPair, tuple[float, float]] = {
    TradingPair.EURUSD: (1.1000, 0.0012),
    TradingPair.GBPUSD: (1.2700, 0.0015),
    TradingPair.USDJPY: (148.0, 0.15),
}


def synthetic_market_data(
    n_bars: int = 1500,
    *,
    timeframe: Timeframe = Timeframe.M15,
    seed: int = 42,
    pairs: Iterable[TradingPair] | None = None,
) -> dict[TradingPair, BarSeries]:
    """Generate deterministic synthetic bars for a self-contained demo."""
    if n_bars < 50:
        raise ValueError("n_bars must be at least 50")

    rng = np.random.default_rng(seed)
    selected = list(pairs or _SYNTHETIC_SPECS)
    unsupported = [pair for pair in selected if pair not in _SYNTHETIC_SPECS]
    if unsupported:
        names = ", ".join(pair.value for pair in unsupported)
        raise ValueError(f"No synthetic specification for: {names}")
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])

    data: dict[TradingPair, BarSeries] = {}
    for pair in selected:
        base, volatility = _SYNTHETIC_SPECS[pair]
        price = base
        bars: list[MarketBar] = []
        for index in range(n_bars):
            move = rng.normal(0, volatility)
            open_price = price
            close_price = open_price + move
            high = max(open_price, close_price) + abs(rng.normal(0, volatility * 0.4))
            low = min(open_price, close_price) - abs(rng.normal(0, volatility * 0.4))
            bars.append(
                MarketBar(
                    pair=pair,
                    timeframe=timeframe,
                    timestamp=start + delta * index,
                    open=round(open_price, 5),
                    high=round(high, 5),
                    low=round(low, 5),
                    close=round(close_price, 5),
                    bar_index=index,
                    volume=float(rng.integers(80, 1200)),
                )
            )
            price = close_price
        data[pair] = BarSeries.from_bars(bars)

    return data


def load_market_data(data_dir: str | Path, config: AppConfig) -> dict[TradingPair, BarSeries]:
    """Load the configured execution timeframe for every available pair."""
    path = Path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Data directory does not exist: {path}")

    if any(path.rglob("*.parquet")):
        from fx_smc_bot.data.providers.parquet_provider import ParquetProvider

        provider = ParquetProvider(path)
    else:
        from fx_smc_bot.data.providers.csv_provider import CsvProvider

        provider = CsvProvider(path)

    data: dict[TradingPair, BarSeries] = {}
    for pair in config.data.primary_pairs:
        for timeframe in config.data.execution_timeframes:
            try:
                data[pair] = provider.load(pair, timeframe)
                break
            except (FileNotFoundError, ValueError):
                continue

    if not data:
        raise ValueError(f"No usable execution-timeframe data found under {path}")
    return data


def load_dashboard_config(path: str | Path | None = None) -> AppConfig:
    """Load a YAML config, or fall back to the framework defaults."""
    if path is None:
        return AppConfig()
    return load_config(Path(path))


def run_snapshot(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
    *,
    source_label: str = "Local data",
) -> DashboardSnapshot:
    """Run one backtest and return the display-ready snapshot."""
    if not data:
        raise ValueError("No market data supplied")

    engine = BacktestEngine(config)
    result = engine.run(data)
    metrics = engine.metrics(result)
    return DashboardSnapshot(
        config=config,
        data=data,
        result=result,
        metrics=metrics,
        source_label=source_label,
    )


def price_frame(series: BarSeries) -> pd.DataFrame:
    """Convert a BarSeries to an OHLCV frame with a UTC timestamp column."""
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(series.timestamps, utc=True),
            "open": series.open,
            "high": series.high,
            "low": series.low,
            "close": series.close,
        }
    )
    if series.volume is not None:
        frame["volume"] = series.volume
    if series.spread is not None:
        frame["spread"] = series.spread
    return frame


def trades_frame(result: BacktestResult) -> pd.DataFrame:
    """Flatten closed trades into a display frame."""
    rows: list[dict[str, object]] = []
    for index, trade in enumerate(result.trades, start=1):
        rows.append(
            {
                "id": index,
                "pair": trade.pair.value,
                "direction": trade.direction.value,
                "family": trade.family.value,
                "opened_at": pd.to_datetime(trade.opened_at, utc=True),
                "closed_at": pd.to_datetime(trade.closed_at, utc=True),
                "entry": trade.entry_price,
                "exit": trade.exit_price,
                "units": trade.units,
                "pnl": trade.pnl,
                "pnl_pips": trade.pnl_pips,
                "rr": trade.reward_risk_ratio,
                "duration_bars": trade.duration_bars,
                "session": trade.session.value if trade.session else "",
                "regime": trade.regime or "",
                "tags": ", ".join(trade.tags),
            }
        )
    columns = [
        "id",
        "pair",
        "direction",
        "family",
        "opened_at",
        "closed_at",
        "entry",
        "exit",
        "units",
        "pnl",
        "pnl_pips",
        "rr",
        "duration_bars",
        "session",
        "regime",
        "tags",
    ]
    return pd.DataFrame(rows, columns=columns)


def equity_frame(result: BacktestResult) -> pd.DataFrame:
    """Flatten the equity curve for charting."""
    rows = [
        {
            "timestamp": pd.to_datetime(point.timestamp, utc=True),
            "equity": point.equity,
            "cash": point.cash,
            "unrealized_pnl": point.unrealized_pnl,
            "drawdown": point.drawdown,
            "drawdown_pct": point.drawdown_pct,
        }
        for point in result.equity_curve
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "equity",
            "cash",
            "unrealized_pnl",
            "drawdown",
            "drawdown_pct",
        ],
    )


def summary_rows(snapshot: DashboardSnapshot) -> list[dict[str, object]]:
    """One row per pair with bar count and range, for the data-quality tab."""
    rows: list[dict[str, object]] = []
    for pair, series in sorted(snapshot.data.items(), key=lambda item: item[0].value):
        timestamps = pd.to_datetime(series.timestamps, utc=True)
        rows.append(
            {
                "pair": pair.value,
                "timeframe": series.timeframe.value,
                "bars": len(series),
                "first_bar": timestamps[0],
                "last_bar": timestamps[-1],
                "has_volume": series.volume is not None,
                "has_spread": series.spread is not None,
            }
        )
    return rows


def monthly_pnl_frame(trades: pd.DataFrame) -> pd.DataFrame:
    """Aggregate realised P&L by month for the performance overview."""
    columns = ["month", "pnl", "trades", "win_rate"]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    frame = trades.copy()
    closed = frame["closed_at"]
    if getattr(closed.dt, "tz", None) is not None:
        closed = closed.dt.tz_convert("UTC").dt.tz_localize(None)
    frame["month"] = closed.dt.to_period("M").astype(str)
    monthly = (
        frame.groupby("month", as_index=False)
        .agg(
            pnl=("pnl", "sum"),
            trades=("id", "count"),
            wins=("pnl", lambda values: int((values > 0).sum())),
        )
        .sort_values("month")
    )
    monthly["win_rate"] = monthly["wins"] / monthly["trades"]
    return monthly[columns]


def pair_summary_frame(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per pair with trade count, win rate and realised P&L."""
    columns = ["pair", "trades", "win_rate", "pnl", "avg_pnl", "pips"]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    summary = (
        trades.groupby("pair", as_index=False)
        .agg(
            trades=("id", "count"),
            wins=("pnl", lambda values: int((values > 0).sum())),
            pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            pips=("pnl_pips", "sum"),
        )
        .sort_values("pnl", ascending=False)
    )
    summary["win_rate"] = summary["wins"] / summary["trades"]
    return summary[columns]


def session_summary_frame(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per session with trade count, win rate and realised P&L."""
    columns = ["session", "trades", "win_rate", "pnl"]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    frame = trades.copy()
    frame["session"] = frame["session"].fillna("unknown").replace("", "unknown")
    summary = (
        frame.groupby("session", as_index=False)
        .agg(
            trades=("id", "count"),
            wins=("pnl", lambda values: int((values > 0).sum())),
            pnl=("pnl", "sum"),
        )
        .sort_values("pnl", ascending=False)
    )
    summary["win_rate"] = summary["wins"] / summary["trades"]
    return summary[columns]
