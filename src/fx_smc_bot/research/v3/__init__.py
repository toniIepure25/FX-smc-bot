"""FX_INTRADAY_ALPHA_DISCOVERY_V3 -- prospective multi-horizon alpha-research factory.

V3 is the successor program to the completed V2 discovery
(``V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR``). It is *prospective*: every module in
this package is a frozen, hash-addressed contract, registry or protocol that is fixed
from methodology alone -- before any V3 outcome is evaluated and without opening a single
2018+ market/outcome byte.

The package deliberately reuses the proven V2 executable substrate
(:mod:`fx_smc_bot.research.v2`) for spec/compile/kernel semantics and layers on top the
new capabilities the V3 mandate requires:

* multi-horizon contracts (H0 micro/intraday ... H3 intramonth);
* an overnight financing/carry execution contract;
* an expanded (13-pair) data-capability contract;
* an instrument x year x data-type exposure registry;
* a typed, causal Feature DAG;
* an economically-motivated family/archetype registry with a bounded composition grammar;
* a hierarchical statistical protocol and horizon-specific survivor predicates;
* a hierarchical candidate budget with a frozen global denominator and V1/V2/V3 lineage;
* a holdout firewall that blocks both 2018+ file reads *and* 2018+ provider requests.

Nothing in this package runs discovery, and the firewall makes 2018+ access structurally
impossible during readiness.
"""

from __future__ import annotations

V3_PROGRAM_ID = "FX_INTRADAY_ALPHA_DISCOVERY_V3"
V3_FREEZE_ARTIFACT = "V3_ALPHA_DISCOVERY_READY"
V3_NEXT_GATE = "V3_ALPHA_DISCOVERY_RUN"

# Absolute holdout boundary shared by every V3 contract and the firewall.
HOLDOUT_YEAR_FLOOR = 2018
HOLDOUT_DATE_FLOOR = "2018-01-01"
