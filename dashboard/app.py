"""FX-SMC Research Cockpit — a local Streamlit dashboard.

Run with:
    streamlit run dashboard/app.py

The page is a read-only research UI. It never places orders and does not claim
that any backtest result is a live edge.
"""

from __future__ import annotations

import html
import inspect
import math
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:  # pragma: no cover - only hit without the dashboard extra
    st.error('Plotly is required. Install the dashboard extra: pip install -e ".[dashboard]"')
    st.stop()

from fx_smc_bot.config import TradingPair
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

st.set_page_config(
    page_title="FX-SMC Research Cockpit",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

GREEN = "#22c55e"
RED = "#ef4444"
SLATE = "#94a3b8"
PANEL = "#0b1220"

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
    [data-testid="stMetric"] {
        background: linear-gradient(180deg, #101b2d 0%, #0b1220 100%);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }
    [data-testid="stMetricLabel"] { color: #94a3b8; }
    [data-testid="stMetricValue"] { color: #f8fafc; }
    .hero {
        display: flex; align-items: flex-start; justify-content: space-between;
        gap: 1rem; padding: 1.2rem 1.4rem; margin-bottom: 1rem;
        border: 1px solid rgba(56, 189, 248, 0.22);
        border-radius: 18px;
        background: radial-gradient(1100px 220px at 10% -20%,
                    rgba(56,189,248,0.22), transparent 60%),
                    linear-gradient(135deg, #0b1220 0%, #111c2f 100%);
    }
    .hero h1 { margin: 0.1rem 0 0.35rem 0; font-size: 2rem; letter-spacing: -0.03em; }
    .hero p { margin: 0; color: #94a3b8; max-width: 760px; }
    .eyebrow { color: #38bdf8; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.18em; }
    .badge {
        white-space: nowrap; color: #fca5a5; border: 1px solid rgba(239,68,68,0.45);
        background: rgba(239,68,68,0.10); border-radius: 999px;
        padding: 0.35rem 0.7rem; font-size: 0.72rem; font-weight: 700;
        letter-spacing: 0.08em;
    }
    .chip {
        display: inline-block; margin: 0 0.35rem 0.35rem 0; padding: 0.2rem 0.55rem;
        border-radius: 999px; border: 1px solid rgba(148,163,184,0.25);
        color: #cbd5e1; font-size: 0.75rem;
    }
    .subtle { color: #94a3b8; font-size: 0.85rem; }
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148,163,184,0.16); border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _stretch_kwargs(func) -> dict[str, object]:
    """Use the modern width API when available, else the legacy switch."""
    return {"width": "stretch"} if "width" in inspect.signature(func).parameters else {
        "use_container_width": True
    }


PLOTLY_STRETCH = _stretch_kwargs(st.plotly_chart)
DATAFRAME_STRETCH = _stretch_kwargs(st.dataframe)
BUTTON_STRETCH = _stretch_kwargs(st.button)


def compact_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:,.1f}k"
    return f"{sign}${value:,.0f}"


def finite(value: float, fallback: str = "—") -> str:
    return fallback if not math.isfinite(value) else f"{value:,.2f}"


def _build_snapshot(
    source: str,
    n_bars: int,
    data_dir: str,
    config_path: str,
) -> DashboardSnapshot:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    config = load_dashboard_config(path)

    if source == "Synthetic demo":
        data = synthetic_market_data(n_bars=n_bars)
        label = f"Synthetic demo · {n_bars:,} bars/pair"
    else:
        data = load_market_data(data_dir, config)
        label = f"Local data · {data_dir}"
    return run_snapshot(config, data, source_label=label)


def make_price_figure(snapshot: DashboardSnapshot, pair: TradingPair) -> go.Figure:
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PANEL,
        font=dict(color="#cbd5e1"),
        hovermode="x unified",
        dragmode="pan",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        title=dict(text=f"{pair.value} · {series.timeframe.value}", x=0.01, font=dict(size=16)),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(
        gridcolor="rgba(148,163,184,0.10)",
        showspikes=True,
        spikemode="across",
        spikedash="dot",
        spikecolor=SLATE,
        spikethickness=1,
    )
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.10)", zeroline=False)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    if has_volume:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


def make_equity_figure(snapshot: DashboardSnapshot) -> go.Figure | None:
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
            line=dict(color="#38bdf8", width=2),
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PANEL,
        font=dict(color="#cbd5e1"),
        hovermode="x unified",
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.08)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.08)", zeroline=False)
    fig.update_yaxes(title_text="Equity", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    return fig


def make_attribution_figure(trades: pd.DataFrame) -> go.Figure | None:
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
        height=260,
        margin=dict(l=10, r=50, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=PANEL,
        font=dict(color="#cbd5e1"),
        xaxis_title="P&L",
        yaxis_title="",
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.08)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.08)")
    return fig


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
      <div>
        <div class="eyebrow">FX-SMC RESEARCH LAB</div>
        <h1>Research Cockpit</h1>
        <p>Price structure, position lifecycle and portfolio diagnostics from the local
        backtest engine. A simulator for research review — not a live signal service.</p>
      </div>
      <div class="badge">NO VALIDATED EDGE</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Run configuration")
    source = st.radio(
        "Market data",
        ["Synthetic demo", "Local dataset"],
        help="The synthetic path is deterministic and needs no data download.",
    )
    if source == "Synthetic demo":
        n_bars = st.slider("Bars per pair", 600, 3000, 1200, step=300)
        data_dir = ""
    else:
        n_bars = 1200
        data_dir = st.text_input("Data directory", "var/smoke/data")
    config_path = st.text_input("Config file", "configs/base.yaml")
    run_clicked = st.button("Run backtest", type="primary", **BUTTON_STRETCH)

    st.divider()
    st.caption(
        "The dashboard runs one in-process backtest. No broker connection, no order "
        "routing, no persistence."
    )

if "snapshot" not in st.session_state:
    try:
        with st.spinner("Running the initial synthetic backtest…"):
            st.session_state.snapshot = _build_snapshot(
                "Synthetic demo", 1200, "", "configs/base.yaml"
            )
    except Exception as exc:  # pragma: no cover - depends on local environment
        st.error(f"Could not start the demo: {exc}")
        st.stop()

if run_clicked:
    try:
        with st.spinner("Running backtest…"):
            st.session_state.snapshot = _build_snapshot(
                source, n_bars, data_dir, config_path
            )
    except Exception as exc:
        st.error(f"Backtest failed: {exc}")
        st.stop()

snapshot: DashboardSnapshot = st.session_state.snapshot
metrics = snapshot.metrics
trades = trades_frame(snapshot.result)
initial = snapshot.result.initial_capital
return_pct = (metrics.total_pnl / initial * 100.0) if initial else 0.0

cols = st.columns(6)
cols[0].metric("Net P&L", compact_money(metrics.total_pnl), f"{return_pct:+.2f}%")
cols[1].metric("Win rate", f"{metrics.win_rate * 100:.1f}%", f"{metrics.total_trades} trades")
cols[2].metric("Profit factor", finite(metrics.profit_factor), "gross wins / losses")
cols[3].metric(
    "Max drawdown",
    f"-{metrics.max_drawdown_pct * 100:.2f}%",
    f"-{compact_money(abs(metrics.max_drawdown))}",
)
cols[4].metric("Sharpe", finite(metrics.sharpe_ratio), "annualised")
cols[5].metric("Expectancy", compact_money(metrics.expectancy), "per trade")

st.markdown(
    f'<span class="chip">Source: {html.escape(snapshot.source_label)}</span>'
    f'<span class="chip">Pairs: {len(snapshot.data)}</span>'
    f'<span class="chip">Initial capital: {compact_money(initial)}</span>'
    f'<span class="chip">Closed trades: {len(trades)}</span>',
    unsafe_allow_html=True,
)

tab_overview, tab_price, tab_trades, tab_data = st.tabs(
    ["Overview", "Price & positions", "Trade ledger", "Data quality"]
)

with tab_overview:
    equity_fig = make_equity_figure(snapshot)
    if equity_fig is not None:
        st.plotly_chart(equity_fig, **PLOTLY_STRETCH, config={"displayModeBar": False})
    else:
        st.info("The run produced no equity curve (no closed trades).")

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("P&L by setup family")
        attribution = make_attribution_figure(trades)
        if attribution is not None:
            st.plotly_chart(
                attribution, **PLOTLY_STRETCH, config={"displayModeBar": False}
            )
        else:
            st.caption("No closed trades to attribute.")
    with right:
        st.subheader("Session mix")
        if trades.empty:
            st.caption("No closed trades.")
        else:
            sessions = (
                trades.groupby("session", dropna=False)
                .agg(trades=("id", "count"), pnl=("pnl", "sum"))
                .reset_index()
            )
            sessions["session"] = sessions["session"].replace("", "unknown")
            st.dataframe(
                sessions,
                hide_index=True,
                **DATAFRAME_STRETCH,
                column_config={
                    "session": "Session",
                    "trades": st.column_config.NumberColumn("Trades", format="%d"),
                    "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
                },
            )

with tab_price:
    pair_options = sorted(snapshot.data, key=lambda pair: pair.value)
    selected_pair = st.selectbox(
        "Pair",
        pair_options,
        format_func=lambda pair: pair.value,
        index=0,
    )
    pair_trades = trades[trades["pair"] == selected_pair.value]
    st.caption(
        f"{len(pair_trades)} closed trades on {selected_pair.value}. "
        "Green/red blocks mark holding periods; triangles mark entries and × marks exits."
    )
    st.plotly_chart(
        make_price_figure(snapshot, selected_pair),
        **PLOTLY_STRETCH,
        config={"displayModeBar": True, "scrollZoom": True},
    )

with tab_trades:
    if trades.empty:
        st.info("No closed trades in this run.")
    else:
        filter_cols = st.columns(3)
        directions = filter_cols[0].multiselect(
            "Direction",
            sorted(trades["direction"].unique()),
            default=sorted(trades["direction"].unique()),
        )
        families = filter_cols[1].multiselect(
            "Setup family",
            sorted(trades["family"].unique()),
            default=sorted(trades["family"].unique()),
        )
        outcomes = filter_cols[2].selectbox("Outcome", ["All", "Winners", "Losers"])

        filtered = trades[
            trades["direction"].isin(directions) & trades["family"].isin(families)
        ].copy()
        if outcomes == "Winners":
            filtered = filtered[filtered["pnl"] > 0]
        elif outcomes == "Losers":
            filtered = filtered[filtered["pnl"] <= 0]

        display = filtered[
            [
                "id",
                "pair",
                "direction",
                "family",
                "opened_at",
                "closed_at",
                "entry",
                "exit",
                "pnl",
                "pnl_pips",
                "rr",
                "duration_bars",
                "session",
                "regime",
            ]
        ].sort_values("opened_at", ascending=False)

        st.dataframe(
            display,
            hide_index=True,
            **DATAFRAME_STRETCH,
            column_config={
                "id": "ID",
                "pair": "Pair",
                "direction": "Side",
                "family": "Family",
                "opened_at": st.column_config.DatetimeColumn("Opened", format="YYYY-MM-DD HH:mm"),
                "closed_at": st.column_config.DatetimeColumn("Closed", format="YYYY-MM-DD HH:mm"),
                "entry": st.column_config.NumberColumn("Entry", format="%.5f"),
                "exit": st.column_config.NumberColumn("Exit", format="%.5f"),
                "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
                "pnl_pips": st.column_config.NumberColumn("Pips", format="%.1f"),
                "rr": st.column_config.NumberColumn("RR", format="%.2f"),
                "duration_bars": st.column_config.NumberColumn("Bars", format="%d"),
                "session": "Session",
                "regime": "Regime",
            },
        )

        if filtered.empty:
            st.info("No trades match the current filters.")
        else:
            selected_id = st.selectbox(
                "Inspect trade",
                filtered["id"].tolist(),
                format_func=lambda value: f"Trade #{value}",
            )
            selected = trades[trades["id"] == selected_id].iloc[0]
            detail = st.columns(5)
            detail[0].metric("Pair", selected["pair"])
            detail[1].metric("Side", str(selected["direction"]).title())
            detail[2].metric("P&L", compact_money(float(selected["pnl"])))
            detail[3].metric("Pips", f"{selected['pnl_pips']:.1f}")
            detail[4].metric("RR", f"{selected['rr']:.2f}")
            st.caption(
                f"Opened {selected['opened_at']:%Y-%m-%d %H:%M} UTC · "
                f"closed {selected['closed_at']:%Y-%m-%d %H:%M} UTC · "
                f"{selected['duration_bars']} bars · {selected['family']} · "
                f"{selected['session'] or 'unknown session'} · {selected['regime'] or 'no regime'}"
            )

with tab_data:
    st.subheader("Loaded series")
    st.dataframe(
        summary_rows(snapshot),
        hide_index=True,
        **DATAFRAME_STRETCH,
        column_config={
            "bars": st.column_config.NumberColumn("Bars", format="%d"),
            "first_bar": st.column_config.DatetimeColumn("First bar", format="YYYY-MM-DD HH:mm"),
            "last_bar": st.column_config.DatetimeColumn("Last bar", format="YYYY-MM-DD HH:mm"),
        },
    )
    st.caption(
        "The dashboard does not download data and does not access the sealed 2018+ "
        "holdout. Use only data you are authorised to inspect."
    )
    with st.expander("Resolved configuration"):
        st.json(snapshot.config.model_dump(mode="json"))

st.divider()
st.caption(
    "FX-SMC Research Cockpit · local simulator · no live trading · "
    "the terminal research verdict remains CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED."
)
