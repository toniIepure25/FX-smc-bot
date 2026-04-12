# Stronger OOS Validation Report

Generated: 2026-04-12T18:10:34.822350

## bos_only_usdjpy

### Anchored Walk-Forward (5 folds)
- Sharpes: ['-0.975', '-0.393', '2.189', '2.864', '-0.441']
- Mean: 0.649 | Std: 1.562

### Rolling Walk-Forward (5 folds)
- Sharpes: ['3.158', '-0.474', '4.043', '3.137', '1.315']
- Mean: 2.236

### Combined OOS (10 folds)
- Mean: 1.442 | Std: 1.778
- % positive: 60%
- % above 0.3: 60%

### Execution Stress
- optimistic: Sharpe=0.894 | PF=2.04 | Trades=221
- neutral: Sharpe=0.850 | PF=1.96 | Trades=220
- conservative: Sharpe=0.811 | PF=1.90 | Trades=220
- stressed: Sharpe=0.776 | PF=1.85 | Trades=220
- Stress test: PASSED

## bos_only_all_pairs

### Anchored Walk-Forward (5 folds)
- Sharpes: ['-0.281', '0.747', '-0.652', '2.713', '-1.131']
- Mean: 0.279 | Std: 1.365

### Rolling Walk-Forward (5 folds)
- Sharpes: ['2.607', '-1.126', '-0.809', '-0.791', '0.677']
- Mean: 0.112

### Combined OOS (10 folds)
- Mean: 0.195 | Std: 1.383
- % positive: 40%
- % above 0.3: 40%

### Execution Stress
- optimistic: Sharpe=0.187 | PF=1.14 | Trades=257
- neutral: Sharpe=0.154 | PF=1.11 | Trades=253
- conservative: Sharpe=0.123 | PF=1.10 | Trades=187
- stressed: Sharpe=0.029 | PF=1.01 | Trades=178
- Stress test: PASSED

## bos_only_usdjpy_cons

### Anchored Walk-Forward (5 folds)
- Sharpes: ['-1.173', '-0.494', '2.146', '2.826', '-0.589']
- Mean: 0.543 | Std: 1.618

### Rolling Walk-Forward (5 folds)
- Sharpes: ['3.134', '-0.609', '-0.664', '3.090', '1.138']
- Mean: 1.218

### Combined OOS (10 folds)
- Mean: 0.881 | Std: 1.682
- % positive: 50%
- % above 0.3: 50%

### Execution Stress
- optimistic: Sharpe=0.755 | PF=1.77 | Trades=202
- neutral: Sharpe=0.716 | PF=1.72 | Trades=202
- conservative: Sharpe=0.696 | PF=1.69 | Trades=202
- stressed: Sharpe=0.627 | PF=1.60 | Trades=202
- Stress test: PASSED

## Candidate Comparison

| Candidate                    | OOS Mean | OOS Std |  %Pos |  >0.3 | Stress |
|------------------------------|----------|---------|-------|-------|--------|
| bos_only_usdjpy              |    1.442 |   1.778 |  60% |  60% |     OK |
| bos_only_all_pairs           |    0.195 |   1.383 |  40% |  40% |     OK |
| bos_only_usdjpy_cons         |    0.881 |   1.682 |  50% |  50% |     OK |