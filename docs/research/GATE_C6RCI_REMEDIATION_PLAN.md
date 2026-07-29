# Gate C6-R-CI Remediation Plan

Status: `PASS`

Only non-semantic Ruff remediation is allowed. No scientific artifacts, thresholds, counts, p-values, claim statuses, seals, or manifests may be altered.

- `src/fx_smc_bot/research/intraday_campaign.py:7` `I001`: `IMPORT_ORDER_ONLY`; sort imports without changing imported names
- `src/fx_smc_bot/research/intraday_campaign.py:9` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:12` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:15` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:21` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:22` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:31` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/intraday_campaign.py:79` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/intraday_campaign.py:215` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/intraday_campaign.py:304` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/overfitting.py:48` `B007`: `STYLE_REWRITE`; rename unused loop variable or remove unused enumerate output
- `src/fx_smc_bot/research/placebos.py:12` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/placebos.py:60` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/placebos.py:108` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/placebos.py:129` `B905`: `STYLE_REWRITE`; add strict=False to preserve truncating zip behavior
- `src/fx_smc_bot/research/placebos.py:142` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/placebos.py:200` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/placebos.py:203` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/placebos.py:205` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
- `src/fx_smc_bot/research/prop_simulation.py:9` `I001`: `IMPORT_ORDER_ONLY`; sort imports without changing imported names
- `src/fx_smc_bot/research/prop_simulation.py:158` `B007`: `STYLE_REWRITE`; rename unused loop variable or remove unused enumerate output
- `src/fx_smc_bot/research/statistical_inference.py:11` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/statistical_inference.py:12` `UP035`: `TYPE_ONLY_IMPORT`; remove unused typing import or move to collections.abc if still needed
- `src/fx_smc_bot/research/statistical_inference.py:12` `F401`: `UNUSED_IMPORT`; remove unused import only after tests confirm behavior
- `src/fx_smc_bot/research/statistical_inference.py:308` `E501`: `FORMAT_ONLY`; wrap expression without changing evaluation order
