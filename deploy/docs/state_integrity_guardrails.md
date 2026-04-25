# State Integrity Guardrails

## Config Fingerprint Verification

Every session start and resume computes `config_fingerprint(cfg)` — a SHA-256 hash of the risk and execution configuration. If the saved fingerprint doesn't match, the service:
1. Refuses to resume from the checkpoint
2. Emits a CRITICAL alert to Telegram
3. Starts a fresh session instead

This prevents accidentally running a modified config against a session that was started with different parameters.

## State Version Check

`LiveState.state_version` is currently 3. On load, unknown fields from older versions are silently ignored. If the state version schema changes, the load method handles forward-compatibility gracefully.

## Corruption Detection

- `json.load()` on a corrupted file raises `json.JSONDecodeError` → caught and logged
- Missing required fields produce `TypeError` on dataclass construction → caught
- Zero-equity states (equity=0, initial_equity=0) are valid for fresh starts but suspicious for resumed sessions — logged as a warning

## Operational Guardrails

| Check | When | Action on failure |
|-------|------|-------------------|
| Config fingerprint | Every startup | Refuse resume, CRITICAL alert |
| State file exists | Startup with auto-resume | Start fresh, INFO log |
| State file valid JSON | Startup with auto-resume | Start fresh, ERROR log |
| Equity > 0 | Post-restore | WARNING log (unexpected for paper) |
| bars_processed monotonic | Post-restore | INFO log |
| last_bar_timestamp parseable | Post-restore | Ignore, feed will resync |
