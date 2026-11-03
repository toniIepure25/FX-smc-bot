"""FX-SMC Research Cockpit — a local Streamlit dashboard.

Run with:
    streamlit run dashboard/app.py

The page is a read-only research UI. It never places orders and does not claim
that any backtest result is a live edge.
"""

from __future__ import annotations

import html
import inspect
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from fx_smc_bot.dashboard.charts import (
        make_attribution_figure,
        make_equity_figure,
        make_monthly_pnl_figure,
        make_pnl_distribution_figure,
        make_price_figure,
        make_trade_focus_figure,
    )
except ImportError:  # pragma: no cover - only hit without the dashboard extra
    st.error('Dashboard dependencies are missing. Run: pip install -e ".[dashboard]"')
    st.stop()

from fx_smc_bot.dashboard.formatting import compact_money, compact_pct, finite
from fx_smc_bot.dashboard.service import (
    DashboardSnapshot,
    load_dashboard_config,
    load_market_data,
    pair_summary_frame,
    run_snapshot,
    session_summary_frame,
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

st.markdown(
    """
    <style>
    .stApp { background: #070c14; }
    .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
    [data-testid="stHeader"] { background: rgba(7,12,20,0.82); }
    [data-testid="stSidebar"] {
        background: #0a101a;
        border-right: 1px solid rgba(148,163,184,0.12);
    }
    [data-testid="stMetric"] {
        background: linear-gradient(180deg, #101b2d 0%, #0b1220 100%);
        border: 1px solid rgba(148,163,184,0.18);
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }
    [data-testid="stMetricLabel"] { color: #94a3b8; }
    [data-testid="stMetricValue"] { color: #f8fafc; }
    .hero {
        display: flex; align-items: flex-start; justify-content: space-between;
        gap: 1rem; padding: 1.2rem 1.4rem; margin-bottom: 1rem;
        border: 1px solid rgba(56,189,248,0.22);
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
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148,163,184,0.16); border-radius: 12px;
    }
    div[data-testid="stTabs"] button { color: #cbd5e1; }
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


def _format_date(value: object) -> str:
    if value is None:
        return "—"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _run_summary(snapshot: DashboardSnapshot) -> dict[str, object]:
    return {
        "source": snapshot.source_label,
        "config_hash": snapshot.result.config_hash,
        "start_date": _format_date(snapshot.result.start_date),
        "end_date": _format_date(snapshot.result.end_date),
        "initial_capital": snapshot.result.initial_capital,
        "final_equity": snapshot.result.final_equity,
        "pairs": [pair.value for pair in snapshot.data],
        "timeframes": sorted({series.timeframe.value for series in snapshot.data.values()}),
        "metrics": asdict(snapshot.metrics),
    }


def _prepare_pair_view(trades: pd.DataFrame) -> pd.DataFrame:
    view = pair_summary_frame(trades)
    if not view.empty:
        view["win_rate"] = view["win_rate"] * 100.0
    return view


def _prepare_session_view(trades: pd.DataFrame) -> pd.DataFrame:
    view = session_summary_frame(trades)
    if not view.empty:
        view["win_rate"] = view["win_rate"] * 100.0
    return view


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
        "One in-process backtest. No broker connection, no order routing, no persistence."
    )
    st.caption("Research data only. Do not point this at the sealed 2018+ holdout.")

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

if snapshot.source_label.startswith("Synthetic"):
    st.warning(
        "Synthetic random-walk demo: use it to review the workflow, not to infer an edge. "
        "Switch to a local dataset for research evidence."
    )
else:
    st.info(
        "Local research dataset. Verify provenance, cost assumptions and the holdout "
        "boundary before treating any result as evidence."
    )

st.markdown(
    f'<span class="chip">Source: {html.escape(snapshot.source_label)}</span>'
    f'<span class="chip">Period: {_format_date(snapshot.result.start_date)} → '
    f"{_format_date(snapshot.result.end_date)}</span>"
    f'<span class="chip">Pairs: {len(snapshot.data)}</span>'
    f'<span class="chip">Initial capital: {compact_money(initial)}</span>'
    f'<span class="chip">Closed trades: {len(trades)}</span>'
    f'<span class="chip">Config: {snapshot.result.config_hash[:8]}</span>',
    unsafe_allow_html=True,
)

kpi = st.columns(6)
kpi[0].metric("Net P&L", compact_money(metrics.total_pnl), f"{return_pct:+.2f}%")
kpi[1].metric("Win rate", compact_pct(metrics.win_rate), f"{metrics.total_trades} trades")
kpi[2].metric("Profit factor", finite(metrics.profit_factor), "gross wins / losses")
kpi[3].metric(
    "Max drawdown",
    f"-{compact_pct(metrics.max_drawdown_pct, 2)}",
    f"-{compact_money(abs(metrics.max_drawdown))}",
)
kpi[4].metric("Sharpe", finite(metrics.sharpe_ratio), "annualised")
kpi[5].metric("Expectancy", compact_money(metrics.expectancy), "per trade")

secondary = st.columns(4)
secondary[0].metric("Avg winner", compact_money(metrics.avg_winner))
secondary[1].metric("Avg loser", compact_money(metrics.avg_loser))
secondary[2].metric("Avg planned RR", finite(metrics.avg_rr_ratio))
secondary[3].metric("Expectancy (pips)", f"{metrics.expectancy_pips:,.1f}")

tab_overview, tab_price, tab_attribution, tab_ledger, tab_data = st.tabs(
    ["Overview", "Price & positions", "Attribution", "Trade ledger", "Data & config"]
)

with tab_overview:
    equity_fig = make_equity_figure(snapshot)
    if equity_fig is not None:
        st.plotly_chart(equity_fig, **PLOTLY_STRETCH, config={"displayModeBar": False})
    else:
        st.info("The run produced no equity curve (no closed trades).")

    lower_left, lower_right = st.columns(2)
    with lower_left:
        st.subheader("Monthly realised P&L")
        monthly = make_monthly_pnl_figure(trades)
        if monthly is not None:
            st.plotly_chart(monthly, **PLOTLY_STRETCH, config={"displayModeBar": False})
        else:
            st.caption("No closed trades.")
    with lower_right:
        st.subheader("Trade P&L distribution")
        distribution = make_pnl_distribution_figure(trades)
        if distribution is not None:
            st.plotly_chart(distribution, **PLOTLY_STRETCH, config={"displayModeBar": False})
        else:
            st.caption("No closed trades.")

    with st.expander("Advanced performance detail"):
        detail = pd.DataFrame(
            [
                ("Total return", compact_pct(metrics.total_pnl / initial if initial else 0.0, 2)),
                ("Annualised return", compact_pct(metrics.annualized_return, 2)),
                ("Sortino", finite(metrics.sortino_ratio)),
                ("Calmar", finite(metrics.calmar_ratio)),
                ("Avg P&L", compact_money(metrics.avg_pnl)),
                ("Avg RR", finite(metrics.avg_rr_ratio)),
                ("Expectancy (pips)", f"{metrics.expectancy_pips:,.2f}"),
                ("Trading days", f"{metrics.total_days:,.1f}"),
            ],
            columns=["Metric", "Value"],
        )
        st.dataframe(detail, hide_index=True, **DATAFRAME_STRETCH)

with tab_price:
    pair_options = sorted(snapshot.data, key=lambda pair: pair.value)
    selected_pair = st.selectbox(
        "Pair",
        pair_options,
        format_func=lambda pair: pair.value,
        index=0,
    )
    pair_trades = trades[trades["pair"] == selected_pair.value].sort_values("opened_at")
    st.caption(
        f"{len(pair_trades)} closed trades on {selected_pair.value}. "
        "Green/red blocks mark holding periods; triangles mark entries and × marks exits."
    )
    st.plotly_chart(
        make_price_figure(snapshot, selected_pair),
        **PLOTLY_STRETCH,
        config={"displayModeBar": True, "scrollZoom": True},
    )

    if not pair_trades.empty:
        st.subheader("Trade focus")
        focus_id = st.selectbox(
            "Zoom to trade",
            pair_trades["id"].tolist(),
            format_func=lambda value: f"Trade #{value}",
        )
        focus_trade = pair_trades[pair_trades["id"] == focus_id].iloc[0]
        st.plotly_chart(
            make_trade_focus_figure(snapshot, selected_pair, focus_trade),
            **PLOTLY_STRETCH,
            config={"displayModeBar": False},
        )

with tab_attribution:
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("P&L by setup family")
        attribution = make_attribution_figure(trades)
        if attribution is not None:
            st.plotly_chart(attribution, **PLOTLY_STRETCH, config={"displayModeBar": False})
        else:
            st.caption("No closed trades to attribute.")
    with right:
        st.subheader("Pair summary")
        st.dataframe(
            _prepare_pair_view(trades),
            hide_index=True,
            **DATAFRAME_STRETCH,
            column_config={
                "pair": "Pair",
                "trades": st.column_config.NumberColumn("Trades", format="%d"),
                "win_rate": st.column_config.NumberColumn("Win rate", format="%.1f%%"),
                "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
                "avg_pnl": st.column_config.NumberColumn("Avg P&L", format="$%.0f"),
                "pips": st.column_config.NumberColumn("Pips", format="%.1f"),
            },
        )

    st.subheader("Session mix")
    st.dataframe(
        _prepare_session_view(trades),
        hide_index=True,
        **DATAFRAME_STRETCH,
        column_config={
            "session": "Session",
            "trades": st.column_config.NumberColumn("Trades", format="%d"),
            "win_rate": st.column_config.NumberColumn("Win rate", format="%.1f%%"),
            "pnl": st.column_config.NumberColumn("P&L", format="$%.0f"),
        },
    )

with tab_ledger:
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

        st.caption(
            f"{len(filtered)} of {len(trades)} trades · "
            f"net P&L {compact_money(float(filtered['pnl'].sum()))}"
        )
        st.download_button(
            "Download filtered ledger (CSV)",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name="fx_smc_filtered_trades.csv",
            mime="text/csv",
            **BUTTON_STRETCH,
        )

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
                f"{selected['session'] or 'unknown session'} · "
                f"{selected['regime'] or 'no regime'}"
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

    rows = summary_rows(snapshot)
    missing_spread = [row["pair"] for row in rows if not row["has_spread"]]
    missing_volume = [row["pair"] for row in rows if not row["has_volume"]]
    if missing_spread:
        st.warning(
            "No spread column for: " + ", ".join(map(str, missing_spread)) +
            ". Cost realism may be incomplete."
        )
    if missing_volume:
        st.caption("No volume column for: " + ", ".join(map(str, missing_volume)) + ".")

    st.caption(
        "The dashboard does not download data and does not access the sealed 2018+ "
        "holdout. Use only data you are authorised to inspect."
    )

    download_cols = st.columns(2)
    with download_cols[0]:
        st.download_button(
            "Download run summary (JSON)",
            data=json.dumps(_run_summary(snapshot), indent=2, default=str).encode("utf-8"),
            file_name="fx_smc_run_summary.json",
            mime="application/json",
            **BUTTON_STRETCH,
        )
    with download_cols[1]:
        st.download_button(
            "Download full ledger (CSV)",
            data=trades.to_csv(index=False).encode("utf-8"),
            file_name="fx_smc_all_trades.csv",
            mime="text/csv",
            **BUTTON_STRETCH,
        )

    with st.expander("Resolved configuration"):
        st.json(snapshot.config.model_dump(mode="json"))

st.divider()
st.caption(
    "FX-SMC Research Cockpit · local simulator · no live trading · "
    "the terminal research verdict remains CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED."
)
