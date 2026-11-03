# Scripts

Command-line entry points and frozen research-gate runners. Run scripts from the
repository root; most resolve data/config paths relative to the current working
directory.

> The research programme is closed. See [../docs/STATUS.md](../docs/STATUS.md)
> before running anything that touches the 2018+ data or the research gates.

---

## Canonical entry points

These are the scripts intended for normal use.

### Data

| Script | Purpose |
|---|---|
| `download_data.py` | Generate synthetic data, import CSVs, or inspect a dataset |
| `ingest_data.py` | Import/normalise real data and build processed Parquet |
| `acquire_fx_history.py` | Acquire FX history through the configured provider |
| `acquire_dukascopy_node_history.py` | Acquire Dukascopy history via the Node helper |
| `run_persistent_acquisition.py` | Resumable acquisition loop with status/retry |
| `acquisition_status.py` | Inspect acquisition state |
| `inspect_data.py` | Quick dataset inspection |
| `generate_validation_data.py` | Build validation datasets from a source |

### Backtest, campaigns and research

| Script | Purpose |
|---|---|
| `run_backtest.py` | Single end-to-end backtest |
| `run_campaign.py` | Ablation, baseline-vs-SMC, walk-forward, parameter sweep |
| `run_research.py` | Research campaign runner |
| `run_validation.py` | Validation campaign |
| `run_alpha_discovery.py` | Broad alpha-discovery runner (historical) |
| `run_v2_discovery.py` | V2 discovery runner (historical) |
| `run_intraday_smc_campaign.py` | Intraday SMC campaign |
| `run_multi_pair_research.py` | Multi-pair research phases |
| `run_pair_specific_research.py` | Pair-specific research themes |
| `run_nearlive_wave.py` | Near-live replay wave |
| `run_1year_hardening.py` | One-year hardening run |
| `run_8week_prop_replay.py` | Eight-week prop-style replay |
| `run_prop_monte_carlo.py` | Prop-account Monte Carlo |
| `compare_experiments.py` | Compare experiment outputs |
| `generate_report.py` | Daily/weekly/health reports |

### Paper and forward trading

| Script | Purpose |
|---|---|
| `run_paper.py` | Historical paper trading replay |
| `run_forward_paper.py` | Forward paper runner (replay or file-watch) |
| `run_live_forward_service.py` | Docker entry point for the forward paper service |
| `run_paper_validation.py` | Legacy 4–6 week paper validation campaign runner |

### Maintenance and certification

| Script | Purpose |
|---|---|
| `certify_2019.py` | 2019 data certification (historical) |
| `maintenance/clean_workspace.py` | Dry-run/apply cleanup of local scratch directories |

## Program-specific directories

| Directory | Contents |
|---|---|
| `v3/` | Data acquisition, certification, discovery and parity scripts for V3 |
| `v4/` | V4 paid-data preflight (programme blocked before acquisition) |
| `v5r/` | V5R discovery, fast run and protocol-conformance rerun |

These are frozen programme tooling. They depend on exact protocol files,
manifests and data layouts; do not refactor them casually.

## Frozen gate runners

`run_gate_*.py` (about 45 files) are one-off gate runners and adjudication tools
from the C2–C6, F0, Q0–Q1, P0–P1, A0 and V-series programmes. They are kept at
their exact paths because:

- tests and postmortems cite those paths as evidence;
- several runners contain self-referential path checks and commit-ledger logic;
- moving them would silently break reproducibility of historical audits.

Do not rename or reorganise these files. Add a note in this index instead.

## Conventions for new scripts

1. Add the script to this index in the same change.
2. Use `argparse` and keep configuration in YAML where possible.
3. Resolve paths from arguments or environment variables, not from a hard-coded
   user directory.
4. Write outputs under `results/` or `var/`; never commit generated artifacts.
5. Add a focused test if the script contains reusable logic.
6. If the script belongs to a new research programme, put it in a new
   programme directory and write a protocol first.
