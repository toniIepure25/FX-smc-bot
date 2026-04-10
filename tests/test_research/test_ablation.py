"""Tests for strategy ablation and decomposition infrastructure."""

from __future__ import annotations

import pytest

from fx_smc_bot.config import AlphaConfig, AppConfig
from fx_smc_bot.research.ablation import (
    AblationResult,
    AblationVariant,
    run_family_ablation,
    run_filter_ablation,
    run_scoring_ablation,
)
from tests.helpers import make_synthetic_data


class TestAblationVariant:
    def test_ablation_variant_creation(self) -> None:
        v = AblationVariant(
            name="test",
            description="test variant",
            config_override={"alpha.enabled_families": ["sweep_reversal"]},
        )
        assert v.name == "test"
        assert v.metrics is None

    def test_ablation_result_summary(self) -> None:
        result = AblationResult(campaign_name="test")
        assert "test" in result.campaign_name
        table = result.summary_table()
        assert "Variant" in table


class TestFamilyAblation:
    def test_family_ablation_produces_variants(self) -> None:
        config = AppConfig()
        config.alpha.enabled_families = ["sweep_reversal", "bos_continuation"]
        data = make_synthetic_data()

        result = run_family_ablation(config, data)

        assert result.campaign_name == "family_ablation"
        assert len(result.variants) >= 3  # baseline + 2 isolation + up to 2 leave-one-out
        names = [v.name for v in result.variants]
        assert "all_families" in names
        assert "only_sweep_reversal" in names
        assert "only_bos_continuation" in names


class TestScoringAblation:
    def test_scoring_ablation_produces_variants(self) -> None:
        config = AppConfig()
        data = make_synthetic_data()

        result = run_scoring_ablation(config, data)

        assert result.campaign_name == "scoring_ablation"
        assert len(result.variants) >= 5
        names = [v.name for v in result.variants]
        assert "structure_only" in names
        assert "default" in names


class TestFilterAblation:
    def test_filter_ablation_sweeps_thresholds(self) -> None:
        config = AppConfig()
        data = make_synthetic_data()

        result = run_filter_ablation(config, data)

        assert result.campaign_name == "filter_ablation"
        assert len(result.variants) >= 6
