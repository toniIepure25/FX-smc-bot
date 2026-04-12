# Paper Stage Escalation Rules

## Candidate: bos_only_usdjpy

---

## Escalation Levels

### Level 1: NOTE
- Log the observation in the weekly review
- No change to monitoring cadence
- Examples: single day with 0 trades, minor spread difference

### Level 2: WARN
- Document in weekly review with specific concern
- Shorten monitoring interval to daily review
- Set a 1-week resolution deadline
- Examples: signal frequency 30-50% off, drawdown approaching 10%

### Level 3: ESCALATE
- Flag for immediate human review
- Pause any config changes
- Conduct root-cause analysis within 48 hours
- Examples: circuit breaker proximity > 80%, win rate dropping below 18%

### Level 4: SUSPEND
- Halt paper trading immediately
- Preserve all artifacts for post-mortem
- Do not restart without explicit review and approval
- Examples: drawdown > 15%, circuit breaker fires, Sharpe < 0 at week 4

---

## Specific Escalation Triggers

### Signal Funnel

| Condition | Level |
|-----------|-------|
| 0 signals for 1 day | NOTE |
| 0 signals for 2 consecutive days | WARN |
| 0 signals for 3 consecutive days | ESCALATE |
| 0 signals for 5 consecutive days | SUSPEND |
| Signal rejection rate > 80% | WARN |
| Signal rejection rate > 95% | ESCALATE |

### Performance

| Condition | Level |
|-----------|-------|
| Daily PnL loss > 3% of equity | WARN |
| Weekly PnL loss > 5% of equity | ESCALATE |
| Running Sharpe < 0.0 at week 3 | WARN |
| Running Sharpe < 0.0 at week 4 | SUSPEND |
| Win rate < 20% over 2-week window | WARN |
| Win rate < 15% over 2-week window | SUSPEND |

### Risk Events

| Condition | Level |
|-----------|-------|
| Throttle activation | NOTE |
| 2+ throttle activations in one day | WARN |
| Lockout activation | ESCALATE |
| Circuit breaker proximity > 80% | ESCALATE |
| Circuit breaker fires | SUSPEND |
| Any config mutation detected | SUSPEND |

### Operational

| Condition | Level |
|-----------|-------|
| Single recoverable error | NOTE |
| Repeated recoverable errors (> 3/day) | WARN |
| Unrecoverable error | ESCALATE |
| Data feed gap > 4 hours | WARN |
| Data feed gap > 24 hours | ESCALATE |

---

## Escalation Response Protocol

1. **NOTE**: Reviewer acknowledges in weekly summary. No further action required.
2. **WARN**: Reviewer documents concern with specific metrics. Sets resolution timeline. Increases monitoring to daily.
3. **ESCALATE**: Reviewer conducts root-cause analysis within 48h. Documents findings. Decides: resolve and continue, or suspend.
4. **SUSPEND**: Paper trading halts. All artifacts preserved. Post-mortem review required before any restart. Restart requires explicit sign-off.
