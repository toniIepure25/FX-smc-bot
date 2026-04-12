# Holdout Evaluation Under Hardened Risk

Generated: 2026-04-12T12:40:13.565204

## Train vs Holdout Comparison

| Candidate | Profile | Train Sharpe | Holdout Sharpe | Train DD | Holdout DD | Train Trades | Holdout Trades | Holdout Gate |
|-----------|---------|-------------|---------------|----------|-----------|-------------|---------------|-------------|
| sweep_plus_bos | size_030_cb125 | 2.076 | 0.154 (-93%) | 13.4% | 12.7% | 513 | 253 | FAIL |
| sweep_plus_bos | hardened_C | 2.026 | 0.147 (-93%) | 12.9% | 14.7% | 509 | 195 | FAIL |
| bos_continuation_only | size_030_cb125 | 1.948 | 0.154 (-92%) | 12.8% | 12.7% | 432 | 253 | FAIL |
| sweep_plus_bos | size_030_tight_daily | 2.069 | 0.054 (-97%) | 15.1% | 15.2% | 481 | 261 | FAIL |
| sweep_plus_bos | size_030 | 2.066 | 0.034 (-98%) | 15.0% | 15.8% | 514 | 470 | FAIL |

## Holdout Gate Summary

- 0/5 profiles pass holdout gate
- **No profiles passed holdout gate**
