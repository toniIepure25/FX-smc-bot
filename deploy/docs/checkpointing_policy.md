# Checkpointing Policy

## Schedule

| Trigger | Frequency | What is saved |
|---------|-----------|---------------|
| Periodic | Every 50 bars (~50 hours at H1) | Full `LiveState` |
| Day boundary | Every day change | Daily review JSON |
| Graceful stop | On SIGINT/SIGTERM | Full `LiveState` + `session_summary.json` |
| Pause | On `runner.pause()` | Full `LiveState` |

## Retention

| Artifact | Retention | Rationale |
|----------|-----------|-----------|
| `state.json` | Keep latest per run_id | Only the latest checkpoint matters for recovery |
| `journal.jsonl` | Keep for full trial duration | Audit trail; needed for post-trial analysis |
| `reviews/day_*.json` | Keep for full trial duration | Daily review history |
| `session_summary.json` | Keep forever | Final session record |
| `alerts.jsonl` | Keep for full trial duration | Alert audit trail |
| `reports/*.md` | Keep for full trial duration | Review history |
| `logs/service.log` | Rotate at 50MB, keep 5 rotations | Operational debugging |

## Disk Usage Estimate (4-week trial)

| Artifact | Estimated size |
|----------|---------------|
| state.json | 5 KB |
| journal.jsonl (28 days) | 5-10 MB |
| Daily reviews (20 trading days) | 100 KB |
| Alerts | 200 KB |
| Reports | 500 KB |
| Logs | 50 MB (with rotation) |
| **Total** | **~65 MB** |

Easily fits on any VPS with 5+ GB disk.
