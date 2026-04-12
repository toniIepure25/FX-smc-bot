# Week 1 Signal Integrity Review

## Candidate: bos_only_usdjpy
## Period: [Start date] — [End date]

---

## Purpose

Verify that the paper trading system is operational, generating BOS continuation
signals on USDJPY, and converting them to trades at a rate consistent with
backtest expectations.

---

## Signal Funnel Analysis

| Metric | Observed | Expected | Status |
|--------|----------|----------|--------|
| Total signals generated | __ | 10-30 | OK/WARN |
| Total signals rejected | __ | Variable | — |
| Rejection rate | __% | < 80% | OK/WARN |
| Trades opened | __ | 5-12 | OK/WARN |
| Trades closed | __ | Variable | — |
| Days with 0 signals | __ | 0-1 | OK/WARN |

## Signal Quality

| Check | Result | Notes |
|-------|--------|-------|
| BOS continuation signals appearing? | Y/N | — |
| USDJPY only? (no stray pairs) | Y/N | — |
| H1 timeframe signals? | Y/N | — |
| H4 HTF confirmation active? | Y/N | — |
| Risk sizing within 0.30%? | Y/N | — |

## Operational Health

| Check | Result |
|-------|--------|
| No system errors | Y/N |
| Journal writing correctly | Y/N |
| Config fingerprint valid | Y/N |
| Operational state = ACTIVE | Y/N |
| No circuit breaker events | Y/N |

## Week 1 Verdict

- [ ] **PASS** — Signal integrity confirmed, proceeding to week 2
- [ ] **WARN** — Signal concerns noted: _______________
- [ ] **FAIL** — Critical issue: _______________

**Notes**: _______________________________________________
