# Q.0-R Execution Certification

Three deterministic smoke replays passed for all four inherited source policies.
Original and inverse schedules are identical; inversion changes economic direction
while preserving entry time, order type, expiry, stop distance, target R, and
session exit. Executable price sides remain ask for long entry, bid for short
entry, bid for long exit, and ask for short exit. Same-bar primary resolution is
adverse-first.

Features stop at signal time, the primary model excludes instrument identity,
outer-test rows never enter fitting, and the 2,680-minute purge plus five-FX-day
embargo remain enforced. Development mode has no replication loader. Date guards
reject the quarantined interval before path resolution, and future prospective
data are unavailable to this gate.

Future-bar perturbation leaves features, decision-time labels, model input,
prediction, action selection, and order intent unchanged. All three replay hashes
are identical, with no runtime errors or reconciliation violations.
