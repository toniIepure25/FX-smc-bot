# Promotion Gate Framework

## Gate Structure

```
4-Week Paper Trial
        │
        ├─ FAIL → Fix issues → Restart trial
        │
        ▼
  Gate 1: Paper Trial Pass
        │
        ├─ FAIL → Extend paper or reject
        │
        ▼
  Gate 2: Broker-Demo Shadow
        │
        ├─ FAIL → Fix integration issues
        │
        ▼
  Gate 3: Broker-Demo Actual
        │
        ├─ FAIL → Review strategy viability
        │
        ▼
  Gate 4: Prop Account Preparation
        │
        ▼
  Live Prop Trading
```

## Gate 1: Paper Trial Pass

**Required evidence**:
- All 4-week success criteria met (see `four_week_paper_trial_program.md`)
- No unresolved P0/P1 incidents
- Operator sign-off on trial review package
- Clean trial manifest with all checkpoints documented

**Possible outcomes**:
- **ADVANCE**: All criteria met → proceed to broker-demo shadow
- **EXTEND**: Most criteria met, but need more data → extend paper by 2 weeks
- **REJECT**: Fundamental issues → reassess strategy

## Gate 2: Broker-Demo Shadow

**Required evidence**:
- Gate 1 passed
- Broker demo account provisioned
- `BrokerGateway` integrated with demo adapter
- Shadow mode: orders generated but not submitted
- 1-week shadow run comparing paper fills vs demo quotes
- Fill price slippage analysis

**Possible outcomes**:
- **ADVANCE**: Shadow parity acceptable → proceed to demo actual
- **FIX**: Integration issues found → fix and re-shadow
- **REJECT**: Fundamental execution issues → hold at paper

## Gate 3: Broker-Demo Actual

**Required evidence**:
- Gate 2 passed
- Demo trades executing correctly
- 2-week demo run with real order submission
- Reconciliation: demo fills vs paper expectations
- No execution anomalies

**Possible outcomes**:
- **ADVANCE**: Demo performance matches expectations → prepare for prop
- **EXTEND**: Need more demo data
- **REJECT**: Execution quality insufficient

## Gate 4: Prop Account Preparation

**Required evidence**:
- Gate 3 passed
- Prop firm account opened
- Compliance requirements met
- Capital allocation plan approved
- Disaster recovery tested
- Kill switch verified on real infrastructure
