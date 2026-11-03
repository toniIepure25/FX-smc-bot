# Research Dashboard

A local, read-only dashboard for inspecting a backtest: price candles, position
lifecycle, equity, drawdown, attribution and the trade ledger.

> **It is a simulator, not a trading terminal.** It does not connect to a broker,
> place orders or claim that the displayed result is a live edge. The research
> verdict remains
> [`CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`](STATUS.md).

---

## Launch

Install the optional UI dependencies and start Streamlit from the repository
root:

```powershell
python -m pip install -e ".[dashboard]"
streamlit run dashboard/app.py
```

Open the URL printed by Streamlit (usually `http://localhost:8501`).

The first page load runs a deterministic synthetic backtest so the dashboard is
usable without downloading data. Use the sidebar to switch to a local dataset.

## What the page shows

| Area | Content |
|---|---|
| Header | Research-only badge and the source/config provenance |
| KPI row | Net P&L, win rate, profit factor, max drawdown, Sharpe, expectancy |
| Overview | Equity curve, underwater/drawdown curve, P&L by setup family, session mix |
| Price & positions | Candlestick + volume, holding-period ribbons, entry triangles, exit ×, position paths |
| Trade ledger | Direction/family/outcome filters, sortable table, per-trade inspector |
| Data quality | Bars, first/last timestamp, volume/spread availability, resolved config |

Chart interactions: drag to pan, scroll to zoom, use the Plotly toolbar for
reset/export. Hovering an entry or exit shows family, P&L, pips and RR.

## Data sources

| Source | How it works |
|---|---|
| Synthetic demo | Deterministic M15 bars for EURUSD/GBPUSD/USDJPY; no network |
| Local dataset | Reads the configured execution timeframe from `--data-dir` (Parquet first, CSV fallback) |

The dashboard does **not** download data and must not be pointed at the sealed
2018+ holdout. Use `var/smoke/data` for the README smoke dataset or another
directory you are authorised to inspect.

## Configuration

The sidebar accepts a YAML config path, default `configs/base.yaml`. The config
controls pairs, timeframes, risk and execution assumptions. The resolved config
is visible in the **Data quality** tab.

## Architecture

```
dashboard/app.py                  Streamlit page, Plotly figures, filters
src/fx_smc_bot/dashboard/service.py
  synthetic_market_data()         deterministic demo bars
  load_market_data()              Parquet/CSV provider wrapper
  run_snapshot()                  one BacktestEngine run
  price_frame() / trades_frame()  display contracts
  equity_frame() / summary_rows()
```

The UI depends on the optional `dashboard` extra (`streamlit`, `plotly`). The
service module has no Streamlit/Plotly import and is covered by normal pytest
tests.

## Tests

```powershell
python -m pytest tests/test_dashboard -q
```

To exercise the actual Streamlit page without a browser:

```python
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("dashboard/app.py", default_timeout=180)
at.run()
assert not at.exception
```

## Limitations

- One in-process backtest at a time; no job queue or run database.
- The demo data is random and exists for wiring/visual checks only.
- The dashboard re-runs the engine on demand; it does not read old run artifacts.
- No authentication: run it locally, not on a public interface.
- Streamlit is an optional dependency and is not installed by the base package.
