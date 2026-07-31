"""Official, side-effect-free financing-rate adapter implementations."""

from fx_smc_bot.research.rate_sources.bank_of_canada import BankOfCanadaAdapter
from fx_smc_bot.research.rate_sources.bank_of_england import BankOfEnglandSoniaAdapter
from fx_smc_bot.research.rate_sources.bank_of_japan import BankOfJapanCallRateAdapter
from fx_smc_bot.research.rate_sources.ecb import EcbEoniaEstrAdapter
from fx_smc_bot.research.rate_sources.new_york_fed import NewYorkFedEffrAdapter
from fx_smc_bot.research.rate_sources.rba import RbaCashRateAdapter
from fx_smc_bot.research.rate_sources.saron import Saron18Adapter

OFFICIAL_RATE_ADAPTERS = (
    NewYorkFedEffrAdapter,
    EcbEoniaEstrAdapter,
    BankOfEnglandSoniaAdapter,
    RbaCashRateAdapter,
    BankOfJapanCallRateAdapter,
    BankOfCanadaAdapter,
    Saron18Adapter,
)

__all__ = [
    "BankOfCanadaAdapter",
    "BankOfEnglandSoniaAdapter",
    "BankOfJapanCallRateAdapter",
    "EcbEoniaEstrAdapter",
    "NewYorkFedEffrAdapter",
    "OFFICIAL_RATE_ADAPTERS",
    "RbaCashRateAdapter",
    "Saron18Adapter",
]
