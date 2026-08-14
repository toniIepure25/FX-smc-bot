"""Frozen V3 portfolio-construction contract.

Portfolio rules are frozen pre-outcome so a portfolio layer can never be used to launder a
weak individual signal into significance. Both individual-alpha evidence and
portfolio-combination evidence must be reported separately; these caps bound the combination.
Currencies are drawn from the capability contract so net-currency exposure is well-defined.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import CURRENCIES

PORTFOLIO_CONTRACT: dict[str, Any] = {
    "artifact_id": "V3_PORTFOLIO_CONTRACT_V1",
    "frozen_pre_outcome": True,
    "max_simultaneous_positions": 8,
    "max_gross_exposure": 4.0,          # sum |weight|, in risk units
    "max_per_currency_exposure": 2.0,   # sum of signed legs touching one currency
    "max_net_usd_exposure": 2.0,
    "max_net_jpy_exposure": 1.5,
    "max_duplicated_correlated_bets": 2,
    "volatility_scaling": "inverse_realized_vol_causal",
    "concentration_limit_per_family": 0.35,   # max fraction of gross from one family
    "currencies": list(CURRENCIES),
    "reporting_rule": "report individual-alpha AND portfolio-combination evidence separately; "
                      "portfolio construction may not hide a weak individual signal.",
}


def portfolio_payload() -> dict[str, Any]:
    payload = dict(PORTFOLIO_CONTRACT)
    payload["portfolio_hash"] = canonical_hash(PORTFOLIO_CONTRACT)
    return payload


def portfolio_hash() -> str:
    return canonical_hash(PORTFOLIO_CONTRACT)
