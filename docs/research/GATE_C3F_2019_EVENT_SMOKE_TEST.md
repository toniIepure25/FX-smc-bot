# Gate C.3F — 2019 Event Smoke Test

## Status: DEFERRED — Pending 2019 Certification

Event funnels may only be run after 2019 data is fully acquired and
certified. No event detection, strategy backtest, or alpha computation
has been performed on any data.

## Plan

Once 2019 is certified, run frozen V2 detectors reporting state-transition
funnels only:

### Sweep Reversal
- Liquidity levels → breaches → reclaims → MSS → displacement → FVG →
  intents → fills → expiries → closes

### Acceptance Continuation
- Levels → breaks → acceptance → displacement → FVG → retests →
  intents → fills → invalidations

### Opening Range (London + New York)
- Completed ranges → breakouts → displacement → FVG → retests →
  intents → fills → expiries

### Breakdowns
- By pair, direction, month, session, level type
- Zero-funnel diagnosis if any stage produces zero events

### Constraints
- No strategy PnL, Sharpe, win rate, or profitability
- No parameter tuning or relaxation
- 2023-2025 (holdout) excluded from event detection
