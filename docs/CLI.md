# Developer CLI

The `fx-smc` command is the supported developer entry point for the reusable
framework. It does **not** replace the frozen research-gate scripts in
`scripts/run_gate_*`; those remain the auditable protocol runners.

After an editable install:

```powershell
python -m pip install -e ".[dev,dashboard]"
fx-smc info
```

If the console script is not on `PATH` (common with per-user Python installs),
use the module form, which is equivalent:

```powershell
python -m fx_smc_bot info
```

## Commands

| Command | Purpose |
|---|---|
| `fx-smc info` | Print version, research status, holdout state and available commands. |
| `fx-smc doctor` | Validate Python, repository layout, config, optional data directory and dashboard extras. |
| `fx-smc data` | Audit coverage, bars and quality diagnostics for a market-data directory. |
| `fx-smc backtest` | Run one in-process backtest on synthetic data or a local dataset. |
| `fx-smc dashboard` | Launch the local Streamlit cockpit. |

### `info`

```powershell
fx-smc info
fx-smc info --json
```

The JSON form is suitable for scripts and release checks. It reports the canonical
verdict (`CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`) and that the 2018+ holdout is
sealed and unread.

### `doctor`

```powershell
fx-smc doctor --config configs/base.yaml
fx-smc doctor --config configs/base.yaml --data-dir var/smoke/data
fx-smc doctor --config configs/base.yaml --strict --json
```

Checks are reported as `ok`, `warn`, `skip` or `fail`:

- Python must be 3.10 or newer;
- the working directory must look like the repository root (warning otherwise);
- the YAML config must load;
- an optional data directory is loaded through the normal provider path, then
  checked for configured-pair coverage and data-quality warnings;
- `streamlit` and `plotly` are reported as warnings when missing.

Exit code is `0` unless a check fails. `--strict` turns warnings into a non-zero
exit, which is what CI uses. `--json` emits machine-readable output.

### `data`

```powershell
fx-smc data --data-dir var/smoke/data
fx-smc data --data-dir var/smoke/data --config configs/base.yaml --json
fx-smc data --data-dir var/smoke/data --strict
```

The audit loads the configured execution timeframes and runs the same
`data.diagnostics` checks used elsewhere in the framework. It reports, per pair:

- timeframe and bar count;
- quality score;
- missing-bar percentage;
- duplicate timestamps, zero-range bars and stale-price sequences;
- diagnostic issue strings.

Exit codes:

| Situation | Exit |
|---|---|
| All configured pairs loaded and no quality warnings | `0` |
| A configured pair is missing or a series has quality warnings | `0` |
| Same warning, with `--strict` | `1` |
| Directory missing, no usable data, or invalid config | `1` |

The audit is read-only and never touches the sealed holdout. It is a preflight
for local runs, not a research verdict. See
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the full preflight sequence.

### `backtest`

Synthetic smoke run, no market data required:

```powershell
fx-smc backtest --synthetic --bars 500
```

Local data run with artifacts:

```powershell
fx-smc backtest --data-dir var/smoke/data --output-dir var/smoke/results --label smoke
```

| Option | Meaning |
|---|---|
| `--config PATH` | YAML config; defaults to `configs/base.yaml` when present, otherwise the library defaults. |
| `--data-dir PATH` | Directory understood by the data provider loader. |
| `--synthetic` | Force deterministic synthetic data (mutually exclusive with `--data-dir`). |
| `--bars N` | Synthetic bars per pair (default 500). |
| `--seed N` | Synthetic RNG seed (default 42). |
| `--output-dir PATH` | Write config, manifest, metrics, trades, equity curve, attribution and report artifacts. |
| `--label TEXT` | Prefix for the timestamped artifact directory. |

The command calls the same `fx_smc_bot.backtesting.runner` used by the dashboard.
It is a wiring/smoke tool, not a research verdict and not evidence of an edge.

### `dashboard`

```powershell
fx-smc dashboard
fx-smc dashboard --port 8501 --host 127.0.0.1
```

The dashboard is read-only, uses no broker credentials and performs no order
submission or persistence. The first load uses deterministic synthetic data;
switch to a local dataset in the sidebar. See [DASHBOARD.md](DASHBOARD.md).

## Local quality tasks

Use the CLI directly, or the small task wrappers:

```powershell
.\tasks.ps1 doctor
.\tasks.ps1 lint
.\tasks.ps1 test-fast
.\tasks.ps1 coverage
.\tasks.ps1 smoke
```

On Unix-like shells with `make`:

```bash
make doctor
make lint
make test-fast
make coverage
make smoke
```

The lint target covers all source packages except the frozen `research` tree,
plus the dashboard page and the touched CLI/data/dashboard tests. `research` is
intentionally excluded because it contains immutable protocol implementations;
do not mass-rewrite it for style.

## Scope and safety

- No command reads or unseals the 2018+ holdout.
- No command changes research verdicts, configs, strategies or evidence.
- The CLI is a developer convenience, not a production trading system.
- The dashboard and backtest use the same in-process simulator; neither connects
  to a broker.
