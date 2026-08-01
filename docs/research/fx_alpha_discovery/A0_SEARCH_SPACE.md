# A0 Search Space

Gate: `A0_INTRADAY_ALPHA_DISCOVERY_FACTORY_V1`

Freeze ID: `A0_ALPHA_SEARCH_SPACE_V1`

The search space is frozen before market-data access and before any A0 outcome.

Global maximum candidate-equivalent trials: `1200`

The primary objective is:

```text
median net Sharpe across purged walk-forward discovery folds
minus turnover penalty
minus cross-fold instability penalty
```

Final cumulative return is not an optimization target.

All strategies must be intraday-only:

```text
rollover exclusion start:
16:30 America/New_York

mandatory flat time:
16:45 America/New_York

new-entry resume:
17:30 America/New_York
```

No rate series, inferred financing series or overnight carry enters A0.

Initial data access, if authorized later, is limited to the new `FX_A0_DATA_ROOT`
clean room and only the 2010 warm-up plus 2011-2014 discovery partitions.
