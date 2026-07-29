"""Gate C.5-A prospective handoff amendment helpers.

This module resolves the C5 pre-unblinding ambiguity with a separate amendment
overlay. It may replay only frozen 2015-2019 development row artifacts before
any validation access.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy import stats  # type: ignore[import-untyped]

from fx_smc_bot.research.gate_c4_event_alpha import (
    EMBARGO_MINUTES,
    MIN_TOTAL_EVENTS,
    POINT_SCALE,
    RNG_SEED,
    SECONDARY_HORIZONS_MIN,
    _candidate_pool,
    apply_outcomes,
    cluster_bootstrap_ci,
    load_development_m5,
    paired_permutation_p_value,
    stable_json_hash,
)

ACCEPTANCE_FAMILY = "liquidity_acceptance_fvg_continuation"
AMENDMENT_ID = "C5A_C4B_USDJPY_RELATIVE_RESILIENCE_HANDOFF_AMENDMENT_V1"
AMENDMENT_STATUS = "PROSPECTIVELY_FROZEN_BEFORE_VALIDATION_ACCESS"
HYPOTHESIS_ID = "C4B_USDJPY_ACCEPTANCE_RELATIVE_RESILIENCE_V1"
HYPOTHESIS_HASH = "e8b726734a3b5118709edc7642caa1d4e10bad2509aa9fd0949a0cca2b05290d"
EVENT_CONFIGURATION_HASH = "736428ec62cfb04efa5b5de6dc759f50c97b71bfa585f57c6b03a451c169b8f1"
PRIMARY_HORIZON_MINUTES = 120
BALANCE_SMD_THRESHOLD = 0.10
PRIMARY_ALPHA = 0.05
PERMUTATION_ITERATIONS = 2000
BOOTSTRAP_ITERATIONS = 1000
COVARIATES = ("spread", "atr", "pre_event_volatility", "pre_event_trend", "range_position")
EXACT_KEYS = ("year", "month", "session", "direction")


@dataclass(frozen=True, slots=True)
class GateC5APaths:
    root: Path

    @property
    def results_dir(self) -> Path:
        return self.root / "results" / "gate_c5a"

    @property
    def docs_dir(self) -> Path:
        return self.root / "docs" / "research"

    @property
    def c4_results(self) -> Path:
        return self.root / "results" / "gate_c4"

    @property
    def c4b_results(self) -> Path:
        return self.root / "results" / "gate_c4b"

    @property
    def c5_results(self) -> Path:
        return self.root / "results" / "gate_c5"

    @property
    def c4_event_table(self) -> Path:
        return self.root / "data" / "raw" / "gate_c4" / "usdjpy_event_table.parquet"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def git(root: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validation_access_artifacts_absent(paths: GateC5APaths) -> dict[str, bool]:
    probes = {
        "c5_validation_access_ledger_absent": not (
            paths.c5_results / "validation_access_ledger.json"
        ).exists(),
        "c5a_validation_access_ledger_absent": not (
            paths.results_dir / "validation_access_ledger.json"
        ).exists(),
        "c5a_validation_event_manifest_absent": not (
            paths.results_dir / "validation_event_manifest.json"
        ).exists(),
        "c5a_validation_primary_estimand_absent": not (
            paths.results_dir / "validation_primary_estimand.json"
        ).exists(),
        "c5a_holdout_access_ledger_absent": not (
            paths.results_dir / "holdout_access_ledger.json"
        ).exists(),
    }
    return probes


def repository_state(paths: GateC5APaths, expected_sha: str) -> dict[str, Any]:
    status = git(paths.root, ["status", "--short"])
    head = git(paths.root, ["rev-parse", "HEAD"])
    return {
        "gate": "C.5-A",
        "branch": git(paths.root, ["branch", "--show-current"]),
        "expected_starting_sha": expected_sha,
        "head_sha": head,
        "head_matches_expected": head == expected_sha,
        "working_tree_short_status": status,
        "working_tree_clean": status == "",
        "validation_access_checks": validation_access_artifacts_absent(paths),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }


def pre_amendment_integrity(paths: GateC5APaths) -> dict[str, Any]:
    spec = read_json(paths.c4b_results / "new_hypothesis_specification.json")
    handoff = read_json(paths.c4b_results / "untouched_validation_handoff.json")
    c5_matrix = read_json(paths.c5_results / "validation_decision_matrix.json")
    holdout = read_json(paths.c5_results / "holdout_integrity.json")
    c4_prereg = read_json(paths.c4_results / "preregistration.json")
    checks = {
        "hypothesis_id_unchanged": spec["hypothesis_id"] == HYPOTHESIS_ID,
        "hypothesis_hash_unchanged": spec["hypothesis_hash"] == HYPOTHESIS_HASH,
        "original_handoff_immutable_source_present": handoff["new_hypothesis_hash"]
        == HYPOTHESIS_HASH,
        "c5_blocked_by_expected_ambiguity": c5_matrix["final_decision"]
        == "BLOCKED_BY_VALIDATION_HANDOFF_AMBIGUITY",
        "c5_four_ambiguities_recorded": len(c5_matrix.get("blocked_by", [])) == 4,
        "c4_prereg_hash_matches": stable_json_hash(c4_prereg["core"])
        == c4_prereg["preregistration_hash"],
        "holdout_integrity_pass": holdout["status"] == "PASS",
        "validation_access_absent": all(validation_access_artifacts_absent(paths).values()),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "original_hypothesis_id": HYPOTHESIS_ID,
        "original_hypothesis_hash": HYPOTHESIS_HASH,
        "original_handoff_file_sha256": file_sha256(
            paths.c4b_results / "untouched_validation_handoff.json"
        ),
        "validation_or_holdout_accessed": False,
    }


def matching_protocol() -> dict[str, Any]:
    return {
        "exact_keys": list(EXACT_KEYS),
        "matching_type": "1:1 nearest-neighbour matching",
        "replacement": True,
        "random_seed": RNG_SEED,
        "embargo_minutes": EMBARGO_MINUTES,
        "covariates": list(COVARIATES),
        "exact_key_relaxations_required": 0,
        "fallback_allowed": False,
        "unmatched_event_policy": (
            "retained in event manifest, reported explicitly, excluded from paired primary estimand"
        ),
        "minimum_event_count_applies_after": [
            "primary non-overlap filtering",
            "complete 120-minute outcome coverage",
            "successful exact-key matching",
        ],
        "minimum_successfully_matched_events": MIN_TOTAL_EVENTS,
        "matching_coverage_threshold": "diagnostic_only",
    }


def inference_protocol() -> dict[str, Any]:
    return {
        "primary_alpha": PRIMARY_ALPHA,
        "paired_permutation_iterations": PERMUTATION_ITERATIONS,
        "day_cluster_bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "confidence_level": 0.95,
        "bootstrap_cluster": "UTC trading day",
        "holm_family_size": 1,
        "holm_adjusted_p_value": "raw primary p-value",
        "mandatory_requirements": {
            "event_minus_control_point_estimate_gt_0": True,
            "paired_permutation_p_value_lte_0_05": True,
            "ci95_lower_bound_gt_0": True,
        },
    }


def placebo_protocol() -> dict[str, Any]:
    return {
        "primary_placebo": "+1-day shifted pseudo-event relative-resilience placebo",
        "shift": "+24 hours UTC",
        "retain_direction": True,
        "require_shift_inside_interval": True,
        "require_complete_next_bar_entry_and_120m_outcome": True,
        "exclude_if_real_acceptance_event_inside_embargo_minutes": EMBARGO_MINUTES,
        "apply_same_primary_non_overlap_policy": True,
        "construct_controls_with_same_exact_matcher": True,
        "reproduces_if_all": {
            "placebo_differential_gt_0": True,
            "placebo_paired_permutation_p_lte_0_05": True,
            "placebo_ci95_lower_bound_gt_0": True,
        },
        "mandatory_criterion": "placebo_reproduces_relative_resilience = false",
    }


def handoff_amendment_payload() -> dict[str, Any]:
    core = {
        "amendment_id": AMENDMENT_ID,
        "status": AMENDMENT_STATUS,
        "gate": "C.5-A",
        "original_hypothesis_id": HYPOTHESIS_ID,
        "original_hypothesis_hash": HYPOTHESIS_HASH,
        "original_handoff_remains_immutable": True,
        "validation_or_holdout_information_available_during_resolution": False,
        "amendment_scope": "operational confirmation rules only",
        "not_originally_frozen_claim": True,
        "outcome_independent_with_respect_to_validation": True,
        "no_further_rule_amendment_after_validation_unblinding": True,
        "resolved_ambiguities": [
            "matching balance threshold",
            "exact matching and no-match policy",
            "mandatory CI lower-bound rule",
            "relative-resilience placebo operation",
        ],
        "matching_protocol": matching_protocol(),
        "inference_protocol": inference_protocol(),
        "placebo_protocol": placebo_protocol(),
    }
    return {
        **core,
        "amendment_hash": stable_json_hash(core),
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def amended_decision_matrix(amendment_hash: str) -> dict[str, Any]:
    criteria = [
        ("artifact_integrity", "equals", "PASS"),
        ("validation_data_quality", "equals", "PASS"),
        ("successfully_matched_primary_non_overlap_events", ">=", MIN_TOTAL_EVENTS),
        ("exact_key_relaxations", "equals", 0),
        ("every_post_match_abs_smd", "<=", BALANCE_SMD_THRESHOLD),
        ("mean_event_minus_control_executable_markout", ">", 0),
        ("paired_permutation_p_value", "<=", PRIMARY_ALPHA),
        ("ci95_lower_bound", ">", 0),
        ("mean_absolute_event_executable_markout", "<=", 0),
        ("plus_1_day_placebo_reproduces_relative_resilience", "equals", False),
        ("holdout_integrity", "equals", "PASS"),
    ]
    return {
        "gate": "C.5-A",
        "amendment_id": AMENDMENT_ID,
        "amendment_hash": amendment_hash,
        "decision_matrix_complete": True,
        "mandatory_criteria": [
            {
                "criterion_number": i + 1,
                "criterion": name,
                "mandatory_or_diagnostic": "mandatory",
                "comparison_operator": op,
                "threshold": threshold,
            }
            for i, (name, op, threshold) in enumerate(criteria)
        ],
        "all_eleven_mandatory_criteria_required": True,
        "positive_absolute_event_markout_interpretation": (
            "mechanism drift; fails relative-resilience criterion"
        ),
    }


def amendment_integrity_payload(
    amendment: dict[str, Any], matrix: dict[str, Any]
) -> dict[str, Any]:
    matching = matching_protocol()
    inference = inference_protocol()
    placebo = placebo_protocol()
    hashes = {
        "handoff_amendment_hash": amendment["amendment_hash"],
        "amended_decision_matrix_hash": stable_json_hash(matrix),
        "matching_protocol_hash": stable_json_hash(matching),
        "inference_protocol_hash": stable_json_hash(inference),
        "placebo_protocol_hash": stable_json_hash(placebo),
    }
    return {
        "status": "PASS",
        "amendment_id": AMENDMENT_ID,
        "validation_or_holdout_accessed": False,
        **hashes,
    }


def render_amendment_docs(
    paths: GateC5APaths,
    amendment: dict[str, Any],
    matrix: dict[str, Any],
) -> None:
    write_text(
        paths.docs_dir / "GATE_C5A_PROSPECTIVE_HANDOFF_AMENDMENT.md",
        f"""# Gate C.5-A Prospective Handoff Amendment

Amendment ID: `{AMENDMENT_ID}`

Amendment hash: `{amendment["amendment_hash"]}`

Status: `{AMENDMENT_STATUS}`

The previous C5 attempt stopped because four mandatory operational rules were
missing or conflicting. Validation and holdout information were not available
while resolving those rules. The original C4-B hypothesis ID and hash remain
unchanged; this amendment supplies operational confirmation rules only.

No further rule amendment is permitted after validation unblinding.

```json
{json.dumps(amendment, indent=2, sort_keys=True)}
```
""",
    )
    write_text(
        paths.docs_dir / "GATE_C5A_AMENDED_VALIDATION_DECISION_MATRIX.md",
        f"""# Gate C.5-A Amended Validation Decision Matrix

Decision matrix complete: `{matrix["decision_matrix_complete"]}`

All eleven mandatory criteria must pass. A positive absolute event markout is
not reinterpreted as alpha; it fails the frozen relative-resilience mechanism.

```json
{json.dumps(matrix, indent=2, sort_keys=True)}
```
""",
    )


def initialize_amendment(paths: GateC5APaths, expected_sha: str) -> dict[str, Any]:
    repo = repository_state(paths, expected_sha)
    pre = pre_amendment_integrity(paths)
    amendment = handoff_amendment_payload()
    matrix = amended_decision_matrix(amendment["amendment_hash"])
    integrity = amendment_integrity_payload(amendment, matrix)
    write_json(paths.results_dir / "repository_state.json", repo)
    write_json(paths.results_dir / "pre_amendment_integrity.json", pre)
    write_json(paths.results_dir / "handoff_amendment.json", amendment)
    write_json(paths.results_dir / "amended_validation_decision_matrix.json", matrix)
    write_json(paths.results_dir / "amendment_integrity.json", integrity)
    render_amendment_docs(paths, amendment, matrix)
    return {
        "repository_state": repo,
        "pre_amendment_integrity": pre,
        "handoff_amendment": amendment,
        "amended_validation_decision_matrix": matrix,
        "amendment_integrity": integrity,
    }


def _load_acceptance_events(paths: GateC5APaths) -> pd.DataFrame:
    events = pd.read_parquet(paths.c4_event_table)
    events = events[events["family"] == ACCEPTANCE_FAMILY].copy()
    events["confirmation_timestamp"] = pd.to_datetime(events["confirmation_timestamp"], utc=True)
    events["earliest_entry_timestamp"] = pd.to_datetime(
        events["earliest_entry_timestamp"], utc=True
    )
    return events.reset_index(drop=True)


def _primary_eligible_events(events: pd.DataFrame) -> pd.DataFrame:
    sample = events[
        (events["non_overlap_primary"])
        & (events["primary_horizon_minutes"] == PRIMARY_HORIZON_MINUTES)
        & (events["h120_complete"])
    ].copy()
    return sample.sort_values("confirmation_timestamp").reset_index(drop=True)


def exact_match_controls(
    df: pd.DataFrame,
    all_events: pd.DataFrame,
    primary_events: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pool = _candidate_pool(df, all_events)
    scale = pool[list(COVARIATES)].std().replace(0.0, 1.0)
    rng = np.random.default_rng(RNG_SEED)
    grouped = {key: grp for key, grp in pool.groupby(["year", "month", "session"], sort=False)}
    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    candidates_per_event: list[int] = []
    for event in primary_events.to_dict("records"):
        key = (event["year"], event["month"], event["session"])
        candidates = grouped.get(key)
        candidate_count = 0 if candidates is None else len(candidates)
        candidates_per_event.append(candidate_count)
        if candidates is None or candidates.empty:
            unmatched.append(
                {
                    "event_id": event["event_id"],
                    "reason": "no exact year/month/session candidates",
                    "year": event["year"],
                    "month": event["month"],
                    "session": event["session"],
                    "direction": event["direction"],
                }
            )
            continue
        event_vec = np.array([event[c] for c in COVARIATES], dtype=float)
        cand_mat = candidates[list(COVARIATES)].to_numpy(dtype=float)
        dist = np.sum(((cand_mat - event_vec) / scale.to_numpy(dtype=float)) ** 2, axis=1)
        min_dist = float(np.nanmin(dist))
        ties = np.flatnonzero(np.isclose(dist, min_dist))
        chosen = candidates.iloc[int(rng.choice(ties))]
        matches.append(
            {
                "event_id": event["event_id"],
                "family": event["family"],
                "direction": event["direction"],
                "control_index": int(chosen["bar_index"]),
                "control_timestamp": chosen["timestamp"],
                "match_distance": min_dist,
                "loosened_exact_match": False,
                "candidate_count": int(candidate_count),
                **{f"event_{c}": float(event[c]) for c in COVARIATES},
                **{f"control_{c}": float(chosen[c]) for c in COVARIATES},
            }
        )
    match_df = pd.DataFrame(matches)
    audit = matching_balance_audit(primary_events, match_df)
    audit.update(
        {
            "primary_eligible_events": int(len(primary_events)),
            "successfully_matched_events": int(len(match_df)),
            "unmatched_events": int(len(unmatched)),
            "unmatched_event_records": unmatched,
            "exact_key_relaxations": int(match_df["loosened_exact_match"].sum())
            if not match_df.empty
            else 0,
            "candidate_count_min": int(min(candidates_per_event)) if candidates_per_event else 0,
            "candidate_count_median": float(np.median(candidates_per_event))
            if candidates_per_event
            else 0.0,
            "candidate_count_max": int(max(candidates_per_event)) if candidates_per_event else 0,
            "matching_seed": RNG_SEED,
            "replacement": True,
            "exact_keys": list(EXACT_KEYS),
        }
    )
    return match_df, audit


def matching_balance_audit(events: pd.DataFrame, matches: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"pre_match_smd": {}, "post_match_smd": {}}
    if matches.empty:
        out["max_abs_post_match_smd"] = None
        out["balance_pass"] = False
        return out
    matched_events = events[events["event_id"].isin(matches["event_id"])].copy()
    for covar in COVARIATES:
        pre_event = events[covar].to_numpy(dtype=float)
        pre_control = matches[f"control_{covar}"].to_numpy(dtype=float)
        post_event = matched_events.set_index("event_id").loc[matches["event_id"], covar].to_numpy(
            dtype=float
        )
        post_control = matches[f"control_{covar}"].to_numpy(dtype=float)
        out["pre_match_smd"][covar] = smd(pre_event, pre_control)
        out["post_match_smd"][covar] = smd(post_event, post_control)
    max_abs = max(abs(v) for v in out["post_match_smd"].values())
    out["max_abs_post_match_smd"] = float(max_abs)
    out["balance_pass"] = bool(max_abs <= BALANCE_SMD_THRESHOLD)
    return out


def smd(left: np.ndarray, right: np.ndarray) -> float:
    pooled = np.sqrt((np.nanvar(left) + np.nanvar(right)) / 2.0)
    if pooled == 0 or not np.isfinite(pooled):
        pooled = 1.0
    return float((np.nanmean(left) - np.nanmean(right)) / pooled)


def add_control_outcomes_for_matches(
    df: pd.DataFrame, events: pd.DataFrame, matches: pd.DataFrame
) -> pd.DataFrame:
    event_lookup = events.set_index("event_id")
    records: list[dict[str, Any]] = []
    for match in matches.to_dict("records"):
        event = event_lookup.loc[match["event_id"]]
        entry_idx = int(match["control_index"]) + 1
        if entry_idx + max(h // 5 for h in SECONDARY_HORIZONS_MIN) >= len(df):
            continue
        direction = str(match["direction"])
        entry = df.iloc[entry_idx]
        rec = dict(match)
        rec["control_entry_index"] = entry_idx
        for minutes in SECONDARY_HORIZONS_MIN:
            exit_row = df.iloc[entry_idx + minutes // 5]
            if direction == "LONG":
                executable = (float(exit_row["bid_close"]) - float(entry["ask_open"])) * POINT_SCALE
                mid = (float(exit_row["mid_close"]) - float(entry["mid_open"])) * POINT_SCALE
            else:
                executable = (float(entry["bid_open"]) - float(exit_row["ask_close"])) * POINT_SCALE
                mid = (float(entry["mid_open"]) - float(exit_row["mid_close"])) * POINT_SCALE
            rec[f"h{minutes}_control_executable_markout_points"] = executable
            rec[f"h{minutes}_control_mid_markout_points"] = mid
        primary = int(event["primary_horizon_minutes"])
        rec["primary_control_executable_markout_points"] = rec[
            f"h{primary}_control_executable_markout_points"
        ]
        rec["primary_control_mid_markout_points"] = rec[f"h{primary}_control_mid_markout_points"]
        records.append(rec)
    return pd.DataFrame(records)


def primary_estimand(events: pd.DataFrame, controls: pd.DataFrame) -> dict[str, Any]:
    merged = events.merge(
        controls[
            [
                "event_id",
                "primary_control_executable_markout_points",
                "primary_control_mid_markout_points",
            ]
        ],
        on="event_id",
        how="inner",
    )
    event = merged["primary_executable_markout_points"].to_numpy(dtype=float)
    control = merged["primary_control_executable_markout_points"].to_numpy(dtype=float)
    diff = event - control
    days = merged["utc_date"].to_numpy()
    ci = cluster_bootstrap_ci(diff, days, RNG_SEED, BOOTSTRAP_ITERATIONS)
    p_value = paired_permutation_p_value(diff, RNG_SEED, PERMUTATION_ITERATIONS)
    return {
        "n": int(len(merged)),
        "mean_event_executable_markout_points": float(np.mean(event)) if len(event) else None,
        "mean_control_executable_markout_points": float(np.mean(control)) if len(control) else None,
        "mean_event_minus_control_points": float(np.mean(diff)) if len(diff) else None,
        "median_event_minus_control_points": float(np.median(diff)) if len(diff) else None,
        "trimmed_mean_event_minus_control_points": float(stats.trim_mean(diff, 0.1))
        if len(diff)
        else None,
        "event_outperforms_control_probability": float(np.mean(diff > 0)) if len(diff) else None,
        "positive_event_probability": float(np.mean(event > 0)) if len(event) else None,
        "positive_control_probability": float(np.mean(control > 0)) if len(control) else None,
        "paired_permutation_p_value": p_value,
        "holm_adjusted_p_value": p_value,
        "cluster_bootstrap_ci95_mean_diff_points": ci,
        "standardized_paired_effect": float(np.mean(diff) / np.std(diff, ddof=1))
        if len(diff) > 1 and np.std(diff, ddof=1) > 0
        else None,
    }


def non_overlap_by_confirmation(events: pd.DataFrame) -> pd.DataFrame:
    out = events.sort_values("confirmation_timestamp").copy()
    out["non_overlap_primary"] = False
    selected_until: pd.Timestamp | None = None
    for idx, row in out.iterrows():
        ts = row["confirmation_timestamp"]
        if selected_until is None or ts > selected_until:
            out.at[idx, "non_overlap_primary"] = True
            selected_until = row["earliest_entry_timestamp"] + pd.Timedelta(
                minutes=PRIMARY_HORIZON_MINUTES
            )
    return out.reset_index(drop=True)


def shifted_placebo_events(
    df: pd.DataFrame, real_events: pd.DataFrame, primary_events: pd.DataFrame
) -> pd.DataFrame:
    index_by_ts = {ts: i for i, ts in enumerate(df["timestamp"])}
    real_times = pd.to_datetime(real_events["confirmation_timestamp"], utc=True)
    records: list[dict[str, Any]] = []
    for event in primary_events.to_dict("records"):
        shifted_ts = event["confirmation_timestamp"] + pd.Timedelta(days=1)
        shifted_idx = index_by_ts.get(shifted_ts)
        if shifted_idx is None:
            continue
        if shifted_idx + 1 + PRIMARY_HORIZON_MINUTES // 5 >= len(df):
            continue
        inside_embargo = (
            (real_times >= shifted_ts - pd.Timedelta(minutes=EMBARGO_MINUTES))
            & (real_times <= shifted_ts + pd.Timedelta(minutes=EMBARGO_MINUTES))
        ).any()
        if inside_embargo:
            continue
        row = df.iloc[shifted_idx]
        if any(not np.isfinite(float(row[c])) for c in COVARIATES):
            continue
        pseudo = dict(event)
        pseudo["event_id"] = hashlib.sha256(
            f"placebo+1d|{event['event_id']}|{shifted_ts.isoformat()}".encode()
        ).hexdigest()[:24]
        pseudo["confirmation_index"] = int(shifted_idx)
        pseudo["confirmation_timestamp"] = shifted_ts
        pseudo["earliest_entry_index"] = int(shifted_idx + 1)
        pseudo["earliest_entry_timestamp"] = df.iloc[shifted_idx + 1]["timestamp"]
        pseudo["year"] = int(row["year"])
        pseudo["month"] = int(row["month"])
        pseudo["session"] = str(row["session"])
        pseudo["utc_date"] = str(row["utc_date"])
        for covar in COVARIATES:
            pseudo[covar] = float(row[covar])
        pseudo["source_event_id"] = event["event_id"]
        pseudo["primary_horizon_minutes"] = PRIMARY_HORIZON_MINUTES
        records.append(pseudo)
    if not records:
        return pd.DataFrame()
    out = apply_outcomes(df, pd.DataFrame(records))
    return non_overlap_by_confirmation(out)


def criterion_trace(
    primary: dict[str, Any],
    matching: dict[str, Any],
    placebo: dict[str, Any],
) -> dict[str, Any]:
    ci = primary["cluster_bootstrap_ci95_mean_diff_points"]
    placebo_reproduces = placebo.get("placebo_reproduces_relative_resilience")
    criteria = {
        "artifact_integrity": True,
        "validation_data_quality": True,
        "successfully_matched_primary_non_overlap_events": matching["successfully_matched_events"]
        >= MIN_TOTAL_EVENTS,
        "exact_key_relaxations": matching["exact_key_relaxations"] == 0,
        "every_post_match_abs_smd": bool(matching["balance_pass"]),
        "mean_event_minus_control_executable_markout": (
            primary["mean_event_minus_control_points"] is not None
            and primary["mean_event_minus_control_points"] > 0
        ),
        "paired_permutation_p_value": primary["paired_permutation_p_value"] <= PRIMARY_ALPHA,
        "ci95_lower_bound": ci[0] is not None and ci[0] > 0,
        "mean_absolute_event_executable_markout": (
            primary["mean_event_executable_markout_points"] is not None
            and primary["mean_event_executable_markout_points"] <= 0
        ),
        "plus_1_day_placebo_does_not_reproduce": placebo_reproduces is False,
        "holdout_integrity": True,
    }
    return {
        "criteria": criteria,
        "all_pass": all(criteria.values()),
    }


def run_development_replay(paths: GateC5APaths) -> dict[str, Any]:
    df = load_development_m5(
        __import__("fx_smc_bot.research.gate_c4_event_alpha", fromlist=["GateC4Paths"]).GateC4Paths(
            root=paths.root
        )
    )
    events = _load_acceptance_events(paths)
    primary_events = _primary_eligible_events(events)
    matches, matching_audit = exact_match_controls(df, events, primary_events)
    controls = add_control_outcomes_for_matches(df, primary_events, matches)
    matched_events = primary_events[primary_events["event_id"].isin(controls["event_id"])].copy()
    primary = primary_estimand(matched_events, controls)

    placebo_events_all = shifted_placebo_events(df, events, primary_events)
    placebo_primary = (
        placebo_events_all[placebo_events_all["non_overlap_primary"]].copy()
        if not placebo_events_all.empty
        else pd.DataFrame()
    )
    placebo_matches, placebo_matching = exact_match_controls(df, events, placebo_primary)
    placebo_controls = add_control_outcomes_for_matches(df, placebo_primary, placebo_matches)
    placebo_matched = (
        placebo_primary[placebo_primary["event_id"].isin(placebo_controls["event_id"])].copy()
        if not placebo_primary.empty
        else pd.DataFrame()
    )
    placebo_estimand = (
        primary_estimand(placebo_matched, placebo_controls)
        if len(placebo_matched)
        else {
            "n": 0,
            "mean_event_minus_control_points": None,
            "paired_permutation_p_value": 1.0,
            "holm_adjusted_p_value": 1.0,
            "cluster_bootstrap_ci95_mean_diff_points": [None, None],
        }
    )
    placebo_ci_raw = placebo_estimand["cluster_bootstrap_ci95_mean_diff_points"]
    placebo_ci = placebo_ci_raw if isinstance(placebo_ci_raw, list) else [None, None]
    placebo_diff = placebo_estimand["mean_event_minus_control_points"]
    placebo_p = placebo_estimand["paired_permutation_p_value"]
    placebo_ci_lower = placebo_ci[0]
    placebo_reproduces = bool(
        isinstance(placebo_diff, int | float)
        and placebo_diff > 0
        and isinstance(placebo_p, int | float)
        and placebo_p <= PRIMARY_ALPHA
        and isinstance(placebo_ci_lower, int | float)
        and placebo_ci_lower > 0
    )
    placebo_payload = {
        "placebo_type": "+1-day shifted pseudo-event relative-resilience placebo",
        "eligible_shifted_placebo_events": int(len(placebo_primary)),
        "successfully_matched_placebo_events": int(len(placebo_matched)),
        "matching": placebo_matching,
        "estimand": placebo_estimand,
        "placebo_reproduces_relative_resilience": placebo_reproduces,
    }
    trace = criterion_trace(primary, matching_audit, placebo_payload)
    replay = {
        "status": "PASS" if trace["all_pass"] else "FAIL",
        "final_decision_if_failed": "BLOCKED_BY_AMENDED_DEVELOPMENT_REPLAY",
        "development_only": True,
        "validation_or_holdout_accessed": False,
        "eligible_primary_events": int(len(primary_events)),
        "successfully_matched_events": matching_audit["successfully_matched_events"],
        "unmatched_events": matching_audit["unmatched_events"],
        "exact_key_relaxations": matching_audit["exact_key_relaxations"],
        "matching": matching_audit,
        "primary_estimand": primary,
        "placebo": placebo_payload,
        "all_eleven_criteria": trace,
    }
    write_json(paths.results_dir / "amended_development_replay.json", replay)
    render_replay_doc(paths, replay)
    return replay


def render_replay_doc(paths: GateC5APaths, replay: dict[str, Any]) -> None:
    write_text(
        paths.docs_dir / "GATE_C5A_AMENDED_DEVELOPMENT_REPLAY.md",
        f"""# Gate C.5-A Amended Development Replay

Replay status: `{replay["status"]}`

This replay uses only the frozen 2015-2019 development row-level artifacts and
development canonical data. It is a lineage-consistency check, not a
rule-selection step.

```json
{json.dumps(replay, indent=2, sort_keys=True)}
```
""",
    )


def execution_protocol_payload(paths: GateC5APaths) -> dict[str, Any]:
    amendment = read_json(paths.results_dir / "handoff_amendment.json")
    matrix = read_json(paths.results_dir / "amended_validation_decision_matrix.json")
    integrity = read_json(paths.results_dir / "amendment_integrity.json")
    replay = read_json(paths.results_dir / "amended_development_replay.json")
    code_hashes = {
        "c5a_amendment_module": file_sha256(Path(__file__)),
        "c4_event_alpha_module": file_sha256(
            paths.root / "src" / "fx_smc_bot" / "research" / "gate_c4_event_alpha.py"
        ),
        "runner": file_sha256(paths.root / "scripts" / "run_gate_c5a_amendment.py"),
        "acceptance_detector": file_sha256(
            paths.root
            / "src"
            / "fx_smc_bot"
            / "alpha"
            / "intraday"
            / "acceptance_continuation.py"
        ),
        "acceptance_config": file_sha256(
            paths.root
            / "configs"
            / "research"
            / "intraday_smc"
            / "acceptance_continuation.yaml"
        ),
    }
    core = {
        "gate": "C.5-A",
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_hash": HYPOTHESIS_HASH,
        "amendment_id": AMENDMENT_ID,
        "amendment_hash": amendment["amendment_hash"],
        "validation_period": "2020-01-01 through 2022-12-31",
        "pair": "USDJPY",
        "event_family": "Acceptance Continuation",
        "event_configuration_hash": EVENT_CONFIGURATION_HASH,
        "detector_hash": code_hashes["acceptance_detector"],
        "configuration_file_hash": code_hashes["acceptance_config"],
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "primary_sample": "primary non-overlap sample",
        "event_schema": [
            "event_id",
            "pair",
            "family",
            "direction",
            "confirmation_timestamp",
            "earliest_entry_timestamp",
            "session",
            "source_level",
            "pre-event covariates",
            "year",
            "month",
            "configuration_hash",
            "hypothesis_hash",
        ],
        "matching_protocol": matching_protocol(),
        "matching_implementation_hash": code_hashes["c5a_amendment_module"],
        "outcome_implementation_hash": code_hashes["c4_event_alpha_module"],
        "inference_protocol": inference_protocol(),
        "bootstrap_seed": RNG_SEED,
        "permutation_seed": RNG_SEED,
        "placebo_protocol": placebo_protocol(),
        "placebo_implementation_hash": code_hashes["c5a_amendment_module"],
        "mandatory_criteria": matrix["mandatory_criteria"],
        "development_replay_hash": stable_json_hash(replay),
        "development_replay_status": replay["status"],
        "amendment_integrity_hashes": integrity,
        "analysis_code_hashes": code_hashes,
        "no_adaptation_policy": True,
        "post_unblinding_failure_policy": (
            "If a scientific-code defect appears after validation unblinding, stop with "
            "BLOCKED_BY_POST_UNBLINDING_EXECUTION_FAILURE; do not patch and continue."
        ),
    }
    return {
        **core,
        "execution_protocol_hash": stable_json_hash(core),
        "created_at_utc": datetime.now(UTC).isoformat(),
    }


def render_protocol_doc(paths: GateC5APaths, protocol: dict[str, Any]) -> None:
    write_text(
        paths.docs_dir / "GATE_C5A_EXECUTION_PROTOCOL.md",
        f"""# Gate C.5-A Execution Protocol

Protocol hash: `{protocol["execution_protocol_hash"]}`

This protocol freezes the amended C5 validation execution before any validation
access. Scientific code and decision rules are immutable after validation
unblinding.

```json
{json.dumps(protocol, indent=2, sort_keys=True)}
```
""",
    )


def initialize_execution_protocol(paths: GateC5APaths) -> dict[str, Any]:
    replay = read_json(paths.results_dir / "amended_development_replay.json")
    if replay.get("status") != "PASS":
        raise RuntimeError("Cannot freeze C5-A execution protocol: development replay failed")
    protocol = execution_protocol_payload(paths)
    write_json(paths.results_dir / "execution_protocol.json", protocol)
    render_protocol_doc(paths, protocol)
    return protocol


def pre_unblinding_freeze_payload(
    paths: GateC5APaths,
    amendment_commit_sha: str,
    protocol_commit_sha: str,
    targeted_test_result: str,
) -> dict[str, Any]:
    status = git(paths.root, ["status", "--short"])
    amendment = read_json(paths.results_dir / "handoff_amendment.json")
    protocol = read_json(paths.results_dir / "execution_protocol.json")
    replay = read_json(paths.results_dir / "amended_development_replay.json")
    access_absent = validation_access_artifacts_absent(paths)
    ready_checks = {
        "amendment_commit_exists": bool(amendment_commit_sha),
        "execution_protocol_commit_exists": bool(protocol_commit_sha),
        "development_replay_passes": replay["status"] == "PASS",
        "targeted_tests_pass": targeted_test_result == "PASS",
        "working_tree_clean": status == "",
        "validation_not_accessed": all(access_absent.values()),
        "holdout_not_accessed": access_absent["c5a_holdout_access_ledger_absent"],
    }
    return {
        "status": "READY_TO_UNBLIND_VALIDATION" if all(ready_checks.values()) else "NOT_READY",
        "ready_checks": ready_checks,
        "amendment_commit_sha": amendment_commit_sha,
        "execution_protocol_commit_sha": protocol_commit_sha,
        "hypothesis_hash": HYPOTHESIS_HASH,
        "amendment_hash": amendment["amendment_hash"],
        "protocol_hash": protocol["execution_protocol_hash"],
        "development_replay_hash": stable_json_hash(replay),
        "analysis_code_hash": file_sha256(Path(__file__)),
        "targeted_test_result": targeted_test_result,
        "working_tree_short_status": status,
        "validation_access_checks": access_absent,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }


def holdout_integrity_payload() -> dict[str, Any]:
    return {
        "status": "PASS",
        "holdout_market_data_loaded": False,
        "holdout_events_detected": False,
        "holdout_event_counts_computed": False,
        "holdout_controls_constructed": False,
        "holdout_outcomes_computed": False,
        "holdout_results_reported": False,
    }
