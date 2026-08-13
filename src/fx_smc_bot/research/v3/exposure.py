"""V3 data-exposure registry: instrument x year x data-type -> exposure level and class.

The mandate is explicit: *do not equate "file existed" with "outcome exposed"*. This
registry records, for every development cell, the strongest exposure that cell has ever
received, and derives:

* ``exposure_class`` -- NEW_DEVELOPMENT (never parsed/inspected), PREVIOUSLY_EXPOSED
  (parsed/feature/outcome/selection-exposed), or SEALED_HOLDOUT (2018+, must stay NONE);
* ``development_role`` -- the frozen role this cell may play in V3.

Known history (seeded truthfully): EURUSD/GBPUSD/USDJPY across 2015-2017 were fully
outcome- and selection-exposed by the V2 discovery, so they are PREVIOUSLY_EXPOSED. The
2015-2017 *calendar window itself* was V2's selection window, so even newly-acquired pairs
on that window are treated as SECONDARY (robustness/engineering) rather than primary, to
foreclose any temporal-snooping concern. The never-used 2010-2014 window is the PRIMARY V3
development region. 2018+ is SEALED and every sealed cell asserts exposure == NONE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import (
    DEVELOPMENT_YEARS,
    INSTRUMENTS,
    SEALED_HOLDOUT_YEARS,
)

# V2's discovery/selection window (calendar window is itself exposed via model selection).
V2_SELECTION_YEARS: tuple[int, ...] = (2015, 2016, 2017)
V2_EXPOSED_INSTRUMENTS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY")
# Primary V3 development window: never used for any prior selection.
PRIMARY_DEVELOPMENT_YEARS: tuple[int, ...] = tuple(
    y for y in DEVELOPMENT_YEARS if y not in V2_SELECTION_YEARS
)


class ExposureLevel(IntEnum):
    NONE = 0
    DOWNLOADED_ONLY = 1
    PARSED = 2
    FEATURE_INSPECTED = 3
    OUTCOME_INSPECTED = 4
    STRATEGY_DESIGN = 5
    MODEL_SELECTION = 6


NEW_DEVELOPMENT = "NEW_DEVELOPMENT_DATA"
PREVIOUSLY_EXPOSED = "PREVIOUSLY_EXPOSED_DEVELOPMENT_DATA"
SEALED_HOLDOUT = "SEALED_HOLDOUT_DATA"

ROLE_PRIMARY = "PRIMARY_DEVELOPMENT"
ROLE_SECONDARY = "SECONDARY_ROBUSTNESS"
ROLE_SEALED = "SEALED_HOLDOUT"


@dataclass(frozen=True, slots=True)
class ExposureCell:
    instrument: str
    year: int
    data_type: str
    exposure_level: ExposureLevel
    exposure_class: str
    development_role: str
    acquired: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "year": self.year,
            "data_type": self.data_type,
            "exposure_level": self.exposure_level.name,
            "exposure_class": self.exposure_class,
            "development_role": self.development_role,
            "acquired": self.acquired,
        }


def _seed_level(instrument: str, year: int) -> ExposureLevel:
    """The strongest exposure a cell has actually received in program history."""

    if year in SEALED_HOLDOUT_YEARS:
        return ExposureLevel.NONE  # sealed: never opened
    if instrument in V2_EXPOSED_INSTRUMENTS and year in V2_SELECTION_YEARS:
        return ExposureLevel.MODEL_SELECTION  # V2 searched + selected here
    return ExposureLevel.NONE  # never acquired/opened before V3


def _classify(instrument: str, year: int, level: ExposureLevel) -> tuple[str, str]:
    if year in SEALED_HOLDOUT_YEARS:
        return SEALED_HOLDOUT, ROLE_SEALED
    exposure_class = PREVIOUSLY_EXPOSED if level >= ExposureLevel.PARSED else NEW_DEVELOPMENT
    # Role is conservative: the whole 2015-2017 window is SECONDARY (V2 selection window),
    # regardless of instrument; only the never-selected 2010-2014 window is PRIMARY.
    role = ROLE_SECONDARY if year in V2_SELECTION_YEARS else ROLE_PRIMARY
    return exposure_class, role


def build_registry(data_type: str = "M1_BIDASK") -> list[ExposureCell]:
    all_years = tuple(sorted(set(DEVELOPMENT_YEARS) | set(SEALED_HOLDOUT_YEARS)))
    cells: list[ExposureCell] = []
    for inst in INSTRUMENTS:
        for year in all_years:
            level = _seed_level(inst.symbol, year)
            exposure_class, role = _classify(inst.symbol, year, level)
            acquired = level >= ExposureLevel.DOWNLOADED_ONLY
            cells.append(
                ExposureCell(
                    instrument=inst.symbol,
                    year=year,
                    data_type=data_type,
                    exposure_level=level,
                    exposure_class=exposure_class,
                    development_role=role,
                    acquired=acquired,
                )
            )
    return cells


def assert_holdout_unexposed(cells: list[ExposureCell]) -> None:
    """Fail loudly if any sealed cell records exposure above NONE."""

    violations = [
        c for c in cells
        if c.year in SEALED_HOLDOUT_YEARS and c.exposure_level != ExposureLevel.NONE
    ]
    if violations:
        raise AssertionError(
            f"V3_EXPOSURE_REGISTRY: {len(violations)} sealed holdout cells record exposure "
            f"> NONE; holdout integrity violated."
        )


def exposure_registry_payload() -> dict[str, Any]:
    cells = build_registry()
    assert_holdout_unexposed(cells)
    by_class: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for c in cells:
        by_class[c.exposure_class] = by_class.get(c.exposure_class, 0) + 1
        by_role[c.development_role] = by_role.get(c.development_role, 0) + 1
    return {
        "artifact_id": "V3_EXPOSURE_REGISTRY_V1",
        "data_type": "M1_BIDASK",
        "primary_development_years": list(PRIMARY_DEVELOPMENT_YEARS),
        "secondary_robustness_years": list(V2_SELECTION_YEARS),
        "sealed_holdout_years": list(SEALED_HOLDOUT_YEARS),
        "cell_count": len(cells),
        "counts_by_exposure_class": by_class,
        "counts_by_development_role": by_role,
        "sealed_cells_all_none": True,
        "2018_plus_market_or_outcome_files_opened": 0,
        "cells": [c.as_dict() for c in cells],
    }


def exposure_registry_hash() -> str:
    return canonical_hash(exposure_registry_payload())
