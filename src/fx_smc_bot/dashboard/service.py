"""Data and result preparation for the local research dashboard.

The dashboard is intentionally a thin layer over the existing backtest engine:
it loads bars, runs one backtest and converts the result into small pandas
frames. Keeping this logic here (instead of inside the Streamlit page) makes it
testable without the optional UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.backtesting.runner import (
    load_market_data,
    run_backtest,
    synthetic_market_data,
)
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult
from fx_smc_bot.research.experiments import load_config

__all__ = [
    "DashboardSnapshot",
    "equity_frame",
    "load_dashboard_config",
    "load_market_data",
    "monthly_pnl_frame",
    "pair_summary_frame",
    "price_frame",
    "run_snapshot",
    "session_summary_frame",
    "summary_rows",
    "synthetic_market_data",
    "trades_frame",
]


@dataclass(frozen=True)
class DashboardSnapshot:
    """A completed backtest and its market data, ready for display."""

    config: AppConfig
    data: dict[TradingPair, BarSeries]
    result: BacktestResult
    metrics: PerformanceSummary
    source_label: str


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
    run = run_backtest(config, data)
    return DashboardSnapshot(
        config=run.config,
        data=run.data,
        result=run.result,
        metrics=run.metrics,
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
