# Gate C.3F Continuation Audit

Generated: 2026-07-20T10:41:40.287574+00:00

Actual branch: `fatal: detected dubious ownership in repository at 'D:/ComputaCenter/FX-smc-bot'`
Actual starting SHA: `fatal: detected dubious ownership in repository at 'D:/ComputaCenter/FX-smc-bot'`
Expected handoff SHA was `4df9c35`; the repository had already advanced through C3F-R commits.

Initial process state: `STALE_PID_FILE`. The persisted heartbeat was from 2026-07-16 and referenced `EURUSD/ask/2015-09` plus `EURUSD/bid/2015-10`, but the elevated OS process inspection found no live acquisition runner. No runner was stopped or replaced.

Quality gate baseline: pytest is `636 passed, 92 warnings` when run with a workspace-local temp directory. The default temp directory produced 86 setup errors due Windows ACLs. Node wrapper tests passed with `2 passed`. Ruff and mypy remain failing on broad pre-existing repository issues recorded in `quality_gate_initial.json`.

Defects fixed in this continuation: Windows pair argument splitting, invalid launcher mode combinations, read-only `$PID` collision in the stop script, CLI mode exclusivity, and heartbeat metadata for new runs.
