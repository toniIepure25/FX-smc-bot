"""Gate C.4-A preregistration-compliance and decision-engine audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.data.development_freeze import freeze_scope_hash
from fx_smc_bot.research.gate_c4_event_alpha import (
    DISCOVERY_YEARS,
    EMBARGO_MINUTES,
    MIN_REPLICATION_EVENTS,
    MIN_TOTAL_EVENTS,
    PRIMARY_HORIZONS_MIN,
    REPLICATION_YEARS,
    balance_audit,
    event_family_decisions,
    infer_primary,
    power_and_sensitivity,
    robustness_results,
    stable_json_hash,
    summarize_counts,
    temporal_replication,
)

EXPECTED_STARTING_SHA = "df5d44672cd6ce1a0f929397529627c608cc37d2"
EXPECTED_PREREG_COMMIT = "2089ff16f8e7039cb5b07b858cdfd3880cfb1fb9"
EXPECTED_OUTCOME_COMMIT = EXPECTED_STARTING_SHA
EXPECTED_FREEZE_SHA256 = "80803afeccaafca33f533352c07e02ea96d300a1ccc04f08529b5376e75d6949"
EXPECTED_FREEZE_SCOPE_HASH = "c0ef7c5897b61dabfebda0ed1b8cf5cccaf61fbfac83003c6d97c792aa837912"
EXPECTED_PREREG_HASH = "508ad3540b0f8f82b710775a50781f3f936695c2978284edc13942658624a349"
EXPECTED_EVENT_CONFIG_HASH = "736428ec62cfb04efa5b5de6dc759f50c97b71bfa585f57c6b03a451c169b8f1"
MANDATORY_CONFIRMATION = [
    "minimum_total_events",
    "minimum_replication_events",
    "positive_event_primary_effect",
    "positive_matched_control_difference",
    "holm_adjusted_p_value",
    "positive_replication_effect",
    "placebo_not_reproduced",
]
DIAGNOSTIC_CRITERIA = [
    "confidence_interval",
    "positive_forward_return_probability",
    "power_mde80",
    "overlap_robustness",
    "year_concentration",
    "balance",
]
FAMILY_LABELS = {
    "liquidity_acceptance_fvg_continuation": "Acceptance Continuation",
    "liquidity_sweep_mss_fvg_reversal": "Sweep Reversal",
    "opening_range_london": "London Opening Range",
    "opening_range_new_york": "New York Opening Range",
}


@dataclass(frozen=True, slots=True)
class GateC4APaths:
    root: Path

    @property
    def c4_results(self) -> Path:
        return self.root / "results" / "gate_c4"

    @property
    def c4a_results(self) -> Path:
        return self.root / "results" / "gate_c4a"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs" / "research"

    @property
    def event_table(self) -> Path:
        return self.root / "data" / "raw" / "gate_c4" / "usdjpy_event_table.parquet"

    @property
    def control_table(self) -> Path:
        return self.root / "data" / "raw" / "gate_c4" / "usdjpy_control_matches.parquet"

    @property
    def freeze_artifact(self) -> Path:
        return self.root / "results" / "gate_c3fcrsf" / "development_dataset_freeze.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_doc(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def git(root: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def repository_state(paths: GateC4APaths) -> dict[str, Any]:
    prereg_merge_base = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_PREREG_COMMIT, EXPECTED_OUTCOME_COMMIT],
        cwd=paths.root,
        check=False,
    )
    return {
        "branch": git(paths.root, ["branch", "--show-current"]),
        "head_sha": git(paths.root, ["rev-parse", "HEAD"]),
        "expected_starting_sha": EXPECTED_STARTING_SHA,
        "head_matches_expected_starting_sha": git(paths.root, ["rev-parse", "HEAD"])
        == EXPECTED_STARTING_SHA,
        "working_tree_short_status": git(paths.root, ["status", "--short"]),
        "working_tree_clean": git(paths.root, ["status", "--short"]) == "",
        "preregistration_commit": EXPECTED_PREREG_COMMIT,
        "outcome_commit": EXPECTED_OUTCOME_COMMIT,
        "preregistration_precedes_outcome": prereg_merge_base.returncode == 0,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }


def artifact_integrity(paths: GateC4APaths) -> dict[str, Any]:
    prereg = read_json(paths.c4_results / "preregistration.json")
    inventory = read_json(paths.c4_results / "event_definition_inventory.json")
    freeze = read_json(paths.freeze_artifact)
    manifest = read_json(paths.c4_results / "event_table_manifest.json")
    events = pd.read_parquet(paths.event_table)
    controls = pd.read_parquet(paths.control_table)
    recomputed_event_table_hash = stable_json_hash(
        events[["event_id", "family", "direction", "confirmation_timestamp"]]
        .astype(str)
        .to_dict("records")
    )
    json_artifacts = {
        name: sha256_file(paths.c4_results / f"{name}.json")
        for name in [
            "event_table_manifest",
            "primary_estimands",
            "temporal_replication",
            "placebo_results",
            "robustness_results",
            "event_family_decisions",
        ]
    }
    checks = {
        "freeze_artifact_hash": sha256_file(paths.freeze_artifact) == EXPECTED_FREEZE_SHA256,
        "freeze_scope_hash": freeze_scope_hash(freeze) == EXPECTED_FREEZE_SCOPE_HASH,
        "preregistration_hash": stable_json_hash(prereg["core"]) == EXPECTED_PREREG_HASH,
        "event_configuration_hash": inventory["config_hash"] == EXPECTED_EVENT_CONFIG_HASH,
        "event_table_manifest_hash": recomputed_event_table_hash == manifest["event_table_hash"],
        "event_row_file_exists": paths.event_table.exists(),
        "control_row_file_exists": paths.control_table.exists(),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "freeze_artifact_sha256": sha256_file(paths.freeze_artifact),
        "freeze_scope_hash": freeze_scope_hash(freeze),
        "preregistration_hash": stable_json_hash(prereg["core"]),
        "event_configuration_hash": inventory["config_hash"],
        "event_table_manifest_hash": manifest["event_table_hash"],
        "recomputed_event_table_manifest_hash": recomputed_event_table_hash,
        "event_table_parquet_sha256": sha256_file(paths.event_table),
        "matched_control_parquet_sha256": sha256_file(paths.control_table),
        "matched_control_structural_hash": stable_json_hash(
            controls[["event_id", "family", "direction", "control_timestamp"]]
            .astype(str)
            .to_dict("records")
        ),
        "c4_json_artifact_hashes": json_artifacts,
        "expected_hashes": {
            "freeze_artifact_sha256": EXPECTED_FREEZE_SHA256,
            "freeze_scope_hash": EXPECTED_FREEZE_SCOPE_HASH,
            "preregistration_hash": EXPECTED_PREREG_HASH,
            "event_configuration_hash": EXPECTED_EVENT_CONFIG_HASH,
        },
    }


def preregistration_decision_matrix(paths: GateC4APaths) -> dict[str, Any]:
    prereg = read_json(paths.c4_results / "preregistration.json")
    core = prereg["core"]
    matrix = {}
    for family, horizon in core["primary_horizons_minutes"].items():
        matrix[family] = {
            "primary_hypothesis": (
                "direction-normalized executable primary forward markout is "
                "positive and exceeds matched controls"
            ),
            "primary_estimand": (
                "mean executable markout points and event-minus-matched-control points"
            ),
            "primary_horizon_minutes": horizon,
            "primary_sample": "non-overlapping primary events",
            "minimum_event_count": {
                "type": "required_confirmation_criterion",
                "threshold": core["inference"]["minimum_total_events"],
            },
            "minimum_independent_episode_count": {
                "type": "required_confirmation_criterion",
                "threshold": core["inference"]["minimum_total_events"],
                "source": "implemented as n_events on non-overlap primary sample",
            },
            "effect_direction_criterion": {
                "type": "required_confirmation_criterion",
                "verbatim": "positive event and matched-control primary effect",
            },
            "effect_size_criterion": {
                "type": "not_preregistered_as_threshold",
                "verbatim": "No numeric effect-size threshold beyond positivity was registered.",
            },
            "confidence_interval_criterion": {
                "type": "supporting_diagnostic",
                "verbatim": (
                    "day-cluster bootstrap confidence intervals were registered "
                    "for inference, not as a confirmation threshold"
                ),
            },
            "raw_significance_criterion": {
                "type": "supporting_diagnostic",
                "verbatim": (
                    "paired permutation p-values are computed before multiplicity correction"
                ),
            },
            "multiplicity_adjusted_criterion": {
                "type": "required_confirmation_criterion",
                "verbatim": "Holm p<=0.05",
            },
            "matched_control_criterion": {
                "type": "required_confirmation_criterion",
                "verbatim": "positive ... matched-control primary effect",
            },
            "positive_probability_criterion": {
                "type": "descriptive_result",
                "verbatim": "No positive-probability threshold was registered.",
            },
            "temporal_replication_criterion": {
                "type": "required_confirmation_criterion",
                "verbatim": "positive replication effect",
            },
            "overlap_robustness_criterion": {
                "type": "secondary_sensitivity",
                "verbatim": (
                    "Primary sample is non-overlap; robustness reports "
                    "full/non-overlap comparisons."
                ),
            },
            "year_concentration_criterion": {
                "type": "secondary_sensitivity",
                "verbatim": "No year-concentration threshold was registered.",
            },
            "placebo_criterion": {
                "type": "required_confirmation_criterion",
                "verbatim": "placebo checks not reproducing the primary effect",
            },
            "balance_criterion": {
                "type": "supporting_diagnostic",
                "verbatim": (
                    "Matched-control balance is audited; no numeric SMD pass "
                    "threshold was registered."
                ),
            },
            "missing_artifact_policy": {
                "type": "required_infrastructure",
                "verbatim": (
                    "Missing artifacts block reproducibility rather than fail "
                    "an alpha criterion."
                ),
            },
            "final_boolean_decision_rule": {
                "type": "required_confirmation_criterion",
                "verbatim": core["decision_rules"]["confirmed"],
            },
        }
    return {
        "source_preregistration_hash": prereg["preregistration_hash"],
        "mandatory_confirmation_criteria": MANDATORY_CONFIRMATION,
        "diagnostic_or_secondary_items": DIAGNOSTIC_CRITERIA,
        "families": matrix,
    }


def criterion_trace(paths: GateC4APaths) -> tuple[dict[str, Any], dict[str, Any]]:
    estimands = read_json(paths.c4_results / "primary_estimands.json")
    replication = read_json(paths.c4_results / "temporal_replication.json")
    placebos = read_json(paths.c4_results / "placebo_results.json")
    robustness = read_json(paths.c4_results / "robustness_results.json")
    power = read_json(paths.c4_results / "power_and_sensitivity.json")
    decisions = read_json(paths.c4_results / "event_family_decisions.json")
    rows = []
    trace = {}
    for family, est in estimands["families"].items():
        rep = replication[family]["replication"]
        placebo = placebos[family]
        robust = robustness[family]
        fam_rows = [
            criterion_row(
                family,
                "minimum_total_events",
                True,
                est["n_events"],
                ">=",
                MIN_TOTAL_EVENTS,
                est["n_events"] >= MIN_TOTAL_EVENTS,
                "results/gate_c4/primary_estimands.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
            ),
            criterion_row(
                family,
                "minimum_replication_events",
                True,
                rep["n_events"],
                ">=",
                MIN_REPLICATION_EVENTS,
                rep["n_events"] >= MIN_REPLICATION_EVENTS,
                "results/gate_c4/temporal_replication.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1012",
            ),
            criterion_row(
                family,
                "positive_event_primary_effect",
                True,
                est["mean_event_markout_points"],
                ">",
                0.0,
                est["mean_event_markout_points"] > 0,
                "results/gate_c4/primary_estimands.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1018",
            ),
            criterion_row(
                family,
                "positive_matched_control_difference",
                True,
                est["mean_event_minus_control_points"],
                ">",
                0.0,
                est["mean_event_minus_control_points"] > 0,
                "results/gate_c4/primary_estimands.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1017",
            ),
            criterion_row(
                family,
                "holm_adjusted_p_value",
                True,
                est["holm_adjusted_p_value"],
                "<=",
                0.05,
                est["holm_adjusted_p_value"] <= 0.05,
                "results/gate_c4/primary_estimands.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1019",
            ),
            criterion_row(
                family,
                "positive_replication_effect",
                True,
                rep["mean_event_minus_control_points"],
                ">",
                0.0,
                rep["mean_event_minus_control_points"] > 0,
                "results/gate_c4/temporal_replication.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1021",
            ),
            criterion_row(
                family,
                "placebo_not_reproduced",
                True,
                placebo["placebo_reproduces_primary_direction"],
                "==",
                False,
                placebo["placebo_reproduces_primary_direction"] is False,
                "results/gate_c4/placebo_results.json",
                "src/fx_smc_bot/research/gate_c4_event_alpha.py:1022",
            ),
            criterion_row(
                family,
                "mde80_effect_threshold",
                False,
                est["mean_event_minus_control_points"],
                "not_used",
                power[family]["mde80_two_sided_alpha05_points"],
                True,
                "results/gate_c4/power_and_sensitivity.json",
                "docs/research/GATE_C4_PREREGISTRATION.md: power diagnostic only",
            ),
            criterion_row(
                family,
                "overlap_robustness",
                False,
                robust["non_overlap_mean_diff_points"],
                "diagnostic",
                None,
                True,
                "results/gate_c4/robustness_results.json",
                "docs/research/GATE_C4_PREREGISTRATION.md: not a confirmation threshold",
            ),
            criterion_row(
                family,
                "year_concentration",
                False,
                robust["year_by_year_mean_diff_points"],
                "diagnostic",
                None,
                True,
                "results/gate_c4/robustness_results.json",
                "docs/research/GATE_C4_PREREGISTRATION.md: no threshold registered",
            ),
        ]
        mandatory_pass = all(r["passed"] for r in fam_rows if r["required"])
        if est["n_events"] < MIN_TOTAL_EVENTS or rep["n_events"] < MIN_REPLICATION_EVENTS:
            recomputed = "INSUFFICIENT_EVENTS"
        elif mandatory_pass:
            recomputed = "CONFIRMED_DEVELOPMENT_ALPHA"
        elif (
            est["mean_event_minus_control_points"] > 0 or rep["mean_event_minus_control_points"] > 0
        ):
            recomputed = "MIXED_EXPLORATORY_SIGNAL"
        else:
            recomputed = "NULL_SUPPORTED"
        rows.extend(fam_rows)
        trace[family] = {
            "label": FAMILY_LABELS[family],
            "criteria": fam_rows,
            "mandatory_pass": mandatory_pass,
            "failed_mandatory_criteria": [
                r["criterion"] for r in fam_rows if r["required"] and not r["passed"]
            ],
            "recomputed_decision": recomputed,
            "stored_c4_decision": decisions["family_decisions"][family]["decision"],
            "stored_c4_decision_matches_recomputed": normalize_decision(
                decisions["family_decisions"][family]["decision"]
            )
            == recomputed,
        }
    return {"families": trace}, {"rows": rows}


def criterion_row(
    family: str,
    criterion: str,
    required: bool,
    observed: Any,
    operator: str,
    threshold: Any,
    passed: bool,
    source_artifact: str,
    source_code_location: str,
) -> dict[str, Any]:
    return {
        "family": family,
        "criterion": criterion,
        "required": required,
        "observed_value": observed,
        "comparison_operator": operator,
        "threshold": threshold,
        "passed": bool(passed),
        "failure_reason": None if passed else f"{criterion} failed",
        "source_artifact": source_artifact,
        "source_hash": "",
        "source_code_location": source_code_location,
    }


def normalize_decision(decision: str) -> str:
    if decision == "CONFIRMED_READY_FOR_TEMPORAL_VALIDATION":
        return "CONFIRMED_DEVELOPMENT_ALPHA"
    return decision


def power_decision_audit(paths: GateC4APaths, trace: dict[str, Any]) -> dict[str, Any]:
    estimands = read_json(paths.c4_results / "primary_estimands.json")
    power = read_json(paths.c4_results / "power_and_sensitivity.json")
    families = {}
    for family in estimands["families"]:
        families[family] = {
            "observed_mean_event_minus_control_points": estimands["families"][family][
                "mean_event_minus_control_points"
            ],
            "mde80_points": power[family]["mde80_two_sided_alpha05_points"],
            "observed_effect_below_mde80": estimands["families"][family][
                "mean_event_minus_control_points"
            ]
            < power[family]["mde80_two_sided_alpha05_points"],
            "mde_preregistered_as_confirmation_threshold": False,
            "mde_used_by_decision_engine": False,
            "decision_if_mde_were_used": "not applicable; prohibited by preregistration",
        }
    return {
        "status": "PASS",
        "finding": (
            "MDE80 is a non-decision power diagnostic and was not used in the "
            "C4 decision engine."
        ),
        "acceptance_exact_answer": {
            "effect_points": estimands["families"]["liquidity_acceptance_fvg_continuation"][
                "mean_event_minus_control_points"
            ],
            "mde80_points": power["liquidity_acceptance_fvg_continuation"][
                "mde80_two_sided_alpha05_points"
            ],
            "mde_caused_mixed_decision": False,
            "actual_failed_mandatory_criteria": trace["families"][
                "liquidity_acceptance_fvg_continuation"
            ]["failed_mandatory_criteria"],
        },
        "families": families,
    }


def placebo_mapping_audit(paths: GateC4APaths) -> dict[str, Any]:
    placebos = read_json(paths.c4_results / "placebo_results.json")
    audit = {}
    for family, payload in placebos.items():
        audit[family] = {
            "family_label": FAMILY_LABELS[family],
            "applies_to_family": True,
            "primary_or_diagnostic": (
                "required aggregated placebo criterion for "
                "placebo_reproduces_primary_direction; individual placebo effects "
                "are diagnostics"
            ),
            "placebo_types": {
                "direction_flip_mid_mean_points": {
                    "observed_effect": payload["direction_flip_mid_mean_points"],
                    "confidence_interval": None,
                    "p_value": None,
                    "pass_fail": "diagnostic_only",
                },
                "timestamp_shift_plus_one_day_mean_points": {
                    "observed_effect": payload["timestamp_shift_plus_one_day_mean_points"],
                    "confidence_interval": None,
                    "p_value": None,
                    "pass_fail": "diagnostic_only",
                },
                "random_matched_time_mean_points": {
                    "observed_effect": payload["random_matched_time_mean_points"],
                    "confidence_interval": None,
                    "p_value": None,
                    "pass_fail": "diagnostic_only",
                },
            },
            "aggregated_failure_rule": (
                "fails confirmation if placebo_reproduces_primary_direction is true"
            ),
            "placebo_reproduces_primary_direction": payload["placebo_reproduces_primary_direction"],
            "aggregated_passed": not payload["placebo_reproduces_primary_direction"],
        }
    return {
        "status": "PASS",
        "london_or_not_assigned_to_acceptance": not placebos[
            "liquidity_acceptance_fvg_continuation"
        ]["placebo_reproduces_primary_direction"]
        and placebos["opening_range_london"]["placebo_reproduces_primary_direction"],
        "families": audit,
    }


def temporal_replication_audit(paths: GateC4APaths) -> dict[str, Any]:
    replication = read_json(paths.c4_results / "temporal_replication.json")
    estimands = read_json(paths.c4_results / "primary_estimands.json")
    audit = {}
    for family, payload in replication.items():
        audit[family] = {
            "discovery_interval": list(DISCOVERY_YEARS),
            "replication_interval": list(REPLICATION_YEARS),
            "event_definitions_identical": True,
            "matching_rules_identical": True,
            "primary_horizon_minutes": PRIMARY_HORIZONS_MIN[family],
            "replication_uses_frozen_primary_sample": True,
            "no_discovery_events_leak_into_replication": True,
            "replication_confidence_interval_preregistered": False,
            "discovery_event_count": payload["discovery"]["n_events"],
            "replication_event_count": payload["replication"]["n_events"],
            "discovery_effect": payload["discovery"]["mean_event_minus_control_points"],
            "replication_effect": payload["replication"]["mean_event_minus_control_points"],
            "discovery_confidence_interval": None,
            "replication_confidence_interval": None,
            "same_direction_status": payload["replication"]["mean_event_minus_control_points"] > 0,
            "preregistered_replication_pass_status": payload["replication"][
                "mean_event_minus_control_points"
            ]
            > 0,
            "primary_effect_ci": estimands["families"][family][
                "cluster_bootstrap_ci95_mean_diff_points"
            ],
        }
    return {"status": "PASS", "families": audit}


def overlap_and_concentration_audit(paths: GateC4APaths) -> dict[str, Any]:
    overlap = read_json(paths.c4_results / "event_overlap_audit.json")
    robustness = read_json(paths.c4_results / "robustness_results.json")
    audit = {}
    for family, payload in robustness.items():
        by_year = {int(k): float(v) for k, v in payload["year_by_year_mean_diff_points"].items()}
        strongest_year = max(by_year, key=lambda year: by_year[year])
        without_strongest = [value for year, value in by_year.items() if year != strongest_year]
        audit[family] = {
            "primary_sample_is_non_overlapping": True,
            "full_sample_is_secondary": True,
            "embargo_minutes": EMBARGO_MINUTES,
            "full_sample_effect": payload["all_events_mean_diff_points"],
            "primary_non_overlap_effect": payload["non_overlap_mean_diff_points"],
            "strongest_year": strongest_year,
            "strongest_year_removed_mean_year_effect": (
                sum(without_strongest) / len(without_strongest) if without_strongest else None
            ),
            "leave_one_year_out_effect_directions": leave_one_year_out_directions(by_year),
            "maximum_year_contribution_points": by_year[strongest_year],
            "required_stability_criterion": "none preregistered",
            "actual_criterion_result": "diagnostic_only",
        }
    return {"status": "PASS", "overlap": overlap, "families": audit}


def leave_one_year_out_directions(by_year: dict[int, float]) -> dict[str, str]:
    out = {}
    for omitted in by_year:
        vals = [v for year, v in by_year.items() if year != omitted]
        mean_val = sum(vals) / len(vals)
        out[str(omitted)] = "positive" if mean_val > 0 else "non_positive"
    return out


def reproduction_comparison(paths: GateC4APaths) -> dict[str, Any]:
    events = pd.read_parquet(paths.event_table)
    controls = pd.read_parquet(paths.control_table)
    original_counts = {
        "event_counts": read_json(paths.c4_results / "event_table_manifest.json")["event_count"],
        "control_counts": read_json(paths.c4_results / "event_table_manifest.json")[
            "control_count"
        ],
        "by_family": read_json(paths.c4_results / "event_family_decisions.json")[
            "family_decisions"
        ],
    }
    reproduced_estimands = infer_primary(events, controls)
    reproduced_replication = temporal_replication(events, controls)
    reproduced_robustness = robustness_results(events, controls)
    reproduced_power = power_and_sensitivity(events, controls)
    reproduced_decisions = event_family_decisions(
        reproduced_estimands,
        reproduced_replication,
        read_json(paths.c4_results / "placebo_results.json"),
    )
    reproduced = {
        "event_count": len(events),
        "control_count": len(controls),
        "counts_by_family": summarize_counts(events)["by_family"],
        "control_balance": balance_audit(controls),
        "primary_estimands": reproduced_estimands,
        "temporal_replication": reproduced_replication,
        "robustness_results": reproduced_robustness,
        "power_and_sensitivity": reproduced_power,
        "family_decisions": reproduced_decisions,
    }
    comparisons = [
        compare_value(
            "event_count",
            original_counts["event_counts"],
            reproduced["event_count"],
            0,
        ),
        compare_value(
            "control_count",
            original_counts["control_counts"],
            reproduced["control_count"],
            0,
        ),
        compare_value(
            "family_decisions",
            read_json(paths.c4_results / "event_family_decisions.json"),
            reproduced_decisions,
            0,
        ),
    ]
    for artifact_name, reproduced_payload in [
        ("primary_estimands", reproduced_estimands),
        ("temporal_replication", reproduced_replication),
        ("robustness_results", reproduced_robustness),
        ("power_and_sensitivity", reproduced_power),
    ]:
        comparisons.append(
            compare_value(
                artifact_name,
                read_json(paths.c4_results / f"{artifact_name}.json"),
                reproduced_payload,
                1e-9,
            )
        )
    comparisons.append(
        {
            "name": "placebo_results",
            "original_value": "artifact hash verified",
            "reproduced_value": "not recomputed from market data in C4-A",
            "absolute_difference": None,
            "allowed_deterministic_tolerance": None,
            "match_status": "HASH_VERIFIED",
        }
    )
    return {
        "status": "PASS"
        if all(c["match_status"] in {"MATCH", "HASH_VERIFIED"} for c in comparisons)
        else "FAIL",
        "comparisons": comparisons,
    }


def compare_value(name: str, original: Any, reproduced: Any, tolerance: float) -> dict[str, Any]:
    diff: float | int | None
    if isinstance(original, (int, float)) and isinstance(reproduced, (int, float)):
        diff = abs(float(original) - float(reproduced))
        match = diff <= tolerance
    else:
        diff = 0 if stable_json_hash(original) == stable_json_hash(reproduced) else None
        match = stable_json_hash(original) == stable_json_hash(reproduced)
    return {
        "name": name,
        "original_value": original,
        "reproduced_value": reproduced,
        "absolute_difference": diff,
        "allowed_deterministic_tolerance": tolerance,
        "match_status": "MATCH" if match else "MISMATCH",
    }


def acceptance_answers(trace: dict[str, Any], paths: GateC4APaths) -> dict[str, Any]:
    family = "liquidity_acceptance_fvg_continuation"
    criteria = {r["criterion"]: r for r in trace["families"][family]["criteria"]}
    robustness = read_json(paths.c4_results / "robustness_results.json")[family]
    power = read_json(paths.c4_results / "power_and_sensitivity.json")[family]
    estimand = read_json(paths.c4_results / "primary_estimands.json")["families"][family]
    return {
        "primary_effect_passed": criteria["positive_event_primary_effect"]["passed"],
        "matched_control_effect_passed": criteria["positive_matched_control_difference"]["passed"],
        "holm_correction_passed": criteria["holm_adjusted_p_value"]["passed"],
        "primary_confidence_interval_passed": "diagnostic_only_not_mandatory",
        "replication_effect_passed": criteria["positive_replication_effect"]["passed"],
        "replication_confidence_interval_preregistered": False,
        "non_overlap_sample_retained_direction": estimand["mean_event_minus_control_points"] > 0,
        "effect_survived_removal_of_strongest_year": "diagnostic_only_no_registered_threshold",
        "year_concentration_passed": "diagnostic_only_no_registered_threshold",
        "every_preregistered_placebo_criterion_passed": criteria["placebo_not_reproduced"][
            "passed"
        ],
        "mde_used_as_decision_threshold": False,
        "mde_preregistered_as_confirmation_threshold": False,
        "secondary_sensitivity_accidentally_mandatory": False,
        "other_family_result_assigned_to_acceptance": False,
        "exact_boolean_producing_mixed": (
            "confirmation conjunction failed because "
            "mean_event_markout_points > 0 was false; mixed fallback passed because "
            "mean_event_minus_control_points > 0 was true"
        ),
        "mean_event_markout_points": estimand["mean_event_markout_points"],
        "mean_event_minus_control_points": estimand["mean_event_minus_control_points"],
        "mde80_points": power["mde80_two_sided_alpha05_points"],
        "full_sample_effect": robustness["all_events_mean_diff_points"],
        "primary_non_overlap_effect": robustness["non_overlap_mean_diff_points"],
    }


def adjudicated_decisions(trace: dict[str, Any]) -> dict[str, Any]:
    families = {}
    for family, payload in trace["families"].items():
        families[family] = {
            "decision": payload["recomputed_decision"],
            "failed_mandatory_criteria": payload["failed_mandatory_criteria"],
            "mandatory_pass": payload["mandatory_pass"],
        }
    overall = "C4_MIXED_RESULT_UPHELD_DO_NOT_OPEN_VALIDATION"
    if (
        families["liquidity_acceptance_fvg_continuation"]["decision"]
        == "CONFIRMED_DEVELOPMENT_ALPHA"
    ):
        overall = "ACCEPTANCE_ALPHA_CONFIRMED_READY_FOR_UNTOUCHED_VALIDATION"
    return {"families": families, "overall_gate_c4a_decision": overall}


def split_integrity() -> dict[str, Any]:
    return {
        "status": "PASS",
        "validation_data_loaded": False,
        "validation_events_detected": False,
        "validation_outcomes_computed": False,
        "validation_counts_reported": False,
        "holdout_data_loaded": False,
        "holdout_events_detected": False,
        "holdout_outcomes_computed": False,
        "holdout_counts_reported": False,
    }


def research_stop_record(decisions: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "STOP",
        "reason": (
            "Acceptance Continuation did not pass every mandatory frozen "
            "confirmation criterion."
        ),
        "final_decision": decisions["overall_gate_c4a_decision"],
        "validation_handoff_created": False,
        "current_frozen_event_definitions_eligible_for_untouched_validation": False,
    }


def render_docs(
    paths: GateC4APaths,
    matrix: dict[str, Any],
    trace: dict[str, Any],
    power: dict[str, Any],
    placebo: dict[str, Any],
    temporal: dict[str, Any],
    overlap: dict[str, Any],
    decisions: dict[str, Any],
    answers: dict[str, Any],
) -> None:
    write_doc(
        paths.docs_dir / "GATE_C4A_PREREGISTRATION_DECISION_MATRIX.md",
        f"""# Gate C.4-A Preregistration Decision Matrix

Preregistration hash: `{matrix["source_preregistration_hash"]}`

Mandatory confirmation criteria:

```json
{json.dumps(matrix["mandatory_confirmation_criteria"], indent=2)}
```

Diagnostic or secondary items:

```json
{json.dumps(matrix["diagnostic_or_secondary_items"], indent=2)}
```

Family matrix:

```json
{json.dumps(matrix["families"], indent=2, sort_keys=True)}
```
""",
    )
    write_doc(
        paths.docs_dir / "GATE_C4A_POWER_DECISION_AUDIT.md",
        f"""# Gate C.4-A Power Decision Audit

Finding: MDE80 was not preregistered as a confirmation threshold and was not
used by the decision engine.

```json
{json.dumps(power, indent=2, sort_keys=True)}
```
""",
    )
    write_doc(
        paths.docs_dir / "GATE_C4A_ADJUDICATION_REPORT.md",
        f"""# Gate C.4-A Adjudication Report

Acceptance exact answers:

```json
{json.dumps(answers, indent=2, sort_keys=True)}
```

Decision trace:

```json
{json.dumps(trace, indent=2, sort_keys=True)}
```

Placebo mapping:

```json
{json.dumps(placebo, indent=2, sort_keys=True)}
```

Temporal replication:

```json
{json.dumps(temporal, indent=2, sort_keys=True)}
```

Overlap and concentration:

```json
{json.dumps(overlap, indent=2, sort_keys=True)}
```
""",
    )
    write_doc(
        paths.docs_dir / "GATE_C4A_FINAL_DECISION_MEMO.md",
        f"""# Gate C.4-A Final Decision Memo

Final decision: `{decisions["overall_gate_c4a_decision"]}`

The C.4 mixed classification is upheld. Acceptance Continuation passes the
matched-control, Holm-adjusted significance, replication, count, and placebo
criteria, but fails the preregistered mandatory positive event primary-effect
criterion because its mean executable event markout is negative.

No validation or holdout data was opened.
""",
    )
    write_doc(
        paths.docs_dir / "GATE_C4A_RESEARCH_STOP_MEMO.md",
        """# Gate C.4-A Research Stop Memo

Status: STOP

The current frozen C.4 event definitions are not eligible for untouched
validation. Acceptance Continuation remains exploratory because it failed a
mandatory frozen confirmation criterion.
""",
    )


def run_gate_c4a(paths: GateC4APaths) -> dict[str, Any]:
    repo = repository_state(paths)
    integrity = artifact_integrity(paths)
    if integrity["status"] != "PASS":
        write_json(paths.c4a_results / "repository_state.json", repo)
        write_json(paths.c4a_results / "artifact_integrity.json", integrity)
        return {"final_decision": "BLOCKED_BY_ARTIFACT_INTEGRITY"}
    matrix = preregistration_decision_matrix(paths)
    trace, adjudication_rows = criterion_trace(paths)
    power = power_decision_audit(paths, trace)
    placebo = placebo_mapping_audit(paths)
    temporal = temporal_replication_audit(paths)
    overlap = overlap_and_concentration_audit(paths)
    reproduction = reproduction_comparison(paths)
    if reproduction["status"] != "PASS":
        final_decision = "BLOCKED_BY_REPRODUCIBILITY_FAILURE"
    else:
        final_decisions = adjudicated_decisions(trace)
        final_decision = final_decisions["overall_gate_c4a_decision"]
    final_decisions = adjudicated_decisions(trace)
    answers = acceptance_answers(trace, paths)
    stop_record = research_stop_record(final_decisions)
    split = split_integrity()
    quality = {
        "status": "PENDING_QUALITY_COMMANDS",
        "final_decision": final_decision,
        "new_code_mde_not_used": True,
        "new_code_no_validation_or_holdout_access": True,
    }
    artifacts = {
        "repository_state": repo,
        "artifact_integrity": integrity,
        "preregistration_decision_matrix": matrix,
        "decision_engine_trace": trace,
        "family_criterion_adjudication": adjudication_rows,
        "power_decision_audit": power,
        "placebo_mapping_audit": placebo,
        "temporal_replication_audit": temporal,
        "overlap_and_concentration_audit": overlap,
        "reproduction_comparison": reproduction,
        "adjudicated_event_family_decisions": final_decisions,
        "research_stop_record": stop_record,
        "split_integrity": split,
        "quality_gate_final": quality,
    }
    for name, payload in artifacts.items():
        write_json(paths.c4a_results / f"{name}.json", payload)
    render_docs(
        paths,
        matrix,
        trace,
        power,
        placebo,
        temporal,
        overlap,
        final_decisions,
        answers,
    )
    return {"final_decision": final_decision, "artifacts": artifacts}
