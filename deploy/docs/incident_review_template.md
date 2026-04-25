# Incident Review Template

## Incident ID: INC-YYYY-MM-DD-NNN

### Summary
_One-line description of the incident_

### Timeline
| Time (UTC) | Event |
|-----------|-------|
| | First indication |
| | Investigation started |
| | Root cause identified |
| | Mitigation applied |
| | Resolution confirmed |

### Impact
- **Trades affected**: _count_
- **PnL impact**: _amount_
- **Downtime**: _duration_
- **Data loss**: _yes/no_

### Root Cause
_Detailed technical description_

### Resolution
_What was done to resolve the issue_

### Classification
- [ ] Strategy issue (alpha logic)
- [ ] Infrastructure issue (VPS, Docker, feed)
- [ ] Configuration issue (parameters, environment)
- [ ] Data issue (feed quality, gaps, errors)
- [ ] External issue (broker, network, provider)

### Severity
- [ ] P0 — Trial invalidation risk
- [ ] P1 — Significant impact, requires immediate action
- [ ] P2 — Moderate impact, fix within 24 hours
- [ ] P3 — Low impact, fix at next opportunity

### Follow-up Actions
1. _Action item 1_
2. _Action item 2_

### Lessons Learned
_What can be done to prevent similar incidents_
