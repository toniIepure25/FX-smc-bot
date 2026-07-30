from datetime import date

import pytest

from fx_smc_bot.research.quant_polarity import (
    BoundaryViolationError,
    OrderIntent,
    authorize_explicit_path,
    authorize_request,
    authorize_training_source,
    invert_order_intent,
)


@pytest.mark.parametrize("instrument", ["EURUSD", "GBPUSD", "USDJPY"])
def test_old_lineage_instruments_are_rejected(instrument: str) -> None:
    with pytest.raises(BoundaryViolationError):
        authorize_request(instrument, date(2015, 1, 1), date(2015, 1, 31), "development")


@pytest.mark.parametrize("mode", ["development", "replication"])
def test_holdout_provider_requests_are_rejected(mode: str) -> None:
    with pytest.raises(BoundaryViolationError):
        authorize_request("AUDUSD", date(2023, 1, 1), date(2023, 1, 31), mode)


@pytest.mark.parametrize(
    "path",
    [
        "market/2023/AUDUSD",
        "market/confirmatory_holdout/AUDUSD",
        "market/_local_ledgers/trades.parquet",
        "market/EURUSD/2019.parquet",
    ],
)
def test_forbidden_market_paths_are_rejected(path: str) -> None:
    with pytest.raises(BoundaryViolationError):
        authorize_explicit_path(path, "development")


def test_replication_partition_is_rejected_in_development_mode() -> None:
    with pytest.raises(BoundaryViolationError):
        authorize_explicit_path("market/AUDUSD/2020-01.parquet", "development")


@pytest.mark.parametrize(
    "path",
    [
        "results/gate_p0rdcra1a/candidate_results.json",
        "results/gate_p1/final_claim_matrix.json",
        "local/strategy_alpha/row_ledger.parquet",
    ],
)
def test_previous_results_cannot_be_used_as_training_labels(path: str) -> None:
    with pytest.raises(BoundaryViolationError):
        authorize_training_source(path, "construct training labels")


def test_inversion_changes_direction_only() -> None:
    original = OrderIntent(
        instrument="AUDUSD",
        direction="LONG",
        signal_time="2019-01-02T08:30:00Z",
        order_type="STOP",
        entry_price=0.701,
        stop_distance=0.001,
        target_r=2.0,
        expiry_bars=3,
        session_cutoff="2019-01-02T11:00:00Z",
    )
    inverse = invert_order_intent(original)
    assert inverse.direction == "SHORT"
    assert inverse.__dict__ | {"direction": original.direction} == original.__dict__
