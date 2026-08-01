# Gate A0 Final Decision Memo

Gate: `A0_INTRADAY_ALPHA_DISCOVERY_FACTORY_V1`

Decision: `BLOCKED_BY_A0_MARKET_DATA_ACCESS`

A0 created a new independent intraday FX alpha discovery lineage:

```text
program_id:
FX_INTRADAY_ALPHA_DISCOVERY_V1

lineage_id:
FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1
```

The classical-factor lineage remains blocked at
`BLOCKED_BY_BOJ_REVISION_PROVENANCE`. That conclusion is unchanged.

A0 is independent of overnight financing rates. Its strategies must open and
close intraday, hold no position through the New York rollover exclusion, use no
official interest-rate series, use no inferred financing series and use no
overnight carry.

The 12 alpha families, feature registry, target registry, trial budget and
search space were frozen before any A0 market-data access or outcome. The global
trial budget is `1200` candidate-equivalent trials.

The run stopped at discovery market-data acquisition because `FX_A0_DATA_ROOT`
was not configured. The gate requires a completely new clean-room root and also
prohibits inspecting prior market-data roots. Therefore no Dukascopy BI5
requests were sent, no M1/M5 partitions were certified, no trials were
registered for empirical execution and no alpha result exists.

The quarantined 2023-2025 interval was not accessed. NZD and NZDUSD were not
accessed. No rate or financing series was accessed. No position crossed
rollover because no execution was run.

No result authorizes live capital, paper trading, a pull request or a merge.
