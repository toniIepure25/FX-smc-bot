# P0-R-DCR-A1A Requirement Provenance

Status: `PASS`

## source_resolution

Scientific consequence: Mixing undocumented M1 with tick-derived M1 can change bars and fills.

Operational consequence: Recovery cannot know which local partitions are reusable.

Prospective resolution: `Dukascopy tick/BI5 -> canonical M1 bid/ask -> M5 bid/ask.`

## warm_up

Scientific consequence: Candidates could begin with unequal state history.

Operational consequence: The first eligible signal cannot be determined reproducibly.

Prospective resolution: `max(500, 46 + 288) = 500 M5 bars.`

## exit_horizon

Scientific consequence: Unbounded holds alter costs, risk, and the estimand.

Operational consequence: A deterministic forced-exit event is required.

Prospective resolution: `Earliest SL, TP, session cutoff, FX-week close, or final bar; no carry.`

## session_calendar

Scientific consequence: DST weeks can shift eligible bars and forced exits.

Operational consequence: Certification needs one timezone-aware calendar contract.

Prospective resolution: `08:00-11:00 local IANA sessions; Sunday/Friday 17:00 New York FX week.`

## usdjpy_role

Scientific consequence: Requiring USDJPY would expand data coverage without benchmark necessity.

Operational consequence: USDJPY must not block primary candidate certification.

Prospective resolution: `EURUSD/GBPUSD strategy required; USDJPY optional diagnostic only.`
