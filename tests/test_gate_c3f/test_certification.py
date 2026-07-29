"""Tests for scope-aware certification semantics.

Proves that:
- 2023-06 cannot receive development certification
- One good month cannot certify 2015-2019
- A development split with missing years cannot pass
- Structural validity and research sufficiency are separate
- Holdout partitions cannot be labeled development data
"""
from __future__ import annotations

import pytest

from fx_smc_bot.data.certification import (
    DEVELOPMENT_YEARS,
    DatasetCertification,
    DevelopmentDatasetCertResult,
    PairYearCertResult,
    PartitionCertification,
    PartitionQuality,
    certify_development_dataset,
    certify_pair_year,
    certify_partition,
)


class TestPartitionCertification:
    def test_valid_partition_gets_structural_validation(self) -> None:
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            negative_spread_count=0, invalid_ohlc_count=0,
            duplicate_count=0, parquet_roundtrip_ok=True,
            resample_ok=True, checksum="abc123",
        )
        result = certify_partition(q)
        assert result.certification == PartitionCertification.STRUCTURALLY_VALIDATED
        assert not result.reasons

    def test_negative_spreads_cause_rejection(self) -> None:
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            negative_spread_count=5, parquet_roundtrip_ok=True,
            resample_ok=True,
        )
        result = certify_partition(q)
        assert result.certification == PartitionCertification.REJECTED
        assert any("negative" in r for r in result.reasons)

    def test_low_alignment_causes_rejection(self) -> None:
        q = PartitionQuality(
            pair="GBPUSD", year=2023, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=10000,
            parquet_roundtrip_ok=True, resample_ok=True,
        )
        result = certify_partition(q)
        assert result.certification == PartitionCertification.REJECTED
        assert any("alignment" in r for r in result.reasons)

    def test_missing_bid_data_rejected(self) -> None:
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=1,
            bid_rows=0, ask_rows=30000, joined_rows=0,
        )
        result = certify_partition(q)
        assert result.certification == PartitionCertification.REJECTED

    def test_empty_partition_exploratory_only(self) -> None:
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=1,
            bid_rows=0, ask_rows=0, joined_rows=0,
        )
        result = certify_partition(q)
        assert result.certification == PartitionCertification.EXPLORATORY_ONLY


class TestHoldoutCannotBeDevelopment:
    def test_2023_06_holdout_scope(self) -> None:
        """2023-06 must get holdout scope, never development."""
        q = PartitionQuality(
            pair="EURUSD", year=2023, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            parquet_roundtrip_ok=True, resample_ok=True,
        )
        result = certify_partition(q)
        assert "holdout" in result.scope
        assert result.certification != DatasetCertification.CERTIFIED_FOR_DEVELOPMENT

    def test_holdout_year_not_in_development_years(self) -> None:
        for year in [2023, 2024, 2025]:
            assert year not in DEVELOPMENT_YEARS

    def test_development_years_are_2015_to_2019(self) -> None:
        assert list(DEVELOPMENT_YEARS) == [2015, 2016, 2017, 2018, 2019]


class TestOneMonthCannotCertifyDataset:
    def test_single_month_pair_year_fails(self) -> None:
        """One good month cannot certify a pair-year."""
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            parquet_roundtrip_ok=True, resample_ok=True,
        )
        partition_result = certify_partition(q)
        pair_year = certify_pair_year("EURUSD", 2019, [partition_result])
        assert not pair_year.passed
        assert any("valid months" in r for r in pair_year.reasons)

    def test_single_month_dataset_fails(self) -> None:
        """One good month cannot certify the development dataset."""
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            parquet_roundtrip_ok=True, resample_ok=True,
        )
        pr = certify_partition(q)
        pyr = certify_pair_year("EURUSD", 2019, [pr])
        result = certify_development_dataset({"EURUSD": [pyr]})
        assert result.certification == DatasetCertification.REJECTED
        assert len(result.reasons) > 0


class TestMissingYearsBlockCertification:
    def test_missing_2015_2018_blocks_development(self) -> None:
        """Development dataset with only 2019 cannot pass."""
        partitions_2019 = []
        for m in range(1, 13):
            q = PartitionQuality(
                pair="EURUSD", year=2019, month=m,
                bid_rows=30000, ask_rows=30000, joined_rows=29500,
                parquet_roundtrip_ok=True, resample_ok=True,
            )
            partitions_2019.append(certify_partition(q))

        pyr_2019 = certify_pair_year("EURUSD", 2019, partitions_2019)
        assert pyr_2019.passed

        result = certify_development_dataset({"EURUSD": [pyr_2019]})
        assert result.certification == DatasetCertification.REJECTED
        for year in [2015, 2016, 2017, 2018]:
            assert any(str(year) in r for r in result.reasons)

    def test_all_five_years_can_pass(self) -> None:
        """All five development years with good data can certify."""
        pair_year_results = []
        for year in range(2015, 2020):
            partitions = []
            for m in range(1, 13):
                q = PartitionQuality(
                    pair="EURUSD", year=year, month=m,
                    bid_rows=30000, ask_rows=30000, joined_rows=29500,
                    parquet_roundtrip_ok=True, resample_ok=True,
                )
                partitions.append(certify_partition(q))
            pair_year_results.append(
                certify_pair_year("EURUSD", year, partitions),
            )

        result = certify_development_dataset({"EURUSD": pair_year_results})
        assert result.certification == DatasetCertification.CERTIFIED_FOR_DEVELOPMENT
        assert not result.reasons


class TestStructuralVsResearchSufficiency:
    def test_structurally_valid_but_not_research_sufficient(self) -> None:
        """A single structurally valid partition is not research sufficient."""
        q = PartitionQuality(
            pair="EURUSD", year=2019, month=6,
            bid_rows=30000, ask_rows=30000, joined_rows=29500,
            parquet_roundtrip_ok=True, resample_ok=True,
        )
        part_result = certify_partition(q)
        assert part_result.certification == PartitionCertification.STRUCTURALLY_VALIDATED

        pair_year = certify_pair_year("EURUSD", 2019, [part_result])
        assert not pair_year.passed

    def test_pair_year_scope_does_not_inherit_to_dataset(self) -> None:
        """Passing pair-year does not auto-certify dataset."""
        partitions = []
        for m in range(1, 13):
            q = PartitionQuality(
                pair="EURUSD", year=2019, month=m,
                bid_rows=30000, ask_rows=30000, joined_rows=29500,
                parquet_roundtrip_ok=True, resample_ok=True,
            )
            partitions.append(certify_partition(q))

        pyr = certify_pair_year("EURUSD", 2019, partitions)
        assert pyr.passed

        ds = certify_development_dataset({"EURUSD": [pyr]})
        assert ds.certification == DatasetCertification.REJECTED
