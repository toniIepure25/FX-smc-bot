# Gate C.4 Event Definition Audit

Status: PREREGISTERED

Runtime universe: `USDJPY` only, enforced by the CRSF pair-scoped freeze.

## Event Families
- `liquidity_sweep_mss_fvg_reversal`: primary 60 minutes; prior-day high/low liquidity sweep, same-bar close reclaim, direction opposite the swept side
- `liquidity_acceptance_fvg_continuation`: primary 120 minutes; two consecutive closes beyond prior-day high/low liquidity level, direction with the break
- `opening_range_london`: primary 60 minutes; first London opening-range displacement close before cutoff
- `opening_range_new_york`: primary 60 minutes; first New York opening-range displacement close before cutoff

## Definition Hashes
Config hash: `736428ec62cfb04efa5b5de6dc759f50c97b71bfa585f57c6b03a451c169b8f1`

- `sweep_source`: `171cea6f92bf492ada5cdd5e5e05681a5fc84404f8b44ea557a8de68dc16b22a`
- `acceptance_source`: `831aada49cc661a2a30a2dce030b6e9d4f2fbc01af0b0813d00aae47c4b3efb0`
- `opening_range_source`: `851ca8a9eec8a4f7e58984261f100ce1652665a8e564f57d1efce7e1b818d192`
- `sweep_config`: `342def379cd60590b69b1072468e7a0014657382cb8b2dfd4dffd24a1ce8bc7b`
- `acceptance_config`: `f668b91ab7f275b438b4079d160d81e755e514e7c7d0e4571626a19ff6c9c875`
- `opening_range_config`: `0a9a05b4137d83968cedc944e41dfbb583f74780274db848da0d1f5236e3ac77`

## Audit Finding
The historical YAML configs still list EURUSD and GBPUSD alongside USDJPY. Gate C.4
does not inherit that universe; it narrows runtime access to the certified CRSF
universe, `USDJPY`.
