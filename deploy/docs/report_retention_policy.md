# Report Retention Policy

## Retention Rules

| Artifact | Retention Period | Location |
|----------|-----------------|----------|
| Daily reports | Full trial duration + 30 days | `forward_runs/reports/` |
| Weekly reports | Full trial duration + 90 days | `forward_runs/reports/` |
| Health reports | 7 days | `forward_runs/reports/` |
| Session summaries | Permanent | `forward_runs/<run_id>/` |
| Event journals | Full trial duration + 90 days | `forward_runs/<run_id>/journal.jsonl` |
| Alert logs | Full trial duration + 30 days | `forward_runs/alerts.jsonl` |
| State checkpoints | Latest only per run | `forward_runs/<run_id>/state.json` |
| Daily review JSONs | Full trial duration + 90 days | `forward_runs/<run_id>/reviews/` |
| Service logs | 50 MB rolling (5 files) | `forward_runs/logs/` |

## Archive Procedure

At the end of the 4-week trial:

1. Stop the service: `docker compose stop forward-paper`
2. Archive the forward_runs volume:
   ```bash
   tar czf trial_$(date +%Y%m%d).tar.gz forward_runs/
   ```
3. Store the archive off-VPS (local machine, cloud storage)
4. The archive contains the complete audit trail for the trial

## Cleanup

Old reports and logs can be cleaned periodically:
```bash
find forward_runs/reports/ -name "health_*.md" -mtime +7 -delete
```
