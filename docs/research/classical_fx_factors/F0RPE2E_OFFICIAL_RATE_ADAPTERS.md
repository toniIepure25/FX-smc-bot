# Gate F0-RP-E2E Official Rate Adapters

Seven bounded, authorized adapters now exist for USD EFFR, the deterministic
EUR EONIA/ESTR split, GBP SONIA, AUD cash rate, the JPY final overnight call
rate, CAD V39079 policy events, and the selected CHF 18:00 SARON fixing.

The shared contracts keep observation date, publication time, effective time,
strategy availability, revisions, parser identity, source hash, and retrieval
time distinct. Retrieval time is provenance only. An authorized HTTP client
rejects redirects and non-official hosts, hashes response bytes before parsing,
and atomically stores immutable payload snapshots outside the Git index.

Synthetic schema, publication, effective-time, revision, timezone, calendar,
as-of, and three-run determinism tests passed. Synthetic certification does not
promote the official adapter stage. Official endpoint certification was not run
after the prospective-integrity stop, so no adapter is represented as officially
certified and no provider request or source snapshot exists.
