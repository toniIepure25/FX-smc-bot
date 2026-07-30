"""Strategy-alpha closure validation without market or row-level data access."""

from __future__ import annotations

import hashlib
import json
from typing import Any

PROGRAM_ID = "FX_SMC_STRATEGY_ALPHA_V1"
LINEAGE_ID = "FX_SMC_STRATEGY_ALPHA_PROSPECTIVE_LINEAGE_V1"
SEAL_ID = "FX_SMC_STRATEGY_ALPHA_LINEAGE_V1"
SEAL_STATUS = "CLOSED_ALL_CANDIDATES_TIER_C_NO_FORWARD_TEST"
CLOSURE_ID = "FX_SMC_STRATEGY_ALPHA_CLOSURE_V1"
QUARANTINE_ID = "FX_SMC_STRATEGY_ALPHA_POSTHOC_QUARANTINE_V1"
FINAL_DECISION = "P1_STRATEGY_ALPHA_PROGRAM_CLOSED_PR_CREATED_READY_FOR_REVIEW"
QUARANTINE_STATUS = "OUTCOME_INFORMED_NOT_CONFIRMABLE_ON_2015_2022"

EXPECTED_RESULTS: dict[str, dict[str, Any]] = {
    "SMC_A_SWEEP_REVERSAL_V1": {
        "trade_count": 202,
        "mean_net_r": 0.010604378019007616,
        "day_cluster_ci": [-0.07471524624636247, 0.09950101604164403],
        "profit_factor": 1.0484759129467567,
        "sharpe": 0.2803239944743469,
        "mean_stress_1_5x_net_r": -0.006564049948166264,
        "mean_stress_2_0x_net_r": -0.02373247791534012,
        "matched_random_alpha_mean_r": -0.005108740876873998,
        "holm_adjusted_p_value": 1.0,
        "tier": "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST",
    },
    "SMC_B_ACCEPTANCE_CONTINUATION_V1": {
        "trade_count": 2676,
        "mean_net_r": -0.15810003865280425,
        "day_cluster_ci": [-0.19886181889211968, -0.11909809286987667],
        "profit_factor": 0.697540583282163,
        "sharpe": -3.101238396768342,
        "mean_stress_1_5x_net_r": -0.20314689819740306,
        "mean_stress_2_0x_net_r": -0.24819375774200184,
        "matched_random_alpha_mean_r": -0.037977498788189235,
        "holm_adjusted_p_value": 1.0,
        "tier": "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST",
    },
    "SMC_C_LONDON_OPENING_RANGE_V1": {
        "trade_count": 360,
        "mean_net_r": -0.08110841562673701,
        "day_cluster_ci": [-0.14648950392805243, -0.013442191814960099],
        "profit_factor": 0.7075700414540482,
        "sharpe": -2.061177052930276,
        "mean_stress_1_5x_net_r": -0.10633442653072471,
        "mean_stress_2_0x_net_r": -0.13156043743471238,
        "matched_random_alpha_mean_r": -0.06299865878206207,
        "holm_adjusted_p_value": 1.0,
        "tier": "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST",
    },
    "SMC_C_NEWYORK_OPENING_RANGE_V1": {
        "trade_count": 753,
        "mean_net_r": -0.03139660244898749,
        "day_cluster_ci": [-0.08720909862743417, 0.023270907560085843],
        "profit_factor": 0.897514439013547,
        "sharpe": -0.6831083289957264,
        "mean_stress_1_5x_net_r": -0.05448396380805454,
        "mean_stress_2_0x_net_r": -0.0775713251671216,
        "matched_random_alpha_mean_r": 0.019275422964931718,
        "holm_adjusted_p_value": 1.0,
        "tier": "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST",
    },
}

EXPECTED_CLAIM_STATUSES = {
    "A": "SUPPORTED",
    "B": "DESCRIPTIVELY_SUPPORTED_BUT_NOT_ROBUST",
    "C": "REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY",
    "D": "REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY",
    "E": "NOT_SUPPORTED",
    "F": "NOT_SUPPORTED",
    "G": "NOT_SUPPORTED",
    "H": "EXPLORATORY_OUTCOME_INFORMED_ONLY",
    "I": "NOT_TESTED_AND_NOT_AUTHORIZED",
}

QUARANTINED_HYPOTHESES = [
    "invert every signal",
    "reverse only Acceptance",
    "reverse only opening-range signals",
    "select Sweep at base costs",
    "select New York based on positive matched-random differential",
    "optimize delay",
    "optimize session cutoff",
    "optimize stop or target",
    "select favorable years",
    "select favorable instruments",
]

HOLDOUT_FLAGS = [
    "sealed_holdout_market_data_loaded",
    "sealed_holdout_storage_enumerated",
    "sealed_holdout_structure_inspected",
    "sealed_holdout_file_counts_computed",
    "sealed_holdout_provider_requests_sent",
    "sealed_holdout_signals_generated",
    "sealed_holdout_trade_counts_computed",
    "sealed_holdout_trades_generated",
    "sealed_holdout_pnl_computed",
    "sealed_holdout_results_reported",
]

REQUIRED_SEAL_PROHIBITIONS = [
    "additional parameter tuning on the existing four candidates using 2015-2022",
    "post-hoc inversion claims using 2015-2022",
    "retroactive Tier-rule modification",
    "relabelling historical results as confirmation",
    "creation of a forward handoff from this closed lineage",
    "access to the sealed 2023-2025 holdout under this lineage",
]

REQUIRED_FUTURE_CONDITIONS = [
    "a new lineage ID",
    "a frozen new hypothesis",
    "an independent instrument universe or genuinely future data",
    "a new preregistration before outcome access",
]


def canonical_json_sha256(payload: Any) -> str:
    """Hash a JSON-compatible payload deterministically."""
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def payload_hash_without(payload: dict[str, Any], excluded_key: str) -> str:
    """Hash a record while excluding its self-referential hash field."""
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != excluded_key}
    )


def _close_check(name: str, observed: float, expected: float) -> dict[str, Any]:
    difference = abs(float(observed) - float(expected))
    return {
        "name": name,
        "observed": observed,
        "expected": expected,
        "absolute_difference": difference,
        "tolerance": 1e-12,
        "match": difference <= 1e-12,
    }


def reproduce_aggregate_results(
    candidate_payload: dict[str, Any],
    benchmark_payload: dict[str, Any],
    adjudication_payload: dict[str, Any],
    execution_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Reproduce frozen results using committed aggregate records only."""
    rows = candidate_payload["results"]
    combined = {row["candidate_id"]: row for row in rows if row["window"] == "combined"}
    windows: dict[str, list[dict[str, Any]]] = {candidate_id: [] for candidate_id in combined}
    for row in rows:
        if row["window"] != "combined":
            windows[row["candidate_id"]].append(row)
    benchmarks = {row["candidate_id"]: row for row in benchmark_payload["results"]}
    tiers = {
        row["candidate_id"]: row for row in adjudication_payload["adjudications"]
    }

    reproduced: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for candidate_id, expected in EXPECTED_RESULTS.items():
        row = combined[candidate_id]
        benchmark = benchmarks[candidate_id]
        tier = tiers[candidate_id]
        window_trade_count = sum(int(item["trade_count"]) for item in windows[candidate_id])
        window_net_r = sum(float(item["net_r"]) for item in windows[candidate_id])
        weighted_window_mean = window_net_r / window_trade_count
        observed = {
            "candidate_id": candidate_id,
            "trade_count": int(row["trade_count"]),
            "mean_net_r": float(row["mean_net_r"]),
            "day_cluster_ci": [float(value) for value in row["day_cluster_ci"]],
            "profit_factor": float(row["profit_factor"]),
            "sharpe": float(row["sharpe"]),
            "mean_stress_1_5x_net_r": float(row["mean_stress_1_5x_net_r"]),
            "mean_stress_2_0x_net_r": float(row["mean_stress_2_0x_net_r"]),
            "matched_random_alpha_mean_r": float(benchmark["matched_random_alpha_mean_r"]),
            "holm_adjusted_p_value": float(benchmark["holm_adjusted_p_value"]),
            "tier": tier["final_tier"],
            "forward_test_eligibility": bool(tier["forward_test_eligibility"]),
            "window_trade_count_sum": window_trade_count,
            "weighted_window_mean_net_r": weighted_window_mean,
        }
        checks.append(
            {
                "name": f"{candidate_id}.trade_count",
                "observed": observed["trade_count"],
                "expected": expected["trade_count"],
                "match": observed["trade_count"] == expected["trade_count"],
            }
        )
        checks.append(
            {
                "name": f"{candidate_id}.window_trade_count_sum",
                "observed": window_trade_count,
                "expected": row["trade_count"],
                "match": window_trade_count == row["trade_count"],
            }
        )
        checks.append(
            _close_check(
                f"{candidate_id}.weighted_window_mean_net_r",
                weighted_window_mean,
                float(row["mean_net_r"]),
            )
        )
        for field in (
            "mean_net_r",
            "profit_factor",
            "sharpe",
            "mean_stress_1_5x_net_r",
            "mean_stress_2_0x_net_r",
            "matched_random_alpha_mean_r",
            "holm_adjusted_p_value",
        ):
            checks.append(
                _close_check(
                    f"{candidate_id}.{field}",
                    float(observed[field]),
                    float(expected[field]),
                )
            )
        for index, value in enumerate(expected["day_cluster_ci"]):
            checks.append(
                _close_check(
                    f"{candidate_id}.day_cluster_ci[{index}]",
                    observed["day_cluster_ci"][index],
                    float(value),
                )
            )
        checks.append(
            {
                "name": f"{candidate_id}.tier",
                "observed": observed["tier"],
                "expected": expected["tier"],
                "match": observed["tier"] == expected["tier"],
            }
        )
        reproduced.append(observed)

    total_trades = sum(item["trade_count"] for item in reproduced)
    checks.extend(
        [
            {
                "name": "execution_manifest.trade_count",
                "observed": execution_manifest["trade_count"],
                "expected": total_trades,
                "match": execution_manifest["trade_count"] == total_trades == 3991,
            },
            {
                "name": "primary_candidate",
                "observed": adjudication_payload["primary_candidate"],
                "expected": None,
                "match": adjudication_payload["primary_candidate"] is None,
            },
            {
                "name": "secondary_candidate",
                "observed": adjudication_payload["secondary_candidate"],
                "expected": None,
                "match": adjudication_payload["secondary_candidate"] is None,
            },
        ]
    )
    return {
        "source_scope": "COMMITTED_AGGREGATE_ARTIFACTS_ONLY",
        "market_data_loaded": False,
        "row_level_ledgers_loaded": False,
        "candidate_results": reproduced,
        "trade_count": total_trades,
        "primary_candidate": None,
        "secondary_candidate": None,
        "checks": checks,
        "status": "PASS" if all(check["match"] for check in checks) else "FAIL",
    }


def build_claim_matrix() -> list[dict[str, Any]]:
    """Return the immutable Gate P.1 claim matrix."""
    return [
        {
            "claim_id": "A",
            "claim": (
                "The repository contains a certified deterministic bid/ask strategy-level "
                "execution and economic-evaluation pipeline for the permitted 2015-2022 data."
            ),
            "status": "SUPPORTED",
        },
        {
            "claim_id": "B",
            "claim": "Sweep reversal generated positive historical mean net expectancy.",
            "status": "DESCRIPTIVELY_SUPPORTED_BUT_NOT_ROBUST",
            "evidence": [
                "mean net R was 0.010604378019007616",
                "day-cluster confidence interval included zero",
                "matched-random alpha was negative",
                "1.5x and 2.0x cost means were negative",
                "leave-one-year-out positivity failed",
            ],
        },
        {
            "claim_id": "C",
            "claim": (
                "Acceptance continuation was historically profitable as a standalone strategy."
            ),
            "status": "REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY",
            "evidence": [
                "mean net R was -0.15810003865280425",
                "day-cluster confidence interval was entirely negative",
                "profit factor was 0.697540583282163",
                "Sharpe was -3.101238396768342",
                "cost escalation worsened the result",
            ],
        },
        {
            "claim_id": "D",
            "claim": "London opening-range continuation was historically profitable.",
            "status": "REJECTED_IN_FROZEN_HISTORICAL_FEASIBILITY",
        },
        {
            "claim_id": "E",
            "claim": "New York opening-range continuation was historically profitable.",
            "status": "NOT_SUPPORTED",
            "evidence": [
                "mean net R was negative",
                "day-cluster confidence interval included zero",
                "profit factor was below one",
                "benchmark-relative alpha was not statistically supported",
            ],
        },
        {
            "claim_id": "F",
            "claim": "Any frozen candidate demonstrated benchmark-relative alpha.",
            "status": "NOT_SUPPORTED",
        },
        {
            "claim_id": "G",
            "claim": "Any frozen candidate justified prospective paper trading.",
            "status": "NOT_SUPPORTED",
        },
        {
            "claim_id": "H",
            "claim": (
                "Positive direction-flip controls establish that inverted versions are profitable "
                "strategies."
            ),
            "status": "EXPLORATORY_OUTCOME_INFORMED_ONLY",
            "boundary": (
                "A polarity hypothesis requires a separate lineage, preregistration, and untouched "
                "instruments or genuinely future data; it cannot be confirmed on 2015-2022."
            ),
        },
        {
            "claim_id": "I",
            "claim": "The current results authorize live-capital deployment.",
            "status": "NOT_TESTED_AND_NOT_AUTHORIZED",
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
    """Build the fixed set of outcome-informed hypotheses."""
    return {
        "quarantine_id": QUARANTINE_ID,
        "hypotheses": [
            {"hypothesis": hypothesis, "status": QUARANTINE_STATUS}
            for hypothesis in QUARANTINED_HYPOTHESES
        ],
        "current_sample_confirmation_permitted": False,
        "future_entry_requirements": [
            "new lineage ID",
            "frozen hypothesis before outcome access",
            "new independent dataset",
        ],
        "status": "ACTIVE",
    }


def validate_posthoc_quarantine(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate quarantine completeness and uniform status."""
    observed = [str(item["hypothesis"]) for item in payload.get("hypotheses", [])]
    statuses = [str(item["status"]) for item in payload.get("hypotheses", [])]
    complete = observed == QUARANTINED_HYPOTHESES
    statuses_fixed = all(status == QUARANTINE_STATUS for status in statuses)
    current_sample_blocked = payload.get("current_sample_confirmation_permitted") is False
    return {
        "complete": complete,
        "statuses_fixed": statuses_fixed,
        "current_sample_blocked": current_sample_blocked,
        "status": (
            "PASS" if complete and statuses_fixed and current_sample_blocked else "FAIL"
        ),
    }


def strategy_alpha_lineage_seal_hash(seal: dict[str, Any]) -> str:
    """Return the canonical lineage seal hash."""
    payload = {
        key: value
        for key, value in seal.items()
        if key not in {"lineage_seal_hash", "validation"}
    }
    return canonical_json_sha256(payload)


def validate_strategy_alpha_lineage_seal(seal: dict[str, Any]) -> dict[str, Any]:
    """Validate identity, immutable prohibitions, and the self-hash."""
    prohibitions = seal.get("prohibitions", [])
    future_conditions = seal.get("permitted_future_work_requires", [])
    checks = {
        "seal_id": seal.get("seal_id") == SEAL_ID,
        "program_id": seal.get("program_id") == PROGRAM_ID,
        "lineage_id": seal.get("lineage_id") == LINEAGE_ID,
        "status": seal.get("status") == SEAL_STATUS,
        "prohibitions": all(item in prohibitions for item in REQUIRED_SEAL_PROHIBITIONS),
        "future_conditions": all(
            item in future_conditions for item in REQUIRED_FUTURE_CONDITIONS
        ),
        "hash": seal.get("lineage_seal_hash") == strategy_alpha_lineage_seal_hash(seal),
    }
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def validate_holdout_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    """Require every declared sealed-holdout action to remain false."""
    checks = {flag: payload.get(flag) is False for flag in HOLDOUT_FLAGS}
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def detect_prohibited_changed_paths(paths: list[str]) -> list[str]:
    """Classify newly changed paths that cannot enter the closure commits."""
    prohibited: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").lower()
        filename = normalized.rsplit("/", maxsplit=1)[-1]
        if normalized.startswith(("data/raw/", "data/canonical/", "data/real/raw/")):
            prohibited.append(path)
        elif normalized.endswith((".parquet", ".bi5")):
            prohibited.append(path)
        elif any(token in filename for token in ("credential", "secret", ".env")):
            prohibited.append(path)
        elif "row_level" in normalized or "provider_payload" in normalized:
            prohibited.append(path)
    return prohibited


def validate_no_forward_handoff(paths: list[str]) -> dict[str, Any]:
    """Reject prospective artifacts introduced by the closed lineage."""
    blocked_tokens = (
        "strategy_alpha_forward_v1",
        "prospective_protocol_freeze",
        "forward_collection_handoff",
        "live_capital_handoff",
        "paper_trading_handoff",
    )
    blocked = [path for path in paths if any(token in path.lower() for token in blocked_tokens)]
    return {"blocked_paths": blocked, "status": "PASS" if not blocked else "FAIL"}
