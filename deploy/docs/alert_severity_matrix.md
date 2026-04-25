# Alert Severity Matrix

| Event | Severity | Category | Notification | Operator Action Required |
|-------|----------|----------|-------------|-------------------------|
| Service started | INFO | lifecycle | Telegram (silent) | None — verify in daily report |
| Service stopped (graceful) | INFO | lifecycle | Telegram (silent) | Verify intentional |
| Service crashed | EMERGENCY | crash | Telegram (buzz) | Check logs, verify auto-restart |
| Feed gap (weekend) | WARNING | feed_health | Telegram (silent) | None — expected |
| Feed gap (unexpected) | WARNING | feed_health | Telegram (silent) | Investigate data source |
| Feed stale (>6 hours) | WARNING | feed_health | Telegram (silent) | Check data pipeline |
| Risk: active → throttled | WARNING | risk_state | Telegram (silent) | Monitor; expect auto-recovery |
| Risk: active → locked | CRITICAL | risk_state | Telegram (buzz) | Review immediately |
| Risk: active → stopped | CRITICAL | risk_state | Telegram (buzz) | Review; may need manual restart |
| Circuit breaker fire | CRITICAL | risk_state | Telegram (buzz) | Review cause; wait for cooldown |
| Config fingerprint mismatch | CRITICAL | state_integrity | Telegram (buzz) | Investigate config change |
| Drift: PF/WR degraded | WARNING | drift | In daily report | Monitor; may need investigation |
| Candidate rejected (normal) | INFO | (journal only) | None | None |
| Trade fill | INFO | (journal only) | In daily report | None |
| Daily report generated | — | — | Telegram (silent) | Review metrics |
| Weekly report generated | — | — | Telegram (silent) | Comprehensive review |
