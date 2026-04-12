# Risk Event Monitoring Specification

## Candidate: bos_only_usdjpy

---

## Risk Events Tracked

### 1. Drawdown Events
- **Metric**: Peak-to-trough equity drawdown as % of peak equity
- **Source**: Equity curve from paper trading journal
- **Thresholds**:
  - Normal: < 8%
  - Warning (SW-6): 8-10%
  - Elevated: 10-12%
  - Critical: 12-15%
  - Hard stop (HSI-2): > 15%

### 2. Circuit Breaker Proximity
- **Metric**: Current drawdown / circuit breaker threshold (12.5%)
- **Source**: Risk state from paper runner
- **Thresholds**:
  - Normal: < 60%
  - Elevated: 60-80%
  - Critical (Level 3 escalation): > 80%
  - Fired (HSI-5): 100%

### 3. Throttle Activations
- **Metric**: Count of throttle activations per day/week
- **Source**: Risk state transitions in journal
- **Thresholds**:
  - Normal: 0-1 per week
  - Warning: 2+ per day
  - Escalation: 5+ per week

### 4. Lockout Activations
- **Metric**: Count of lockout activations
- **Source**: Risk state transitions in journal
- **Thresholds**:
  - Normal: 0
  - Escalation: Any activation

### 5. Operational State Transitions
- **Metric**: Changes from ACTIVE to THROTTLED/LOCKED_OUT/STOPPED
- **Source**: State log from paper runner
- **Track**: timestamp, from_state, to_state, trigger_reason

### 6. Loss Streaks
- **Metric**: Consecutive losing trades
- **Source**: Trade blotter
- **Thresholds**:
  - Normal: 1-5 consecutive losses
  - Warning: 6-8 consecutive losses
  - Escalation: 9-12 consecutive losses
  - Hard review: > 12 consecutive losses

### 7. Risk Utilization
- **Metric**: Current portfolio risk / max_portfolio_risk (0.9%)
- **Source**: Risk state
- **Thresholds**:
  - Normal: < 70%
  - Elevated: 70-90%
  - Warning: > 90%

---

## Risk Event Log Format

Each risk event should be logged with:
```json
{
  "timestamp": "2026-04-14T10:30:00Z",
  "event_type": "drawdown_warning",
  "severity": "warning",
  "value": 0.105,
  "threshold": 0.10,
  "details": "Peak-to-trough drawdown reached 10.5%",
  "session_id": "pv_20260414_...",
  "action_required": "increase monitoring frequency"
}
```

---

## Weekly Risk Summary

Each weekly review should include:

| Category | Count | Max Severity | Notes |
|----------|-------|-------------|-------|
| Drawdown events | N | warn/critical | Current DD: X% |
| Throttle activations | N | note/warn | Dates: ... |
| Lockout activations | N | escalate | — |
| CB proximity events | N | — | Max proximity: X% |
| Loss streaks > 5 | N | — | Longest: X |
| State transitions | N | — | Summary |
