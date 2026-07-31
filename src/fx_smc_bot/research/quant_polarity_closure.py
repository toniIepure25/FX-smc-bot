"""Quant-polarity closure validation using committed aggregate artifacts only."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

PROGRAM_ID = "FX_QUANT_POLARITY_META_V2"
LINEAGE_ID = "FX_QUANT_EDGE_DISCOVERY_LINEAGE_V2"
SEAL_ID = "FX_QUANT_POLARITY_META_V2_LINEAGE_SEAL_V1"
SEAL_STATUS = "CLOSED_NO_DEVELOPMENT_CANDIDATE_NO_REPLICATION"
CLOSURE_ID = "FX_QUANT_POLARITY_META_V2_CLOSURE_V1"
QUARANTINE_ID = "FX_QUANT_POLARITY_META_V2_POSTHOC_QUARANTINE_V1"
QUARANTINE_STATUS = "OUTCOME_INFORMED_NOT_CONFIRMABLE_IN_CURRENT_LINEAGE"
Q0R_DECISION = "Q0R_NO_CANDIDATE_SURVIVED_INDEPENDENT_REPLICATION"
Q1_CREATED_DECISION = "Q1_QUANT_POLARITY_PROGRAM_CLOSED_PR_CREATED_READY_FOR_REVIEW"
Q1_EXISTING_DECISION = (
    "Q1_QUANT_POLARITY_PROGRAM_CLOSED_PR_ALREADY_EXISTS_READY_FOR_REVIEW"
)

CANDIDATE_IDS = (
    "Q0_INV_SWEEP_V1",
    "Q0_INV_ACCEPTANCE_V1",
    "Q0_INV_LONDON_OR_V1",
    "Q0_INV_NEWYORK_OR_V1",
    "Q0_META_POLARITY_ELASTIC_NET_V1",
)
DETERMINISTIC_CANDIDATES = CANDIDATE_IDS[:4]

EXPECTED_RESULTS: dict[str, dict[str, float | int]] = {
    "Q0_INV_SWEEP_V1": {
        "trade_count": 364,
        "mean_net_r": -0.32180508268531444,
        "profit_factor": 0.29752214142460354,
        "mean_stress_1_5x_net_r": -0.3566398459810714,
        "mean_stress_2_0x_net_r": -0.3914746092768284,
        "probabilistic_sharpe": 2.3076910960572319e-13,
        "deflated_sharpe": 2.4902929492675005e-123,
    },
    "Q0_INV_ACCEPTANCE_V1": {
        "trade_count": 6932,
        "mean_net_r": -0.7624451188940735,
        "profit_factor": 0.10729335715865178,
        "mean_stress_1_5x_net_r": -0.8587348880385567,
        "mean_stress_2_0x_net_r": -0.95502465718304,
        "probabilistic_sharpe": 7.53787601322482e-282,
        "deflated_sharpe": 0.0,
    },
    "Q0_INV_LONDON_OR_V1": {
        "trade_count": 930,
        "mean_net_r": -0.4102997315530225,
        "profit_factor": 0.16077818858460013,
        "mean_stress_1_5x_net_r": -0.4713457415645153,
        "mean_stress_2_0x_net_r": -0.5323917515760079,
        "probabilistic_sharpe": 1.9012291639924638e-74,
        "deflated_sharpe": 0.0,
    },
    "Q0_INV_NEWYORK_OR_V1": {
        "trade_count": 1488,
        "mean_net_r": -0.4211009868169465,
        "profit_factor": 0.23331430497732297,
        "mean_stress_1_5x_net_r": -0.4732850104281334,
        "mean_stress_2_0x_net_r": -0.5254690340393203,
        "probabilistic_sharpe": 1.9617744883144603e-69,
        "deflated_sharpe": 0.0,
    },
    "Q0_META_POLARITY_ELASTIC_NET_V1": {
        "trade_count": 6,
        "mean_net_r": -0.12186740741145506,
        "profit_factor": 0.07761347310367869,
        "mean_stress_1_5x_net_r": -0.13314980657724576,
        "mean_stress_2_0x_net_r": -0.1444322057430365,
        "probabilistic_sharpe": 0.036996615272133763,
        "deflated_sharpe": 2.4072381359488004e-07,
    },
}

EXPECTED_BENCHMARKS: dict[str, dict[str, float]] = {
    "Q0_INV_SWEEP_V1": {
        "matched_random_alpha": -0.2554387266481907,
        "raw_permutation_p_value": 1.0,
        "holm_adjusted_p_value": 1.0,
        "fdr_adjusted_p_value": 1.0,
        "romano_wolf_adjusted_p_value": 0.0003999200159968006,
    },
    "Q0_INV_ACCEPTANCE_V1": {
        "matched_random_alpha": -0.5275786373197038,
        "raw_permutation_p_value": 1.0,
        "holm_adjusted_p_value": 1.0,
        "fdr_adjusted_p_value": 1.0,
        "romano_wolf_adjusted_p_value": 0.0001999600079984003,
    },
    "Q0_INV_LONDON_OR_V1": {
        "matched_random_alpha": -0.21511247711209341,
        "raw_permutation_p_value": 1.0,
        "holm_adjusted_p_value": 1.0,
        "fdr_adjusted_p_value": 1.0,
        "romano_wolf_adjusted_p_value": 0.0001999600079984003,
    },
    "Q0_INV_NEWYORK_OR_V1": {
        "matched_random_alpha": -0.2840619748484751,
        "raw_permutation_p_value": 1.0,
        "holm_adjusted_p_value": 1.0,
        "fdr_adjusted_p_value": 1.0,
        "romano_wolf_adjusted_p_value": 0.0001999600079984003,
    },
    "Q0_META_POLARITY_ELASTIC_NET_V1": {
        "matched_random_alpha": -0.1282468904668793,
        "raw_permutation_p_value": 0.8475152484751525,
        "holm_adjusted_p_value": 1.0,
        "fdr_adjusted_p_value": 1.0,
        "romano_wolf_adjusted_p_value": 0.2429514097180564,
    },
}

EXPECTED_FACTOR_ALPHA = {
    "Q0_INV_SWEEP_V1": -0.28033879198930334,
    "Q0_INV_ACCEPTANCE_V1": -3.05360352519059,
    "Q0_INV_LONDON_OR_V1": -0.5765647851334814,
    "Q0_INV_NEWYORK_OR_V1": -0.5631093637908369,
    "Q0_META_POLARITY_ELASTIC_NET_V1": 0.1861771636773347,
}

EXPECTED_CLAIM_STATUSES = {
    "A": "SUPPORTED",
    "B": "REJECTED",
    "C": "NOT_SUPPORTED_INSUFFICIENT_ACTIVITY_AND_NEGATIVE_ECONOMICS",
    "D": "NOT_SUPPORTED",
    "E": "NOT_TESTED_BECAUSE_NO_CANDIDATE_WAS_ELIGIBLE",
    "F": "REJECTED_IN_DEVELOPMENT",
    "G": "FALSE_INTERPRETATION",
    "H": "REJECTED_BY_HISTORICAL_INTEGRITY_EVENT",
    "I": "FALSE",
    "J": "NOT_AUTHORIZED",
}

QUARANTINED_HYPOTHESES = (
    "lower the 0.55 model probability thresholds",
    "remove the ABSTAIN action",
    "change target-label construction",
    "change elastic-net regularization grid",
    "use instrument identity as a predictive feature",
    "introduce tree, boosting or neural models on the same development sample",
    "select only USDCHF for the meta-model",
    "select favorable development years",
    "select favorable instruments",
    "exclude losing trades",
    "change transaction costs",
    "change session definitions",
    "change purge or embargo",
    "access 2020-2022 despite the empty shortlist",
    "use the quarantined historical interval as confirmation",
    "reverse the inverted policies again",
    "optimize stop loss or take profit",
    "add another SMC transformation",
)

REQUIRED_SEAL_PROHIBITIONS = (
    "further tuning on the current 2015-2019 development sample",
    "lowering eligibility criteria",
    "accessing replication data under this lineage",
    "creating a future candidate from this lineage",
    "creating a paper or live handoff",
    "using the quarantined historical interval as confirmation",
    "relabeling negative performance as alpha",
)

REQUIRED_FUTURE_CONDITIONS = (
    "new lineage ID",
    "new financially motivated hypothesis",
    "new candidate family",
    "new preregistration",
    "new multiple-testing family",
    "independent data partition",
)

ALLOWED_CLOSURE_ACTIONS = frozenset(
    {
        "read_committed_aggregate",
        "verify_hash",
        "publish_negative_result",
        "seal_lineage",
        "create_review_pr",
    }
)


def canonical_json_sha256(payload: Any) -> str:
    """Hash a JSON-compatible payload deterministically."""
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def payload_hash_without(payload: dict[str, Any], *excluded_keys: str) -> str:
    """Hash a record while excluding self-referential fields."""
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in excluded_keys}
    )


def _exact(name: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {
        "name": name,
        "observed": observed,
        "expected": expected,
        "match": observed == expected,
    }


def _close(name: str, observed: float, expected: float) -> dict[str, Any]:
    difference = abs(float(observed) - float(expected))
    return {
        "name": name,
        "observed": observed,
        "expected": expected,
        "absolute_difference": difference,
        "tolerance": 1e-12,
        "match": math.isclose(
            float(observed), float(expected), rel_tol=0.0, abs_tol=1e-12
        ),
    }


def reproduce_aggregate_results(
    sources: dict[str, dict[str, Any]],
    *,
    memo_text: str,
    manifest_hash_agreement: bool,
) -> dict[str, Any]:
    """Reproduce Q0-R conclusions without market or row-level data access."""
    checks: list[dict[str, Any]] = []
    data = sources["data_certification"]
    freeze = sources["dataset_freeze"]
    candidates = sources["candidate_results"]["results"]
    benchmarks = sources["benchmark_results"]["results"]
    factors = sources["factor_alpha"]["results"]
    inference = sources["inference"]["results"]
    overfitting = sources["overfitting"]
    stability = sources["stability"]["candidates"]
    adjudication = sources["adjudication"]
    shortlist = sources["shortlist"]
    final = sources["final_decision"]

    for name, observed, exact_expected in (
        ("data.pair_months_planned", data["pair_months_planned"], 240),
        ("data.pair_months_certified", data["pair_months_certified"], 240),
        ("data.missing", data["missing"], 0),
        ("data.failed", data["failed"], 0),
        ("data.successful_zero_row", data["successful_zero_row"], 0),
        ("data.total_m1_rows", data["total_m1_rows"], 7_455_419),
        ("data.total_m5_rows", data["total_m5_rows"], 1_494_623),
        ("freeze.pair_month_count", freeze["pair_month_count"], 240),
    ):
        checks.append(_exact(name, observed, exact_expected))

    reproduced_candidates: dict[str, Any] = {}
    for candidate_id in CANDIDATE_IDS:
        result = candidates[candidate_id]
        benchmark = benchmarks[candidate_id]
        expected_result = EXPECTED_RESULTS[candidate_id]
        expected_benchmark = EXPECTED_BENCHMARKS[candidate_id]
        for field, metric_expected in expected_result.items():
            observed = result[field]
            check = (
                _exact(f"{candidate_id}.{field}", observed, metric_expected)
                if field == "trade_count"
                else _close(
                    f"{candidate_id}.{field}", observed, float(metric_expected)
                )
            )
            checks.append(check)
        for field, benchmark_expected in expected_benchmark.items():
            checks.append(
                _close(
                    f"{candidate_id}.{field}",
                    benchmark[field],
                    benchmark_expected,
                )
            )
        checks.append(
            _close(
                f"{candidate_id}.factor_alpha",
                factors[candidate_id]["alpha"],
                EXPECTED_FACTOR_ALPHA[candidate_id],
            )
        )
        checks.append(
            _close(
                f"{candidate_id}.factor_alpha_cross_artifact",
                inference[candidate_id]["factor_adjusted_hac"]["alpha"],
                factors[candidate_id]["alpha"],
            )
        )
        reproduced_candidates[candidate_id] = {
            **{field: result[field] for field in EXPECTED_RESULTS[candidate_id]},
            **{
                field: benchmark[field]
                for field in EXPECTED_BENCHMARKS[candidate_id]
            },
            "factor_adjusted_hac_alpha": factors[candidate_id]["alpha"],
            "yearly_mean_net_r": result["yearly_mean_net_r"],
            "instrument_mean_net_r": stability[candidate_id][
                "instrument_mean_net_r"
            ],
        }

    for candidate_id in DETERMINISTIC_CANDIDATES:
        yearly = candidates[candidate_id]["yearly_mean_net_r"]
        instruments = stability[candidate_id]["instrument_mean_net_r"]
        checks.append(
            _exact(
                f"{candidate_id}.all_development_years_negative",
                len(yearly) == 5 and all(value < 0 for value in yearly.values()),
                True,
            )
        )
        checks.append(
            _exact(
                f"{candidate_id}.all_development_instruments_negative",
                len(instruments) == 4
                and all(value < 0 for value in instruments.values()),
                True,
            )
        )

    meta = stability["Q0_META_POLARITY_ELASTIC_NET_V1"]
    checks.extend(
        [
            _exact("meta.trade_count", meta["trade_count"], 6),
            _exact("meta.positive_instrument_count", meta["positive_instrument_count"], 1),
            _close(
                "family.white_reality_check_p_value",
                overfitting["white_reality_check_p_value"],
                0.9898,
            ),
            _close(
                "family.hansen_spa_p_value",
                overfitting["hansen_spa_p_value"],
                1.0,
            ),
            _close("family.pbo", overfitting["pbo"], 1.0),
            _exact(
                "adjudication.all_ineligible",
                all(not row["eligible"] for row in adjudication["candidates"]),
                True,
            ),
            _exact("adjudication.selected_candidates", adjudication["selected_candidates"], []),
            _exact("shortlist.selected_candidates", shortlist["selected_candidates"], []),
            _exact(
                "shortlist.replication_data_accessed",
                shortlist["replication_data_accessed"],
                False,
            ),
            _exact(
                "shortlist.replication_provider_request_sent",
                shortlist["replication_provider_request_sent"],
                False,
            ),
            _exact("final.decision", final["decision"], Q0R_DECISION),
            _exact("final.replication_access_started", final["replication_access_started"], False),
            _exact(
                "final.replication_outcomes_generated",
                final["replication_outcomes_generated"],
                False,
            ),
            _exact(
                "final.future_candidate_frozen",
                final["candidate_frozen_for_future_prospective_confirmation"],
                False,
            ),
            _exact(
                "final.future_collection_handoff_created",
                final["future_collection_handoff_created"],
                False,
            ),
            _exact("manifest.hash_agreement", manifest_hash_agreement, True),
        ]
    )

    normalized_memo = " ".join(memo_text.split())
    memo_tokens = (
        Q0R_DECISION,
        "7,455,419 M1 rows",
        "1,494,623 M5 rows",
        "`C=0.01`",
        "`l1_ratio=0.0`",
        "White Reality Check was 0.9898",
        "Hansen SPA was 1.0",
        "PBO was 1.0",
        "No result authorizes live-capital deployment.",
    )
    for token in memo_tokens:
        checks.append(_exact(f"memo.contains:{token}", token in normalized_memo, True))

    numeric_differences = [
        float(check["absolute_difference"])
        for check in checks
        if "absolute_difference" in check
    ]
    mismatches = [check for check in checks if not check["match"]]
    return {
        "source_scope": "COMMITTED_AGGREGATE_ARTIFACTS_ONLY",
        "market_data_loaded": False,
        "row_level_features_loaded": False,
        "row_level_predictions_loaded": False,
        "row_level_trades_loaded": False,
        "candidate_results": reproduced_candidates,
        "family_inference": {
            "white_reality_check_p_value": overfitting["white_reality_check_p_value"],
            "hansen_spa_p_value": overfitting["hansen_spa_p_value"],
            "pbo": overfitting["pbo"],
            "maximum_dsr_probability": max(
                float(candidates[candidate_id]["deflated_sharpe"])
                for candidate_id in CANDIDATE_IDS
            ),
        },
        "aggregate_check_count": len(checks),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "maximum_numeric_difference": max(numeric_differences, default=0.0),
        "hash_agreement": manifest_hash_agreement,
        "checks": checks,
        "status": "PASS" if not mismatches else "FAIL",
    }


def build_claim_matrix() -> list[dict[str, Any]]:
    """Return the immutable Q1 claim matrix."""
    return [
        {
            "claim_id": "A",
            "claim": (
                "The repository contains a clean-room, capability-restricted, "
                "deterministic bid/ask research pipeline for quant-polarity evaluation."
            ),
            "status": "SUPPORTED",
        },
        {
            "claim_id": "B",
            "claim": (
                "Simple inversion of the four previously studied SMC policies produced "
                "positive development expectancy on independent instruments."
            ),
            "status": "REJECTED",
        },
        {
            "claim_id": "C",
            "claim": "The elastic-net polarity meta-model produced a usable trading candidate.",
            "status": "NOT_SUPPORTED_INSUFFICIENT_ACTIVITY_AND_NEGATIVE_ECONOMICS",
        },
        {
            "claim_id": "D",
            "claim": "Any candidate justified independent replication.",
            "status": "NOT_SUPPORTED",
        },
        {
            "claim_id": "E",
            "claim": "Independent replication failed.",
            "status": "NOT_TESTED_BECAUSE_NO_CANDIDATE_WAS_ELIGIBLE",
        },
        {
            "claim_id": "F",
            "claim": "Any candidate demonstrated positive benchmark-relative alpha.",
            "status": "REJECTED_IN_DEVELOPMENT",
        },
        {
            "claim_id": "G",
            "claim": "Small Romano-Wolf values establish profitable alpha.",
            "status": "FALSE_INTERPRETATION",
        },
        {
            "claim_id": "H",
            "claim": (
                "The quarantined historical interval remains an untouched "
                "confirmatory holdout."
            ),
            "status": "REJECTED_BY_HISTORICAL_INTEGRITY_EVENT",
        },
        {
            "claim_id": "I",
            "claim": "A future candidate or prospective protocol was created.",
            "status": "FALSE",
        },
        {
            "claim_id": "J",
            "claim": (
                "The current results authorize paper trading or live-capital deployment."
            ),
            "status": "NOT_AUTHORIZED",
        },
    ]


def validate_claim_matrix(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate exact claim identities and statuses."""
    observed = {str(item["claim_id"]): str(item["status"]) for item in claims}
    checks = {
        claim_id: observed.get(claim_id) == status
        for claim_id, status in EXPECTED_CLAIM_STATUSES.items()
    }
    return {
        "expected_statuses": EXPECTED_CLAIM_STATUSES,
        "observed_statuses": observed,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def build_posthoc_quarantine() -> dict[str, Any]:
    """Build the fixed set of outcome-informed rescue hypotheses."""
    payload: dict[str, Any] = {
        "quarantine_id": QUARANTINE_ID,
        "hypotheses": [
            {"hypothesis": hypothesis, "status": QUARANTINE_STATUS}
            for hypothesis in QUARANTINED_HYPOTHESES
        ],
        "current_lineage_confirmation_permitted": False,
        "future_work_requires": list(REQUIRED_FUTURE_CONDITIONS),
        "status": "ACTIVE",
    }
    payload["quarantine_hash"] = payload_hash_without(payload, "quarantine_hash")
    return payload


def validate_posthoc_quarantine(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate quarantine completeness, status, and hash."""
    hypotheses = payload.get("hypotheses", [])
    checks = {
        "identity": payload.get("quarantine_id") == QUARANTINE_ID,
        "complete": [item.get("hypothesis") for item in hypotheses]
        == list(QUARANTINED_HYPOTHESES),
        "uniform_status": all(
            item.get("status") == QUARANTINE_STATUS for item in hypotheses
        ),
        "current_lineage_blocked": (
            payload.get("current_lineage_confirmation_permitted") is False
        ),
        "hash": payload.get("quarantine_hash")
        == payload_hash_without(payload, "quarantine_hash", "validation"),
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def build_failure_mechanism_audit() -> dict[str, Any]:
    """Separate scientific evidence from operational and integrity controls."""
    dimensions = {
        "scientific_failure": "FAIL_NO_ELIGIBLE_DEVELOPMENT_CANDIDATE",
        "statistical_failure": "FAIL_NO_FAMILY_OR_MULTIPLICITY_ADJUSTED_SUPPORT",
        "economic_failure": "FAIL_ALL_CANDIDATE_MEAN_NET_R_NEGATIVE",
        "model_failure": "FAIL_META_MODEL_INSUFFICIENT_ACTIVITY_AND_NEGATIVE_ECONOMICS",
        "execution_failure": "PASS_NO_EXECUTION_INTEGRITY_FAILURE",
        "data_failure": "PASS_DATASET_FULLY_CERTIFIED",
        "integrity_failure": "PASS_Q0R_CLEAN_ROOM_INTEGRITY_PRESERVED",
    }
    return {
        "dimensions": dimensions,
        "controls": {
            "data_certification": "PASS",
            "clean_room_isolation": "PASS",
            "safe_io": "PASS",
            "execution_integrity": "PASS",
            "lookahead_protection": "PASS",
            "model_selection_separation": "PASS",
            "economic_performance": "FAIL",
            "benchmark_relative_alpha": "FAIL",
            "development_eligibility": "FAIL",
            "replication": "NOT_ACCESSED",
            "prospective_candidate": "NOT_CREATED",
        },
        "conclusion": (
            "The absence of an eligible candidate is due to negative economic and "
            "statistical evidence, not missing data, runtime failure, or incomplete "
            "certification."
        ),
        "status": "PASS",
    }


def build_statistical_interpretation() -> dict[str, Any]:
    """Encode the frozen interpretation of the negative statistical findings."""
    return {
        "white_reality_check": {
            "p_value": 0.9898,
            "interpretation": (
                "No evidence that the best frozen candidate outperformed the null "
                "after candidate-family data-snooping adjustment."
            ),
        },
        "hansen_spa": {
            "p_value": 1.0,
            "interpretation": "No candidate demonstrated superior predictive ability.",
        },
        "pbo": {
            "value": 1.0,
            "interpretation": (
                "The selection structure is maximally consistent with backtest "
                "overfitting or nontransportable selection."
            ),
        },
        "dsr": {
            "maximum_probability": 2.4072381359488004e-07,
            "interpretation": (
                "No Sharpe result survives multiple-testing and non-normality adjustment."
            ),
        },
        "stability": (
            "Negative deterministic-candidate performance spans every development "
            "instrument and year rather than one isolated subgroup."
        ),
        "empty_shortlist": (
            "Stopping before replication was the preregistered scientific gate working "
            "as designed, not an operational failure."
        ),
        "romano_wolf_boundary": (
            "Small values for deterministic candidates accompany negative relative "
            "effects and do not establish profitable alpha."
        ),
        "status": "PASS",
    }


def lineage_seal_hash(seal: dict[str, Any]) -> str:
    """Return the canonical Q1 lineage seal hash."""
    return payload_hash_without(seal, "lineage_seal_hash", "validation")


def validate_lineage_seal(seal: dict[str, Any]) -> dict[str, Any]:
    """Validate identity, closure guards, and the canonical seal hash."""
    prohibitions = seal.get("prohibitions", [])
    future = seal.get("permitted_future_work_requires", [])
    checks = {
        "seal_id": seal.get("seal_id") == SEAL_ID,
        "program_id": seal.get("program_id") == PROGRAM_ID,
        "lineage_id": seal.get("lineage_id") == LINEAGE_ID,
        "status": seal.get("status") == SEAL_STATUS,
        "prohibitions": all(item in prohibitions for item in REQUIRED_SEAL_PROHIBITIONS),
        "future_conditions": all(item in future for item in REQUIRED_FUTURE_CONDITIONS),
        "hash": seal.get("lineage_seal_hash") == lineage_seal_hash(seal),
        "replication_accessed": seal.get("replication_accessed") is False,
        "future_candidate_created": seal.get("future_candidate_created") is False,
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def validate_closed_lineage_action(action: str) -> dict[str, Any]:
    """Permit publication actions and reject any attempt to reopen research."""
    permitted = action in ALLOWED_CLOSURE_ACTIONS
    return {
        "action": action,
        "permitted": permitted,
        "status": "PASS" if permitted else "BLOCKED_BY_LINEAGE_SEAL",
    }


def detect_prohibited_changed_paths(paths: list[str]) -> list[str]:
    """Classify paths that cannot enter Q1 closure commits."""
    prohibited: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").lower()
        filename = normalized.rsplit("/", maxsplit=1)[-1]
        if normalized.startswith(("data/raw/", "data/canonical/", "data/real/raw/")):
            prohibited.append(path)
        elif normalized.endswith((".parquet", ".bi5", ".csv", ".feather")):
            prohibited.append(path)
        elif any(token in filename for token in ("credential", "secret", ".env")):
            prohibited.append(path)
        elif any(
            token in normalized
            for token in (
                "row_level",
                "provider_payload",
                "individual_trade",
                "feature_rows",
            )
        ):
            prohibited.append(path)
    return prohibited


def validate_no_future_or_live_handoff(paths: list[str]) -> dict[str, Any]:
    """Reject candidate, prospective, paper, or live handoff artifacts."""
    blocked_tokens = (
        "future_candidate_freeze",
        "future_prospective_protocol",
        "future_collection_handoff",
        "paper_trading_handoff",
        "live_capital_handoff",
    )
    blocked = [
        path for path in paths if any(token in path.lower() for token in blocked_tokens)
    ]
    return {"blocked_paths": blocked, "status": "PASS" if not blocked else "FAIL"}
