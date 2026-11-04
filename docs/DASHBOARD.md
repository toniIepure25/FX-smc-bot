# Research Dashboard

A local, read-only dashboard for inspecting a backtest: price candles, position
lifecycle, equity, drawdown, attribution and the trade ledger.

> **It is a simulator, not a trading terminal.** It does not connect to a broker,
> place orders or claim that the displayed result is a live edge. The research
> verdict remains
> [`CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`](STATUS.md).

---

## Launch

Install the optional UI dependencies and launch the cockpit from the repository
root:

```powershell
python -m pip install -e ".[dashboard]"
python -m fx_smc_bot dashboard
```

The CLI starts Streamlit on `http://127.0.0.1:8501` by default. The direct
equivalent, if you prefer it, is:

```powershell
python -m streamlit run dashboard/app.py
```

Open the URL printed by Streamlit.

The first page load runs a deterministic synthetic backtest so the dashboard is
usable without downloading data. Use the sidebar to switch to a local dataset.

## What the page shows

| Area | Content |
|---|---|
| Header | Research-only badge and source/period/config provenance |
| KPI row | Net P&L, win rate, profit factor, max drawdown, Sharpe, expectancy |
| Secondary row | Average winner/loser, planned RR, expectancy in pips |
| Overview | Equity and underwater curves, monthly realised P&L, trade P&L distribution, advanced metrics |
| Price & positions | Candlestick + volume, holding ribbons, entries/exits, position paths, single-trade zoom |
| Attribution | P&L by setup family, pair summary, session summary |
| Trade ledger | Direction/family/outcome filters, sortable table, per-trade inspector, CSV export |
| Data & config | Per-pair quality diagnostics, bars and timestamp range, volume/spread availability, JSON and CSV export, resolved config |

Chart interactions: drag to pan, scroll to zoom, use the Plotly toolbar for
reset/export. Hovering an entry or exit shows family, P&L, pips and RR. The
**Trade focus** selector zooms to the bars around one trade and draws entry/exit
reference levels.

Every run also exposes two read-only downloads: the filtered ledger as CSV and a
run summary as JSON (source, config hash, period, metrics). Exports are generated
in memory; nothing is written back to the repository.

The page uses the project theme in `.streamlit/config.toml` (dark, compact) when
Streamlit is started from the repository root.

## Caching and refresh

The expensive part of the page is one in-process backtest. It is cached with
`st.cache_resource` under this key:

- synthetic/local source;
- bar count;
- data directory;
- config path;
- config file modification time;
- a session reload generation.

That means switching tabs or filtering the ledger does not rerun the engine.
Editing the YAML file invalidates the cache automatically. If the data files
change while the config path stays the same, use **Reload data / config** in the
sidebar; it increments the generation and forces a fresh run. The cache is
in-memory and disappears when Streamlit restarts. It is not a run database.

## Data quality

The **Data & config** tab shows a diagnostics table for every loaded pair:
quality score, missing-bar percentage, duplicate timestamps, zero-range bars,
stale-price sequences and issue strings. A warning is shown when any pair falls
below the project threshold. These are data-hygiene checks, not evidence that a
strategy is valid. For a CLI preflight that uses the same diagnostics, see
[CLI.md](CLI.md#data).

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
is visible in the **Data & config** tab.

## Architecture

```
dashboard/app.py                    Streamlit layout, controls, filters, exports
src/fx_smc_bot/dashboard/
  service.py                        snapshot orchestration, display frames
  charts.py                         Plotly figure builders (no Streamlit import)
  formatting.py                     compact money/percentage helpers
src/fx_smc_bot/backtesting/runner.py  shared synthetic/load/run path used by CLI + dashboard
.streamlit/config.toml              local dark theme; no secrets
```

The UI depends on the optional `dashboard` extra (`streamlit`, `plotly`). The
service module has no Streamlit/Plotly import and is covered by normal pytest
tests; the chart builders are smoke-tested when Plotly is installed.

## Tests

```powershell
python -m pytest tests/test_dashboard -q
```

`tests/test_dashboard/test_service.py` checks the frame contracts and
reconciles monthly, pair and session P&L against the ledger, including the
data-quality frame.
`tests/test_dashboard/test_charts.py` smoke-tests the Plotly builders and skips
cleanly when the optional extra is absent.
`tests/test_dashboard/test_app.py` drives the real Streamlit page with
`AppTest` and asserts five tabs, five Plotly charts, the data-quality section and
no exceptions.

To exercise the page manually without a browser:

```python
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("dashboard/app.py", default_timeout=180)
at.run()
assert not at.exception
```

## Limitations

- One in-process backtest at a time; no job queue or run database.
- The demo data is random and exists for wiring/visual checks only.
- The dashboard caches the current run; it does not read old run artifacts.
- No authentication: run it locally, not on a public interface.
- Streamlit is an optional dependency and is not installed by the base package.
