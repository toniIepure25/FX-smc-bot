# Service Lifecycle Definition

## States

```
  ┌─────────┐
  │ STOPPED │◄──────────────────────────────┐
  └────┬────┘                               │
       │ docker compose up                  │ docker compose stop
       ▼                                    │ or SIGTERM
  ┌─────────┐     checkpoint found?    ┌────┴────┐
  │STARTING │─────── yes ─────────────►│RESUMING │
  └────┬────┘                          └────┬────┘
       │ no                                 │
       │           config fingerprint OK?   │
       │◄───────── yes ────────────────────┘
       │
       ▼
  ┌─────────┐
  │ RUNNING │◄─────── auto-restart ───────┐
  └────┬────┘                             │
       │                                  │
       ├── feed exhausted ──► STOPPED     │
       ├── SIGTERM ─────────► STOPPED     │
       └── unhandled exception ──► CRASHED┤
                                          │
  ┌─────────┐                             │
  │ CRASHED │─── docker restart policy ──►┘
  └─────────┘
```

## Startup Sequence

1. Configure logging (console + file)
2. Build frozen config, compute fingerprint
3. Build alert router (Log + File + Telegram)
4. Scan for latest checkpoint (if `AUTO_RESUME=true`)
5. Validate checkpoint config fingerprint
6. Build data feed (file-watch or replay)
7. Load HTF data
8. Create `ForwardPaperRunner`
9. Write `health.json` → `"starting"`
10. Send startup alert to Telegram
11. Call `runner.start(resume_from=...)`

## Shutdown Sequence

1. Signal received (SIGINT/SIGTERM)
2. `runner._running = False` (signal handler in ForwardPaperRunner)
3. Current bar finishes processing
4. `runner.stop()`:
   - Final checkpoint saved
   - Session summary written
   - Journal closed
5. Write `health.json` → `"stopped"`
6. Send shutdown alert to Telegram
7. Process exits with code 0

## Crash Sequence

1. Unhandled exception in `runner.start()`
2. Write `health.json` → `"crashed"`
3. Send EMERGENCY alert to Telegram
4. Exception re-raised (process exits with non-zero code)
5. Docker restart policy triggers container restart
6. Recovery flow begins (see `recovery_and_resume_protocol.md`)
