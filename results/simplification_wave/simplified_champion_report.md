# Simplified Champion Report

Generated: 2026-04-12T17:55:06.129230

## 1. Family Decisions

| Family | Status | Reason |
|--------|--------|--------|
| bos_continuation | **PROMOTED** | Only profitable family in holdout; positive WF mean |
| sweep_reversal | **DEMOTED** | Loss-making in holdout (WR 60%->29%); family reversal |
| fvg_retrace | **REMOVED** | Already excluded in prior waves |

## 2. Pair Universe Decisions

- **USDJPY only**: VIABLE (holdout Sharpe=0.850, WF mean=0.649)
- **EURUSD only**: REJECTED (holdout Sharpe=-0.818, WF mean=-0.208)
- **GBPUSD only**: REJECTED (holdout Sharpe=-1.380, WF mean=-0.588)
- **All 3 pairs**: MARGINAL (holdout Sharpe=0.154, WF mean=0.279)
- **EURUSD+GBPUSD**: REJECTED (holdout Sharpe=-1.097, WF mean=0.100)
- **USDJPY+EURUSD**: VIABLE (holdout Sharpe=0.862, WF mean=0.684)
- **USDJPY+GBPUSD**: MARGINAL (holdout Sharpe=0.114, WF mean=0.713)

## 3. Shortlisted Simplified Configs

| Variant                              | Pairs                  | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|--------------------------------------|------------------------|--------|---------|--------|---------|-------|----------------|
| bos_only | USDJPY only               | USDJPY only            |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| bos_only | All 3 pairs               | All 3 pairs            |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| bos_only_usdjpy_conservative         | USDJPY only            |    202 |   0.716 |   1.72 |   10.2% | 30.2% |      20,309.21 |

### Walk-Forward

| Variant                              | Pairs                  |  WF Mean |    Std |  %Pos |  >0.3 |                          Folds |
|--------------------------------------|------------------------|----------|--------|-------|-------|--------------------------------|
| bos_only | USDJPY only               | USDJPY only            |    0.649 |  1.562 |  40% |  40% | -0.975, -0.393, 2.189, 2.864, -0.441 |
| bos_only | All 3 pairs               | All 3 pairs            |    0.279 |  1.365 |  40% |  40% | -0.281, 0.747, -0.652, 2.713, -1.131 |
| bos_only_usdjpy_conservative         | USDJPY only            |    0.543 |  1.618 |  40% |  40% | -1.173, -0.494, 2.146, 2.826, -0.589 |

## 4. Recommendation

Primary candidate: **bos_only_usdjpy** (WF mean=0.649, holdout Sharpe=0.850)