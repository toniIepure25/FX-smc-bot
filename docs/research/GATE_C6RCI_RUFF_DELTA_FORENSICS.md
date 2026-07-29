# Gate C6-R-CI Ruff Delta Forensics

Target Ruff findings: `99`

HEAD Ruff findings before remediation: `124`

New-on-branch findings: `25`

Ambiguous findings: `0`

- `src/fx_smc_bot/research/intraday_campaign.py:7:1` `I001` Import block is un-sorted or un-formatted | intro `13a57db1f950` | risk `IMPORT_ORDER_ONLY`
- `src/fx_smc_bot/research/intraday_campaign.py:9:8` `F401` `hashlib` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:12:25` `F401` `dataclasses.asdict` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:15:25` `F401` `typing.Literal` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:21:5` `F401` `fx_smc_bot.config.PAIR_PIP_INFO` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:22:5` `F401` `fx_smc_bot.config.TIMEFRAME_MINUTES` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:31:47` `F401` `fx_smc_bot.domain.ClosedTrade` imported but unused | intro `13a57db1f950` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/intraday_campaign.py:79:101` `E501` Line too long (102 > 100) | intro `13a57db1f950` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/intraday_campaign.py:215:101` `E501` Line too long (102 > 100) | intro `13a57db1f950` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/intraday_campaign.py:304:101` `E501` Line too long (103 > 100) | intro `13a57db1f950` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/overfitting.py:48:9` `B007` Loop control variable `rank` not used within loop body | intro `2112d7b584a2` | risk `STYLE_REWRITE`
- `src/fx_smc_bot/research/placebos.py:12:20` `F401` `typing.Literal` imported but unused | intro `708e38594e85` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/placebos.py:60:101` `E501` Line too long (113 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/placebos.py:108:101` `E501` Line too long (113 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/placebos.py:129:30` `B905` `zip()` without an explicit `strict=` parameter | intro `708e38594e85` | risk `STYLE_REWRITE`
- `src/fx_smc_bot/research/placebos.py:142:101` `E501` Line too long (113 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/placebos.py:200:101` `E501` Line too long (136 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/placebos.py:203:101` `E501` Line too long (131 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/placebos.py:205:101` `E501` Line too long (111 > 100) | intro `708e38594e85` | risk `FORMAT_ONLY`
- `src/fx_smc_bot/research/prop_simulation.py:9:1` `I001` Import block is un-sorted or un-formatted | intro `12f45b03dd48` | risk `IMPORT_ORDER_ONLY`
- `src/fx_smc_bot/research/prop_simulation.py:158:9` `B007` Loop control variable `i` not used within loop body | intro `12f45b03dd48` | risk `STYLE_REWRITE`
- `src/fx_smc_bot/research/statistical_inference.py:11:36` `F401` `dataclasses.field` imported but unused | intro `2112d7b584a2` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/statistical_inference.py:12:1` `UP035` Import from `collections.abc` instead: `Sequence` | intro `2112d7b584a2` | risk `TYPE_ONLY_IMPORT`
- `src/fx_smc_bot/research/statistical_inference.py:12:20` `F401` `typing.Sequence` imported but unused | intro `2112d7b584a2` | risk `UNUSED_IMPORT`
- `src/fx_smc_bot/research/statistical_inference.py:308:101` `E501` Line too long (122 > 100) | intro `13a57db1f950` | risk `FORMAT_ONLY`
