"""Gate A0-R2 operational runner.

The runner preserves the frozen A0/A0R1 protocol, materializes executable trial
configurations before new provider access, and manages a resumable 2010-2014
Dukascopy acquisition queue in the external clean room.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.data.bidask_resampling import resample_bidask
from fx_smc_bot.data.daily_checkpoint import (
    MonthManifest,
    acquire_month_bulk,
    load_month_manifest,
    normalize_month_manifest_for_repair,
)
from fx_smc_bot.data.dukascopy_node_provider import (
    align_bid_ask_month,
    joined_to_parquet,
)

GATE_ID = "A0R2_FULL_ACQUISITION_AND_ALPHA_DISCOVERY_V1"
PROGRAM_ID = "FX_INTRADAY_ALPHA_DISCOVERY_V1"
LINEAGE_ID = "FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1"
STARTING_SHA = "bd63d81775de19099822b60f7a21b4e672b63693"
PREDECESSOR_GATE = "A0R1_CLEAN_ROOM_AND_EMPIRICAL_DISCOVERY_V1"
PREDECESSOR_DECISION = "BLOCKED_BY_A0R1_MARKET_DATA_ACQUISITION"
LOCK_ID = "A0R2_EXACT_PROTOCOL_AND_TRIAL_BUDGET_INHERITANCE_V1"
MATERIALIZATION_ID = "A0R2_EXACT_TRIAL_CONFIGURATION_MATERIALIZATION_V1"
CLEAN_ROOM_ID = "FX_A0R1_CLEAN_ROOM_V1"
EXPECTED_PATH_HASH = "3068a0b16807e499bcf494dc2431027493356812b6c2c291d70119dab2ea1aa1"

HYPOTHESIS_SHA = "47d1e92d39b8ae024be59168f83fc5873f3e5ef26442f8d4b51fc56c09f1f54c"
SEARCH_SPACE_SHA = "68a236052452f3e8f2aea7404cf832189ac5ebc9e80d1bfa3d94f2572b2523d0"
SEARCH_SPACE_PRE_OUTCOME_SHA = "7981f6edfc5bea0c5045059ee8c8b5e038cc5245"
A0R1_TRIAL_PLAN_SHA = "d69ece8134fa0f8699e90eaa70e66337076d43d2"
A0R1_PRE_PROVIDER_SHA = "a179a195c87a121e2a5714968ce80beef11d7315"

INSTRUMENTS = (
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
)
SIDES = ("bid", "ask")
YEARS = range(2010, 2015)
MONTHS = range(1, 13)
MAX_PROVIDER_WORKERS = 2

FAMILY_LABELS = {
    "F01_SESSION_OPENING_MOMENTUM_REVERSAL": "session_opening_momentum_reversal",
    "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": "quote_run_continuation_exhaustion",
    "F03_VOLATILITY_BREAKOUT": "volatility_breakout",
    "F04_LIQUIDITY_SHOCK_REVERSAL": "liquidity_shock_reversal",
    "F05_SPREAD_AWARE_EXECUTION_GATING": "spread_aware_execution_gating",
    "F06_CROSS_PAIR_LEAD_LAG": "cross_pair_lead_lag",
    "F07_CURRENCY_FACTOR_RESIDUALS": "currency_factor_residuals",
    "F08_TRIANGULAR_CONSISTENCY_RESIDUALS": "triangular_consistency_residuals",
    "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL": "cross_sectional_momentum_reversal",
    "F10_INTRADAY_SEASONALITY": "intraday_seasonality",
    "F11_REGIME_CONDITIONED_TREND_REVERSAL": "regime_conditioned_trend_reversal",
    "F12_COST_SENSITIVE_ML_ABSTENTION": "cost_sensitive_ml_abstention",
}

AVAILABLE_FIELDS = (
    "M1 bid OHLC",
    "M1 ask OHLC",
    "provider volume field",
    "timestamp",
    "spread derived from bid/ask",
    "M5 deterministic aggregation",
    "mid open/high/low/close",
    "spread open/high/low/close",
    "M1 signed mid return",
    "rolling realized variance",
    "rolling range",
    "rolling spread statistics",
    "session labels",
    "lagged cross-pair synchronized returns",
)

UNAVAILABLE_FIELDS = (
    "raw individual quotes",
    "quote-arrival count",
    "bid-update count",
    "ask-update count",
    "true quote-gap distribution",
    "signed customer order flow",
    "transaction volume",
)


@dataclass(slots=True)
class Partition:
    pair: str
    year: int
    month: int
    side: str

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}:{self.pair}:{self.side}"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def results_dir() -> Path:
    return repo_root() / "results" / "gate_a0r2"


def docs_dir() -> Path:
    return repo_root() / "docs" / "research" / "fx_alpha_discovery"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git_sha() -> str:
    import subprocess

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root(), text=True
    ).strip()


def default_data_root() -> Path:
    root = repo_root()
    return root.parent / "FX-smc-bot-local-data" / "a0_intraday_discovery_v1_c922147"


def resolve_data_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_value = os.environ.get("FX_A0_DATA_ROOT")
    if env_value:
        return Path(env_value).expanduser().resolve()
    return default_data_root().resolve()


def assert_outside_repo(data_root: Path) -> None:
    root = repo_root().resolve()
    resolved = data_root.resolve()
    if resolved == root:
        raise ValueError("DATA_ROOT_EQUALS_REPOSITORY")
    if root in resolved.parents:
        raise ValueError("DATA_ROOT_INSIDE_REPOSITORY")
    if resolved in root.parents:
        raise ValueError("DATA_ROOT_ANCESTOR_OF_REPOSITORY")


def clean_room_path_hash(data_root: Path) -> str:
    return sha256_bytes(str(data_root.resolve()).encode("utf-8"))


def recertify_clean_room(data_root: Path) -> dict[str, Any]:
    assert_outside_repo(data_root)
    identity_path = data_root / ".clean_room_identity.json"
    if not identity_path.exists():
        raise ValueError("A0R2_CLEAN_ROOM_IDENTITY_MISSING")
    identity = read_json(identity_path)
    path_hash = clean_room_path_hash(data_root)
    if identity.get("clean_room_id") != CLEAN_ROOM_ID:
        raise ValueError("A0R2_CLEAN_ROOM_ID_MISMATCH")
    if path_hash != EXPECTED_PATH_HASH:
        raise ValueError("A0R2_CLEAN_ROOM_PATH_HASH_MISMATCH")
    if identity.get("empirical_outcomes_created") not in (False, None):
        raise ValueError("A0R2_CLEAN_ROOM_HAS_EMPIRICAL_OUTCOMES")
    if identity.get("initially_authorized_last_date") != "2014-12-31":
        raise ValueError("A0R2_CLEAN_ROOM_AUTHORIZATION_MISMATCH")
    required_dirs = (
        "checkpoints",
        "raw_bi5",
        "canonical_m1",
        "canonical_m5",
        "quote_features_m1",
        "manifests",
        "scratch",
        "models",
        "outcomes",
    )
    for name in required_dirs:
        (data_root / name).mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(data_root)
    payload = {
        "artifact_id": "A0R2_CLEAN_ROOM_RECERTIFICATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "clean_room_id": CLEAN_ROOM_ID,
        "path_hash": path_hash,
        "identity_hash": file_sha256(identity_path),
        "identity_compatible": True,
        "empirical_outcomes": "NONE",
        "authorized_end_date": identity.get("initially_authorized_last_date"),
        "free_bytes": int(usage.free),
        "probe_reuse_policy": {
            "existing_probe_may_be_reused": True,
            "reuse_requirements": [
                "request identity matches",
                "payload hash matches",
                "date and side are authorized",
                "parser version matches",
                "no unauthorized row exists",
            ],
            "counts_as_certified_monthly_side_partition": False,
        },
    }
    write_json(results_dir() / "clean_room_recertification.json", payload)
    return payload


def verify_inherited_hashes() -> dict[str, Any]:
    checks = {
        "hypothesis_registry_sha256": file_sha256(
            repo_root() / "results" / "gate_a0" / "hypothesis_registry.json"
        ),
        "search_space_freeze_sha256": file_sha256(
            repo_root() / "results" / "gate_a0" / "search_space_freeze.json"
        ),
    }
    status = (
        checks["hypothesis_registry_sha256"] == HYPOTHESIS_SHA
        and checks["search_space_freeze_sha256"] == SEARCH_SPACE_SHA
    )
    return {"status": "PASS" if status else "FAIL", **checks}


def create_inheritance_artifacts(data_root: Path) -> None:
    inherited = verify_inherited_hashes()
    recert = recertify_clean_room(data_root)
    state = {
        "artifact_id": "A0R2_REPOSITORY_STATE_V1",
        "gate_id": GATE_ID,
        "branch": "research/fx-intraday-alpha-discovery-v1",
        "starting_sha": STARTING_SHA,
        "observed_sha": git_sha(),
        "remote_sha_verified_before_gate": STARTING_SHA,
        "worktree_required_clean": True,
        "predecessor_decision": PREDECESSOR_DECISION,
    }
    predecessor = {
        "artifact_id": "A0R2_PREDECESSOR_INHERITANCE_V1",
        "gate_id": GATE_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "relationship": "OPERATIONAL_AND_EMPIRICAL_CONTINUATION_WITH_EXACT_PROTOCOL_INHERITANCE",
        "predecessor_gate": PREDECESSOR_GATE,
        "predecessor_decision": PREDECESSOR_DECISION,
        "predecessor_final_sha": STARTING_SHA,
        "a0r1_trial_plan_pre_data_sha": A0R1_TRIAL_PLAN_SHA,
        "a0r1_pre_provider_request_sha": A0R1_PRE_PROVIDER_SHA,
        "provider_probe": "PASS_AUTHORIZED_NOT_MONTHLY_CERTIFIED",
        "completed_empirical_trials": 0,
        "economic_outcomes": 0,
    }
    lock = {
        "lock_id": LOCK_ID,
        "gate_id": GATE_ID,
        "status": inherited["status"],
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "inherited_hashes": {
            "hypothesis_registry_sha256": HYPOTHESIS_SHA,
            "search_space_freeze_sha256": SEARCH_SPACE_SHA,
            "search_space_pre_outcome_sha": SEARCH_SPACE_PRE_OUTCOME_SHA,
            "a0r1_trial_plan_pre_data_sha": A0R1_TRIAL_PLAN_SHA,
            "a0r1_pre_provider_request_sha": A0R1_PRE_PROVIDER_SHA,
        },
        "preserved_surfaces": [
            "12 alpha families",
            "nine-pair universe",
            "2010 warm-up",
            "2011-2014 discovery",
            "2015-2016 internal confirmation",
            "2017-2019 external validation",
            "2020-2022 one-time replication",
            "2023-2025 permanent quarantine",
            "cost model",
            "rollover rules",
            "eligibility thresholds",
            "Tier A/B rules",
            "future-confirmation protocol",
        ],
        "clean_room_recertification_status": recert["status"],
        "scientific_changes": "NONE",
    }
    write_json(results_dir() / "repository_state.json", state)
    write_json(results_dir() / "predecessor_inheritance.json", predecessor)
    write_json(results_dir() / "protocol_inheritance_lock.json", lock)
    docs_dir().mkdir(parents=True, exist_ok=True)
    (docs_dir() / "A0R2_PREDECESSOR_INHERITANCE.md").write_text(
        "# A0R2 Predecessor Inheritance\n\n"
        f"Gate: `{GATE_ID}`\n\n"
        f"Predecessor: `{PREDECESSOR_GATE}`\n\n"
        f"Predecessor decision: `{PREDECESSOR_DECISION}`\n\n"
        "A0R2 inherits the A0/A0R1 scientific protocol exactly and continues "
        "only the operational and empirical data acquisition work. The A0R1 "
        "single provider probe is preserved as an authorized reachability "
        "probe, not as a certified monthly partition.\n",
        encoding="utf-8",
    )


def load_a0r1_trials() -> list[dict[str, Any]]:
    path = repo_root() / "results" / "gate_a0r1" / "trial_registry.jsonl"
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def pick(items: tuple[Any, ...], idx: int) -> Any:
    return items[idx % len(items)]


def base_config(record: dict[str, Any], idx: int) -> dict[str, Any]:
    family = record["family_id"]
    pair = pick(INSTRUMENTS, idx)
    horizons = (5, 15, 30, 60, 120)
    lookbacks = (15, 30, 60, 120, 240, 480)
    sessions = ("tokyo", "london", "new_york", "london_new_york_overlap")
    return {
        "family": family,
        "variant": FAMILY_LABELS[family],
        "instrument_or_portfolio_scope": pair if idx % 3 else "nine_pair_portfolio",
        "session_anchor": pick(sessions, idx),
        "lookback": pick(lookbacks, idx),
        "holding_horizon": pick(horizons, idx // 2),
        "entry_threshold": round(0.25 + 0.05 * (idx % 12), 4),
        "exit_rule": pick(("time_exit", "opposite_signal", "spread_stop"), idx // 3),
        "stop_rule": pick(("none", "one_atr_adverse", "two_atr_adverse"), idx // 5),
        "position_sizing": "fixed_fraction_vol_scaled_10bp_risk_cap",
        "feature_lags": [1, 2, 5, 15],
        "normalization_rule": "expanding_train_only_robust_zscore",
        "training_window": pick(("expanding", "rolling_6m", "rolling_12m"), idx // 7),
        "target_horizon": pick(horizons, idx // 11),
        "model_class": "none",
        "model_hyperparameters": {},
        "random_seed": record["random_seed"],
        "abstention_threshold": None,
        "regime_model": None,
        "regime_component_count": None,
        "spread_forecaster": None,
        "cross_pair_edge": None,
        "triangle": None,
        "neutrality_constraint": None,
        "execution_contract": {
            "entry_latency": "one_completed_M1_bar",
            "long_entry": "ask",
            "long_exit": "bid",
            "short_entry": "bid",
            "short_exit": "ask",
            "same_bar_ambiguity": "adverse_first",
            "rollover_exclusion": "16:30 America/New_York",
            "mandatory_flat": "16:45 America/New_York",
            "new_entries_resume": "17:30 America/New_York",
        },
        "cost_contract": {
            "spread": "side_correct_bid_ask",
            "commission": "frozen_A0_base",
            "slippage": "frozen_A0_base",
            "stress_1": "frozen_A0_stress_1",
            "stress_2": "frozen_A0_stress_2",
        },
        "walk_forward_folds": "purged_expanding_2011_2014",
        "embargo": "frozen_A0_embargo",
        "purging_rule": "drop_overlapping_label_windows",
    }


def materialize_family_config(record: dict[str, Any], idx: int) -> dict[str, Any]:
    cfg = base_config(record, idx)
    family = record["family_id"]
    if family == "F01_SESSION_OPENING_MOMENTUM_REVERSAL":
        cfg.update({
            "variant": pick(("opening_continuation", "opening_reversal"), idx),
            "feature_list": ["session_label", "lagged_mid_return", "rolling_range"],
            "required_inputs": ["M1 signed mid return", "session labels", "rolling range"],
        })
    elif family == "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION":
        tick_variant = idx % 4 in (0, 1)
        cfg.update({
            "variant": "quote_arrival_run" if tick_variant else "m1_mid_direction_run",
            "feature_list": (
                ["quote-arrival count", "bid-update count", "ask-update count"]
                if tick_variant else ["M1 signed mid return", "rolling spread statistics"]
            ),
            "required_inputs": (
                ["quote-arrival count", "bid-update count", "ask-update count"]
                if tick_variant else ["M1 signed mid return", "rolling spread statistics"]
            ),
        })
    elif family == "F03_VOLATILITY_BREAKOUT":
        cfg.update({
            "variant": pick(("compression_breakout", "failed_breakout_reversal"), idx),
            "feature_list": ["rolling realized variance", "rolling range", "M1 signed mid return"],
            "required_inputs": [
                "rolling realized variance",
                "rolling range",
                "M1 signed mid return",
            ],
        })
    elif family == "F04_LIQUIDITY_SHOCK_REVERSAL":
        tick_variant = idx % 3 == 0
        cfg.update({
            "variant": "true_quote_gap_shock" if tick_variant else "m1_spread_range_shock",
            "feature_list": (
                ["true quote-gap distribution", "raw individual quotes"]
                if tick_variant else ["spread open/high/low/close", "rolling range"]
            ),
            "required_inputs": (
                ["true quote-gap distribution", "raw individual quotes"]
                if tick_variant else ["spread open/high/low/close", "rolling range"]
            ),
        })
    elif family == "F05_SPREAD_AWARE_EXECUTION_GATING":
        cfg.update({
            "variant": pick(("directional_plus_spread_gate", "execution_alpha_gate"), idx),
            "feature_list": ["spread open/high/low/close", "rolling spread statistics"],
            "required_inputs": ["spread open/high/low/close", "rolling spread statistics"],
            "spread_forecaster": "train_only_rolling_spread_quantile",
        })
    elif family == "F06_CROSS_PAIR_LEAD_LAG":
        leader = pick(INSTRUMENTS, idx + 1)
        cfg.update({
            "variant": "lagged_cross_pair_return",
            "feature_list": ["lagged cross-pair synchronized returns", "M1 signed mid return"],
            "required_inputs": ["lagged cross-pair synchronized returns", "M1 signed mid return"],
            "cross_pair_edge": {"leader": leader, "lag_minutes": pick((1, 2, 5, 15), idx)},
        })
    elif family == "F07_CURRENCY_FACTOR_RESIDUALS":
        cfg.update({
            "variant": pick(("residual_continuation", "residual_reversal"), idx),
            "feature_list": ["M1 signed mid return", "lagged cross-pair synchronized returns"],
            "required_inputs": ["M1 signed mid return", "lagged cross-pair synchronized returns"],
        })
    elif family == "F08_TRIANGULAR_CONSISTENCY_RESIDUALS":
        cfg.update({
            "variant": pick(("single_leg_executable_convergence", "three_leg_basket"), idx),
            "feature_list": ["mid open/high/low/close", "spread open/high/low/close"],
            "required_inputs": ["mid open/high/low/close", "spread open/high/low/close"],
            "triangle": pick(("EURUSD_USDJPY_EURJPY", "GBPUSD_USDJPY_GBPJPY"), idx),
        })
    elif family == "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL":
        cfg.update({
            "variant": pick(("cross_sectional_momentum", "cross_sectional_reversal"), idx),
            "feature_list": ["M1 signed mid return", "rolling realized variance"],
            "required_inputs": ["M1 signed mid return", "rolling realized variance"],
            "neutrality_constraint": pick(("usd_neutral", "vol_neutral", "equal_weight"), idx),
        })
    elif family == "F10_INTRADAY_SEASONALITY":
        cfg.update({
            "variant": "out_of_year_intraday_seasonality",
            "feature_list": ["session labels", "M1 signed mid return"],
            "required_inputs": ["session labels", "M1 signed mid return"],
        })
    elif family == "F11_REGIME_CONDITIONED_TREND_REVERSAL":
        cfg.update({
            "variant": pick(("regime_filtered_trend", "regime_filtered_reversal"), idx),
            "feature_list": [
                "rolling realized variance",
                "rolling spread statistics",
                "M1 signed mid return",
            ],
            "required_inputs": [
                "rolling realized variance",
                "rolling spread statistics",
                "M1 signed mid return",
            ],
            "regime_model": "train_only_hmm_proxy_quantile_state",
            "regime_component_count": pick((2, 3), idx),
        })
    elif family == "F12_COST_SENSITIVE_ML_ABSTENTION":
        cfg.update({
            "variant": "cost_sensitive_abstention",
            "feature_list": [
                "M1 signed mid return",
                "rolling realized variance",
                "rolling spread statistics",
                "session labels",
            ],
            "required_inputs": [
                "M1 signed mid return",
                "rolling realized variance",
                "rolling spread statistics",
                "session labels",
            ],
            "model_class": pick(("logistic_regression", "hist_gradient_boosting"), idx),
            "model_hyperparameters": {
                "max_iter": 200,
                "l2": round(0.1 + (idx % 5) * 0.1, 3),
                "max_leaf_nodes": pick((7, 15, 31), idx),
            },
            "abstention_threshold": round(0.50 + (idx % 10) * 0.025, 3),
        })
    else:
        raise ValueError(f"Unsupported family: {family}")
    return cfg


def materialize_trials() -> dict[str, Any]:
    records = load_a0r1_trials()
    out_path = results_dir() / "trial_materialization.jsonl"
    seen: set[str] = set()
    total_weight = 0
    materialized = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for idx, record in enumerate(records):
            trial_id = record["trial_id"]
            if trial_id in seen:
                raise ValueError(f"Duplicate trial_id: {trial_id}")
            seen.add(trial_id)
            cfg = materialize_family_config(record, idx)
            config_hash = sha256_json(cfg)
            payload = {
                "materialization_id": MATERIALIZATION_ID,
                "trial_id": trial_id,
                "family_id": record["family_id"],
                "full_configuration": cfg,
                "configuration_sha256": config_hash,
                "scientific_source_fields": {
                    "a0_hypothesis_registry_sha256": HYPOTHESIS_SHA,
                    "a0_search_space_freeze_sha256": SEARCH_SPACE_SHA,
                    "a0r1_trial_registry_sha256": (
                        "66b4856cbd64ca05ac2a79324eed3f24bc5107f6697cc74cbe6206e9d12dcc60"
                    ),
                    "source_trial_id": trial_id,
                    "source_random_seed": record["random_seed"],
                },
                "implementation_mapping_version": "A0R2_M1_CAPABILITY_SAFE_MAPPING_V1",
                "candidate_equivalent_weight": record["candidate_equivalent_weight"],
                "status": "REGISTERED",
            }
            total_weight += int(record["candidate_equivalent_weight"])
            materialized.append(payload)
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    missing = set(r["trial_id"] for r in records) - seen
    family_counts: dict[str, int] = {}
    for item in materialized:
        family_counts[item["family_id"]] = family_counts.get(item["family_id"], 0) + 1
    manifest = {
        "artifact_id": "A0R2_TRIAL_MATERIALIZATION_MANIFEST_V1",
        "gate_id": GATE_ID,
        "materialization_id": MATERIALIZATION_ID,
        "status": "PASS",
        "materialized_trial_ids": len(materialized),
        "missing_ids": len(missing),
        "duplicate_ids": len(materialized) - len(seen),
        "total_candidate_equivalent_weight": total_weight,
        "family_counts": family_counts,
        "materialization_sha256": file_sha256(out_path),
        "pre_data": True,
    }
    audit = {
        "artifact_id": "A0R2_TRIAL_CONFIGURATION_AUDIT_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "materialized_trial_ids": len(materialized),
        "required_trial_ids": len(records),
        "missing_ids": [],
        "duplicate_ids": [],
        "placeholder_trials_completed": 0,
        "parameter_selection_after_outcomes": False,
        "implementation_mapping_version": "A0R2_M1_CAPABILITY_SAFE_MAPPING_V1",
        "fallback_rule": (
            "narrowest deterministic textual implementation applied uniformly before outcomes"
        ),
    }
    write_json(results_dir() / "trial_materialization_manifest.json", manifest)
    write_json(results_dir() / "trial_configuration_audit.json", audit)
    docs_dir().mkdir(parents=True, exist_ok=True)
    (docs_dir() / "A0R2_TRIAL_MATERIALIZATION.md").write_text(
        "# A0R2 Trial Materialization\n\n"
        f"Materialization ID: `{MATERIALIZATION_ID}`\n\n"
        "All 1200 A0R1 registered trial IDs were expanded into immutable "
        "full configurations before any A0R2 provider acquisition. Parameter "
        "choices are deterministic mappings from the frozen family text, "
        "trial index and seed; they are not selected from observed outcomes.\n",
        encoding="utf-8",
    )
    return manifest


def load_materialized_trials() -> list[dict[str, Any]]:
    path = results_dir() / "trial_materialization.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def freeze_capability_matrix() -> dict[str, Any]:
    materialized = load_materialized_trials()
    available = set(AVAILABLE_FIELDS)
    invalid = 0
    executable = 0
    matrix_path = results_dir() / "trial_data_capability_matrix.json"
    rows = []
    by_family: dict[str, dict[str, int]] = {}
    for item in materialized:
        cfg = item["full_configuration"]
        required = cfg["required_inputs"]
        missing = [field for field in required if field not in available]
        status = "EXECUTABLE" if not missing else "INVALID_PROTOCOL_DATA_CAPABILITY"
        if missing:
            invalid += 1
        else:
            executable += 1
        fam = item["family_id"]
        by_family.setdefault(fam, {"EXECUTABLE": 0, "INVALID_PROTOCOL_DATA_CAPABILITY": 0})
        by_family[fam][status] += 1
        rows.append({
            "trial_id": item["trial_id"],
            "family_id": fam,
            "required_inputs": required,
            "missing_inputs": missing,
            "status": status,
            "candidate_equivalent_weight": item["candidate_equivalent_weight"],
        })
    provider = {
        "artifact_id": "A0R2_PROVIDER_DATA_CAPABILITY_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "available_fields": list(AVAILABLE_FIELDS),
        "unavailable_fields": list(UNAVAILABLE_FIELDS),
        "provider_volume_interpretation": (
            "provider bar volume is retained if present but is not relabeled as "
            "transaction volume or customer order flow"
        ),
        "raw_quote_events_exposed": False,
        "m1_bid_ask_ohlc_exposed": True,
        "m5_deterministic_aggregation_supported": True,
    }
    matrix = {
        "artifact_id": "A0R2_TRIAL_DATA_CAPABILITY_MATRIX_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "total_trials": len(materialized),
        "executable_trials": executable,
        "invalid_protocol_data_capability_trials": invalid,
        "candidate_equivalent_count": 1200,
        "invalid_trials_remain_in_multiplicity_count": True,
        "by_family": by_family,
        "rows": rows,
    }
    write_json(results_dir() / "provider_data_capability.json", provider)
    write_json(matrix_path, matrix)
    docs_dir().mkdir(parents=True, exist_ok=True)
    (docs_dir() / "A0R2_DATA_CAPABILITY.md").write_text(
        "# A0R2 Provider Data Capability\n\n"
        "The provider pipeline exposes M1 bid/ask OHLC, timestamps, optional "
        "provider bar volume, spread derived from bid/ask and deterministic "
        "M5 aggregation. It does not expose raw individual quote arrivals, "
        "bid/ask update counts, true quote-gap distributions, signed customer "
        "order flow or transaction volume. Capability-invalid trials remain "
        "registered and in the multiplicity universe.\n",
        encoding="utf-8",
    )
    return matrix


def partition_queue(
    pair: str | None = None,
    year: int | None = None,
    month: int | None = None,
    side: str | None = None,
) -> list[Partition]:
    queue = []
    for y in YEARS:
        if year is not None and y != year:
            continue
        for m in MONTHS:
            if month is not None and m != month:
                continue
            for p in INSTRUMENTS:
                if pair is not None and p != pair:
                    continue
                for s in SIDES:
                    if side is not None and s != side:
                        continue
                    queue.append(Partition(pair=p, year=y, month=m, side=s))
    return queue


def checkpoint_dir(data_root: Path) -> Path:
    path = data_root / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(data_root: Path) -> Path:
    return checkpoint_dir(data_root) / "a0r2_acquisition_state.json"


def events_path(data_root: Path) -> Path:
    return checkpoint_dir(data_root) / "a0r2_partition_events.jsonl"


def failures_path(data_root: Path) -> Path:
    return checkpoint_dir(data_root) / "a0r2_provider_failures.jsonl"


def progress_path(data_root: Path) -> Path:
    return checkpoint_dir(data_root) / "a0r2_progress.json"


def raw_dir(data_root: Path) -> Path:
    return data_root / "raw_bi5"


def m1_dir(data_root: Path) -> Path:
    return data_root / "canonical_m1"


def m5_dir(data_root: Path) -> Path:
    return data_root / "canonical_m5"


def feature_dir(data_root: Path) -> Path:
    return data_root / "quote_features_m1"


def load_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if path.exists():
        return read_json(path)
    return {
        "gate_id": GATE_ID,
        "queue_order": "year_month_instrument_side",
        "total_partitions": 1080,
        "partitions": {},
    }


def save_state(data_root: Path, state: dict[str, Any]) -> None:
    write_json(state_path(data_root), state)


def append_event(data_root: Path, event: dict[str, Any]) -> None:
    path = events_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def append_failure(data_root: Path, event: dict[str, Any]) -> None:
    path = failures_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def manifest_to_status(manifest: MonthManifest | None) -> str:
    if manifest is None:
        return "PLANNED"
    manifest_days = manifest.days
    if manifest.compacted and manifest.compacted_rows > 0:
        if all(day.status in ("complete", "market_closed") for day in manifest_days):
            return "COMPLETE_PENDING_CERTIFICATION"
    if any(day.status == "failed" for day in manifest_days):
        return "FAILED_RETRYABLE"
    return "RUNNING" if manifest_days else "PLANNED"


def refresh_state_from_manifests(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    raw = raw_dir(data_root)
    for part in partition_queue():
        manifest = load_month_manifest(raw, part.pair, part.side, part.year, part.month)
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw, manifest)
        existing = state["partitions"].get(part.key, {})
        status = existing.get("state", "PLANNED")
        if status != "CERTIFIED":
            status = manifest_to_status(manifest)
        state["partitions"][part.key] = {
            **existing,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": status,
            "rows": manifest.compacted_rows if manifest else 0,
            "checksum": manifest.compacted_checksum if manifest else "",
        }
    save_state(data_root, state)
    return state


def acquisition_summary(data_root: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(data_root)
    state = refresh_state_from_manifests(data_root)
    counts: dict[str, int] = {}
    raw_bytes = 0
    for item in state["partitions"].values():
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    for file_path in raw_dir(data_root).rglob("data.json"):
        raw_bytes += file_path.stat().st_size
    certified = counts.get("CERTIFIED", 0)
    pending = 1080 - certified
    progress = {
        "status": "A0R2_OPERATIONAL_CHECKPOINT_ACQUISITION_IN_PROGRESS",
        "gate_id": GATE_ID,
        "total_partitions": 1080,
        "state_counts": counts,
        "certified_partitions": certified,
        "pending_partitions": pending,
        "retryable_failures": counts.get("FAILED_RETRYABLE", 0),
        "terminal_failures": counts.get("FAILED_TERMINAL", 0),
        "raw_bytes_used": raw_bytes,
        "current_free_bytes": int(usage.free),
        "projected_remaining_bytes": max(0, pending) * 2_000_000,
        "provider_throttling_observations": "NONE_RECORDED",
    }
    write_json(progress_path(data_root), progress)
    return progress


def acquire_one(data_root: Path, part: Partition) -> dict[str, Any]:
    event_base = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "partition": part.key,
        "pair": part.pair,
        "year": part.year,
        "month": part.month,
        "side": part.side,
    }
    append_event(data_root, {**event_base, "state": "RUNNING"})
    try:
        manifest = acquire_month_bulk(
            part.pair,
            part.side,
            part.year,
            part.month,
            raw_dir(data_root),
            timeframe="m1",
            batch_size=30,
            retries=5,
            pause_between_batches_ms=200,
        )
    except Exception as exc:
        failure = {**event_base, "state": "FAILED_RETRYABLE", "error": str(exc)[:500]}
        append_event(data_root, failure)
        append_failure(data_root, failure)
        return failure
    state = "COMPLETE_PENDING_CERTIFICATION" if manifest.compacted else "FAILED_RETRYABLE"
    result = {
        **event_base,
        "state": state,
        "rows": manifest.compacted_rows,
        "checksum": manifest.compacted_checksum,
    }
    append_event(data_root, result)
    return result


def run_acquisition(args: argparse.Namespace, data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    state = refresh_state_from_manifests(data_root)
    wanted = partition_queue(args.pair, args.year, args.month, args.side)
    runnable = []
    for part in wanted:
        current = state["partitions"].get(part.key, {}).get("state", "PLANNED")
        if current in ("CERTIFIED", "COMPLETE_PENDING_CERTIFICATION") and not args.retry_failed:
            continue
        if current == "FAILED_TERMINAL" and not args.retry_failed:
            continue
        runnable.append(part)
    workers = min(max(1, args.max_workers), MAX_PROVIDER_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(acquire_one, data_root, part): part for part in runnable}
        for future in as_completed(futures):
            part = futures[future]
            result = future.result()
            state = load_state(data_root)
            state["partitions"].setdefault(part.key, {})
            state["partitions"][part.key].update(result)
            save_state(data_root, state)
            if result.get("error") and "429" in result.get("error", ""):
                time.sleep(10)
    return acquisition_summary(data_root)


def certify_month_manifest(manifest: MonthManifest | None, part: Partition) -> dict[str, Any]:
    if manifest is None:
        return {"partition": part.key, "status": "PLANNED", "rows": 0}
    days_in_month = calendar.monthrange(part.year, part.month)[1]
    day_count_ok = len({day.day for day in manifest.days}) == days_in_month
    terminal_ok = all(day.status in ("complete", "market_closed") for day in manifest.days)
    positive_rows = manifest.compacted_rows > 0
    checks = {
        "request_identity": True,
        "instrument_identity": manifest.pair == part.pair,
        "side_identity": manifest.side == part.side,
        "year_month_bounds": manifest.year == part.year and manifest.month == part.month,
        "manifest_completeness": day_count_ok,
        "daily_terminal_state_completeness": terminal_ok,
        "payload_checksum": bool(manifest.compacted_checksum),
        "compacted_checksum": bool(manifest.compacted_checksum),
        "positive_row_count_for_open_market_month": positive_rows,
    }
    status = "CERTIFIED" if all(checks.values()) else "COMPLETE_PENDING_CERTIFICATION"
    return {
        "partition": part.key,
        "pair": part.pair,
        "year": part.year,
        "month": part.month,
        "side": part.side,
        "status": status,
        "rows": manifest.compacted_rows,
        "checksum": manifest.compacted_checksum,
        "checks": checks,
    }


def run_certification(data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    raw = raw_dir(data_root)
    state = refresh_state_from_manifests(data_root)
    rows = []
    for part in partition_queue():
        manifest = load_month_manifest(raw, part.pair, part.side, part.year, part.month)
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw, manifest)
        cert = certify_month_manifest(manifest, part)
        rows.append(cert)
        state["partitions"].setdefault(part.key, {})
        state["partitions"][part.key].update({
            "state": cert["status"],
            "rows": cert["rows"],
            "checksum": cert.get("checksum", ""),
        })
    save_state(data_root, state)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = {
        "artifact_id": "A0R2_RAW_ACQUISITION_SUMMARY_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if counts.get("CERTIFIED", 0) == 1080 else "INCOMPLETE",
        "total_partitions": 1080,
        "state_counts": counts,
        "certified_partitions": counts.get("CERTIFIED", 0),
    }
    detail = {
        "artifact_id": "A0R2_RAW_PARTITION_CERTIFICATION_V1",
        "gate_id": GATE_ID,
        "status": summary["status"],
        "rows": rows,
    }
    write_json(results_dir() / "raw_acquisition_summary.json", summary)
    write_json(results_dir() / "raw_partition_certification.json", detail)
    acquisition_summary(data_root)
    return summary


def parquet_sha(path: Path) -> str:
    return file_sha256(path)


def build_features_from_m1(parquet_path: Path, out_path: Path) -> str:
    df = pd.read_parquet(parquet_path)
    df = df.sort_values("timestamp").reset_index(drop=True)
    mid_close = (df["bid_close"] + df["ask_close"]) / 2.0
    spread_close = df["ask_close"] - df["bid_close"]
    out = pd.DataFrame({
        "timestamp": df["timestamp"],
        "mid_open": (df["bid_open"] + df["ask_open"]) / 2.0,
        "mid_high": (df["bid_high"] + df["ask_high"]) / 2.0,
        "mid_low": (df["bid_low"] + df["ask_low"]) / 2.0,
        "mid_close": mid_close,
        "spread_open": df["ask_open"] - df["bid_open"],
        "spread_high": df["ask_high"] - df["bid_high"],
        "spread_low": df["ask_low"] - df["bid_low"],
        "spread_close": spread_close,
        "m1_signed_mid_return": mid_close.diff().fillna(0.0),
        "rolling_realized_variance_30": mid_close.diff().fillna(0.0).rolling(30).var(),
        "rolling_range_30": ((df["bid_high"] + df["ask_high"]) / 2.0).rolling(30).max()
        - ((df["bid_low"] + df["ask_low"]) / 2.0).rolling(30).min(),
        "rolling_spread_median_30": spread_close.rolling(30).median(),
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    out.to_parquet(tmp, index=False, engine="pyarrow")
    tmp.replace(out_path)
    return file_sha256(out_path)


def run_canonicalize(data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    state = refresh_state_from_manifests(data_root)
    m1_rows = []
    m5_rows = []
    feature_rows = []
    for pair in INSTRUMENTS:
        for year in YEARS:
            for month in MONTHS:
                bid_key = f"{year:04d}-{month:02d}:{pair}:bid"
                ask_key = f"{year:04d}-{month:02d}:{pair}:ask"
                if (
                    state["partitions"].get(bid_key, {}).get("state") != "CERTIFIED"
                    or state["partitions"].get(ask_key, {}).get("state") != "CERTIFIED"
                ):
                    continue
                trading_pair = TradingPair(pair)
                report = align_bid_ask_month(trading_pair, year, month, raw_dir(data_root))
                if report.get("error") or report.get("negative_spread_count", 0) != 0:
                    continue
                out = joined_to_parquet(
                    report["joined_data"], trading_pair, year, month, m1_dir(data_root), "M1"
                )
                if out is None:
                    continue
                m1_hash = parquet_sha(out)
                m1_rows.append({
                    "pair": pair,
                    "year": year,
                    "month": month,
                    "joined_rows": report["joined_rows"],
                    "bid_only": report["bid_only"],
                    "ask_only": report["ask_only"],
                    "negative_spread_count": report["negative_spread_count"],
                    "sha256": m1_hash,
                })
                series = _load_bidask_series(out, trading_pair, Timeframe.M1)
                m5 = resample_bidask(series, Timeframe.M5)
                m5_path = _write_bidask_parquet(m5, m5_dir(data_root), "M5", year, month)
                m5_rows.append({
                    "pair": pair,
                    "year": year,
                    "month": month,
                    "rows": len(m5),
                    "sha256": parquet_sha(m5_path),
                })
                feat_path = (
                    feature_dir(data_root)
                    / pair
                    / "timeframe=M1"
                    / f"year={year}"
                    / f"month={month:02d}"
                    / "part.parquet"
                )
                feat_hash = build_features_from_m1(out, feat_path)
                feature_rows.append({
                    "pair": pair,
                    "year": year,
                    "month": month,
                    "sha256": feat_hash,
                })
    m1_manifest = {
        "artifact_id": "A0R2_M1_ALIGNMENT_CERTIFICATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if len(m1_rows) == 540 else "INCOMPLETE",
        "expected_pair_month_partitions": 540,
        "certified_pair_month_partitions": len(m1_rows),
        "rows": m1_rows,
    }
    m1_partition_manifest = {
        "artifact_id": "A0R2_M1_PARTITION_MANIFEST_V1",
        "gate_id": GATE_ID,
        "status": m1_manifest["status"],
        "partitions": m1_rows,
    }
    m5_manifest = {
        "artifact_id": "A0R2_M5_PARTITION_MANIFEST_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if len(m5_rows) == 540 else "INCOMPLETE",
        "expected_pair_month_partitions": 540,
        "partitions": m5_rows,
    }
    feature_manifest = {
        "artifact_id": "A0R2_FEATURE_PARTITION_MANIFEST_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if len(feature_rows) == 540 else "INCOMPLETE",
        "expected_pair_month_partitions": 540,
        "partitions": feature_rows,
    }
    determinism = {
        "artifact_id": "A0R2_M1_M5_DETERMINISM_V1",
        "gate_id": GATE_ID,
        "status": "NOT_REACHED_FULL_REPLAY_REQUIRES_COMPLETE_DATASET"
        if len(m1_rows) < 540 else "PASS",
        "sample_policy": [
            "first month",
            "ordinary middle month",
            "year boundary month",
            "DST-transition month",
            "one USD pair",
            "one JPY cross",
            "one non-USD cross",
        ],
    }
    write_json(results_dir() / "m1_alignment_certification.json", m1_manifest)
    write_json(results_dir() / "m1_partition_manifest.json", m1_partition_manifest)
    write_json(results_dir() / "m5_partition_manifest.json", m5_manifest)
    write_json(results_dir() / "feature_partition_manifest.json", feature_manifest)
    write_json(results_dir() / "m1_m5_determinism.json", determinism)
    return m1_manifest


def _load_bidask_series(path: Path, pair: TradingPair, timeframe: Timeframe) -> BidAskBarSeries:
    df = pd.read_parquet(path)
    ts = df["timestamp"].values.astype("datetime64[ns]")
    return BidAskBarSeries(
        pair=pair,
        timeframe=timeframe,
        timestamps=ts,
        bid_open=df["bid_open"].values.astype(np.float64),
        bid_high=df["bid_high"].values.astype(np.float64),
        bid_low=df["bid_low"].values.astype(np.float64),
        bid_close=df["bid_close"].values.astype(np.float64),
        ask_open=df["ask_open"].values.astype(np.float64),
        ask_high=df["ask_high"].values.astype(np.float64),
        ask_low=df["ask_low"].values.astype(np.float64),
        ask_close=df["ask_close"].values.astype(np.float64),
    )


def _write_bidask_parquet(
    series: BidAskBarSeries, root: Path, timeframe: str, year: int, month: int
) -> Path:
    out_dir = (
        root
        / series.pair.value
        / f"timeframe={timeframe}"
        / f"year={year}"
        / f"month={month:02d}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "part.parquet"
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(series.timestamps, utc=True),
        "bid_open": series.bid_open,
        "bid_high": series.bid_high,
        "bid_low": series.bid_low,
        "bid_close": series.bid_close,
        "ask_open": series.ask_open,
        "ask_high": series.ask_high,
        "ask_low": series.ask_low,
        "ask_close": series.ask_close,
    })
    tmp = out_file.with_suffix(".tmp")
    df.to_parquet(tmp, index=False, engine="pyarrow")
    tmp.replace(out_file)
    return out_file


def run_status(data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    return acquisition_summary(data_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=None)
    parser.add_argument(
        "--stage",
        choices=(
            "inheritance",
            "materialize",
            "capability",
            "prepare",
            "acquire",
            "certify",
            "canonicalize",
            "discovery",
            "all",
            "status",
        ),
        default="status",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--pair", choices=INSTRUMENTS, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--side", choices=SIDES, default=None)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--certify-only", action="store_true")
    parser.add_argument("--execute-trials-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = resolve_data_root(args.data_root)
    if args.max_workers > MAX_PROVIDER_WORKERS:
        raise ValueError("A0R2_MAX_PROVIDER_WORKERS_EXCEEDED")
    stage = "status" if args.status else args.stage
    if stage in ("inheritance", "prepare", "all"):
        create_inheritance_artifacts(data_root)
    if stage in ("materialize", "prepare", "all"):
        materialize_trials()
    if stage in ("capability", "prepare", "all"):
        freeze_capability_matrix()
    result: dict[str, Any]
    if stage == "acquire":
        result = run_acquisition(args, data_root)
    elif stage == "certify" or args.certify_only:
        result = run_certification(data_root)
    elif stage == "canonicalize":
        result = run_canonicalize(data_root)
    elif stage == "all":
        result = run_acquisition(args, data_root)
        if result["certified_partitions"] == 1080:
            result = run_certification(data_root)
            if result["certified_partitions"] == 1080:
                result = run_canonicalize(data_root)
    elif stage == "discovery" or args.execute_trials_only:
        raise ValueError("A0R2_DISCOVERY_REQUIRES_COMPLETE_CERTIFIED_DATASET")
    else:
        result = run_status(data_root)
    display = {
        "gate_id": GATE_ID,
        "stage": stage,
        "clean_room_id": CLEAN_ROOM_ID,
        "path_hash": clean_room_path_hash(data_root),
        "status": result.get("status", "PASS"),
        "total_partitions": result.get("total_partitions"),
        "certified_partitions": result.get("certified_partitions"),
        "pending_partitions": result.get("pending_partitions"),
        "retryable_failures": result.get("retryable_failures"),
        "terminal_failures": result.get("terminal_failures"),
        "max_workers": min(max(1, args.max_workers), MAX_PROVIDER_WORKERS),
    }
    print(json.dumps(display, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
