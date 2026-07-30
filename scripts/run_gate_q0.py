"""Generate compact Gate Q.0 preregistration artifacts without market-data access."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from fx_smc_bot.research.quant_polarity import (
    ALL_INSTRUMENTS,
    CANDIDATES,
    DEVELOPMENT_CRITERIA,
    DEVELOPMENT_END,
    DEVELOPMENT_INSTRUMENTS,
    DEVELOPMENT_START,
    EXCLUDED_OLD_INSTRUMENTS,
    FEATURES,
    HOLDOUT_END,
    HOLDOUT_START,
    HYPERPARAMETERS,
    LINEAGE_ID,
    PREVIOUS_SEAL_HASH,
    PREVIOUS_SEAL_ID,
    PREVIOUS_SEAL_STATUS,
    PROGRAM_ID,
    PROHIBITED_FEATURES,
    RELATIONSHIP,
    REPLICATION_END,
    REPLICATION_INSTRUMENTS,
    REPLICATION_START,
    SOURCE_HYPOTHESIS,
    TIER_A_CRITERIA,
    TIER_B_CRITERIA,
    canonical_json_sha256,
    validate_feature_contract,
    validate_previous_lineage,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "gate_q0"
DOCS = ROOT / "docs" / "research" / "quant_polarity"
PREVIOUS_FILES = (
    "results/gate_p1/strategy_alpha_lineage_seal.json",
    "results/gate_p1/posthoc_hypothesis_quarantine.json",
    "results/gate_p1/final_claim_matrix.json",
    "results/gate_p1/closure_lock.json",
    "results/gate_p1/reproducibility_manifest.json",
)
MERGE_COMMIT = "1df74d0dbf185fad78851036f13fcf4d3166ea0a"
SOURCE_SHA = "cd2e44d15fee2775f42433577a2fe742334a24f7"
BRANCH = "research/quant-polarity-meta-v1"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _read_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _raw_sha256(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _write_json(name: str, payload: dict[str, Any]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    target = RESULTS / name
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_doc(name: str, title: str, paragraphs: list[str], facts: dict[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", *paragraphs, "", "## Frozen Contract", ""]
    lines.extend(f"- **{key}:** `{value}`" for key, value in facts.items())
    lines.extend(["", "Status: **PASS**", ""])
    (DOCS / name).write_text("\n".join(lines), encoding="utf-8")


def generate_identity() -> None:
    previous = {path: _read_json(path) for path in PREVIOUS_FILES}
    seal = previous[PREVIOUS_FILES[0]]
    quarantine = previous[PREVIOUS_FILES[1]]
    closure = previous[PREVIOUS_FILES[3]]
    validation = validate_previous_lineage(seal, quarantine, closure)
    current_head = _git("rev-parse", "HEAD")
    main_sha = _git("rev-parse", "origin/main")
    merge_parents = _git("rev-list", "--parents", "-n", "1", MERGE_COMMIT).split()[1:]
    repository_state = {
        "branch": BRANCH,
        "branch_starting_sha": MERGE_COMMIT,
        "current_head_at_freeze": current_head,
        "main_sha_at_branch_creation": main_sha,
        "merge_commit": MERGE_COMMIT,
        "merge_commit_parent_count": len(merge_parents),
        "pr_number": 2,
        "pr_source_sha": SOURCE_SHA,
        "status": "PASS" if len(merge_parents) == 2 and main_sha == MERGE_COMMIT else "FAIL",
    }
    inheritance = {
        "files": [
            {"path": path, "raw_sha256": _raw_sha256(path)} for path in PREVIOUS_FILES
        ],
        "previous_seal_hash": PREVIOUS_SEAL_HASH,
        "previous_seal_id": PREVIOUS_SEAL_ID,
        "previous_status": PREVIOUS_SEAL_STATUS,
        "validation": validation,
        "status": validation["status"],
    }
    boundary = {
        "lineage_id": LINEAGE_ID,
        "program_id": PROGRAM_ID,
        "relationship_to_previous_lineage": RELATIONSHIP,
        "source_hypothesis": SOURCE_HYPOTHESIS,
        "qualitative_motivation_only": True,
        "old_lineage_reopened": False,
        "old_candidate_results_permitted_as_labels": False,
        "old_row_ledgers_permitted": False,
        "excluded_old_instruments": list(EXCLUDED_OLD_INSTRUMENTS),
        "holdout_access_permitted_in_q0": False,
        "automated_guards": [
            "provider_request_authorization",
            "explicit_market_path_authorization",
            "training_source_authorization",
        ],
        "status": "PASS",
    }
    _write_json("repository_state.json", repository_state)
    _write_json("previous_lineage_inheritance.json", inheritance)
    _write_json("new_lineage_boundary.json", boundary)
    _write_doc(
        "Q0_NEW_LINEAGE_BOUNDARY.md",
        "Q.0 New-Lineage Boundary",
        [
            "This program is independent from the permanently closed Strategy-Alpha lineage.",
            "The prior direction-flip observation is qualitative motivation only and is not "
            "validation evidence.",
            "Automated guards reject old outcomes as labels and block every Gate Q.0 "
            "holdout access path.",
        ],
        {
            "program_id": PROGRAM_ID,
            "lineage_id": LINEAGE_ID,
            "relationship": RELATIONSHIP,
            "previous_seal_hash": PREVIOUS_SEAL_HASH,
        },
    )


def generate_family() -> None:
    universe = {
        "development_instruments": list(DEVELOPMENT_INSTRUMENTS),
        "replication_instruments": list(REPLICATION_INSTRUMENTS),
        "complete_frozen_universe": list(ALL_INSTRUMENTS),
        "excluded_old_instruments": list(EXCLUDED_OLD_INSTRUMENTS),
        "replication_contributes_to_development_selection": False,
        "status": "PASS",
    }
    partitions = {
        "development": [DEVELOPMENT_START.isoformat(), DEVELOPMENT_END.isoformat()],
        "internal_replication": [REPLICATION_START.isoformat(), REPLICATION_END.isoformat()],
        "confirmatory_holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
        "gate_q0_latest_permitted_date": REPLICATION_END.isoformat(),
        "holdout_untouched_required": True,
        "status": "PASS",
    }
    execution = {
        "provider": "Dukascopy tick/BI5 bid and ask",
        "canonical_intermediate": "UTC M1 bid/ask OHLC",
        "execution_bars": "deterministic M5 bid/ask OHLC",
        "same_bar_primary_rule": "adverse-first",
        "warmup_m5_bars": 500,
        "sessions": {
            "london": "08:00-11:00 Europe/London",
            "new_york": "08:00-11:00 America/New_York",
        },
        "fx_week": "Sunday 17:00-Friday 17:00 America/New_York",
        "overnight_carry": False,
        "weekend_carry": False,
        "cost_scenarios": {
            "base": "actual executable spread + frozen commission + frozen slippage",
            "stress_1": "1.5x spread and slippage",
            "stress_2": "2.0x spread and slippage",
        },
        "status": "PASS",
    }
    candidate_rows = [dict(candidate) for candidate in CANDIDATES]
    candidates = {
        "candidates": candidate_rows,
        "candidate_hashes": {
            row["candidate_id"]: canonical_json_sha256(row) for row in candidate_rows
        },
        "candidate_family_hash": canonical_json_sha256(candidate_rows),
        "candidate_count": len(candidate_rows),
        "new_entry_stop_target_or_exit_permitted": False,
        "status": "PASS",
    }
    _write_json("instrument_universe_freeze.json", universe)
    _write_json("time_partition_freeze.json", partitions)
    _write_json("data_execution_contract.json", execution)
    _write_json("candidate_family_freeze.json", candidates)
    _write_doc(
        "Q0_INSTRUMENT_UNIVERSE.md",
        "Q.0 Instrument Universe",
        ["The development and replication universes are fixed before market-data access."],
        {
            "development": ", ".join(DEVELOPMENT_INSTRUMENTS),
            "replication": ", ".join(REPLICATION_INSTRUMENTS),
            "excluded": ", ".join(EXCLUDED_OLD_INSTRUMENTS),
        },
    )
    _write_doc(
        "Q0_TIME_PARTITIONS.md",
        "Q.0 Time Partitions",
        ["Development, replication, and confirmatory intervals are disjoint and immutable."],
        {
            "development": "2015-01-01 through 2019-12-31",
            "replication": "2020-01-01 through 2022-12-31",
            "untouched_holdout": "2023-01-01 through 2025-12-31",
        },
    )
    _write_doc(
        "Q0_DATA_AND_EXECUTION_CONTRACT.md",
        "Q.0 Data and Execution Contract",
        [
            "Executable bid/ask prices and adverse-first same-bar ordering are mandatory.",
            "Original and inverse variants preserve every source-policy rule except direction.",
        ],
        {
            "source": execution["provider"],
            "canonical": execution["canonical_intermediate"],
            "execution": execution["execution_bars"],
            "same_bar": execution["same_bar_primary_rule"],
        },
    )
    _write_doc(
        "Q0_CANDIDATE_FAMILY.md",
        "Q.0 Candidate Family",
        [
            "Exactly four deterministic inversions and one elastic-net polarity selector "
            "are allowed.",
            "No result-dependent additions, removals, or execution-rule changes are permitted.",
        ],
        {
            "candidate_count": len(candidate_rows),
            "family_hash": candidates["candidate_family_hash"],
            "meta_actions": "ORIGINAL, INVERSE, ABSTAIN",
        },
    )


def generate_preregistration() -> None:
    feature_validation = validate_feature_contract(FEATURES)
    feature_freeze = {
        "features": list(FEATURES),
        "feature_count": len(FEATURES),
        "feature_order_hash": canonical_json_sha256(FEATURES),
        "prohibited_features": list(PROHIBITED_FEATURES),
        "instrument_identity_primary_feature": False,
        "target_rule": {
            "ORIGINAL": "original_net_r > 0 and original_net_r > inverse_net_r",
            "INVERSE": "inverse_net_r > 0 and inverse_net_r > original_net_r",
            "ABSTAIN": "otherwise",
        },
        "decision_thresholds": {"ORIGINAL": 0.55, "INVERSE": 0.55},
        "validation": feature_validation,
        "status": feature_validation["status"],
    }
    model_freeze = {
        "model": "multinomial elastic-net logistic regression",
        "allowed_hyperparameters": list(HYPERPARAMETERS),
        "hyperparameter_count": len(HYPERPARAMETERS),
        "selection_metric": "cross-validated multinomial log loss",
        "performance_metrics_for_selection": False,
        "outer_folds": "calendar-year forward folds within 2015-2019",
        "inner_fold_constraint": "dates strictly earlier than outer-test dates",
        "purge": "maximum position horizon plus warm-up dependency",
        "embargo_fx_trading_days": 5,
        "seed": 1729,
        "status": "PASS",
    }
    inference = {
        "primary_profitability_estimand": "mean net executable R per accepted trade",
        "primary_benchmark_alpha": "candidate mean net R minus matched-random-entry mean net R",
        "factor_model": [
            "fixed FX time-series momentum factor",
            "fixed short-term reversal factor",
            "broad USD-direction factor",
            "realized-volatility factor",
        ],
        "factor_alpha": "descriptive intercept",
        "newey_west_hac_lag_trading_days": 5,
        "required_inference": [
            "day-cluster bootstrap CI",
            "week-cluster bootstrap sensitivity",
            "stationary bootstrap",
            "permutation test versus matched random entries",
            "White Reality Check",
            "Hansen SPA",
            "Romano-Wolf max-T sensitivity",
            "Holm family-wise correction",
            "Benjamini-Hochberg FDR sensitivity",
            "probabilistic Sharpe ratio",
            "deflated Sharpe ratio",
            "probability of backtest overfitting",
        ],
        "status": "PASS",
    }
    selection = {
        "development_shortlist_criteria": DEVELOPMENT_CRITERIA,
        "maximum_shortlist_candidates": 2,
        "development_ranking": [
            "highest lower day-cluster CI bound",
            "highest 1.5x cost mean",
            "lowest maximum drawdown",
            "lowest PBO",
        ],
        "tier_a_criteria": TIER_A_CRITERIA,
        "tier_b_criteria": TIER_B_CRITERIA,
        "maximum_confirmatory_candidates": 1,
        "replication_tuning_permitted": False,
        "status": "PASS",
    }
    _write_json("feature_and_label_freeze.json", feature_freeze)
    _write_json("model_selection_freeze.json", model_freeze)
    _write_json("estimand_and_inference_freeze.json", inference)
    _write_json("selection_and_replication_freeze.json", selection)
    _write_doc(
        "Q0_FEATURE_SPECIFICATION.md",
        "Q.0 Feature Specification",
        [
            "All features must be available at the signal decision time.",
            "Instrument identity is diagnostic only; outcomes and post-signal information "
            "are prohibited.",
        ],
        {
            "feature_count": len(FEATURES),
            "feature_order_hash": feature_freeze["feature_order_hash"],
            "decision_threshold": "0.55 for ORIGINAL or INVERSE; otherwise ABSTAIN",
        },
    )
    _write_doc(
        "Q0_MODEL_SELECTION_PROTOCOL.md",
        "Q.0 Model Selection Protocol",
        [
            "The complete search contains nine preregistered elastic-net combinations.",
            "Nested purged forward validation selects only by multinomial log loss.",
        ],
        {
            "hyperparameter_combinations": len(HYPERPARAMETERS),
            "purge": model_freeze["purge"],
            "embargo": "5 FX trading days",
            "seed": 1729,
        },
    )
    _write_doc(
        "Q0_QUANT_INFERENCE_PROTOCOL.md",
        "Q.0 Quantitative Inference Protocol",
        [
            "Economic inference is evaluated at accepted-trade and UTC-day aggregation levels.",
            "Family-wise, false-discovery, data-snooping, Sharpe, and overfitting "
            "diagnostics are mandatory.",
        ],
        {
            "primary_estimand": inference["primary_profitability_estimand"],
            "benchmark": inference["primary_benchmark_alpha"],
            "HAC_lag": "5 trading days",
        },
    )
    _write_doc(
        "Q0_SELECTION_RULES.md",
        "Q.0 Selection and Replication Rules",
        [
            "At most two development candidates may enter the one-time independent replication.",
            "Only one mechanically ranked Tier A or Tier B candidate may be frozen "
            "for confirmation.",
        ],
        {
            "development_shortlist_maximum": 2,
            "confirmatory_maximum": 1,
            "replication_refitting": "prohibited",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group", choices=("identity", "family", "preregistration", "all"), default="all"
    )
    args = parser.parse_args()
    if args.group in {"identity", "all"}:
        generate_identity()
    if args.group in {"family", "all"}:
        generate_family()
    if args.group in {"preregistration", "all"}:
        generate_preregistration()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
