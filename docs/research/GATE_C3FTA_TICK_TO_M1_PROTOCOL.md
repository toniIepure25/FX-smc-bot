# Gate C.3F-TA Tick-To-M1 Protocol

Status: `DEFINED_NOT_EXECUTED_BLOCKED_BY_FROZEN_PLAN_MISSING`

Protocol hash: `e48dd4f3abcfc51b12cd1ec71958c11f4a1eb74115f2190d71191dcb04a9360f`

For each UTC minute and side:

- open is first tick
- high is maximum tick
- low is minimum tick
- close is last tick

Minute buckets are `[minute_start, minute_start + 60s)`, with ticks exactly
on `minute_start` included in that minute. Duplicate timestamps preserve
provider order. No-tick minutes are not forward-filled unless canonical
behavior is independently proven.

This protocol was not used to execute an audit because the frozen 44-window
plan cannot be proven from committed artifacts.
