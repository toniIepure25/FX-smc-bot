# Gate F0-RP-E2E Rate Alignment

Alignment is fixed at `17:05 America/New_York` and uses calendar version
`F0RPE2E_RATE_CALENDARS_V2`. The eight named calendars are explicit, including
historical exceptional closures required by the authorized 2010-2022 range.

Selection requires membership in the requested dataset freeze, a pinned passing
certification, a valid series/calendar identity, an observation date no later
than the trading day, and publication/effective availability no later than the
strategy timestamp. Carry-forward uses only the last legally available rate.
There is no interpolation or backward fill.

The EUR transition is enforced as EONIA through 2019-09-30 and ESTR from
2019-10-01, with wrong-regime or overlapping input rejected. Synthetic tests
passed; no official daily rate panel was generated after the prospective stop.
