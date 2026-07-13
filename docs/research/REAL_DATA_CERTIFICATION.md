# Real Data Certification Report

**Audit Date**: 2026-07-13
**Branch**: `research/rigorous-intraday-smc-validation`

---

## Available Data Inventory

### Source: Yahoo Finance (yfinance)

| Pair | Timeframe | Rows | Date Range | Missing% | Quality | Spread | Bid/Ask |
|------|-----------|------|------------|----------|---------|--------|---------|
| EURUSD | M15 | 5,673 | 2026-01-19 → 2026-04-10 | 27.8% | 0.617 | None | No |
| EURUSD | H1 | 12,354 | 2024-04-10 → 2026-04-10 | 29.5% | 0.656 | None | No |
| EURUSD | H4 | 3,184 | 2024-04-10 → 2026-04-10 | 27.3% | 0.681 | None | No |
| GBPUSD | M15 | 5,673 | 2026-01-19 → 2026-04-10 | 27.8% | 0.677 | None | No |
| GBPUSD | H1 | 12,356 | 2024-04-10 → 2026-04-10 | 29.5% | 0.666 | None | No |
| GBPUSD | H4 | 3,184 | 2024-04-10 → 2026-04-10 | 27.3% | 0.689 | None | No |
| USDJPY | M15 | 5,579 | 2026-01-19 → 2026-04-10 | 29.0% | 0.680 | None | No |
| USDJPY | H1 | 12,268 | 2024-04-10 → 2026-04-10 | 30.0% | 0.679 | None | No |
| USDJPY | H4 | 3,177 | 2024-04-10 → 2026-04-10 | 27.5% | 0.675 | None | No |

---

## Critical Data Deficiencies

### 1. No M5 or M1 Data Available
The intraday SMC strategies are designed for M5 execution timeframe. No M5 or M1 data exists in the repository. The available M15 data covers only ~3 months.

### 2. No Bid/Ask Spread Data
All available data is mid-price only. The execution model requires bid/ask or at minimum a historical spread series to model realistic transaction costs. Without spread data, any backtest result conflates trading costs with alpha.

### 3. Insufficient Time Coverage
- **M15**: ~3 months (Jan-Apr 2026) — far below the 8-10 year target
- **H1/H4**: ~2 years (Apr 2024 - Apr 2026) — insufficient for multi-regime validation
- **No data before 2024** — cannot assess strategy behavior across different monetary policy regimes (e.g., 2016-2020 low-vol, 2022-2023 high-vol)

### 4. High Missing Bar Rate (27-30%)
Most of this is expected (weekends, holidays), but the missing bar rate is not separated from genuine gaps. Quality scores range 0.617-0.689, below the 0.90 threshold for research-grade data.

### 5. Zero Volume
All volume fields are 0, making volume-dependent analysis impossible.

### 6. No Independent Data Source
Only Yahoo Finance is available. No Dukascopy, FXCM, or broker-quality data for cross-validation.

---

## Required Data Not Available

| Requirement | Status | Impact |
|-------------|--------|--------|
| M1 bid/ask tick data | NOT AVAILABLE | Cannot model realistic fills |
| M5 OHLCV data | NOT AVAILABLE | Cannot run intraday strategies at target resolution |
| 8-10 year coverage | NOT AVAILABLE | Cannot assess multi-regime robustness |
| Bid/ask spread series | NOT AVAILABLE | Cannot certify execution realism |
| Multiple data sources | NOT AVAILABLE | Cannot cross-validate |
| London session M5 bars | NOT AVAILABLE | Cannot test Strategy A/B/C at design resolution |
| NY session M5 bars | NOT AVAILABLE | Cannot test Opening Range strategy |

---

## Certification Decision

### EURUSD / GBPUSD / USDJPY (all timeframes)

**Status: `REJECTED` for final research; `CERTIFIED_FOR_EXPLORATORY_RESEARCH_ONLY` at H1**

**Reasons:**
1. Mid-price only — cannot model bid/ask execution costs
2. No M5 data — cannot run strategies at design resolution
3. ~2 years H1 maximum — insufficient for multi-regime validation
4. ~3 months M15 — insufficient for any meaningful statistical inference
5. No spread data — execution realism cannot be certified
6. Single source (Yahoo Finance) — no cross-validation possible

### Required Actions to Achieve `CERTIFIED_FOR_FINAL_RESEARCH`

1. Acquire M1 bid/ask data from Dukascopy (free) or FXCM covering 2014-2024
2. Resample to M5/M15/H1/H4 with proper aggregation
3. Compute and store historical spread series
4. Validate against a second source
5. Compute provenance checksums
6. Re-run data quality diagnostics
7. Verify DST boundary handling on real date coverage

---

## Data Quality Report (Existing Yahoo Data)

Saved to: `results/pre_holdout/data_quality/data_quality.json`

```json
{
  "source": "yahoo_finance",
  "price_type": "mid",
  "spread_source": "none",
  "certification": "REJECTED",
  "pairs": {
    "EURUSD": {
      "M15": {"rows": 5673, "missing_pct": 27.8, "quality": 0.617},
      "H1": {"rows": 12354, "missing_pct": 29.5, "quality": 0.656},
      "H4": {"rows": 3184, "missing_pct": 27.3, "quality": 0.681}
    },
    "GBPUSD": {
      "M15": {"rows": 5673, "missing_pct": 27.8, "quality": 0.677},
      "H1": {"rows": 12356, "missing_pct": 29.5, "quality": 0.666},
      "H4": {"rows": 3184, "missing_pct": 27.3, "quality": 0.689}
    },
    "USDJPY": {
      "M15": {"rows": 5579, "missing_pct": 29.0, "quality": 0.680},
      "H1": {"rows": 12268, "missing_pct": 30.0, "quality": 0.679},
      "H4": {"rows": 3177, "missing_pct": 27.5, "quality": 0.675}
    }
  },
  "blocking_issues": [
    "No M5/M1 data",
    "No bid/ask spread",
    "Insufficient time coverage",
    "Single source only"
  ]
}
```
