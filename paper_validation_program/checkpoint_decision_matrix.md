# Checkpoint Decision Matrix

## Candidate: bos_only_usdjpy

This matrix defines the exact decision logic at each checkpoint.

---

## Decision Categories

| Decision | Meaning | Action |
|----------|---------|--------|
| **CONTINUE** | On track, proceed to next checkpoint | No action needed |
| **WARN** | Concern noted, increased monitoring | Document concern, shorten review interval |
| **EXTEND** | Inconclusive, need more data | Add 2-4 weeks to paper period |
| **SUSPEND** | Hard stop triggered | Halt paper trading immediately |
| **PROMOTE** | Paper stage passed | Prepare live deployment package |
| **REJECT** | Strategy failed paper stage | Archive and document failure mode |

---

## Hard Stop Triggers (Any Checkpoint)

These cause immediate **SUSPEND** regardless of other metrics:

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Drawdown exceeds limit | > 15% peak-to-trough | Immediate halt |
| Circuit breaker fires | Any activation | Immediate halt |
| Win rate collapse | < 15% over any 2-week window | Immediate halt |
| Signal drought | 0 signals for 5 consecutive trading days | Immediate halt |
| System error | Repeated unrecoverable errors | Immediate halt |
| Config mutation | Fingerprint mismatch detected | Immediate halt |

---

## Week 1 Decision Matrix

| Signal Count | Errors | Decision |
|-------------|--------|----------|
| 5-12 trades | None | CONTINUE |
| 2-4 trades | None | WARN — low frequency |
| 13-20 trades | None | WARN — high frequency |
| 0-1 trades | None | WARN — investigate funnel |
| Any | System errors | SUSPEND |

---

## Week 2 Decision Matrix

| Signal Deviation | Drawdown | Win Rate | Decision |
|-----------------|----------|----------|----------|
| < 30% | < 10% | 18-45% | CONTINUE |
| 30-50% | < 10% | 18-45% | WARN |
| < 50% | 10-15% | 18-45% | WARN |
| > 50% | Any | Any | WARN — consider suspend |
| Any | > 15% | Any | SUSPEND |
| Any | Any | < 15% (2wk) | SUSPEND |

---

## Week 4 Decision Matrix

| Paper Sharpe | Drawdown | Trade Count | Decision |
|-------------|----------|-------------|----------|
| > 0.3 | < 10% | 20-48 | CONTINUE (strong) |
| 0.0-0.3 | < 12% | 15-60 | CONTINUE (adequate) |
| -0.2 to 0.0 | < 12% | 15-60 | WARN — monitor closely |
| < -0.2 | Any | Any | SUSPEND |
| > 0.0 | 10-15% | Any | WARN — DD concern |
| Any | > 15% | Any | SUSPEND |
| Any | Any | < 10 | WARN — insufficient data |

---

## Week 6 Final Decision Matrix

| Paper Sharpe | PF | Trade Count | Discrepancy | Decision |
|-------------|-----|-------------|-------------|----------|
| > 0.5 | > 1.3 | > 30 | < 30% | **PROMOTE** |
| 0.3-0.5 | > 1.1 | > 25 | < 40% | **PROMOTE** (conditional) |
| 0.1-0.3 | > 1.0 | > 20 | < 40% | **EXTEND** 2-4 weeks |
| 0.0-0.1 | Any | > 15 | < 50% | **EXTEND** with concerns |
| < 0.0 | Any | Any | Any | **REJECT** |
| Any | Any | < 15 | Any | **EXTEND** (insufficient data) |
| Any | Any | Any | > 50% | **REJECT** (paper/backtest divergence) |
