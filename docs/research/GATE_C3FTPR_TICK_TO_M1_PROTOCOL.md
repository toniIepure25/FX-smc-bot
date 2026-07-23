# Gate C.3F-TPR Tick-To-M1 Protocol

Status: `FROZEN_BEFORE_AUDIT_EXECUTION`

Protocol hash: `058c413b99bcceb8cf87e10282b4c6b15edc8ccd1a3663dc0a9f5fd63d8e683f`

For each UTC minute and side:

- open = first tick
- high = maximum tick
- low = minimum tick
- close = last tick

Minute and audit windows are left-closed/right-open. Ticks exactly on a
minute boundary belong to the minute starting at that timestamp. Duplicate
timestamps preserve provider/input order. EURUSD and GBPUSD use scale
`100000`; USDJPY uses scale `1000`. No-tick minutes are not forward-filled.

This protocol is frozen before any C3F-TPR tick-window download or comparison.
