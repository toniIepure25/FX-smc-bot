"""Official, side-effect-free financing-rate adapter implementations."""

from fx_smc_bot.research.rate_sources.bank_of_canada import (
    BankOfCanadaAdapter,
    BankOfCanadaAdapterV2,
)
from fx_smc_bot.research.rate_sources.bank_of_england import (
    BankOfEnglandSoniaAdapter,
    BankOfEnglandSoniaAdapterV2,
)
from fx_smc_bot.research.rate_sources.bank_of_japan import (
    BankOfJapanCallRateAdapter,
    BankOfJapanCallRateAdapterV2,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient
from fx_smc_bot.research.rate_sources.ecb import (
    EcbEoniaEstrAdapter,
    EcbEoniaEstrAdapterV2,
    EcbEoniaEstrAdapterV3,
)
from fx_smc_bot.research.rate_sources.new_york_fed import (
    NewYorkFedEffrAdapter,
    NewYorkFedEffrAdapterV2,
)
from fx_smc_bot.research.rate_sources.rba import RbaCashRateAdapter, RbaCashRateAdapterV2
from fx_smc_bot.research.rate_sources.saron import Saron18Adapter, Saron18AdapterV2

OFFICIAL_RATE_ADAPTERS = (
    NewYorkFedEffrAdapter,
    EcbEoniaEstrAdapter,
    BankOfEnglandSoniaAdapter,
    RbaCashRateAdapter,
    BankOfJapanCallRateAdapter,
    BankOfCanadaAdapter,
    Saron18Adapter,
)

OFFICIAL_RATE_ADAPTERS_V2 = (
    NewYorkFedEffrAdapterV2,
    EcbEoniaEstrAdapterV2,
    BankOfEnglandSoniaAdapterV2,
    RbaCashRateAdapterV2,
    BankOfJapanCallRateAdapterV2,
    BankOfCanadaAdapterV2,
    Saron18AdapterV2,
)

__all__ = [
    "BankOfCanadaAdapter",
    "BankOfCanadaAdapterV2",
    "BankOfEnglandSoniaAdapter",
    "BankOfEnglandSoniaAdapterV2",
    "BankOfJapanCallRateAdapter",
    "BankOfJapanCallRateAdapterV2",
    "EcbEoniaEstrAdapter",
    "EcbEoniaEstrAdapterV2",
    "EcbEoniaEstrAdapterV3",
    "NewYorkFedEffrAdapter",
    "NewYorkFedEffrAdapterV2",
    "OFFICIAL_RATE_ADAPTERS",
    "OFFICIAL_RATE_ADAPTERS_V2",
    "OfficialRateSnapshotClient",
    "RbaCashRateAdapter",
    "RbaCashRateAdapterV2",
    "Saron18Adapter",
    "Saron18AdapterV2",
]
