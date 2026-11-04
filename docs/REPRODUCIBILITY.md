# Reproducibility

This repository mixes two kinds of work with different reproducibility rules:

| Area | Rule |
|---|---|
| Framework, CLI and dashboard | Reproducible from a clean checkout with the commands below. |
| Research evidence (`results/`, frozen gate protocols) | Immutable evidence. Do not regenerate, overwrite or "fix" it to make a check pass. |
| Holdout (`2018+`) | Sealed. No command in this guide reads it. |

The canonical research status is [STATUS.md](STATUS.md). The synthetic smoke
path is deterministic; research re-runs require the original data and frozen
protocol and may legitimately produce different outputs from the archived
evidence when data or dependencies change.

## 1. Clean environment

Use 64-bit Python **3.10–3.13**; CI covers 3.10 and 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,dashboard]"
```

`requirements.lock` is the historical dependency record. It is intentionally not
used as the primary install path because the project extras are the supported
interface. To audit or recreate the historical environment:

```powershell
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

Record the interpreter and package versions in every run report:

```powershell
python --version
python -m pip freeze > var/repro/pip-freeze.txt
python -m fx_smc_bot doctor --config configs/base.yaml --strict
```

## 2. Deterministic synthetic smoke run

The synthetic provider uses a fixed seed and does not touch `data/` or the
holdout. It exercises signal generation, risk, execution, the ledger and metrics.

```powershell
$run = "var/repro/synthetic-$(Get-Date -Format yyyyMMdd-HHmmss)"
python -m fx_smc_bot backtest `
  --synthetic --bars 500 --seed 42 `
  --config configs/base.yaml `
  --output-dir $run --label repro-synthetic

Get-ChildItem $run
Get-FileHash (Join-Path $run "metrics.json"), (Join-Path $run "config.json") -Algorithm SHA256
```

Expected artifacts include the resolved `config.json`, a reproducibility
`manifest.json` (source, pairs, bars, seed, Python version), `metrics.json`,
`trades.csv`, `equity_curve.csv`, `attribution.json` and the text report.
`config.json` is the authoritative record of the config actually used; do not
substitute the input YAML. `manifest.json` records the synthetic seed and bar
count so a run can be repeated exactly.

A second run with the same interpreter, dependencies and seed should produce the
same synthetic trades and metrics. Treat a mismatch as a regression until proven
otherwise, and attach both `pip-freeze.txt` files when comparing.

## 3. File-based local backtest

Use this path when validating the CSV/Parquet loaders. It is separate from the
synthetic demo and does not certify research data.

```powershell
python scripts/download_data.py --mode generate `
  --output-dir var/repro/data `
  --start 2024-01-01 --end 2024-02-01

python -m fx_smc_bot data --data-dir var/repro/data --strict

python -m fx_smc_bot backtest `
  --data-dir var/repro/data `
  --config configs/base.yaml `
  --output-dir var/repro/file-backed --label repro-file
```

The `data --strict` step checks configured-pair coverage, bar counts, duplicate
timestamps, missing bars, stale sequences and the quality score before the
backtest runs. Use `--json` to archive the audit beside the run artifact. If the
loader reports missing pairs or malformed bars, stop and inspect the data. Do not
"fix" it by editing the research evidence.

## 4. Tests and CI parity

```powershell
python -m ruff check src/fx_smc_bot --exclude src/fx_smc_bot/research
python -m fx_smc_bot doctor --config configs/base.yaml --strict
python -m pytest -q --cov=fx_smc_bot --cov-report=term-missing
```

The full suite includes frozen protocol tests. CI runs the same commands on
Python 3.10 and 3.12 and uploads `coverage.xml`; a local pass on one interpreter
is not proof that the other matrix entry passes. CI also builds the sdist/wheel,
checks the metadata with `twine`, installs the wheel, and builds the Docker image
to verify the unprivileged user and a synthetic backtest inside the container.

## 5. Research re-runs

Research programmes are frozen and evidence-bearing. Do not run a gate or
campaign merely to reproduce a headline number without first reading the
protocol and [STATUS.md](STATUS.md). In particular:

- the 2018+ holdout is sealed and must remain unread;
- gate results and configs are evidence, not tuning inputs;
- a changed result requires a new protocol/version, not an overwrite.

Use the program-specific protocol under `docs/research/` and the registry under
`results/` for the exact frozen command and artifact manifest.

## 6. Checklist for a reportable run

- [ ] Clean environment and `pip freeze` saved.
- [ ] `doctor --strict` passes.
- [ ] Local datasets pass `fx-smc data --strict`.
- [ ] Input config copied into the run directory as resolved `config.json`.
- [ ] Seed, bar count, data directory and command recorded.
- [ ] Output artifacts hashed.
- [ ] Holdout untouched.
- [ ] Research results not modified to make a check green.
