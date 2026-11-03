"""Local research dashboard helpers."""

from fx_smc_bot.dashboard.service import (
    DashboardSnapshot,
    equity_frame,
    load_dashboard_config,
    load_market_data,
    price_frame,
    run_snapshot,
    summary_rows,
    synthetic_market_data,
    trades_frame,
)

__all__ = [
    "DashboardSnapshot",
    "equity_frame",
    "load_dashboard_config",
    "load_market_data",
    "price_frame",
    "run_snapshot",
    "summary_rows",
    "synthetic_market_data",
    "trades_frame",
]
