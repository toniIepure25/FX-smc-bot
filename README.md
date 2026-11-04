# FX-smc-bot

**Research-grade FX / Smart Money Concepts (SMC) framework and research archive.**

> **Status: `CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`**
>
> The 2026 FX M1 structural alpha-discovery program is closed. Across the tested
> data (13 pairs, M1, 2010–2017) there is **no validated, actionable edge** and no
> candidate that survives the program's pre-holdout gates. The holdout (2018+) was
> never inspected. See [docs/STATUS.md](docs/STATUS.md) for the authoritative
> status and [the terminal postmortem](docs/research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md)
> for the evidence.
>
> This repository is a research and engineering artifact. It is **not** a trading
> signal service, **not** investment advice, and **not** validated for live money.

---

## What this is

A modular Python framework for formalising discretionary SMC/ICT ideas into
testable rules, with the infrastructure needed to reject weak ideas honestly:

- market-structure primitives (swings, BOS/CHoCH, FVG, order blocks, liquidity);
- config-driven candidate generation and systematic ablation;
- portfolio-aware risk sizing and constraints;
- bid/ask-aware execution simulation with cost stress;
- event-driven backtesting, regime tagging and attribution;
- walk-forward, multiplicity-aware statistics and frozen research protocols;
- paper/forward trading plumbing with an append-only audit journal.

The research result is negative. The framework, the test suite, the data
plumbing and the research protocol are the reusable output.

## Status at a glance

| Area | State |
|---|---|
| Alpha research on current FX data | **Closed — no survivor** (`CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`) |
| Holdout 2018+ | **Sealed and unread** |
| Core framework code | Reusable; 12 packages under `src/fx_smc_bot/` |
| Test suite | 1,900+ tests; pytest collection is green |
| Lint | Ruff clean across all non-research source; frozen `research` excluded |
| CI | GitHub Actions: lint, `doctor --strict` and full pytest on Python 3.10 / 3.12 |
| Developer CLI | `fx-smc info`, `doctor`, `backtest`, `dashboard` |
| Forward paper service | Legacy Docker service; requires credentials; **not validated** |
| Research dashboard | Local Streamlit cockpit for price, positions and performance |
| Recommended action | Do not deploy. Read [docs/STATUS.md](docs/STATUS.md) before starting new work. |

## Quick start

**Prerequisites:** Python 3.10+ (3.12/3.13 recommended), `pip` (or `uv`), and a
shell. Commands below are shown for PowerShell; on Unix activate with
`source .venv/bin/activate`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,dashboard]"

# Validate the checkout, then run a self-contained smoke backtest.
python -m fx_smc_bot info
python -m fx_smc_bot doctor --config configs/base.yaml
python -m fx_smc_bot backtest --synthetic --bars 500
```

`fx-smc` is installed as the console script; if it is not on `PATH`, the
`python -m fx_smc_bot` form above is equivalent.

Run the full test suite (~6 minutes on a laptop):

```powershell
python -m pytest -q
```

To exercise the original file-based smoke path:

```powershell
# 1. Generate one month of synthetic M1 data and resample it.
python scripts/download_data.py --mode generate --output-dir var/smoke/data --start 2024-01-01 --end 2024-02-01

# 2. Run a small end-to-end backtest and write artifacts.
python scripts/run_backtest.py --data-dir var/smoke/data --output-dir var/smoke/results --label smoke
```

The synthetic path validates wiring, not profitability. It must never be used as
evidence of an edge.

For the pinned environment, `requirements.lock` is a `uv pip compile` lock file:

```powershell
uv pip install --require-hashes -r requirements.lock
```

## Research dashboard

A local Streamlit cockpit shows price candles, holding-period ribbons, entry/exit
markers, equity and drawdown, monthly/attribution diagnostics and a filterable
trade ledger. It also exports the filtered ledger (CSV) and a run summary (JSON):

```powershell
python -m pip install -e ".[dashboard]"
python -m fx_smc_bot dashboard
```

The first load uses deterministic synthetic data; switch to a local dataset in
the sidebar. It is read-only, performs no order submission, and never connects to
a broker. See [docs/DASHBOARD.md](docs/DASHBOARD.md).

## Developer CLI

The `fx-smc` command wraps the repeatable developer workflow without touching the
frozen research-gate scripts:

| Command | Purpose |
|---|---|
| `fx-smc info` | Version, canonical verdict, holdout state and command list |
| `fx-smc doctor` | Validate Python, repository layout, config, data and dashboard extras |
| `fx-smc backtest` | One in-process backtest on synthetic data or a local dataset |
| `fx-smc dashboard` | Launch the local cockpit |

`doctor --strict --json` is suitable for CI, and `info --json` for release checks.
See [docs/CLI.md](docs/CLI.md) for flags, exit codes and scope.

## Repository map

| Path | Purpose |
|---|---|
| `src/fx_smc_bot/` | Library: data, structure, alpha, risk, portfolio, execution, backtesting, ml, dashboard, research, live, utils |
| `dashboard/` | Local Streamlit research cockpit — see [docs/DASHBOARD.md](docs/DASHBOARD.md) |
| `.streamlit/` | Project-local dark theme for the dashboard; no secrets |
| `scripts/` | CLI entry points and frozen research-gate runners — see [scripts/README.md](scripts/README.md) |
| `configs/` | YAML configuration for framework, risk profiles and research programs |
| `tests/` | Unit, integration and protocol-conformance tests |
| `docs/` | Guides, status and the research archive — start at [docs/README.md](docs/README.md) |
| `.github/workflows/` | CI: lint, checkout validation and the full test suite |
| `Makefile`, `tasks.ps1` | Local task wrappers for install, lint, test, doctor and smoke |
| `results/` | Committed research evidence and decision artifacts — see [results/README.md](results/README.md) |
| `data/` | Local datasets (mostly ignored) and small tracked samples — see [data/README.md](data/README.md) |
| `deploy/` | VPS, Docker and operations runbooks |
| `tools/` | Independent Dukascopy `.bi5` parsers and Node acquisition helpers |
| `paper_validation_program/` | Legacy paper-trading programme design (not executed) |
| `forensics/` | Preserved copies of code used in forensic audits |
| `var/` | Local scratch, caches and quarantine (gitignored) — see [var/README.md](var/README.md) |

## Research status

The programme tested broad signal classes (momentum, mean reversion, volatility,
session/calendar, ML) and then "true structural" models (Kalman, GMM,
cross-sectional ranking, PCA residuals, GRU/TCN, cost-aware stopping) on M1 FX
data. Every candidate was evaluated against pre-registered gates, multiplicity
corrections and execution costs.

| Version | Scope | Candidates | Verdict |
|---|---|---:|---|
| V1–V3 | Broad signal search | 1,388 | `V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` |
| V4 | CME FX futures L2 (Databento) | 0 | Never executed — no paid-data acquisition |
| V5 | First "structural models" attempt | 160 | `V5_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` — invalid due to fidelity failures |
| V5R | True structural models | 88 | `V5R_TRUE_STRUCTURAL_MODELS_NO_PRE_HOLDOUT_EDGE` — invalid due to protocol deviations |
| V5R corrected | Protocol-conformance rerun | 88 | `V5R_CORRECTED_NO_PRE_HOLDOUT_EDGE` — scientific null |

There are **zero scientific survivors**. The one isolated positive (R7: 5 trades,
+675 bps gross, Sharpe 0.002) is a small-sample artifact, not alpha.

Program rules that remain in force:

- no V6 on the same FX data;
- no parameter sweeps, signal inversions or post-hoc threshold tuning;
- no candidate rescues and no 2018+ inspection;
- any new programme needs a new data class or market **and** a new pre-registered
  protocol.

## Reusable infrastructure

| Component | Why it is useful beyond this programme |
|---|---|
| `data/` | Tick/M1 ingestion, Dukascopy `.bi5`, bid/ask resampling, manifests, holdout firewalls |
| `execution/` | Bid/ask-aware fills, spread/slippage stress, cost realism |
| `research/` | Frozen configs, walk-forward, multiplicity corrections (WRC/SPA/Romano-Wolf/Holm/BH), PBO/CSCV |
| `research/v3/` | Acquisition certification, data gates, survivorship and boundary checks |
| `research/v5r/` | Kalman, GMM, cross-sectional, PCA and sequence-model reference implementations |
| `live/` | Paper broker, JSONL journal, resumable state, health checks and alerts |
| `tests/` | Protocol-conformance and golden-execution tests that encode expensive lessons |

## Forward paper service (legacy)

The Docker stack in `docker-compose.yml` runs a forward paper-trading service for
the legacy `bos_only_usdjpy` programme:

```powershell
Copy-Item .env.example .env
# Fill in broker/Telegram credentials, then review deploy/docs/ before starting.
docker compose up --build forward-paper
```

This service was built for an earlier programme and is **not** evidence of a
current edge. Do not point it at a live account.

## Documentation

| Document | Content |
|---|---|
| [docs/STATUS.md](docs/STATUS.md) | **Canonical current status**, lineage and prohibited actions |
| [docs/README.md](docs/README.md) | Full documentation index |
| [docs/CLI.md](docs/CLI.md) | Developer CLI and local quality tasks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Framework architecture and module map |
| [docs/DATA_GUIDE.md](docs/DATA_GUIDE.md) | Data sources, schema and ingestion |
| [docs/RISK_MODEL.md](docs/RISK_MODEL.md) | Sizing, constraints and exposure budgeting |
| [docs/RESEARCH_METHODOLOGY.md](docs/RESEARCH_METHODOLOGY.md) | Ablation, walk-forward and robustness methodology |
| [docs/VALIDATION_GUIDE.md](docs/VALIDATION_GUIDE.md) | OOS discipline and go/no-go criteria |
| [docs/PAPER_TRADING_GUIDE.md](docs/PAPER_TRADING_GUIDE.md) | Paper broker and operational controls |
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | Research dashboard: price, positions, filters |
| [docs/EXPERIMENT_PLAYBOOK.md](docs/EXPERIMENT_PLAYBOOK.md) | Step-by-step experiment recipes |
| [docs/research/README.md](docs/research/README.md) | Research archive index and program verdicts |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Prioritised engineering and research options |

## Testing and quality

```powershell
# Full suite
python -m pytest -q

# Fast core subset
python -m pytest tests/test_domain.py tests/test_cli.py tests/test_structure tests/test_backtesting tests/test_risk tests/test_alpha tests/test_dashboard -q

# Lint all non-research source, plus the dashboard/CLI tests
python -m ruff check src/fx_smc_bot --exclude src/fx_smc_bot/research
python -m ruff check tests/test_cli.py tests/test_dashboard tests/test_backtesting/test_runner.py

# Validate the checkout the same way CI does
python -m fx_smc_bot doctor --config configs/base.yaml --strict
```

The suite includes frozen protocol tests, data-boundary tests and golden
execution cases. Some tests are intentionally strict about paths and must run
from the repository root. The `research` package is excluded from the style gate
because it contains immutable protocol implementations; do not mass-rewrite it.

## Roadmap

The programme is closed scientifically, but the repository can still be improved
as an engineering asset. See [docs/ROADMAP.md](docs/ROADMAP.md) for the detailed
P1–P3 plan: lint/type hygiene, CI, packaging, reproducibility, a possible new
data class, and the decision to either archive the project or start a new,
pre-registered research programme.

## License

No license file is present. Add an explicit license before distributing the code
or accepting external contributions. Until then, treat it as proprietary.
