"""Executable ablation framework for intraday SMC strategies.

Each ablation is a typed configuration override that:
- Resolves against an existing config field
- Fails loudly for invalid paths
- Produces a unique resolved config hash
- Modifies the actual runtime behavior
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AblationSpec:
    """A single ablation override."""
    name: str
    config_path: str
    override_value: Any
    description: str = ""


CANONICAL_ABLATIONS: dict[str, list[AblationSpec]] = {
    "liquidity_sweep_mss_fvg_reversal": [
        AblationSpec(
            name="no_displacement",
            config_path="displacement_body_ratio",
            override_value=0.0,
            description="Disable displacement requirement",
        ),
        AblationSpec(
            name="no_fvg",
            config_path="fvg_min_atr",
            override_value=0.0,
            description="Disable FVG minimum size requirement",
        ),
        AblationSpec(
            name="no_htf_filter",
            config_path="eligible_level_types",
            override_value=[
                "equal_highs", "equal_lows",
                "session_high", "session_low",
                "prior_day_high", "prior_day_low",
                "prior_week_high", "prior_week_low",
            ],
            description="Accept all level types (no HTF filtering)",
        ),
        AblationSpec(
            name="conservative_entry",
            config_path="entry_fvg_pct",
            override_value=0.25,
            description="Enter at 25% of FVG instead of 50%",
        ),
        AblationSpec(
            name="aggressive_entry",
            config_path="entry_fvg_pct",
            override_value=0.75,
            description="Enter at 75% of FVG instead of 50%",
        ),
        AblationSpec(
            name="tight_target",
            config_path="target_r",
            override_value=1.5,
            description="1.5R target instead of 2.0R",
        ),
        AblationSpec(
            name="wide_target",
            config_path="target_r",
            override_value=3.0,
            description="3.0R target instead of 2.0R",
        ),
    ],
    "liquidity_acceptance_fvg_continuation": [
        AblationSpec(
            name="no_displacement",
            config_path="displacement_body_ratio",
            override_value=0.0,
            description="Disable displacement requirement",
        ),
        AblationSpec(
            name="no_fvg",
            config_path="fvg_min_atr",
            override_value=0.0,
            description="Disable FVG minimum size requirement",
        ),
        AblationSpec(
            name="single_acceptance",
            config_path="acceptance_consecutive_closes",
            override_value=1,
            description="Require only 1 close instead of 2",
        ),
        AblationSpec(
            name="conservative_entry",
            config_path="entry_fvg_pct",
            override_value=0.25,
            description="Enter at 25% of FVG",
        ),
        AblationSpec(
            name="tight_target",
            config_path="target_r",
            override_value=1.5,
            description="1.5R target",
        ),
    ],
    "opening_range_displacement_fvg_retest": [
        AblationSpec(
            name="no_displacement",
            config_path="displacement_body_ratio",
            override_value=0.0,
            description="Disable displacement requirement",
        ),
        AblationSpec(
            name="no_fvg",
            config_path="fvg_min_atr",
            override_value=0.0,
            description="Disable FVG minimum size requirement",
        ),
        AblationSpec(
            name="conservative_entry",
            config_path="entry_fvg_pct",
            override_value=0.25,
            description="Enter at 25% of FVG",
        ),
        AblationSpec(
            name="tight_target",
            config_path="target_r",
            override_value=1.5,
            description="1.5R target",
        ),
    ],
}


def apply_ablation(
    base_config: dict[str, Any],
    ablation: AblationSpec,
) -> dict[str, Any]:
    """Apply a single ablation to a config dict. Raises for invalid paths."""
    config = copy.deepcopy(base_config)

    parts = ablation.config_path.split(".")
    target = config
    for part in parts[:-1]:
        if part not in target:
            raise KeyError(
                f"Invalid ablation path '{ablation.config_path}': "
                f"key '{part}' not found in config"
            )
        target = target[part]

    final_key = parts[-1]
    if final_key not in target:
        raise KeyError(
            f"Invalid ablation path '{ablation.config_path}': "
            f"key '{final_key}' not found in config. "
            f"Available: {sorted(target.keys())}"
        )

    target[final_key] = ablation.override_value
    return config


def ablation_config_hash(config: dict[str, Any]) -> str:
    """Produce a unique hash for a resolved ablation config."""
    raw = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def generate_ablation_configs(
    family: str,
    base_config: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str]]:
    """Generate all ablation variants for a family.

    Returns list of (ablation_name, config_dict, config_hash).
    """
    ablations = CANONICAL_ABLATIONS.get(family, [])
    results = []

    full_hash = ablation_config_hash(base_config)
    results.append(("full_model", base_config, full_hash))

    for abl in ablations:
        try:
            variant = apply_ablation(base_config, abl)
            h = ablation_config_hash(variant)
            results.append((abl.name, variant, h))
        except KeyError:
            raise

    return results
