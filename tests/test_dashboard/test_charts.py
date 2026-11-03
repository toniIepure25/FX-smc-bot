"""Smoke tests for Plotly figure builders (optional dashboard extra)."""

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("plotly")

from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.dashboard.charts import (
    make_attribution_figure,
    make_equity_figure,
    make_monthly_pnl_figure,
    make_pnl_distribution_figure,
    make_price_figure,
    make_trade_focus_figure,
)
from fx_smc_bot.dashboard.service import run_snapshot, synthetic_market_data, trades_frame


def test_figures_build_for_a_synthetic_snapshot() -> None:
    snapshot = run_snapshot(AppConfig(), synthetic_market_data(300), source_label="test")
    trades = trades_frame(snapshot.result)
    if trades.empty:
        pytest.skip("Synthetic run produced no closed trades")

    pair = TradingPair(trades.iloc[0]["pair"])
    figures = [
        make_price_figure(snapshot, pair),
        make_equity_figure(snapshot),
        make_attribution_figure(trades),
        make_monthly_pnl_figure(trades),
        make_pnl_distribution_figure(trades),
        make_trade_focus_figure(snapshot, pair, trades.iloc[0]),
    ]

    assert all(figure is not None for figure in figures)
    assert len(figures[0].data) >= 2
    assert len(figures[-1].data) >= 2


def test_empty_frames_return_no_optional_figures() -> None:
    empty = pd.DataFrame(columns=["id", "pnl", "closed_at", "family", "pair"])
    assert make_attribution_figure(empty) is None
    assert make_monthly_pnl_figure(empty) is None
    assert make_pnl_distribution_figure(empty) is None
