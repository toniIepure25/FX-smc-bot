# Data

Local market data and small tracked samples. Raw tick/M1 datasets are **not**
committed; the working copy is several GB and is ignored by git.

> The 2018+ holdout is sealed. See [../docs/STATUS.md](../docs/STATUS.md) before
> reading or acquiring data outside the 2010–2017 research window.

---

## Layout

| Path | Content | Tracked? |
|---|---|---|
| `EURUSD/`, `GBPUSD/`, `USDJPY/` | Small sample CSVs (15m/1h/4h) used by examples and tests | Yes |
| `real/EURUSD/`, `real/GBPUSD/`, `real/USDJPY/` | Sample real-data CSVs and manifests | Partly |
| `real/raw/` | Downloaded raw files | No |
| `real/manifests/` | Dataset manifests and checksums | Partly |
| `real/acquisition_plan.json` | Acquisition plan | Yes |
| `real/data_readiness_report.md` | Readiness assessment | Yes |
| `raw/` | Generic input drop for `ingest_data.py` | No |
| `canonical/` | Canonical M1/tick store used by research gates | No |
| `acquisition_state/` | Resumable acquisition state | No |
| `synthetic_control/` | Synthetic control datasets | No |

The exact local size depends on which acquisition runs were performed. Do not
assume a fresh clone contains research data.

## Canonical schema

Processed bars follow:

| Column | Type | Meaning |
|---|---|---|
| `timestamp` | `datetime64[ns, UTC]` | Bar open time |
| `open` | `float64` | Open |
| `high` | `float64` | High |
| `low` | `float64` | Low |
| `close` | `float64` | Close |
| `volume` | `float64` (optional) | Tick volume |
| `spread` | `float64` (optional) | Spread at bar close |

Bid/ask-aware research uses separate bid and ask series; see
`src/fx_smc_bot/data/bidask.py` and `bidask_resampling.py`.

## Getting data

Synthetic data (safe, for wiring only):

```powershell
python scripts/download_data.py --mode generate --output-dir var/smoke/data
```

Import local CSVs:

```powershell
python scripts/ingest_data.py --input data/raw/EURUSD_M1.csv --pair EURUSD --timeframe 1m
```

Dukascopy acquisition:

```powershell
python scripts/acquire_fx_history.py --help
python scripts/acquire_dukascopy_node_history.py --help
```

See [../docs/DATA_GUIDE.md](../docs/DATA_GUIDE.md) and
[../scripts/README.md](../scripts/README.md) for the full pipeline.

## Rules

1. Never commit raw ticks, M1 archives or broker exports.
2. Record a manifest/hash for every dataset used in a research decision.
3. Do not mix synthetic and real data in the same result.
4. Do not touch 2018+ data without a new protocol and an explicit decision.
5. Keep credential files out of `data/`; use `.env`.
