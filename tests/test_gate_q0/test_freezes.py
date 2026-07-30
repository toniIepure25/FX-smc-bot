from fx_smc_bot.research.quant_polarity import (
    ALL_INSTRUMENTS,
    CANDIDATES,
    DEVELOPMENT_INSTRUMENTS,
    FEATURES,
    HYPERPARAMETERS,
    REPLICATION_INSTRUMENTS,
    validate_feature_contract,
)


def test_instrument_universe_is_exact() -> None:
    assert DEVELOPMENT_INSTRUMENTS == ("AUDUSD", "NZDUSD", "USDCAD", "USDCHF")
    assert REPLICATION_INSTRUMENTS == ("EURJPY", "GBPJPY")
    assert len(ALL_INSTRUMENTS) == 6


def test_candidate_family_is_exact_and_unique() -> None:
    candidate_ids = [candidate["candidate_id"] for candidate in CANDIDATES]
    assert candidate_ids == [
        "Q0_INV_SWEEP_V1",
        "Q0_INV_ACCEPTANCE_V1",
        "Q0_INV_LONDON_OR_V1",
        "Q0_INV_NEWYORK_OR_V1",
        "Q0_META_POLARITY_ELASTIC_NET_V1",
    ]
    assert len(candidate_ids) == len(set(candidate_ids)) == 5


def test_feature_contract_is_exact() -> None:
    assert len(FEATURES) == 18
    assert validate_feature_contract(FEATURES)["status"] == "PASS"


def test_hyperparameter_search_is_exact() -> None:
    assert len(HYPERPARAMETERS) == 9
    assert {row["inverse_regularization_c"] for row in HYPERPARAMETERS} == {0.01, 0.1, 1.0}
    assert {row["l1_ratio"] for row in HYPERPARAMETERS} == {0.0, 0.5, 1.0}
