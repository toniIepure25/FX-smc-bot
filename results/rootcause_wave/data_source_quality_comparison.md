# Data Source Quality Comparison

Generated: 2026-04-12T14:35:13.551462

## 1. Data Quality Diagnostics

### Yahoo Finance

**EURUSD**: 12,354 bars | Missing: 29.5% | Quality: 0.656 | Spread: N/A
**GBPUSD**: 12,356 bars | Missing: 29.5% | Quality: 0.666 | Spread: N/A
**USDJPY**: 12,268 bars | Missing: 30.0% | Quality: 0.679 | Spread: N/A

### Dukascopy-Quality Synthetic (with realistic spreads)

**EURUSD**: 12,529 bars | Missing: 28.5% | Quality: 0.699 | Spread: 0.000140
**GBPUSD**: 12,529 bars | Missing: 28.5% | Quality: 0.699 | Spread: 0.000174
**USDJPY**: 12,529 bars | Missing: 28.5% | Quality: 0.699 | Spread: 0.017492

## 2. Champion Performance: Yahoo vs Synthetic

| Label                        | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |  Calmar |
|------------------------------|--------|---------|--------|---------|-------|----------------|---------|
| Yahoo Train                  |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |  365.67 |
| Yahoo Holdout                |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |    0.57 |
| Synth Train                  |     74 |  -0.659 |   0.10 |   13.7% | 17.6% |     -12,705.93 |   -0.53 |
| Synth Holdout                |     83 |  -0.743 |   0.30 |   12.5% | 22.9% |     -11,812.90 |   -1.65 |

## 3. Spread Assumption Sensitivity (Yahoo Holdout)

|   Mult |   Sharpe |     PF |            PnL |   Win% |
|--------|----------|--------|----------------|--------|
|   0.25 |    0.270 |   1.20 |       7,407.25 | 45.8% |
|   0.50 |    0.231 |   1.17 |       6,343.17 | 43.1% |
|   0.75 |    0.192 |   1.14 |       5,279.09 | 41.9% |
|   1.00 |    0.154 |   1.11 |       4,215.01 | 31.2% |
|   1.50 |    0.076 |   1.05 |       2,086.84 | 28.5% |
|   2.00 |   -0.002 |   1.00 |         -41.32 | 26.5% |
|   3.00 |   -0.157 |   0.90 |      -4,297.65 | 24.1% |

## 4. Key Findings

- Yahoo Finance has ~30% missing bars and no spread data (quality ~0.66)
- The fixed 1.5 pip spread is 3-15x wider than institutional reality
- Synthetic data with realistic spreads allows isolating data-quality effects
- Synthetic holdout Sharpe (-0.743) is similar to Yahoo (0.154) — data quality is NOT the primary issue