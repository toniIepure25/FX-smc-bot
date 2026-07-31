# Gate F.0 Factor Definitions

The factor family for `FX_CLASSICAL_RISK_PREMIA_V1` is fixed ex ante at exactly
six candidates. It contains no SMC, Acceptance, opening-range, inversion,
polarity, or machine-learning transformation. Prior lineage seals remain closed.

Let `C_t` denote the certified daily research close. A decision executed on day
`t` uses data through `t-1`. `clip(x,-1,1)` is inclusive, and `sign(0)=0`.

## 1. `F0_TSMOM_COMPOSITE_V1`

For `h` in `{21, 63, 126, 252}`, define
`r_h = C_(t-1) / C_(t-1-h) - 1`. The signal is:

```text
mean(sign(r_21), sign(r_63), sign(r_126), sign(r_252))
```

Its possible values are `-1.0, -0.5, 0.0, 0.5, 1.0`.

## 2. `F0_SHORT_TERM_REVERSAL_V1`

Using the five-day close return and the standard deviation of the latest 60
daily close-to-close returns available through `t-1`:

```text
clip(-five_day_return / (sqrt(5) * sixty_day_daily_volatility), -1, 1)
```

## 3. `F0_DUAL_HORIZON_TREND_V1`

Compute recursive close EMAs through `t-1` with spans 50 and 200 trading days
and smoothing `alpha = 2 / (span + 1)`. The signal is:

```text
clip(
    (EMA_50 - EMA_200)
    / (C_(t-1) * sixty_day_daily_volatility * sqrt(252)),
    -1,
    1
)
```

## 4. `F0_DONCHIAN_BREAKOUT_V1`

- Enter long when the previous close is above the previous 55-day high.
- Enter short when the previous close is below the previous 55-day low.
- Exit long when the previous close is below the previous 20-day low.
- Exit short when the previous close is above the previous 20-day high.

The comparator is the certified close for `t-1`. Upper channels are rolling
maxima of certified daily highs and lower channels are rolling minima of
certified daily lows. Their windows end on `t-2`, so the comparator observation
is excluded. The state persists until a frozen exit or opposite-entry condition
occurs.

## 5. `F0_RATE_DIFFERENTIAL_CARRY_V1`

Using only rates eligible under their actual publication/effective timestamps:

```text
clip((base overnight rate - quote overnight rate) / 0.05, -1, 1)
```

## 6. `F0_FIXED_MULTI_FACTOR_V1`

Combine Candidates 1-5 with fixed factor risk-contribution targets:

| Factor | Target |
|---|---:|
| TSMOM | 25% |
| Short-term reversal | 15% |
| Dual-horizon trend | 20% |
| Donchian breakout | 15% |
| Rate-differential carry | 25% |

These are risk-contribution targets, not nominal capital weights, and may not be
optimized. Lookbacks, formulas, family membership, and weights may not change
after outcomes. Undefined denominators or missing inputs produce
`NO_POSITION_CHANGE_WITH_RECORDED_REASON`. This freeze contains no results.
