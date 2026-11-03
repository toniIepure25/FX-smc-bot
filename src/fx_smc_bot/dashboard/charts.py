"""Plotly figure builders for the local research dashboard.

Keeping figures in a separate module keeps ``dashboard/app.py`` focused on
layout and widgets, and lets the chart contract be smoke-tested without a
browser.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from fx_smc_bot.config import TradingPair
from fx_smc_bot.dashboard.formatting import compact_money
from fx_smc_bot.dashboard.service import (
    DashboardSnapshot,
    equity_frame,
    monthly_pnl_frame,
    price_frame,
    trades_frame,
)

GREEN = "#22c55e"
RED = "#ef4444"
SLATE = "#94a3b8"
PANEL = "#0b1220"
BLUE = "#38bdf8"

_BASE_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": PANEL,
    "font": dict(color="#cbd5e1"),
}


def _apply_axes(fig: go.Figure) -> None:
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.10)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.10)", zeroline=False)


def make_price_figure(snapshot: DashboardSnapshot, pair: TradingPair) -> go.Figure:
    """Candlesticks with volume, holding ribbons, entries and exits."""
    series = snapshot.data[pair]
    prices = price_frame(series)
    trades = trades_frame(snapshot.result)
    trades = trades[trades["pair"] == pair.value].copy()

    has_volume = "volume" in prices.columns and prices["volume"].fillna(0).abs().sum() > 0
    rows = 2 if has_volume else 1
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.78, 0.22] if has_volume else [1.0],
    )

    fig.add_trace(
        go.Candlestick(
            x=prices["timestamp"],
            open=prices["open"],
            high=prices["high"],
            low=prices["low"],
            close=prices["close"],
            name=pair.value,
            increasing_line_color=GREEN,
            increasing_fillcolor=GREEN,
            decreasing_line_color=RED,
            decreasing_fillcolor=RED,
            whiskerwidth=0.4,
        ),
        row=1,
        col=1,
    )

    if has_volume:
        colors = [
            "rgba(34,197,94,0.35)" if close >= open_ else "rgba(239,68,68,0.35)"
            for open_, close in zip(prices["open"], prices["close"], strict=False)
        ]
        fig.add_trace(
            go.Bar(
                x=prices["timestamp"],
                y=prices["volume"],
                name="Volume",
                marker_color=colors,
                hovertemplate="Volume %{y:,.0f}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    # Holding-period ribbons: each trade gets a translucent block on the price chart.
    for _, trade in trades.iterrows():
        opened = trade["opened_at"]
        closed = trade["closed_at"]
        if pd.isna(opened) or pd.isna(closed) or closed <= opened:
            continue
        color = GREEN if trade["pnl"] >= 0 else RED
        fig.add_vrect(
            x0=opened,
            x1=closed,
            fillcolor=color,
            opacity=0.06,
            line_width=0,
            layer="below",
            row=1,
            col=1,
        )

    # Entry / exit paths make the position lifecycle readable at a glance.
    line_x: list[object] = []
    line_y: list[float] = []
    for _, trade in trades.iterrows():
        line_x.extend([trade["opened_at"], trade["closed_at"], None])
        line_y.extend([float(trade["entry"]), float(trade["exit"]), None])
    if line_x:
        fig.add_trace(
            go.Scatter(
                x=line_x,
                y=line_y,
                mode="lines",
                line=dict(color="rgba(148,163,184,0.45)", width=1),
                hoverinfo="skip",
                showlegend=False,
                name="Position path",
            ),
            row=1,
            col=1,
        )

    for direction, symbol, color in (
        ("long", "triangle-up", GREEN),
        ("short", "triangle-down", RED),
    ):
        subset = trades[trades["direction"] == direction]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["opened_at"],
                y=subset["entry"],
                mode="markers",
                name=f"{direction.title()} entry",
                marker=dict(
                    symbol=symbol,
                    size=11,
                    color=color,
                    line=dict(color="#020617", width=1),
                ),
                customdata=subset[["family", "pnl", "rr"]].to_numpy(),
                hovertemplate=(
                    f"<b>{direction.upper()} entry</b><br>"
                    "%{x|%Y-%m-%d %H:%M}<br>"
                    "Price %{y:.5f}<br>"
                    "Family %{customdata[0]}<br>"
                    "P&L %{customdata[1]:,.0f}<br>"
                    "RR %{customdata[2]:.2f}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

    if not trades.empty:
        exit_colors = [GREEN if pnl >= 0 else RED for pnl in trades["pnl"]]
        fig.add_trace(
            go.Scatter(
                x=trades["closed_at"],
                y=trades["exit"],
                mode="markers",
                name="Exit",
                marker=dict(symbol="x", size=9, color=exit_colors, line=dict(width=2)),
                customdata=trades[["pnl", "pnl_pips", "family"]].to_numpy(),
                hovertemplate=(
                    "<b>EXIT</b><br>"
                    "%{x|%Y-%m-%d %H:%M}<br>"
                    "Price %{y:.5f}<br>"
                    "P&L %{customdata[0]:,.0f} (%{customdata[1]:.1f} pips)<br>"
                    "Family %{customdata[2]}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

    fig.update_layout(
        height=650,
        margin=dict(l=10, r=10, t=42, b=10),
        hovermode="x unified",
        dragmode="pan",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        title=dict(text=f"{pair.value} · {series.timeframe.value}", x=0.01, font=dict(size=16)),
        xaxis_rangeslider_visible=False,
        **_BASE_LAYOUT,
    )
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikedash="dot",
        spikecolor=SLATE,
        spikethickness=1,
    )
    _apply_axes(fig)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    if has_volume:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


def make_trade_focus_figure(
    snapshot: DashboardSnapshot,
    pair: TradingPair,
    trade: pd.Series,
    *,
    padding_bars: int = 18,
) -> go.Figure:
    """Zoom the chart around one trade, with entry and exit reference levels."""
    series = snapshot.data[pair]
    prices = price_frame(series)
    opened = pd.Timestamp(trade["opened_at"])
    closed = pd.Timestamp(trade["closed_at"])
    opened_idx = int((prices["timestamp"] - opened).abs().argmin())
    closed_idx = int((prices["timestamp"] - closed).abs().argmin())
    start = max(0, min(opened_idx, closed_idx) - padding_bars)
    end = min(len(prices), max(opened_idx, closed_idx) + padding_bars + 1)
    window = prices.iloc[start:end]

    fig = go.Figure(
        go.Candlestick(
            x=window["timestamp"],
            open=window["open"],
            high=window["high"],
            low=window["low"],
            close=window["close"],
            name=pair.value,
            increasing_line_color=GREEN,
            increasing_fillcolor=GREEN,
            decreasing_line_color=RED,
            decreasing_fillcolor=RED,
            whiskerwidth=0.4,
        )
    )
    fig.add_vrect(
        x0=opened,
        x1=closed,
        fillcolor=GREEN if trade["pnl"] >= 0 else RED,
        opacity=0.10,
        line_width=0,
        layer="below",
    )
    fig.add_hline(
        y=float(trade["entry"]),
        line=dict(color=BLUE, width=1, dash="dot"),
        annotation_text=f"Entry {trade['entry']:.5f}",
        annotation_position="top left",
    )
    fig.add_hline(
        y=float(trade["exit"]),
        line=dict(color=GREEN if trade["pnl"] >= 0 else RED, width=1, dash="dot"),
        annotation_text=f"Exit {trade['exit']:.5f}",
        annotation_position="bottom left",
    )
    fig.add_trace(
        go.Scatter(
            x=[opened],
            y=[float(trade["entry"])],
            mode="markers",
            name="Entry",
            marker=dict(symbol="triangle-up" if trade["direction"] == "long" else "triangle-down",
                        size=12, color=BLUE),
            hovertemplate="Entry %{y:.5f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[closed],
            y=[float(trade["exit"])],
            mode="markers",
            name="Exit",
            marker=dict(symbol="x", size=11, color=SLATE),
            hovertemplate="Exit %{y:.5f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=330,
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        showlegend=False,
        title=dict(
            text=(
                f"Trade #{int(trade['id'])} · {pair.value} · "
                f"{str(trade['direction']).upper()} · {compact_money(float(trade['pnl']))}"
            ),
            x=0.01,
            font=dict(size=14),
        ),
        xaxis_rangeslider_visible=False,
        **_BASE_LAYOUT,
    )
    _apply_axes(fig)
    return fig


def make_equity_figure(snapshot: DashboardSnapshot) -> go.Figure | None:
    """Equity and underwater curves."""
    equity = equity_frame(snapshot.result)
    if equity.empty:
        return None

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.68, 0.32],
        subplot_titles=("Equity", "Drawdown"),
    )
    fig.add_trace(
        go.Scatter(
            x=equity["timestamp"],
            y=equity["equity"],
            mode="lines",
            name="Equity",
            line=dict(color=BLUE, width=2),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Equity $%{y:,.0f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_hline(
        y=snapshot.result.initial_capital,
        line=dict(color=SLATE, width=1, dash="dot"),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=equity["timestamp"],
            y=-equity["drawdown_pct"] * 100.0,
            mode="lines",
            name="Drawdown",
            line=dict(color=RED, width=1.5),
            fill="tozeroy",
            fillcolor="rgba(239,68,68,0.12)",
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>Drawdown %{y:.2f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        height=430,
        margin=dict(l=10, r=10, t=36, b=10),
        hovermode="x unified",
        showlegend=False,
        **_BASE_LAYOUT,
    )
    _apply_axes(fig)
    fig.update_yaxes(title_text="Equity", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    return fig


def make_attribution_figure(trades: pd.DataFrame) -> go.Figure | None:
    """Horizontal P&L bars by setup family."""
    if trades.empty:
        return None

    by_family = (
        trades.groupby("family", as_index=False)["pnl"]
        .sum()
        .sort_values("pnl", ascending=True)
    )
    colors = [GREEN if pnl >= 0 else RED for pnl in by_family["pnl"]]
    fig = go.Figure(
        go.Bar(
            x=by_family["pnl"],
            y=by_family["family"],
            orientation="h",
            marker_color=colors,
            text=[compact_money(v) for v in by_family["pnl"]],
            textposition="outside",
            hovertemplate="%{y}<br>P&L $%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=55, t=20, b=10),
        xaxis_title="P&L",
        yaxis_title="",
        **_BASE_LAYOUT,
    )
    _apply_axes(fig)
    return fig


def make_monthly_pnl_figure(trades: pd.DataFrame) -> go.Figure | None:
    """Monthly realised P&L bars, useful for spotting clustered performance."""
    monthly = monthly_pnl_frame(trades)
    if monthly.empty:
        return None

    colors = [GREEN if pnl >= 0 else RED for pnl in monthly["pnl"]]
    fig = go.Figure(
        go.Bar(
            x=monthly["month"],
            y=monthly["pnl"],
            marker_color=colors,
            customdata=monthly[["trades"]].to_numpy(),
            hovertemplate=(
                "%{x}<br>P&L $%{y:,.0f}<br>"
                "Trades %{customdata[0]:.0f}<extra></extra>"
            ),
        )
    )
    fig.add_hline(y=0, line=dict(color=SLATE, width=1))
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="",
        yaxis_title="P&L",
        **_BASE_LAYOUT,
    )
    _apply_axes(fig)
    fig.update_xaxes(type="category")
    return fig


def make_pnl_distribution_figure(trades: pd.DataFrame) -> go.Figure | None:
    """Distribution of trade P&L, split visually by zero."""
    if trades.empty:
        return None

    fig = go.Figure(
        go.Histogram(
            x=trades["pnl"],
            nbinsx=32,
            marker_color=BLUE,
            opacity=0.8,
            hovertemplate="P&L $%{x:,.0f}<br>Trades %{y}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line=dict(color=SLATE, width=1, dash="dot"))
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="P&L per trade",
        yaxis_title="Trades",
        bargap=0.05,
        **_BASE_LAYOUT,
    )
    _apply_axes(fig)
    return fig
