# Trial Decision Matrix

## End-of-Trial Decision Tree

```
                    All hard criteria met?
                    ┌────┴────┐
                   YES       NO
                    │         │
                    │    Which criteria failed?
                    │    ┌────┴────────────────────┐
                    │   Trade count    Performance   Operational
                    │   < 40           PF<1/WR<35%   Uptime<95%
                    │    │             DD>8%          Feed<90%
                    │    │                │               │
                    │  Extend 2wk    Investigate      Fix infra
                    │  more data     strategy         re-trial
                    │                viability
                    │
              Soft criteria review
              ┌────┴────┐
             ALL OK    CONCERNS
              │            │
         ADVANCE      Document concerns
         to broker-    Continue if
         demo shadow   non-blocking
```

## Decision Outcomes

| Outcome | Criteria | Action |
|---------|----------|--------|
| **ADVANCE** | All hard criteria met, no P0/P1 incidents | Begin broker-demo shadow setup |
| **EXTEND** | Most criteria met, need more data | Continue paper for 2 more weeks |
| **FIX & RETRY** | Operational issues only (not strategy) | Fix infrastructure, restart trial |
| **HOLD** | Strategy concerns but not fatal | Extended investigation, no advancement |
| **REJECT** | Fundamental strategy failure | Re-evaluate strategy viability |

## Scoring Rubric

| Metric | Score 3 (Strong) | Score 2 (Adequate) | Score 1 (Weak) | Score 0 (Fail) |
|--------|-----------------|-------------------|----------------|----------------|
| Trades | > 60 | 40-60 | 20-40 | < 20 |
| Win rate | > 50% | 35-50% | 25-35% | < 25% |
| PF | > 1.5 | 1.0-1.5 | 0.7-1.0 | < 0.7 |
| Max DD | < 4% | 4-6% | 6-8% | > 8% |
| Uptime | > 99% | 95-99% | 90-95% | < 90% |
| CB fires | 0 | 1 | 2 | 3+ |

**Minimum passing score**: 12/18 with no Score 0 in any category.
