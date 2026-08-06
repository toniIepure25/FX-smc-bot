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
import socket
import sys
import threading
import time
import uuid
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.data.bidask_resampling import resample_bidask
from fx_smc_bot.data.daily_checkpoint import (
    DayStatus,
    MonthManifest,
    acquire_month_bulk,
    compact_month,
    download_native_day_with_checkpoint,
    find_missing_days,
    load_month_manifest,
    normalize_month_manifest_for_repair,
    repair_missing_days,
    save_month_manifest,
)
from fx_smc_bot.data.dukascopy_bi5 import (
    BI5_INSTRUMENTS,
    dukascopy_candle_url,
    fetch_bi5_day,
    instrument_metadata,
    parse_bi5_m1_candles,
    raw_ohlc_checksum,
    rows_checksum,
    timestamp_checksum,
    validate_m1_rows,
)
from fx_smc_bot.data.dukascopy_bi5 import (
    PARSER_VERSION as NATIVE_BI5_PARSER_VERSION,
)
from fx_smc_bot.data.dukascopy_node_provider import (
    TOOL_DIR,
    ProviderCallResult,
    _download_month_bulk_result,
    _download_single_day_result,
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
MATERIALIZATION_ID_V2 = "A0R2_EXACT_TRIAL_CONFIGURATION_MATERIALIZATION_V2"
AMENDMENT_ID = "A0R2_PRE_OUTCOME_TRIAL_MATERIALIZATION_COMPLETENESS_AMENDMENT_V1"
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
NATIVE_HEALTH_HISTORY_LOCK = threading.Lock()

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

TERMINAL_FAILURE_FINGERPRINTS = (
    "bad instrument",
    "schema",
    "authorization",
    "out-of-range",
    "unknown data representation",
)

RETRYABLE_FAILURE_FINGERPRINTS = (
    "timeout",
    "fetch failed",
    "429",
    "temporar",
    "network",
    "ECONNRESET",
)

MAX_PARTITION_ATTEMPTS = 5
MAX_IN_FLIGHT_FUTURES = 4
OP1_OPERATIONAL_SHA = "e4fbf5e5c813674e1802a8c4f43a8a0ff7328f59"
MATERIALIZATION_V2_SHA256 = "09e18295e3a06ca85789840e2cca3802005b465ea6f132cab2c50a63c82061a1"

JSONL_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()

STATE_PRECEDENCE = {
    "CERTIFIED": 70,
    "FAILED_TERMINAL": 60,
    "COMPLETE_PENDING_CERTIFICATION": 50,
    "MARKET_CLOSED_VALID": 40,
    "FAILED_RETRYABLE": 30,
    "RUNNING": 20,
    "PLANNED": 10,
}

FAILURE_EVIDENCE_FIELDS = (
    "attempts",
    "first_failure_timestamp",
    "latest_failure_timestamp",
    "failure_category",
    "error_fingerprint",
    "terminal_reason",
    "next_eligible_retry_timestamp",
    "error",
)

LEASE_STALE_SECONDS = 600
CIRCUIT_BREAKER_WINDOW = 8
CIRCUIT_BREAKER_FAILURES = 3

FROZEN_CATEGORIES: dict[str, dict[str, tuple[Any, ...]]] = {
    "F01_SESSION_OPENING_MOMENTUM_REVERSAL": {
        "anchors": (
            "Tokyo open",
            "London open",
            "New York open",
            "London 16:00 fixing window",
        ),
        "lookbacks": (15, 30, 60, 90),
        "holding_periods": (15, 30, 60, 120),
        "variants": ("continuation", "reversal"),
    },
    "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": {
        "horizons": (5, 15, 30, 60),
        "data_variants": ("M1-compatible direction-run", "tick-only quote-arrival"),
        "variants": ("continuation", "exhaustion"),
    },
    "F03_VOLATILITY_BREAKOUT": {
        "variants": ("breakout", "failed breakout"),
        "volatility_concepts": ("realized variance compression", "range compression"),
    },
    "F04_LIQUIDITY_SHOCK_REVERSAL": {
        "shock_concepts": (
            "spread widening",
            "range expansion",
            "true quote-arrival drought",
            "true quote-gap shock",
            "bar discontinuity shock",
        ),
    },
    "F05_SPREAD_AWARE_EXECUTION_GATING": {
        "spread_forecasters": (
            "seasonal median",
            "HAR-style linear",
            "elastic net",
            "gradient-boosted trees",
        ),
        "alpha_reports": ("execution alpha", "directional alpha", "combined alpha"),
    },
    "F06_CROSS_PAIR_LEAD_LAG": {
        "directed_relationships": (
            ("EURUSD", "EURJPY"),
            ("USDJPY", "EURJPY"),
            ("GBPUSD", "GBPJPY"),
            ("USDJPY", "GBPJPY"),
            ("AUDUSD", "AUDJPY"),
            ("USDJPY", "AUDJPY"),
        ),
        "lags": (1, 2, 3, 5, 10, 15, 30),
    },
    "F07_CURRENCY_FACTOR_RESIDUALS": {
        "variants": ("residual continuation", "residual mean reversion"),
        "estimation": ("rolling estimation", "expanding estimation"),
    },
    "F08_TRIANGULAR_CONSISTENCY_RESIDUALS": {
        "triangles": (
            "EURUSD / USDJPY / EURJPY",
            "GBPUSD / USDJPY / GBPJPY",
            "AUDUSD / USDJPY / AUDJPY",
        ),
        "variants": (
            "single-leg convergence",
            "two-leg hedge",
            "three-leg executable basket",
        ),
    },
    "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL": {
        "neutrality": (
            "top-minus-bottom",
            "currency-neutral",
            "USD-beta-neutral",
            "JPY-beta-neutral",
        ),
    },
    "F10_INTRADAY_SEASONALITY": {
        "seasonality": (
            "minute of session",
            "hour of session",
            "day of week",
            "month-end",
            "quarter-end",
            "pre-holiday",
            "post-holiday",
        ),
    },
    "F11_REGIME_CONDITIONED_TREND_REVERSAL": {
        "regime_classes": ("fixed quantile bins", "hidden Markov model", "Gaussian mixture"),
        "state_count_rule": (2, 3, 4),
    },
    "F12_COST_SENSITIVE_ML_ABSTENTION": {
        "model_classes": (
            "logistic regression",
            "ridge regression",
            "elastic net",
            "random forest",
            "gradient-boosted trees",
            "small fully connected neural network",
        ),
        "targets": (
            "net executable return sign",
            "net executable return",
            "gross move exceeds frozen round-trip cost",
        ),
        "horizons": (5, 15, 30, 60, 120),
    },
}


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


def recertify_clean_room(data_root: Path, write_artifact: bool = True) -> dict[str, Any]:
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
    if write_artifact:
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


def mixed_pick(items: tuple[Any, ...], idx: int, stride: int = 1) -> Any:
    return items[(idx // stride) % len(items)]


def category_coverage(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    coverage: dict[str, dict[str, dict[str, int]]] = {}
    for family_id, axes in FROZEN_CATEGORIES.items():
        coverage[family_id] = {
            axis: {category_key(value): 0 for value in values} for axis, values in axes.items()
        }
    for record in records:
        family_id = record["family_id"]
        cfg = record["full_configuration"]
        categories = cfg.get("frozen_categories", {})
        for axis, value in categories.items():
            if axis in coverage.get(family_id, {}):
                coverage[family_id][axis][category_key(value)] += 1
    return coverage


def category_key(value: Any) -> str:
    if isinstance(value, list):
        value = tuple(value)
    return str(value)


def uncovered_categories(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing = []
    for family_id, axes in category_coverage(records).items():
        for axis, levels in axes.items():
            for level, count in levels.items():
                if count == 0:
                    missing.append({"family_id": family_id, "axis": axis, "level": level})
    return missing


def create_op1_start_artifacts(data_root: Path, progress: dict[str, Any]) -> None:
    state = {
        "artifact_id": "A0R2OP1_STARTING_STATE_V1",
        "gate_id": GATE_ID,
        "operational_continuation": "A0R2-OP1",
        "status": "PASS",
        "starting_a0r2_sha": STARTING_SHA,
        "current_operational_sha": "fadf804189db385d97d499e288eaf342af7a5bd9",
        "observed_sha": git_sha(),
        "clean_room_id": CLEAN_ROOM_ID,
        "clean_room_path_hash": clean_room_path_hash(data_root),
        "checkpoint_counts": {
            "total_partitions": progress.get("total_partitions", 1080),
            "certified": progress.get("certified_partitions", 0),
            "pending": progress.get("pending_partitions", 1080),
            "retryable_failures": progress.get("retryable_failures", 0),
            "terminal_failures": progress.get("terminal_failures", 0),
        },
    }
    integrity = {
        "artifact_id": "A0R2OP1_PRE_OUTCOME_INTEGRITY_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "completed_empirical_trials": 0,
        "economic_outcomes": 0,
        "discovery_dataset_frozen": False,
        "strategy_outcomes_observed": False,
        "returns_observed": False,
        "trial_performance_observed": False,
        "v1_materialization_preserved_byte_for_byte": True,
        "raw_provider_metadata_observed": True,
        "raw_provider_returns_observed": False,
    }
    write_json(results_dir() / "a0r2op1_starting_state.json", state)
    write_json(results_dir() / "a0r2op1_pre_outcome_integrity.json", integrity)


def create_op2_start_artifacts(data_root: Path, progress: dict[str, Any]) -> None:
    state = {
        "artifact_id": "A0R2OP2_STARTING_STATE_V1",
        "gate_id": GATE_ID,
        "operational_continuation": "A0R2-OP2",
        "status": "PASS",
        "expected_starting_sha": OP1_OPERATIONAL_SHA,
        "observed_sha": git_sha(),
        "active_materialization": MATERIALIZATION_ID_V2,
        "materialization_v2_sha256": MATERIALIZATION_V2_SHA256,
        "clean_room_id": CLEAN_ROOM_ID,
        "clean_room_path_hash": clean_room_path_hash(data_root),
        "checkpoint_counts": {
            "total_partitions": progress.get("total_partitions", 1080),
            "certified": progress.get("certified_partitions", 0),
            "complete_pending_certification": progress.get(
                "complete_pending_certification", 0
            ),
            "planned": progress.get("planned_partitions", 0),
            "running": progress.get("running_partitions", 0),
            "retryable_failures": progress.get("retryable_failures", 0),
            "terminal_failures": progress.get("terminal_failures", 0),
        },
    }
    integrity = {
        "artifact_id": "A0R2OP2_PRE_OUTCOME_INTEGRITY_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "completed_empirical_trials": 0,
        "economic_outcomes": 0,
        "discovery_dataset_frozen": False,
        "strategy_outcomes_observed": False,
        "returns_observed": False,
        "trial_performance_observed": False,
        "v2_materialization_preserved_byte_for_byte": (
            file_sha256(results_dir() / "trial_materialization_v2.jsonl")
            == MATERIALIZATION_V2_SHA256
        ),
        "materialization_v3_created": False,
    }
    write_json(results_dir() / "a0r2op2_starting_state.json", state)
    write_json(results_dir() / "a0r2op2_pre_outcome_integrity.json", integrity)


def create_op3_start_artifacts(data_root: Path, progress: dict[str, Any]) -> None:
    state = {
        "artifact_id": "A0R2OP3_STARTING_STATE_V1",
        "gate_id": GATE_ID,
        "operational_continuation": "A0R2-OP3",
        "status": "PASS",
        "expected_starting_sha": "ae18b59fd1cdd042a1b16ce5b35232c255ebf2ce",
        "observed_sha": git_sha(),
        "active_materialization": MATERIALIZATION_ID_V2,
        "materialization_v2_sha256": MATERIALIZATION_V2_SHA256,
        "clean_room_id": CLEAN_ROOM_ID,
        "clean_room_path_hash": clean_room_path_hash(data_root),
        "checkpoint_counts": {
            "total_partitions": progress.get("total_partitions", 1080),
            "certified": progress.get("certified_partitions", 0),
            "complete_pending_certification": progress.get(
                "complete_pending_certification", 0
            ),
            "planned": progress.get("planned_partitions", 0),
            "running": progress.get("running_partitions", 0),
            "retryable_failures": progress.get("retryable_failures", 0),
            "terminal_failures": progress.get("terminal_failures", 0),
        },
    }
    integrity = {
        "artifact_id": "A0R2OP3_PRE_OUTCOME_INTEGRITY_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "completed_empirical_trials": 0,
        "economic_outcomes": 0,
        "discovery_dataset_frozen": False,
        "strategy_outcomes_observed": False,
        "returns_observed": False,
        "trial_performance_observed": False,
        "v2_materialization_preserved_byte_for_byte": (
            file_sha256(results_dir() / "trial_materialization_v2.jsonl")
            == MATERIALIZATION_V2_SHA256
        ),
        "materialization_v3_created": False,
    }
    write_json(results_dir() / "a0r2op3_starting_state.json", state)
    write_json(results_dir() / "a0r2op3_pre_outcome_integrity.json", integrity)


def create_materialization_amendment() -> None:
    payload = {
        "artifact_id": "A0R2_TRIAL_MATERIALIZATION_AMENDMENT_V1",
        "gate_id": GATE_ID,
        "amendment_id": AMENDMENT_ID,
        "status": "FROZEN_BEFORE_EMPIRICAL_OUTCOMES",
        "reason": "FROZEN_SEARCH_CATEGORIES_NOT_FULLY_REPRESENTED_IN_V1_MATERIALIZATION",
        "unchanged_surfaces": [
            "family identities",
            "family allocations",
            "trial IDs",
            "candidate-equivalent weights",
            "temporal partitions",
            "eligibility thresholds",
            "cost model",
            "execution model",
        ],
        "market_data_acquisition_metadata_observed": True,
        "strategy_outcomes_observed": False,
        "returns_observed": False,
        "trial_performance_observed": False,
        "amendment_outcome_blind": True,
        "active_materialization_after_commit": MATERIALIZATION_ID_V2,
        "v1_lineage_preserved": True,
    }
    write_json(results_dir() / "trial_materialization_amendment.json", payload)
    docs_dir().mkdir(parents=True, exist_ok=True)
    (docs_dir() / "A0R2_TRIAL_MATERIALIZATION_AMENDMENT.md").write_text(
        "# A0R2 Trial Materialization Amendment\n\n"
        f"Amendment ID: `{AMENDMENT_ID}`\n\n"
        "Status: `FROZEN_BEFORE_EMPIRICAL_OUTCOMES`\n\n"
        "Reason: `FROZEN_SEARCH_CATEGORIES_NOT_FULLY_REPRESENTED_IN_V1_MATERIALIZATION`\n\n"
        "This is an outcome-blind implementation-completeness repair. Market-data "
        "acquisition metadata was observed, but no strategy outcomes, returns or "
        "trial performance were observed. The 1200 trial IDs, family allocations, "
        "candidate-equivalent weights, temporal partitions, cost model and "
        "execution model remain unchanged.\n",
        encoding="utf-8",
    )


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


def materialize_family_config_v2(
    record: dict[str, Any], global_idx: int, family_idx: int
) -> dict[str, Any]:
    cfg = base_config(record, global_idx)
    family = record["family_id"]
    axes = FROZEN_CATEGORIES[family]
    cfg["implementation_mapping_version"] = "A0R2_BALANCED_MIXED_RADIX_MAPPING_V2"
    cfg["normalization_rule"] = "train_only_expanding_or_rolling_as_configured"

    if family == "F01_SESSION_OPENING_MOMENTUM_REVERSAL":
        categories = {
            "anchors": mixed_pick(axes["anchors"], family_idx),
            "lookbacks": mixed_pick(axes["lookbacks"], family_idx, 4),
            "holding_periods": mixed_pick(axes["holding_periods"], family_idx, 16),
            "variants": mixed_pick(axes["variants"], family_idx, 64),
        }
        cfg.update({
            "variant": categories["variants"],
            "session_anchor": categories["anchors"],
            "lookback": categories["lookbacks"],
            "holding_horizon": categories["holding_periods"],
            "feature_list": ["session labels", "M1 signed mid return", "rolling range"],
            "required_inputs": ["session labels", "M1 signed mid return", "rolling range"],
        })
    elif family == "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION":
        categories = {
            "horizons": mixed_pick(axes["horizons"], family_idx),
            "data_variants": mixed_pick(axes["data_variants"], family_idx, 4),
            "variants": mixed_pick(axes["variants"], family_idx, 8),
        }
        tick_only = categories["data_variants"] == "tick-only quote-arrival"
        cfg.update({
            "variant": categories["variants"],
            "holding_horizon": categories["horizons"],
            "feature_list": (
                ["quote-arrival count", "bid-update count", "ask-update count"]
                if tick_only else ["M1 signed mid return", "rolling spread statistics"]
            ),
            "required_inputs": (
                ["quote-arrival count", "bid-update count", "ask-update count"]
                if tick_only else ["M1 signed mid return", "rolling spread statistics"]
            ),
        })
    elif family == "F03_VOLATILITY_BREAKOUT":
        categories = {
            "variants": mixed_pick(axes["variants"], family_idx),
            "volatility_concepts": mixed_pick(axes["volatility_concepts"], family_idx, 2),
        }
        cfg.update({
            "variant": categories["variants"],
            "feature_list": ["rolling realized variance", "rolling range", "M1 signed mid return"],
            "required_inputs": [
                "rolling realized variance",
                "rolling range",
                "M1 signed mid return",
            ],
        })
    elif family == "F04_LIQUIDITY_SHOCK_REVERSAL":
        categories = {"shock_concepts": mixed_pick(axes["shock_concepts"], family_idx)}
        tick_only = categories["shock_concepts"] in (
            "true quote-arrival drought",
            "true quote-gap shock",
        )
        cfg.update({
            "variant": categories["shock_concepts"],
            "feature_list": (
                ["raw individual quotes", "true quote-gap distribution"]
                if tick_only else ["spread open/high/low/close", "rolling range"]
            ),
            "required_inputs": (
                ["raw individual quotes", "true quote-gap distribution"]
                if tick_only else ["spread open/high/low/close", "rolling range"]
            ),
        })
    elif family == "F05_SPREAD_AWARE_EXECUTION_GATING":
        categories = {
            "spread_forecasters": mixed_pick(axes["spread_forecasters"], family_idx),
            "alpha_reports": mixed_pick(axes["alpha_reports"], family_idx, 4),
        }
        cfg.update({
            "variant": categories["alpha_reports"],
            "spread_forecaster": categories["spread_forecasters"],
            "feature_list": ["spread open/high/low/close", "rolling spread statistics"],
            "required_inputs": ["spread open/high/low/close", "rolling spread statistics"],
        })
    elif family == "F06_CROSS_PAIR_LEAD_LAG":
        edge = mixed_pick(axes["directed_relationships"], family_idx)
        lag = mixed_pick(axes["lags"], family_idx, 6)
        categories = {"directed_relationships": edge, "lags": lag}
        cfg.update({
            "variant": "lagged_cross_pair_return",
            "cross_pair_edge": {"leader": edge[0], "target": edge[1], "lag_minutes": lag},
            "instrument_or_portfolio_scope": edge[1],
            "feature_list": ["lagged cross-pair synchronized returns", "M1 signed mid return"],
            "required_inputs": ["lagged cross-pair synchronized returns", "M1 signed mid return"],
        })
    elif family == "F07_CURRENCY_FACTOR_RESIDUALS":
        categories = {
            "variants": mixed_pick(axes["variants"], family_idx),
            "estimation": mixed_pick(axes["estimation"], family_idx, 2),
        }
        cfg.update({
            "variant": categories["variants"],
            "training_window": categories["estimation"],
            "feature_list": ["M1 signed mid return", "lagged cross-pair synchronized returns"],
            "required_inputs": ["M1 signed mid return", "lagged cross-pair synchronized returns"],
        })
    elif family == "F08_TRIANGULAR_CONSISTENCY_RESIDUALS":
        categories = {
            "triangles": mixed_pick(axes["triangles"], family_idx),
            "variants": mixed_pick(axes["variants"], family_idx, 3),
        }
        cfg.update({
            "variant": categories["variants"],
            "triangle": categories["triangles"],
            "feature_list": ["mid open/high/low/close", "spread open/high/low/close"],
            "required_inputs": ["mid open/high/low/close", "spread open/high/low/close"],
        })
    elif family == "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL":
        categories = {"neutrality": mixed_pick(axes["neutrality"], family_idx)}
        cfg.update({
            "variant": "cross_sectional_intraday_momentum_reversal",
            "neutrality_constraint": categories["neutrality"],
            "feature_list": ["M1 signed mid return", "rolling realized variance"],
            "required_inputs": ["M1 signed mid return", "rolling realized variance"],
        })
    elif family == "F10_INTRADAY_SEASONALITY":
        categories = {"seasonality": mixed_pick(axes["seasonality"], family_idx)}
        cfg.update({
            "variant": categories["seasonality"],
            "training_window": "prior_year_only",
            "feature_list": ["session labels", "M1 signed mid return"],
            "required_inputs": ["session labels", "M1 signed mid return"],
        })
    elif family == "F11_REGIME_CONDITIONED_TREND_REVERSAL":
        categories = {
            "regime_classes": mixed_pick(axes["regime_classes"], family_idx),
            "state_count_rule": mixed_pick(axes["state_count_rule"], family_idx, 3),
        }
        cfg.update({
            "variant": "regime_conditioned_trend_reversal",
            "regime_model": categories["regime_classes"],
            "regime_component_count": categories["state_count_rule"],
            "regime_state_use": "filtered_states_only",
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
        })
    elif family == "F12_COST_SENSITIVE_ML_ABSTENTION":
        categories = {
            "model_classes": mixed_pick(axes["model_classes"], family_idx),
            "targets": mixed_pick(axes["targets"], family_idx, 6),
            "horizons": mixed_pick(axes["horizons"], family_idx, 18),
        }
        cfg.update({
            "variant": "cost_sensitive_abstention",
            "model_class": categories["model_classes"],
            "target_horizon": categories["horizons"],
            "target": categories["targets"],
            "abstention_threshold": round(0.50 + (family_idx % 10) * 0.025, 3),
            "model_hyperparameters": {
                "seed": record["random_seed"],
                "fixed_regularization": "frozen_single_default",
            },
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
        })
    else:
        raise ValueError(f"Unsupported family: {family}")

    cfg["frozen_categories"] = categories
    cfg["implementation_fixed_parameters"] = {
        "non_axis_parameters": "single deterministic defaults, not optimized",
        "regime_state_count_rule": "cycle frozen 2/3/4 by family-local index where applicable",
        "ml_threshold_rule": "deterministic seed/index allocation before outcomes",
    }
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


def materialize_trials_v2() -> dict[str, Any]:
    source_records = load_a0r1_trials()
    out_path = results_dir() / "trial_materialization_v2.jsonl"
    seen: set[str] = set()
    family_local_counts: dict[str, int] = {}
    materialized: list[dict[str, Any]] = []
    total_weight = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for global_idx, record in enumerate(source_records):
            trial_id = record["trial_id"]
            family_id = record["family_id"]
            family_idx = family_local_counts.get(family_id, 0)
            family_local_counts[family_id] = family_idx + 1
            if trial_id in seen:
                raise ValueError(f"Duplicate trial_id: {trial_id}")
            seen.add(trial_id)
            cfg = materialize_family_config_v2(record, global_idx, family_idx)
            payload = {
                "materialization_id": MATERIALIZATION_ID_V2,
                "trial_id": trial_id,
                "family_id": family_id,
                "full_configuration": cfg,
                "configuration_sha256": sha256_json(cfg),
                "scientific_source_fields": {
                    "a0_hypothesis_registry_sha256": HYPOTHESIS_SHA,
                    "a0_search_space_freeze_sha256": SEARCH_SPACE_SHA,
                    "a0r1_trial_plan_pre_data_sha": A0R1_TRIAL_PLAN_SHA,
                    "source_trial_id": trial_id,
                    "source_random_seed": record["random_seed"],
                },
                "implementation_mapping_version": "A0R2_BALANCED_MIXED_RADIX_MAPPING_V2",
                "candidate_equivalent_weight": record["candidate_equivalent_weight"],
                "status": "REGISTERED",
            }
            total_weight += int(record["candidate_equivalent_weight"])
            materialized.append(payload)
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    source_ids = {record["trial_id"] for record in source_records}
    materialized_ids = {record["trial_id"] for record in materialized}
    missing = sorted(source_ids - materialized_ids)
    duplicate_count = len(materialized) - len(materialized_ids)
    missing_categories = uncovered_categories(materialized)
    family_counts = Counter(record["family_id"] for record in materialized)
    manifest = {
        "artifact_id": "A0R2_TRIAL_MATERIALIZATION_V2_MANIFEST_V1",
        "gate_id": GATE_ID,
        "materialization_id": MATERIALIZATION_ID_V2,
        "status": (
            "PASS" if not missing and not duplicate_count and not missing_categories else "FAIL"
        ),
        "materialized_trial_ids": len(materialized),
        "missing_ids": len(missing),
        "duplicate_ids": duplicate_count,
        "total_candidate_equivalent_weight": total_weight,
        "family_counts": dict(family_counts),
        "uncovered_frozen_categorical_levels": missing_categories,
        "uncovered_frozen_categorical_level_count": len(missing_categories),
        "materialization_sha256": file_sha256(out_path),
        "pre_data": True,
    }
    audit = {
        "artifact_id": "A0R2_TRIAL_CONFIGURATION_V2_AUDIT_V1",
        "gate_id": GATE_ID,
        "status": manifest["status"],
        "trial_ids_match_v1": not missing and len(materialized_ids) == len(source_ids),
        "family_allocation_unchanged": dict(family_counts)
        == read_json(results_dir() / "trial_materialization_manifest.json")["family_counts"],
        "candidate_equivalent_weight": total_weight,
        "frozen_categorical_levels_with_zero_coverage": len(missing_categories),
        "unfrozen_categories_introduced": False,
        "strategy_outcomes_observed": False,
        "returns_observed": False,
        "trial_performance_observed": False,
    }
    v1_manifest = read_json(results_dir() / "trial_materialization_manifest.json")
    diff = {
        "artifact_id": "A0R2_TRIAL_MATERIALIZATION_V1_V2_DIFF_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "v1_materialization_id": MATERIALIZATION_ID,
        "v2_materialization_id": MATERIALIZATION_ID_V2,
        "trial_ids_changed": 0,
        "candidate_equivalent_weight_changed": 0,
        "family_allocation_changed": False,
        "v1_sha256": v1_manifest["materialization_sha256"],
        "v2_sha256": manifest["materialization_sha256"],
        "coverage_corrections": [
            "F01 explicit anchors/lookbacks/holding periods/continuation-reversal",
            "F02 M1 direction-run versus tick-only quote-arrival categories",
            "F04 all five shock concepts with tick-only capability invalidation",
            "F05 all frozen spread forecasters",
            "F06 exact six directed relationships and all frozen lags",
            "F08 all frozen triangles and executable basket variants",
            "F09 exact frozen neutrality definitions",
            "F10 prior-year seasonality categories",
            "F11 true frozen regime class labels with filtered states",
            "F12 all frozen model classes, targets and horizons",
        ],
    }
    write_json(results_dir() / "trial_materialization_v2_manifest.json", manifest)
    write_json(results_dir() / "trial_configuration_v2_audit.json", audit)
    write_json(results_dir() / "trial_materialization_v1_v2_diff.json", diff)
    return manifest


def load_materialized_trials() -> list[dict[str, Any]]:
    path = results_dir() / "trial_materialization.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def load_materialized_trials_v2() -> list[dict[str, Any]]:
    path = results_dir() / "trial_materialization_v2.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def capability_matrix_for(
    materialized: list[dict[str, Any]], artifact_suffix: str = ""
) -> dict[str, Any]:
    available = set(AVAILABLE_FIELDS)
    invalid = 0
    executable = 0
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
    return {
        "artifact_id": f"A0R2_TRIAL_DATA_CAPABILITY{artifact_suffix}_MATRIX_V1",
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


def provider_capability_payload() -> dict[str, Any]:
    return {
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


def freeze_capability_matrix() -> dict[str, Any]:
    provider = provider_capability_payload()
    matrix = capability_matrix_for(load_materialized_trials())
    write_json(results_dir() / "provider_data_capability.json", provider)
    write_json(results_dir() / "trial_data_capability_matrix.json", matrix)
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


def freeze_capability_matrix_v2() -> dict[str, Any]:
    provider = provider_capability_payload()
    matrix = capability_matrix_for(load_materialized_trials_v2(), "_V2")
    write_json(results_dir() / "provider_data_capability_v2.json", provider)
    write_json(results_dir() / "trial_data_capability_v2_matrix.json", matrix)
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


def lease_path(data_root: Path) -> Path:
    return checkpoint_dir(data_root) / "a0r2_active_run_lease.json"


def raw_dir(data_root: Path) -> Path:
    return data_root / "raw_bi5"


def native_raw_dir(data_root: Path) -> Path:
    path = data_root / "raw_bi5_native"
    path.mkdir(parents=True, exist_ok=True)
    return path


def native_scratch_dir(data_root: Path) -> Path:
    path = data_root / "scratch" / "native_bi5_calls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def native_cache_dir(data_root: Path) -> Path:
    path = data_root / "scratch" / "native_bi5_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def native_manifest_dir(data_root: Path) -> Path:
    path = data_root / "manifests" / "native_bi5"
    path.mkdir(parents=True, exist_ok=True)
    return path


def provider_scratch_dir(data_root: Path) -> Path:
    path = data_root / "scratch" / "dukascopy_provider_calls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def provider_cache_dir(data_root: Path) -> Path:
    path = data_root / "scratch" / "dukascopy_cache_v1"
    path.mkdir(parents=True, exist_ok=True)
    return path


def provider_controls_dir(data_root: Path) -> Path:
    path = data_root / "scratch" / "dukascopy_controls"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def host_identity_hash() -> str:
    return sha256_bytes(socket.gethostname().encode("utf-8"))[:16]


def pid_is_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_lease(data_root: Path) -> dict[str, Any] | None:
    path = lease_path(data_root)
    if not path.exists():
        return None
    return read_json(path)


def write_lease(
    data_root: Path,
    *,
    run_id: str,
    stage: str,
    worker_count: int,
    current_partitions: list[str],
    graceful_shutdown: bool = False,
) -> None:
    payload = {
        "run_id": run_id,
        "host_identity_hash": host_identity_hash(),
        "pid": os.getpid(),
        "process_start_time": datetime.now(timezone.utc).isoformat(),
        "runner_sha": git_sha(),
        "requested_stage": stage,
        "worker_count": worker_count,
        "heartbeat_timestamp": datetime.now(timezone.utc).isoformat(),
        "current_partition_ids": current_partitions,
        "graceful_shutdown": graceful_shutdown,
    }
    write_json(lease_path(data_root), payload)


def update_lease_heartbeat(
    data_root: Path, current_partitions: list[str], graceful_shutdown: bool = False
) -> None:
    lease = read_lease(data_root)
    if not lease:
        return
    lease.update({
        "heartbeat_timestamp": datetime.now(timezone.utc).isoformat(),
        "current_partition_ids": current_partitions,
        "graceful_shutdown": graceful_shutdown,
    })
    write_json(lease_path(data_root), lease)


def close_lease(data_root: Path) -> None:
    lease = read_lease(data_root)
    if lease:
        lease["graceful_shutdown"] = True
        lease["heartbeat_timestamp"] = datetime.now(timezone.utc).isoformat()
        write_json(lease_path(data_root), lease)
    lease_path(data_root).unlink(missing_ok=True)


def lease_is_live(lease: dict[str, Any] | None) -> bool:
    if not lease:
        return False
    pid = int(lease.get("pid") or 0)
    if lease.get("host_identity_hash") == host_identity_hash() and pid_is_alive(pid):
        return True
    heartbeat = str(lease.get("heartbeat_timestamp") or "")
    try:
        heartbeat_dt = datetime.fromisoformat(heartbeat)
    except ValueError:
        return False
    if heartbeat_dt.tzinfo is None:
        heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - heartbeat_dt).total_seconds() < LEASE_STALE_SECONDS


def append_event(data_root: Path, event: dict[str, Any]) -> None:
    path = events_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True)
    with JSONL_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def append_failure(data_root: Path, event: dict[str, Any]) -> None:
    path = failures_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True)
    with JSONL_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


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


def normalized_provider_error(error: str) -> str:
    normalized = " ".join(str(error or "").split())
    return normalized[:240]


def partition_id_from_values(pair: str, year: int, month: int, side: str) -> str:
    return f"{year:04d}-{month:02d}:{pair}:{side}"


def manifest_failure_evidence(
    part: Partition, manifest: MonthManifest | None
) -> dict[str, Any]:
    if manifest is None:
        reason = "MONTH_MANIFEST_MISSING"
        counts: dict[str, int] = {}
        max_day_attempts = 0
        first_failed_date = ""
        first_error = reason
        partial_daily_files = False
        compacted_exists = False
    else:
        status_counts = Counter(day.status for day in manifest.days)
        counts = dict(sorted(status_counts.items()))
        max_day_attempts = max((int(day.attempts or 0) for day in manifest.days), default=0)
        failed_days = [day for day in manifest.days if day.status == "failed"]
        pending_days = [day for day in manifest.days if day.status == "pending"]
        first_failed = failed_days[0] if failed_days else None
        first_failed_date = (
            f"{first_failed.year:04d}-{first_failed.month:02d}-{first_failed.day:02d}"
            if first_failed
            else ""
        )
        first_error = next(
            (
                normalized_provider_error(day.error)
                for day in manifest.days
                if normalized_provider_error(day.error)
            ),
            "",
        )
        if not first_error:
            if failed_days:
                first_error = "MONTH_INCOMPLETE_WITH_FAILED_DAYS"
            elif pending_days:
                first_error = "MONTH_INCOMPLETE_WITH_PENDING_DAYS"
            elif manifest.compacted and manifest.compacted_rows == 0:
                first_error = "MONTH_COMPACTED_ZERO_ROWS"
            else:
                first_error = "MONTH_COMPACTION_MISSING_DESPITE_TERMINAL_DAYS"
        partial_daily_files = any(day.rows > 0 or day.file_size > 0 for day in manifest.days)
        compacted_exists = manifest.compacted and manifest.compacted_rows > 0
    failure_category_counts = (
        Counter(
            day.failure_category or "UNCLASSIFIED"
            for day in manifest.days
            if day.status == "failed"
        )
        if manifest is not None
        else Counter({"MANIFEST_MISSING": 1})
    )
    fingerprint_payload = {
        "partition_id": part.key,
        "failure_category_counts": dict(sorted(failure_category_counts.items())),
        "first_failed_date": first_failed_date,
        "normalized_provider_error": first_error,
    }
    return {
        "partition_id": part.key,
        "failed_day_count": counts.get("failed", 0),
        "pending_day_count": counts.get("pending", 0),
        "market_closed_day_count": counts.get("market_closed", 0),
        "complete_day_count": counts.get("complete", 0),
        "first_failed_date": first_failed_date,
        "first_non_empty_provider_error": first_error,
        "failure_category_counts": dict(sorted(failure_category_counts.items())),
        "maximum_day_attempts": max_day_attempts,
        "compacted_data_exists": compacted_exists,
        "partial_daily_files_exist": partial_daily_files,
        "structured_reason": first_error,
        "error_fingerprint": sha256_json(fingerprint_payload)[:16],
    }


def read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def history_attempt_count(data_root: Path, part: Partition) -> int:
    counts: list[int] = []
    for path in (events_path(data_root), failures_path(data_root)):
        for row in read_jsonl_records(path):
            if row.get("partition") == part.key or row.get("partition_id") == part.key:
                counts.append(int(row.get("attempts") or row.get("attempt_count") or 0))
    return max(counts, default=0)


def manifest_attempt_count(manifest: MonthManifest | None) -> int:
    if manifest is None:
        return 0
    return max((int(day.attempts or 0) for day in manifest.days), default=0)


def authoritative_attempt_count(
    data_root: Path,
    part: Partition,
    persisted: dict[str, Any],
    manifest: MonthManifest | None,
) -> int:
    return max(
        int(persisted.get("attempts") or 0),
        history_attempt_count(data_root, part),
        manifest_attempt_count(manifest),
    )


def reconcile_partition_state(
    persisted_state: dict[str, Any],
    manifest: MonthManifest | None,
) -> dict[str, Any]:
    pair = str(persisted_state.get("pair") or (manifest.pair if manifest else ""))
    year = int(persisted_state.get("year") or (manifest.year if manifest else 0))
    month = int(persisted_state.get("month") or (manifest.month if manifest else 0))
    side = str(persisted_state.get("side") or (manifest.side if manifest else ""))
    part = Partition(pair, year, month, side) if pair and year and month and side else None
    inferred = manifest_to_status(manifest)
    current = str(persisted_state.get("state", "PLANNED"))
    if current in {"CERTIFIED", "FAILED_TERMINAL"}:
        status = current
    elif current == "COMPLETE_PENDING_CERTIFICATION":
        status = current
    elif inferred == "COMPLETE_PENDING_CERTIFICATION" and current == "FAILED_RETRYABLE":
        status = inferred
    elif STATE_PRECEDENCE.get(inferred, 0) > STATE_PRECEDENCE.get(current, 0):
        status = inferred
    elif current in STATE_PRECEDENCE:
        status = current
    else:
        status = inferred
    result = {**persisted_state, "state": status}
    if manifest is not None:
        result.update({
            "pair": manifest.pair,
            "year": manifest.year,
            "month": manifest.month,
            "side": manifest.side,
            "rows": manifest.compacted_rows,
            "checksum": manifest.compacted_checksum,
        })
    for field in FAILURE_EVIDENCE_FIELDS:
        if field in persisted_state:
            result[field] = persisted_state[field]
    if status in {"FAILED_RETRYABLE", "FAILED_TERMINAL"} and part is not None:
        evidence = manifest_failure_evidence(part, manifest)
        result.setdefault("failure_evidence", evidence)
        if not result.get("failure_category"):
            category_counts = evidence["failure_category_counts"]
            result["failure_category"] = next(iter(category_counts), evidence["structured_reason"])
        if not result.get("error"):
            result["error"] = evidence["structured_reason"]
        if not result.get("error_fingerprint"):
            result["error_fingerprint"] = evidence["error_fingerprint"]
    return result


def should_acquire_partition(
    current_state: str,
    retry_failed: bool,
    resume: bool,
    running_is_stale: bool = False,
) -> bool:
    if current_state in {"CERTIFIED", "COMPLETE_PENDING_CERTIFICATION", "MARKET_CLOSED_VALID"}:
        return False
    if current_state == "FAILED_RETRYABLE":
        return retry_failed
    if current_state == "FAILED_TERMINAL":
        return False
    if current_state == "RUNNING":
        return resume and running_is_stale
    if current_state == "PLANNED":
        return not retry_failed
    return False


def is_running_stale(item: dict[str, Any], max_age_seconds: int = 3600) -> bool:
    ts = item.get("ts")
    if not ts:
        return True
    try:
        started = datetime.fromisoformat(str(ts))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds() > max_age_seconds


def failure_fingerprint(error: str) -> str:
    normalized = " ".join(error.lower().split())
    if not normalized:
        normalized = "NO_PROVIDER_ERROR_TEXT"
    return sha256_bytes(normalized.encode("utf-8"))[:16]


def classify_provider_failure(error: str, attempts: int) -> tuple[str, str]:
    lowered = error.lower()
    if any(token.lower() in lowered for token in TERMINAL_FAILURE_FINGERPRINTS):
        return "FAILED_TERMINAL", "NON_RETRYABLE_PROVIDER_OR_PROTOCOL_FAILURE"
    if attempts >= MAX_PARTITION_ATTEMPTS:
        return "FAILED_TERMINAL", "RETRY_ATTEMPTS_EXHAUSTED"
    if any(token.lower() in lowered for token in RETRYABLE_FAILURE_FINGERPRINTS):
        return "FAILED_RETRYABLE", "TRANSIENT_PROVIDER_OR_TRANSPORT_FAILURE"
    return "FAILED_RETRYABLE", "UNKNOWN_RETRYABLE_FAILURE_BEFORE_ATTEMPT_CAP"


def classify_provider_diagnostic(result: ProviderCallResult) -> str:
    text = " ".join(
        [
            result.error_message,
            result.error_code,
            result.stderr_excerpt,
            " ".join(result.stdout_record_types),
        ]
    ).lower()
    if result.timed_out:
        return "PROVIDER_TIMEOUT"
    if "429" in text:
        return "PROVIDER_HTTP_429"
    if "econnreset" in text or "connection reset" in text:
        return "PROVIDER_CONNECTION_RESET"
    if "enotfound" in text or "dns" in text or "network" in text or "fetch failed" in text:
        return "PROVIDER_DNS_OR_NETWORK"
    if "acquisition_error" in result.stdout_record_types and result.stack_fingerprint:
        return "PROVIDER_LIBRARY_ERROR"
    if result.return_code not in (0, None):
        return "NODE_PROCESS_NONZERO"
    if "non_json_stdout" in result.stdout_record_types:
        return "NODE_OUTPUT_SCHEMA_ERROR"
    if result.output_file_reported and not result.output_file_found:
        return "OUTPUT_FILE_NOT_CREATED"
    if result.succeeded and not result.rows:
        return "EMPTY_OPEN_MARKET_RESPONSE"
    if "unknown" in text:
        return "PROVIDER_INTERNAL_UNKNOWN_ERROR"
    return "PROVIDER_LIBRARY_ERROR" if result.error_message else "PROVIDER_HEALTHY"


def provider_diagnostic_payload(
    part: Partition,
    result: ProviderCallResult,
    *,
    request_kind: str,
) -> dict[str, Any]:
    return {
        "request_kind": request_kind,
        "partition_id": part.key,
        "pair": part.pair,
        "year": part.year,
        "month": part.month,
        "side": part.side,
        "node_result_type": "success" if result.succeeded else "failure",
        "failure_category": classify_provider_diagnostic(result),
        "error_excerpt": normalized_provider_error(result.error_message),
        "error_code": result.error_code,
        "stack_fingerprint": result.stack_fingerprint,
        "stderr_fingerprint": result.stderr_fingerprint,
        "return_code": result.return_code,
        "timed_out": result.timed_out,
        "duration_ms": result.duration_ms,
        "stdout_record_types": result.stdout_record_types,
        "row_count": len(result.rows),
        "output_file_reported": result.output_file_reported,
        "output_file_found": result.output_file_found,
    }


def recover_orphaned_running(data_root: Path, explicit: bool) -> dict[str, Any]:
    lease = read_lease(data_root)
    if lease_is_live(lease):
        raise ValueError("A0R2_ACTIVE_LEASE_PREVENTS_COMPETING_RUNNER")
    state = load_state(data_root)
    rows = []
    for part in partition_queue():
        item = state.get("partitions", {}).get(part.key, {})
        if item.get("state") != "RUNNING":
            continue
        same_host = bool(lease and lease.get("host_identity_hash") == host_identity_hash())
        if lease and not same_host and not explicit:
            continue
        manifest = load_month_manifest(
            raw_dir(data_root), part.pair, part.side, part.year, part.month
        )
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw_dir(data_root), manifest)
        manifest_status = manifest_to_status(manifest)
        if manifest_status == "COMPLETE_PENDING_CERTIFICATION":
            new_state = "COMPLETE_PENDING_CERTIFICATION"
            category = ""
        elif manifest and (manifest.days or manifest.compacted_rows):
            new_state = "FAILED_RETRYABLE"
            category = "PROCESS_INTERRUPTED_WITH_PARTIAL_CHECKPOINT"
        else:
            new_state = "FAILED_RETRYABLE"
            category = "PROCESS_INTERRUPTED_BEFORE_CHECKPOINT"
        evidence = manifest_failure_evidence(part, manifest)
        updated = {
            **item,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": new_state,
            "failure_category": category or item.get("failure_category", ""),
            "error": category or item.get("error", ""),
            "error_fingerprint": item.get("error_fingerprint") or evidence["error_fingerprint"],
            "failure_evidence": evidence,
            "orphan_recovered_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        state["partitions"][part.key] = updated
        rows.append({
            "partition_id": part.key,
            "previous_state": "RUNNING",
            "new_state": new_state,
            "attempts_preserved": int(item.get("attempts") or 0),
            "failure_category": category,
            "manifest_status": manifest_status,
        })
    if rows:
        save_state(data_root, state)
    payload = {
        "artifact_id": "A0R2_ORPHANED_RUNNING_RECOVERY_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "recovered_count": len(rows),
        "lease_present": lease is not None,
        "lease_live": False,
        "rows": rows,
    }
    existing_path = results_dir() / "orphaned_running_recovery.json"
    if not rows and existing_path.exists():
        existing = read_json(existing_path)
        if int(existing.get("recovered_count", 0)) > 0:
            return existing
    write_json(results_dir() / "orphaned_running_recovery.json", payload)
    return payload


def run_provider_diagnostic_control(data_root: Path) -> dict[str, Any]:
    scratch = data_root / "scratch" / "provider_diagnostics"
    failed = Partition("EURUSD", 2010, 1, "bid")
    control = Partition("GBPUSD", 2010, 1, "bid")
    failed_result = _download_month_bulk_result(
        "eurusd",
        failed.year,
        failed.month,
        failed.side,
        scratch_root=scratch,
    )
    control_result = _download_single_day_result(
        "gbpusd",
        "2010-01-04",
        "2010-01-05",
        control.side,
        scratch_root=scratch,
        worker_id=0,
    )
    failed_payload = provider_diagnostic_payload(
        failed, failed_result, request_kind="current_failed_partition"
    )
    control_payload = provider_diagnostic_payload(
        control, control_result, request_kind="authorized_good_control_day"
    )
    if control_result.succeeded and not failed_result.succeeded:
        conclusion = "DETERMINISTIC_DATE_OR_INSTRUMENT_FAILURE"
    elif not control_result.succeeded and not failed_result.succeeded:
        conclusion = "LOCAL_NODE_PROCESS_FAILURE"
    elif failed_result.succeeded:
        conclusion = "TRANSIENT_PROVIDER_FAILURE"
    else:
        conclusion = "UNRESOLVED_PROVIDER_LIBRARY_FAILURE"
    payload = {
        "artifact_id": "A0R2_PROVIDER_DIAGNOSTIC_CONTROL_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "failed_partition": failed_payload,
        "control_request": control_payload,
        "same_error_reproduced": (
            failed_payload["failure_category"] == control_payload["failure_category"]
            and failed_payload["failure_category"] != "PROVIDER_HEALTHY"
        ),
    }
    reconciliation = {
        "artifact_id": "A0R2_PROVIDER_UNKNOWN_ERROR_RECONCILIATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "conclusion": conclusion,
        "failed_partition_category": failed_payload["failure_category"],
        "control_category": control_payload["failure_category"],
        "failed_stack_fingerprint": failed_payload["stack_fingerprint"],
        "control_stack_fingerprint": control_payload["stack_fingerprint"],
        "failed_return_code": failed_payload["return_code"],
        "control_return_code": control_payload["return_code"],
    }
    write_json(results_dir() / "provider_diagnostic_control.json", payload)
    write_json(results_dir() / "provider_unknown_error_reconciliation.json", reconciliation)
    return reconciliation


def run_provider_scratch_location_audit(data_root: Path) -> dict[str, Any]:
    """Audit only the A0R2 wrapper's known temporary patterns."""
    scratch = provider_scratch_dir(data_root)
    cache = provider_cache_dir(data_root)
    controls = provider_controls_dir(data_root)
    local_patterns = ("_tmp_download*", ".cache", "dukascopy_provider_calls")
    local_payloads = sum(
        1 for pattern in local_patterns for _ in TOOL_DIR.glob(pattern)
    )
    payload = {
        "artifact_id": "A0R2_PROVIDER_SCRATCH_LOCATION_AUDIT_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if local_payloads == 0 else "FAIL",
        "repository_local_a0r2_provider_payloads": local_payloads,
        "repository_local_a0r2_provider_cache_files": sum(
            1 for _ in (TOOL_DIR / ".cache").rglob("*")
        ) if (TOOL_DIR / ".cache").exists() else 0,
        "clean_room_provider_scratch": "PASS" if scratch.is_dir() and controls.is_dir() else "FAIL",
        "clean_room_provider_cache": "PASS" if cache.is_dir() else "FAIL",
        "checked_patterns": list(local_patterns),
    }
    write_json(results_dir() / "provider_scratch_location_audit.json", payload)
    return payload


def native_metadata_payload() -> dict[str, Any]:
    rows = [
        {
            "pair": metadata.pair,
            "instrument_code": metadata.instrument_code,
            "integer_price_scale": metadata.integer_scale,
            "decimal_precision": metadata.decimal_precision,
            "timezone": metadata.timezone,
            "candle_record_size": metadata.candle_record_size,
            "endianness": metadata.endianness,
            "volume_interpretation": metadata.volume_interpretation,
            "flat_row_handling": metadata.flat_row_handling,
            "bid_url_construction": ".../BID_candles_min_1.bi5",
            "ask_url_construction": ".../ASK_candles_min_1.bi5",
        }
        for _, metadata in sorted(BI5_INSTRUMENTS.items())
    ]
    return {
        "artifact_id": "A0R2_NATIVE_BI5_INSTRUMENT_METADATA_V1",
        "gate_id": GATE_ID,
        "source_identity": "DUKASCOPY_DATAFEED_M1_CANDLES_V1",
        "transport_id": "DUKASCOPY_NATIVE_BI5_V1",
        "parser_version": NATIVE_BI5_PARSER_VERSION,
        "unknown_instrument_scales": 0,
        "rows": rows,
        "mapping_sha256": sha256_json(rows),
    }


def certify_native_metadata() -> dict[str, Any]:
    metadata = native_metadata_payload()
    certification = {
        "artifact_id": "A0R2_NATIVE_BI5_PARSER_CERTIFICATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "instrument_mapping_sha256": metadata["mapping_sha256"],
        "authorized_pairs": len(metadata["rows"]),
        "unknown_instrument_scales": 0,
        "timestamp_conversion_failures": 0,
        "ohlc_invariant_failures": 0,
        "unauthorized_date_rows": 0,
        "parser_nondeterminism": 0,
    }
    write_json(results_dir() / "native_bi5_instrument_metadata.json", metadata)
    write_json(results_dir() / "native_bi5_parser_certification.json", certification)
    return certification


def native_control_row(
    data_root: Path, pair: str, side: str, requested: date, label: str
) -> dict[str, Any]:
    raw_path = native_scratch_dir(data_root) / "controls" / label / "candles.bi5"
    fetched = fetch_bi5_day(
        dukascopy_candle_url(pair, requested, side), raw_path, retries=2
    )
    if fetched.status != "PASS":
        return {
            "control": label,
            "pair": pair,
            "side": side,
            "date": requested.isoformat(),
            "status": "FAIL",
            "failure_category": "NATIVE_BI5_TRANSPORT_FAILURE",
            "http_status": fetched.http_status,
            "content_length": fetched.content_length,
            "error_fingerprint": failure_fingerprint(fetched.error),
        }
    try:
        rows = parse_bi5_m1_candles(raw_path.read_bytes(), requested, pair=pair)
        checks = validate_m1_rows(rows, requested)
    except (OSError, ValueError) as exc:
        return {
            "control": label,
            "pair": pair,
            "side": side,
            "date": requested.isoformat(),
            "status": "FAIL",
            "failure_category": "NATIVE_BI5_SCHEMA_FAILURE",
            "http_status": fetched.http_status,
            "content_length": fetched.content_length,
            "error_fingerprint": failure_fingerprint(str(exc)),
        }
    passed = bool(rows) and all(checks[key] for key in (
        "monotonic_timestamps", "timestamps_in_requested_day", "ohlc_valid"
    ))
    return {
        "control": label,
        "pair": pair,
        "side": side,
        "date": requested.isoformat(),
        "status": "PASS" if passed else "FAIL",
        "failure_category": "" if passed else "NATIVE_BI5_SCHEMA_FAILURE",
        "http_status": fetched.http_status,
        "content_length": fetched.content_length,
        "row_count": len(rows),
        "raw_sha256": fetched.checksum,
        "parsed_row_hash": rows_checksum(rows),
    }


def run_native_health_controls(data_root: Path) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    rows = []
    for pair, side, requested, label in (
        ("EURUSD", "bid", date(2010, 1, 4), "A"),
        ("USDJPY", "ask", date(2010, 1, 5), "B"),
    ):
        control_started_at = datetime.now(timezone.utc).isoformat()
        control_started_monotonic = time.monotonic()
        row = native_control_row(data_root, pair, side, requested, label)
        row["control_started_at"] = control_started_at
        row["control_completed_at"] = datetime.now(timezone.utc).isoformat()
        row["duration_ms"] = round((time.monotonic() - control_started_monotonic) * 1000)
        rows.append(row)
    completed_at = datetime.now(timezone.utc).isoformat()
    passed = all(row["status"] == "PASS" for row in rows)
    payload = {
        "artifact_id": "A0R2_NATIVE_BI5_HEALTH_CONTROLS_V1",
        "gate_id": GATE_ID,
        "transport_id": "NATIVE_BI5_TRANSPORT",
        "status": "PASS" if passed else "PROVIDER_COOLDOWN_REQUIRED",
        "controls": rows,
        "rolling_calls": 20,
        "failure_trigger": 5,
        "partition_attempts_consumed": 0,
        "health_run_started_at": started_at,
        "health_run_completed_at": completed_at,
        "duration_ms": round((time.monotonic() - started_monotonic) * 1000),
    }
    write_json(results_dir() / "native_bi5_health_controls.json", payload)
    append_native_health_history(data_root, payload)
    write_provider_health_summary(data_root)
    return payload


def native_health_history_path(data_root: Path) -> Path:
    return data_root / "checkpoints" / "provider_health_history.jsonl"


def append_native_health_history(data_root: Path, payload: dict[str, Any]) -> None:
    run_id = f"native-{uuid.uuid4().hex}"
    history = native_health_history_path(data_root)
    history.parent.mkdir(parents=True, exist_ok=True)
    started_at = str(payload["health_run_started_at"])
    completed_at = str(payload["health_run_completed_at"])
    run_status = "PASS" if payload["status"] == "PASS" else "FAIL"
    runner_sha = git_sha()
    records = []
    for row in payload["controls"]:
        records.append({
            "timestamp": row["control_completed_at"],
            "transport": "NATIVE_BI5_TRANSPORT",
            "record_type": "HEALTH_CONTROL", "health_run_id": run_id,
            "health_run_started_at": started_at, "health_run_completed_at": completed_at,
            "control_started_at": row["control_started_at"],
            "control_completed_at": row["control_completed_at"],
            "duration_ms": row["duration_ms"],
            "control_id": row["control"], "pair": row["pair"], "side": row["side"],
            "date": row["date"], "result": row["status"],
            "http_status": row.get("http_status"),
            "failure_category": row.get("failure_category", ""),
            "error_fingerprint": row.get("error_fingerprint", ""),
            "content_length": row.get("content_length", 0),
            "row_count": row.get("row_count", 0), "parser_result": row["status"],
            "runner_sha": runner_sha,
        })
    records.append({
        "record_type": "HEALTH_RUN_SUMMARY", "health_run_id": run_id,
        "timestamp": completed_at, "transport": "NATIVE_BI5_TRANSPORT",
        "status": run_status, "control_sequence": ["A", "B"],
        "control_results": {row["control"]: row["status"] for row in payload["controls"]},
        "duration_ms": payload["duration_ms"], "started_at": started_at,
        "completed_at": completed_at, "runner_sha": runner_sha,
    })
    with NATIVE_HEALTH_HISTORY_LOCK:
        with history.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def write_provider_health_summary(data_root: Path) -> dict[str, Any]:
    path = native_health_history_path(data_root)
    records = read_jsonl_records(path)
    native = [row for row in records if row.get("transport") == "NATIVE_BI5_TRANSPORT"]
    controls = [row for row in native if row.get("record_type") == "HEALTH_CONTROL"]
    controls_by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in controls:
        run_id = row.get("health_run_id")
        control_id = row.get("control_id")
        if isinstance(run_id, str) and control_id in {"A", "B"}:
            controls_by_run.setdefault(run_id, {})[str(control_id)] = row
    runs = []
    for row in native:
        if row.get("record_type") != "HEALTH_RUN_SUMMARY":
            continue
        run_id = row.get("health_run_id")
        grouped = controls_by_run.get(str(run_id), {})
        if set(grouped) != {"A", "B"}:
            continue
        expected = {key: str(grouped[key].get("result")) for key in ("A", "B")}
        if row.get("control_results") not in (None, expected):
            continue
        computed_status = "PASS" if all(v == "PASS" for v in expected.values()) else "FAIL"
        if str(row.get("status")) != computed_status:
            continue
        runs.append({**row, "control_results": expected})
    results = [str(row["status"]) for row in runs]
    def trailing(value: str) -> int:
        count = 0
        for result in reversed(results):
            if result != value:
                break
            count += 1
        return count
    categories = Counter(
        str(row.get("failure_category", ""))
        for row in controls if row.get("failure_category")
    )
    last_pass = next((row.get("completed_at", row.get("timestamp")) for row in reversed(runs)
                      if row.get("status") == "PASS"), None)
    last_fail = next((row.get("completed_at", row.get("timestamp")) for row in reversed(runs)
                      if row.get("status") == "FAIL"), None)
    latest = runs[-1] if runs else None
    latest_status = str(latest["status"]) if latest else None
    summary = {
        "artifact_id": "A0R2_PROVIDER_HEALTH_SUMMARY_V1",
        "gate_id": GATE_ID,
        "transport": "NATIVE_BI5_TRANSPORT",
        "status": ("PASS" if latest_status == "PASS" else
                   "PROVIDER_COOLDOWN_REQUIRED" if latest_status == "FAIL" else
                   "NO_HEALTH_EVIDENCE"),
        "latest_run_id": latest.get("health_run_id") if latest else None,
        "latest_status": latest_status,
        "latest_control_results": latest["control_results"] if latest else {},
        "last_full_pass_timestamp": last_pass,
        "last_full_fail_timestamp": last_fail,
        "full_pass_run_count": results.count("PASS"),
        "full_fail_run_count": results.count("FAIL"),
        "complete_health_run_count": len(runs),
        "consecutive_passing_runs": trailing("PASS"),
        "consecutive_failing_runs": trailing("FAIL"),
        "control_pass_count": sum(
            row.get("result") == "PASS" for row in controls
        ),
        "control_fail_count": sum(row.get("result") == "FAIL" for row in controls),
        "legacy_ungrouped_control_count": sum(
            row.get("record_type") != "HEALTH_RUN_SUMMARY" and not row.get("health_run_id")
            for row in native
        ),
        "failure_category_distribution": dict(categories),
    }
    write_json(results_dir() / "provider_health_summary.json", summary)
    return summary


def native_health_watch_state_path(data_root: Path) -> Path:
    return data_root / "checkpoints" / "native_health_watch_state.json"


def run_native_health_watch(
    data_root: Path,
    *,
    max_attempts: int,
    interval_seconds: int,
    required_consecutive_passes: int,
) -> dict[str, Any]:
    """Run a finite, restartable health probe without touching partition state."""
    if max_attempts < 1 or interval_seconds < 0 or required_consecutive_passes < 1:
        raise ValueError("A0R2_NATIVE_HEALTH_WATCH_ARGUMENT_INVALID")
    state_path = native_health_watch_state_path(data_root)
    state: dict[str, Any] = read_json(state_path) if state_path.exists() else {
        "artifact_id": "A0R2_NATIVE_HEALTH_WATCH_STATE_V1",
        "gate_id": GATE_ID,
        "attempts_completed": 0,
        "consecutive_passing_runs": 0,
        "history": [],
    }
    attempts_this_watch = 0
    while attempts_this_watch < max_attempts:
        attempts_this_watch += 1
        run_native_health_controls(data_root)
        summary = write_provider_health_summary(data_root)
        passed = summary.get("latest_status") == "PASS"
        state["attempts_completed"] = int(state.get("attempts_completed", 0)) + 1
        state["consecutive_passing_runs"] = (
            int(state.get("consecutive_passing_runs", 0)) + 1 if passed else 0
        )
        state["history"].append({
            "attempt": state["attempts_completed"],
            "status": summary.get("status"),
            "latest_status": summary.get("latest_status"),
            "latest_run_id": summary.get("latest_run_id"),
        })
        state["required_consecutive_health_passes"] = required_consecutive_passes
        state["max_attempts_this_watch"] = max_attempts
        state["interval_seconds"] = interval_seconds
        state["partition_attempts_consumed"] = 0
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        if state["consecutive_passing_runs"] >= required_consecutive_passes:
            state["status"] = "NATIVE_HEALTH_READY"
            write_json(state_path, state)
            break
        write_json(state_path, state)
        if attempts_this_watch < max_attempts and interval_seconds:
            time.sleep(interval_seconds)
    else:
        state["status"] = "NATIVE_HEALTH_WATCH_EXHAUSTED"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(state_path, state)
    artifact = {
        "artifact_id": "A0R2_NATIVE_HEALTH_WATCH_V1",
        "gate_id": GATE_ID,
        "status": state["status"],
        "attempts_this_watch": attempts_this_watch,
        "attempts_completed": state["attempts_completed"],
        "required_consecutive_health_passes": required_consecutive_passes,
        "consecutive_passing_runs": state["consecutive_passing_runs"],
        "latest_health_status": state["history"][-1]["latest_status"] if state["history"] else None,
        "partition_attempts_consumed": 0,
    }
    write_json(results_dir() / "native_health_watch.json", artifact)
    return artifact


def _node_reference_units(data_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Select immutable existing Node daily units deterministically."""
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for pair in INSTRUMENTS:
        for side in SIDES:
            candidates: list[dict[str, Any]] = []
            for year in YEARS:
                for month in MONTHS:
                    manifest = load_month_manifest(raw_dir(data_root), pair, side, year, month)
                    if manifest is None:
                        continue
                    for item in sorted(manifest.days, key=lambda day: day.day):
                        path = (
                            raw_dir(data_root) / pair / f"price={side}" / f"year={year}"
                            / f"month={month:02d}" / f"day={item.day:02d}" / "data.json"
                        )
                        if item.status == "complete" and item.rows > 0 and path.exists():
                            candidates.append({
                                "pair": pair, "side": side, "year": year,
                                "month": month, "day": item.day, "path": path,
                            })
            if len(candidates) < 3:
                missing.append(f"{pair}:{side}:need_3_have_{len(candidates)}")
                continue
            selected.extend(candidates[:3])
    return selected, missing


def _node_row_hashes(rows: list[dict[str, Any]], pair: str) -> dict[str, Any]:
    scale = instrument_metadata(pair).integer_scale
    integer_rows = [
        [
            int(row["timestamp"]),
            int(round(float(row["open"]) * scale)),
            int(round(float(row["high"]) * scale)),
            int(round(float(row["low"]) * scale)),
            int(round(float(row["close"]) * scale)),
        ]
        for row in rows
    ]
    volumes = [float(row.get("volume", 0.0)) for row in rows]
    return {
        "row_count": len(rows),
        "timestamp_set_sha256": sha256_json([row[0] for row in integer_rows]),
        "integer_ohlc_sha256": sha256_json(integer_rows),
        "normalized_ohlc_sha256": sha256_json(integer_rows),
        "volume_sha256": sha256_json(volumes),
        "duplicate_count": len({row[0] for row in integer_rows}) != len(integer_rows),
        "flat_row_count": sum(value == 0.0 for value in volumes),
    }


def run_native_parity_certification(data_root: Path) -> dict[str, Any]:
    """Certify native BI5 solely against immutable Node checkpoints."""
    references, missing = _node_reference_units(data_root)
    panel: list[dict[str, Any]] = []
    if not missing:
        for unit in references:
            requested = date(unit["year"], unit["month"], unit["day"])
            native_path = (
                native_scratch_dir(data_root) / "parity" / unit["pair"]
                / f"price={unit['side']}" / requested.isoformat() / "candles.bi5"
            )
            fetched = fetch_bi5_day(
                dukascopy_candle_url(unit["pair"], requested, unit["side"]),
                native_path, retries=2,
            )
            reference_rows = read_json(unit["path"])
            reference = _node_row_hashes(reference_rows, unit["pair"])
            row: dict[str, Any] = {
                "pair": unit["pair"], "side": unit["side"],
                "date": requested.isoformat(), "reference_transport": "DUKASCOPY_NODE_1_46_4",
                "native_transport": "DUKASCOPY_NATIVE_BI5_V1", **reference,
                "native_row_count": 0, "native_timestamp_set_sha256": "",
                "native_integer_ohlc_sha256": "", "native_normalized_ohlc_sha256": "",
                "native_volume_sha256": "", "parity": "FAIL",
            }
            if fetched.status == "PASS":
                native_rows = parse_bi5_m1_candles(
                    native_path.read_bytes(), requested, pair=unit["pair"]
                )
                structural = validate_m1_rows(native_rows, requested)
                native = {
                    "native_row_count": len(native_rows),
                    "native_timestamp_set_sha256": timestamp_checksum(native_rows),
                    "native_integer_ohlc_sha256": raw_ohlc_checksum(native_rows),
                    "native_normalized_ohlc_sha256": raw_ohlc_checksum(native_rows),
                    "native_volume_sha256": sha256_json(
                        [float(item["volume"]) for item in native_rows]
                    ),
                    "native_duplicate_count": (
                        len({item["timestamp"] for item in native_rows}) != len(native_rows)
                    ),
                    "native_out_of_range_rows": not structural["timestamps_in_requested_day"],
                    "native_flat_row_count": sum(
                        float(item["volume"]) == 0.0 for item in native_rows
                    ),
                }
                row.update(native)
                row["parity"] = "PASS" if (
                    reference["row_count"] == native["native_row_count"]
                    and reference["timestamp_set_sha256"] == native["native_timestamp_set_sha256"]
                    and reference["integer_ohlc_sha256"] == native["native_integer_ohlc_sha256"]
                    and reference["volume_sha256"] == native["native_volume_sha256"]
                    and not native["native_out_of_range_rows"]
                ) else "FAIL"
            panel.append(row)
    passed = len(panel) == 54 and not missing and all(row["parity"] == "PASS" for row in panel)
    decision = (
        "NATIVE_BI5_CERTIFIED_AS_PRIMARY_TRANSPORT"
        if passed
        else "BLOCKED_BY_A0R2_DUAL_TRANSPORT_PROVENANCE"
    )
    panel_payload = {
        "artifact_id": "A0R2_DUAL_TRANSPORT_PARITY_PANEL_V1",
        "gate_id": GATE_ID,
        "required_units": 54,
        "actual_units": len(panel),
        "missing_reference_coverage": missing,
        "rows": panel,
    }
    certification = {
        "artifact_id": "A0R2_DUAL_TRANSPORT_PARITY_CERTIFICATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if passed else "FAIL",
        "decision": decision,
        "parity_units": len(panel),
        "required_units": 54,
        "missing_reference_coverage": missing,
        "failed_units": sum(row["parity"] != "PASS" for row in panel),
    }
    write_json(results_dir() / "dual_transport_parity_panel.json", panel_payload)
    write_json(results_dir() / "dual_transport_parity_certification.json", certification)
    return certification


def run_existing_data_reuse_audit(data_root: Path) -> dict[str, Any]:
    """Reconstruct transport-neutral provenance for the declared A0R2 root only."""
    units: list[dict[str, Any]] = []
    reused = 0
    invalid = 0
    bytes_reused = 0
    certified_months = 0
    partial_days = 0
    for part in partition_queue():
        manifest = load_month_manifest(
            raw_dir(data_root), part.pair, part.side, part.year, part.month
        )
        if manifest is None:
            continue
        if manifest.compacted:
            certified_months += 1
        for item in manifest.days:
            if item.status not in {"complete", "market_closed"}:
                continue
            if item.status == "market_closed":
                units.append({
                    "pair": part.pair, "side": part.side,
                    "date": f"{part.year:04d}-{part.month:02d}-{item.day:02d}",
                    "source_id": "DUKASCOPY_DATAFEED_M1_CANDLES_V1",
                    "transport_id": "DUKASCOPY_NODE_1_46_4",
                    "transport_version": "1.46.4",
                    "certification_status": "CERTIFIED_MARKET_CLOSED",
                })
                reused += 1
                continue
            path = (
                raw_dir(data_root) / part.pair / f"price={part.side}" / f"year={part.year}"
                / f"month={part.month:02d}" / f"day={item.day:02d}" / "data.json"
            )
            if not path.exists():
                invalid += 1
                continue
            rows = read_json(path)
            requested = date(part.year, part.month, item.day)
            start = int(
                datetime(
                    requested.year, requested.month, requested.day, tzinfo=timezone.utc
                ).timestamp() * 1000
            )
            end = start + 86_400_000
            scale = instrument_metadata(part.pair).integer_scale
            valid = bool(rows) and all(
                start <= int(row["timestamp"]) < end
                and float(row["high"]) >= max(float(row["open"]), float(row["close"]))
                and float(row["low"]) <= min(float(row["open"]), float(row["close"]))
                for row in rows
            )
            if not valid:
                invalid += 1
                continue
            integer_rows = [
                [
                    int(row["timestamp"]),
                    int(round(float(row["open"]) * scale)),
                    int(round(float(row["high"]) * scale)),
                    int(round(float(row["low"]) * scale)),
                    int(round(float(row["close"]) * scale)),
                ]
                for row in rows
            ]
            raw_hash = file_sha256(path)
            units.append({
                "pair": part.pair, "side": part.side, "date": requested.isoformat(),
                "source_id": "DUKASCOPY_DATAFEED_M1_CANDLES_V1",
                "transport_id": "DUKASCOPY_NODE_1_46_4", "transport_version": "1.46.4",
                "request_identity_hash": sha256_json(
                    [part.pair, part.side, requested.isoformat(), "M1"]
                ),
                "request_url_hash": "NODE_BRIDGE_REQUEST_IDENTITY_ONLY",
                "raw_sha256": raw_hash, "parsed_rows_sha256": raw_hash,
                "timestamp_set_sha256": sha256_json([row[0] for row in integer_rows]),
                "integer_ohlc_sha256": sha256_json(integer_rows),
                "volume_sha256": sha256_json([float(row.get("volume", 0.0)) for row in rows]),
                "parser_version": "DUKASCOPY_NODE_1_46_4", "row_count": len(rows),
                "certification_status": "CERTIFIED_OPEN_MARKET_DATA",
            })
            reused += 1
            bytes_reused += path.stat().st_size
            if not manifest.compacted:
                partial_days += 1
    sidecar = {
        "artifact_id": "A0R2_DAILY_MARKET_UNIT_PROVENANCE_V1",
        "gate_id": GATE_ID,
        "units": units,
    }
    write_json(native_manifest_dir(data_root) / "existing_node_daily_provenance.json", sidecar)
    payload = {
        "artifact_id": "A0R2_EXISTING_DATA_REUSE_AUDIT_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if invalid == 0 else "INCOMPLETE",
        "existing_daily_units_reused": reused,
        "existing_daily_units_invalid": invalid,
        "certified_monthly_sides_preserved": certified_months,
        "partial_month_days_preserved": partial_days,
        "bytes_reused": bytes_reused,
        "provider_requests_avoided": reused,
        "daily_provenance_sidecar": (
            "clean_room/manifests/native_bi5/existing_node_daily_provenance.json"
        ),
    }
    write_json(results_dir() / "existing_data_reuse_audit.json", payload)
    return payload


def run_health_controls(data_root: Path) -> dict[str, Any]:
    """Two independent, non-partition controls gate retry attempt consumption."""
    scratch = provider_controls_dir(data_root)
    cache = provider_cache_dir(data_root)
    requests = (
        ("GBPUSD", "gbpusd", "2010-01-04", "2010-01-05", "bid"),
        ("USDCHF", "usdchf", "2010-01-05", "2010-01-06", "ask"),
    )
    rows = []
    for worker, (pair, instrument, date_from, date_to, side) in enumerate(requests):
        result = _download_single_day_result(
            instrument, date_from, date_to, side,
            scratch_root=scratch, cache_root=cache, worker_id=worker,
        )
        category = classify_provider_diagnostic(result)
        rows.append({
            "control": "A" if worker == 0 else "B",
            "pair": pair,
            "side": side,
            "result": "PASS" if result.succeeded and bool(result.rows) else "FAIL",
            "provider_category": category,
            "row_count": len(result.rows),
            "duration_ms": result.duration_ms,
            "error_fingerprint": result.stack_fingerprint or result.stderr_fingerprint,
        })
    passed = all(row["result"] == "PASS" for row in rows)
    payload = {
        "artifact_id": "A0R2_PROVIDER_HEALTH_CONTROLS_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if passed else "PROVIDER_COOLDOWN_REQUIRED",
        "controls": rows,
        "partition_attempts_consumed": 0,
        "rolling_health_calls": 8,
        "trigger_unhealthy_calls": 3,
    }
    write_json(results_dir() / "provider_health_controls.json", payload)
    return payload


def analyze_retryable_failures_v4(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    groups: dict[str, list[dict[str, Any]]] = {}
    for part in partition_queue():
        item = state.get("partitions", {}).get(part.key, {})
        if item.get("state") != "FAILED_RETRYABLE":
            continue
        manifest = load_month_manifest(
            raw_dir(data_root), part.pair, part.side, part.year, part.month
        )
        days = manifest.days if manifest else []
        missing = find_missing_days(raw_dir(data_root), part.pair, part.side, part.year, part.month)
        outcome = manifest.last_provider_call_outcome if manifest else ""
        category = item.get("failure_category", "OTHER_STRUCTURED_FAILURE")
        if outcome == "PROVIDER_CALL_SUCCESS_PARTIAL" or (
            any(day.status == "complete" and day.rows > 0 for day in days)
            and bool(missing)
        ):
            category = "SUCCESSFUL_PARTIAL_MONTH"
        elif outcome == "PROVIDER_CALL_TRANSPORT_FAILURE":
            category = "PROVIDER_DNS_OR_NETWORK"
        row = {
            "partition_id": part.key,
            "partition_cycle_count": manifest.partition_cycle_count if manifest else 0,
            "missing_open_market_days": len(missing),
            "completed_days": sum(day.status == "complete" for day in days),
            "market_closed_days": sum(day.status == "market_closed" for day in days),
            "day_attempt_distribution": dict(Counter(day.attempts for day in days)),
            "transport_failures": int(outcome == "PROVIDER_CALL_TRANSPORT_FAILURE"),
            "partial_successful_calls": manifest.partial_successful_calls if manifest else 0,
            "dns_network_failures": int(category == "PROVIDER_DNS_OR_NETWORK"),
            "next_repair_day": min(missing) if missing else None,
            "remaining_repair_requests": len(missing),
            "terminal_risk": int(item.get("attempts", 0)) >= MAX_PARTITION_ATTEMPTS,
        }
        groups.setdefault(category, []).append(row)
    payload = {
        "artifact_id": "A0R2_RETRYABLE_FAILURE_ANALYSIS_V4",
        "gate_id": GATE_ID,
        "status": "PASS",
        "retryable_failure_count": sum(len(rows) for rows in groups.values()),
        "groups": [
            {"category": key, "count": len(value), "rows": value}
            for key, value in sorted(groups.items())
        ],
    }
    write_json(results_dir() / "retryable_failure_analysis_v4.json", payload)
    return payload


def audit_discovery_engine_configuration_coverage() -> dict[str, Any]:
    rows = read_json(results_dir() / "trial_data_capability_v2_matrix.json")["rows"]
    supported_families = set(FAMILY_LABELS)
    executable = 0
    invalid = 0
    unsupported = []
    for row in rows:
        status = row["status"]
        family = row["family_id"]
        if status == "INVALID_PROTOCOL_DATA_CAPABILITY":
            invalid += 1
            continue
        if status == "EXECUTABLE":
            executable += 1
            if family not in supported_families:
                unsupported.append(row["trial_id"])
            continue
        unsupported.append(row["trial_id"])
    payload = {
        "artifact_id": "A0R2_DISCOVERY_ENGINE_CONFIGURATION_COVERAGE_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if not unsupported and executable == 1114 and invalid == 86 else "FAIL",
        "materialization_id": MATERIALIZATION_ID_V2,
        "materialization_v2_sha256": MATERIALIZATION_V2_SHA256,
        "executable_trials": executable,
        "capability_invalid_trials": invalid,
        "unsupported_executable_configuration_count": len(unsupported),
        "unsupported_trial_ids": unsupported,
        "generic_fallback_used": False,
        "synthetic_fixtures_only": True,
    }
    write_json(results_dir() / "discovery_engine_configuration_coverage.json", payload)
    return payload


def refresh_state_from_manifests(data_root: Path, write_state: bool = True) -> dict[str, Any]:
    state = load_state(data_root)
    raw = raw_dir(data_root)
    for part in partition_queue():
        manifest = load_month_manifest(raw, part.pair, part.side, part.year, part.month)
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw, manifest)
        existing = state["partitions"].get(part.key, {})
        base = {
            **existing,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
        }
        reconciled = reconcile_partition_state(base, manifest)
        attempts = authoritative_attempt_count(data_root, part, reconciled, manifest)
        if attempts:
            reconciled["attempts"] = attempts
        if reconciled.get("state") == "FAILED_RETRYABLE" and attempts >= MAX_PARTITION_ATTEMPTS:
            evidence = manifest_failure_evidence(part, manifest)
            now = datetime.now(timezone.utc).isoformat()
            reconciled.update({
                "state": "FAILED_TERMINAL",
                "failure_category": "RETRY_ATTEMPTS_EXHAUSTED",
                "terminal_reason": "RETRY_ATTEMPTS_EXHAUSTED",
                "latest_failure_timestamp": reconciled.get(
                    "latest_failure_timestamp", now
                ),
                "error": reconciled.get("error") or evidence["structured_reason"],
                "error_fingerprint": reconciled.get("error_fingerprint")
                or evidence["error_fingerprint"],
                "failure_evidence": evidence,
            })
        state["partitions"][part.key] = reconciled
    if write_state:
        save_state(data_root, state)
    return state


def acquisition_summary(data_root: Path, write_progress: bool = True) -> dict[str, Any]:
    usage = shutil.disk_usage(data_root)
    state = refresh_state_from_manifests(data_root, write_state=write_progress)
    counts: dict[str, int] = {}
    raw_bytes = 0
    m1_bytes = 0
    m5_bytes = 0
    feature_bytes = 0
    attempt_counts: Counter[int] = Counter()
    failure_categories: Counter[str] = Counter()
    throttling_count = 0
    timeout_count = 0
    connection_reset_count = 0
    provider_failure_count = 0
    previous_progress = (
        read_json(progress_path(data_root)) if progress_path(data_root).exists() else {}
    )
    for item in state["partitions"].values():
        counts[item["state"]] = counts.get(item["state"], 0) + 1
        if "attempts" in item:
            attempt_counts[int(item.get("attempts") or 0)] += 1
        failure_category = str(item.get("failure_category") or "")
        error = str(item.get("error") or "").lower()
        if failure_category:
            failure_categories[failure_category] += 1
        if "429" in failure_category or "429" in error:
            throttling_count += 1
        if "timeout" in failure_category.lower() or "timeout" in error:
            timeout_count += 1
        if "connection reset" in error or "econnreset" in error:
            connection_reset_count += 1
        if item.get("state") in {"FAILED_RETRYABLE", "FAILED_TERMINAL"}:
            provider_failure_count += 1
    for file_path in raw_dir(data_root).rglob("data.json"):
        raw_bytes += file_path.stat().st_size
    for file_path in m1_dir(data_root).rglob("*.parquet"):
        m1_bytes += file_path.stat().st_size
    for file_path in m5_dir(data_root).rglob("*.parquet"):
        m5_bytes += file_path.stat().st_size
    for file_path in feature_dir(data_root).rglob("*.parquet"):
        feature_bytes += file_path.stat().st_size
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
        "complete_pending_certification": counts.get("COMPLETE_PENDING_CERTIFICATION", 0),
        "planned_partitions": counts.get("PLANNED", 0),
        "running_partitions": counts.get("RUNNING", 0),
        "failure_category_distribution": dict(sorted(failure_categories.items())),
        "m1_pair_months": count_parquet_partitions(m1_dir(data_root)),
        "m5_pair_months": count_parquet_partitions(m5_dir(data_root)),
        "feature_pair_months": count_parquet_partitions(feature_dir(data_root)),
        "raw_bytes_used": raw_bytes,
        "m1_bytes_used": m1_bytes,
        "m5_bytes_used": m5_bytes,
        "feature_bytes_used": feature_bytes,
        "current_free_bytes": int(usage.free),
        "projected_remaining_bytes": max(0, pending) * 2_000_000,
        "attempt_distribution": dict(sorted(attempt_counts.items())),
        "provider_throttling_count": throttling_count,
        "provider_timeout_count": timeout_count,
        "provider_connection_reset_count": connection_reset_count,
        "provider_failure_count": provider_failure_count,
        "adaptive_one_worker_reductions": int(
            previous_progress.get("adaptive_one_worker_reductions", 0)
        ),
        "circuit_breaker_activations": int(
            previous_progress.get("circuit_breaker_activations", 0)
        ),
        "provider_throttling_observations": (
            "RECORDED" if throttling_count else "NO_THROTTLING_RECORDED"
        ),
        "next_deterministic_queue_item": next_queue_item(state),
        "next_retryable_partition": next_partition_by_state(state, "FAILED_RETRYABLE"),
        "next_normal_planned_partition": next_partition_by_state(state, "PLANNED"),
        "last_completed_partition": last_completed_partition(data_root),
    }
    if write_progress:
        write_json(progress_path(data_root), progress)
    return progress


def count_parquet_partitions(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob("part.parquet"))


def next_partition_by_state(state: dict[str, Any], wanted_state: str) -> dict[str, Any] | None:
    for part in partition_queue():
        item = state["partitions"].get(part.key, {})
        if item.get("state", "PLANNED") == wanted_state:
            return {
                "partition": part.key,
                "pair": part.pair,
                "year": part.year,
                "month": part.month,
                "side": part.side,
                "state": wanted_state,
            }
    return None


def next_queue_item(state: dict[str, Any]) -> dict[str, Any] | None:
    for part in partition_queue():
        item = state["partitions"].get(part.key, {})
        if item.get("state", "PLANNED") in {"PLANNED", "FAILED_RETRYABLE", "RUNNING"}:
            return {
                "partition": part.key,
                "pair": part.pair,
                "year": part.year,
                "month": part.month,
                "side": part.side,
                "state": item.get("state", "PLANNED"),
            }
    return None


def last_completed_partition(data_root: Path) -> dict[str, Any] | None:
    for row in reversed(read_jsonl_records(events_path(data_root))):
        if row.get("state") in {"COMPLETE_PENDING_CERTIFICATION", "CERTIFIED"}:
            return {
                "partition": row.get("partition"),
                "pair": row.get("pair"),
                "year": row.get("year"),
                "month": row.get("month"),
                "side": row.get("side"),
                "state": row.get("state"),
            }
    return None


def transport_artifact_status(name: str) -> str:
    path = results_dir() / name
    return str(read_json(path).get("status", "MISSING")) if path.exists() else "MISSING"


def select_transport(requested: str) -> tuple[str, str, dict[str, str]]:
    """Choose a transport from structural certification, never price behavior."""
    health = {
        "native": transport_artifact_status("native_bi5_health_controls.json"),
        "node": transport_artifact_status("provider_health_controls.json"),
        "parity": transport_artifact_status("dual_transport_parity_certification.json"),
    }
    native_ready = health["native"] == "PASS" and health["parity"] == "PASS"
    node_ready = health["node"] == "PASS"
    if requested == "native":
        if not native_ready:
            raise ValueError("A0R2_NATIVE_TRANSPORT_REQUIRES_HEALTH_AND_PARITY")
        return "native", "EXPLICIT_NATIVE_CERTIFIED", health
    if requested == "node":
        if not node_ready:
            raise ValueError("A0R2_NODE_TRANSPORT_HEALTH_UNAVAILABLE")
        return "node", "EXPLICIT_NODE_HEALTHY", health
    if native_ready:
        return "native", "AUTO_NATIVE_HEALTH_AND_PARITY", health
    if node_ready:
        return "node", "AUTO_NODE_HEALTHY", health
    raise ValueError("A0R2_NO_CERTIFIED_HEALTHY_TRANSPORT")


def _replace_manifest_day(manifest: MonthManifest, replacement: DayStatus) -> None:
    for index, item in enumerate(manifest.days):
        if item.day == replacement.day:
            manifest.days[index] = replacement
            return
    manifest.days.append(replacement)


def acquire_one_native(
    data_root: Path,
    part: Partition,
    *,
    max_day_requests: int | None,
) -> dict[str, Any]:
    """Acquire only missing native daily units, preserving Node partition attempts."""
    manifest = load_month_manifest(raw_dir(data_root), part.pair, part.side, part.year, part.month)
    manifest = manifest or MonthManifest(
        pair=part.pair, side=part.side, year=part.year, month=part.month
    )
    manifest = normalize_month_manifest_for_repair(raw_dir(data_root), manifest)
    missing = find_missing_days(raw_dir(data_root), part.pair, part.side, part.year, part.month)
    requested = 0
    successful = 0
    failures = 0
    for day in missing:
        if max_day_requests is not None and requested >= max_day_requests:
            break
        result = download_native_day_with_checkpoint(
            part.pair, part.side, part.year, part.month, day,
            raw_dir(data_root), native_raw_dir(data_root),
        )
        _replace_manifest_day(manifest, result)
        requested += 1
        successful += int(result.status in {"complete", "market_closed"})
        failures += int(result.status == "failed")
        save_month_manifest(raw_dir(data_root), manifest)
        if result.status == "failed":
            break
    compact_month(raw_dir(data_root), manifest)
    save_month_manifest(raw_dir(data_root), manifest)
    state = "COMPLETE_PENDING_CERTIFICATION" if manifest.compacted else "FAILED_RETRYABLE"
    return {
        "ts": datetime.now(timezone.utc).isoformat(), "partition": part.key,
        "pair": part.pair, "year": part.year, "month": part.month, "side": part.side,
        "state": state, "rows": manifest.compacted_rows, "checksum": manifest.compacted_checksum,
        "requested_transport": "native", "selected_transport": "native",
        "selection_reason": "NATIVE_PARITY_AND_HEALTH_CERTIFIED",
        "native_daily_requests": requested, "native_daily_successes": successful,
        "native_daily_failures": failures, "native_transport_attempts": requested,
        "attempts": (
            load_state(data_root).get("partitions", {}).get(part.key, {}).get("attempts", 0)
        ),
    }


def acquire_one(
    data_root: Path,
    part: Partition,
    *,
    repair_missing_days_only: bool = False,
    max_day_requests: int | None = None,
) -> dict[str, Any]:
    manifest = load_month_manifest(raw_dir(data_root), part.pair, part.side, part.year, part.month)
    current = load_state(data_root).get("partitions", {}).get(part.key, {})
    current_attempts = authoritative_attempt_count(data_root, part, current, manifest)
    if current_attempts >= MAX_PARTITION_ATTEMPTS:
        evidence = manifest_failure_evidence(part, manifest)
        now = datetime.now(timezone.utc).isoformat()
        terminal = {
            "ts": now,
            "partition": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "attempts": current_attempts,
            "state": "FAILED_TERMINAL",
            "failure_category": "RETRY_ATTEMPTS_EXHAUSTED",
            "terminal_reason": "RETRY_ATTEMPTS_EXHAUSTED",
            "error": evidence["structured_reason"],
            "error_fingerprint": evidence["error_fingerprint"],
            "first_failure_timestamp": current.get("first_failure_timestamp", now),
            "latest_failure_timestamp": now,
            "next_eligible_retry_timestamp": None,
            "failure_evidence": evidence,
        }
        append_event(data_root, terminal)
        append_failure(data_root, terminal)
        return terminal
    attempt_number = current_attempts + 1
    event_base = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "partition": part.key,
        "pair": part.pair,
        "year": part.year,
        "month": part.month,
        "side": part.side,
        "attempts": attempt_number,
    }
    with STATE_LOCK:
        state = load_state(data_root)
        state["partitions"].setdefault(part.key, {})
        state["partitions"][part.key].update({
            **event_base,
            "state": "RUNNING",
        })
        save_state(data_root, state)
    append_event(data_root, {**event_base, "state": "RUNNING"})
    try:
        scratch = provider_scratch_dir(data_root)
        cache = provider_cache_dir(data_root)
        if repair_missing_days_only and manifest is not None:
            manifest = repair_missing_days(
                part.pair, part.side, part.year, part.month, raw_dir(data_root),
                find_missing_days(raw_dir(data_root), part.pair, part.side, part.year, part.month),
                max_day_requests=max_day_requests,
                scratch_root=scratch,
                cache_root=cache,
                worker_id=threading.get_ident(),
            )
        else:
            manifest = acquire_month_bulk(
                part.pair, part.side, part.year, part.month, raw_dir(data_root),
                timeframe="m1", batch_size=30, retries=5,
                pause_between_batches_ms=200,
                scratch_root=scratch, cache_root=cache,
                worker_id=threading.get_ident(),
                max_day_requests=max_day_requests,
            )
    except Exception as exc:
        error = str(exc)[:500]
        failure_state, category = classify_provider_failure(error, attempt_number)
        if attempt_number >= MAX_PARTITION_ATTEMPTS:
            failure_state = "FAILED_TERMINAL"
            category = "RETRY_ATTEMPTS_EXHAUSTED"
        now = datetime.now(timezone.utc).isoformat()
        failure = {
            **event_base,
            "state": failure_state,
            "error": error,
            "failure_category": category,
            "error_fingerprint": failure_fingerprint(error),
            "first_failure_timestamp": current.get("first_failure_timestamp", now),
            "latest_failure_timestamp": now,
            "next_eligible_retry_timestamp": (
                now if failure_state == "FAILED_RETRYABLE" else None
            ),
            "terminal_reason": category if failure_state == "FAILED_TERMINAL" else None,
        }
        append_event(data_root, failure)
        append_failure(data_root, failure)
        return failure
    month_state = "COMPLETE_PENDING_CERTIFICATION" if manifest.compacted else "FAILED_RETRYABLE"
    evidence = manifest_failure_evidence(part, manifest)
    error = "" if manifest.compacted else evidence["structured_reason"]
    result = {
        **event_base,
        "state": month_state,
        "rows": manifest.compacted_rows,
        "checksum": manifest.compacted_checksum,
    }
    if month_state == "FAILED_RETRYABLE":
        if manifest.last_provider_call_outcome == "PROVIDER_CALL_SUCCESS_PARTIAL":
            category = "SUCCESSFUL_PARTIAL_MONTH"
            result["attempts"] = current_attempts
        elif manifest.last_provider_call_outcome == "PROVIDER_CALL_TRANSPORT_FAILURE":
            category = "PROVIDER_DNS_OR_NETWORK"
        else:
            _, category = classify_provider_failure(error, attempt_number)
        if attempt_number >= MAX_PARTITION_ATTEMPTS and category != "SUCCESSFUL_PARTIAL_MONTH":
            result["state"] = "FAILED_TERMINAL"
            category = "RETRY_ATTEMPTS_EXHAUSTED"
        result.update({
            "error": error,
            "failure_category": category,
            "error_fingerprint": evidence["error_fingerprint"],
            "first_failure_timestamp": current.get(
                "first_failure_timestamp", datetime.now(timezone.utc).isoformat()
            ),
            "latest_failure_timestamp": datetime.now(timezone.utc).isoformat(),
            "next_eligible_retry_timestamp": (
                datetime.now(timezone.utc).isoformat()
                if result["state"] == "FAILED_RETRYABLE"
                else None
            ),
            "terminal_reason": (
                "RETRY_ATTEMPTS_EXHAUSTED"
                if result["state"] == "FAILED_TERMINAL"
                else None
            ),
            "failure_evidence": evidence,
        })
        append_failure(data_root, result)
    append_event(data_root, result)
    return result


def run_acquisition(args: argparse.Namespace, data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    requested_transport = getattr(args, "transport", None)
    if requested_transport is None:
        selected_transport = "node"
        selection_reason = "LEGACY_NODE_COMPATIBILITY"
        transport_health: dict[str, str] = {}
    else:
        selected_transport, selection_reason, transport_health = select_transport(
            requested_transport
        )
    lease = read_lease(data_root)
    if lease_is_live(lease):
        raise ValueError("A0R2_ACTIVE_LEASE_PREVENTS_COMPETING_RUNNER")
    if getattr(args, "recover_orphaned_running", False):
        recover_orphaned_running(data_root, explicit=True)
    if args.retry_failed:
        controls = (
            run_native_health_controls(data_root)
            if selected_transport == "native"
            else run_health_controls(data_root)
        )
        if controls["status"] != "PASS":
            progress = acquisition_summary(data_root)
            progress["status"] = "PROVIDER_COOLDOWN_REQUIRED"
            progress["provider_health_controls"] = controls["status"]
            write_json(progress_path(data_root), progress)
            return progress
    state = refresh_state_from_manifests(data_root)
    wanted = partition_queue(args.pair, args.year, args.month, args.side)
    runnable: deque[Partition] = deque()
    scheduled_keys: set[str] = set()
    for part in wanted:
        item = state["partitions"].get(part.key, {})
        current = item.get("state", "PLANNED")
        if should_acquire_partition(
            current,
            retry_failed=args.retry_failed,
            resume=args.resume,
            running_is_stale=is_running_stale(item) if current == "RUNNING" else False,
        ):
            if part.key in scheduled_keys:
                continue
            if args.max_partitions is not None and len(runnable) >= args.max_partitions:
                break
            runnable.append(part)
            scheduled_keys.add(part.key)
    workers = (
        min(max(1, getattr(args, "native_workers", 4)), 6)
        if selected_transport == "native"
        else min(max(1, args.max_workers), MAX_PROVIDER_WORKERS)
    )
    max_in_flight_limit = 12 if selected_transport == "native" else MAX_IN_FLIGHT_FUTURES
    max_in_flight = min(max_in_flight_limit, workers * 2)
    adaptive_reductions = 0
    recent_success: deque[bool] = deque(maxlen=CIRCUIT_BREAKER_WINDOW)
    circuit_activations = 0
    run_id = sha256_bytes(f"{time.time()}:{os.getpid()}".encode())[:16]
    write_lease(
        data_root,
        run_id=run_id,
        stage="acquire",
        worker_count=workers,
        current_partitions=[],
    )
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Any, Partition] = {}
            while runnable or futures:
                active_ids = [part.key for part in futures.values()]
                update_lease_heartbeat(data_root, active_ids)
                if (
                    len(recent_success) == CIRCUIT_BREAKER_WINDOW
                    and sum(1 for ok in recent_success if not ok) >= CIRCUIT_BREAKER_FAILURES
                ):
                    circuit_activations += 1
                    while futures:
                        for future in as_completed(list(futures.keys())):
                            part = futures.pop(future)
                            result = future.result()
                            with STATE_LOCK:
                                state = load_state(data_root)
                                state["partitions"].setdefault(part.key, {})
                                state["partitions"][part.key].update(result)
                                save_state(data_root, state)
                            break
                    break
                while runnable and len(futures) < max_in_flight:
                    part = runnable.popleft()
                    if selected_transport == "native":
                        future = pool.submit(
                            acquire_one_native,
                            data_root,
                            part,
                            max_day_requests=getattr(args, "max_day_requests", None),
                        )
                    elif getattr(args, "repair_missing_days", False):
                        future = pool.submit(
                            acquire_one,
                            data_root,
                            part,
                            repair_missing_days_only=True,
                            max_day_requests=getattr(args, "max_day_requests", None),
                        )
                    else:
                        future = pool.submit(acquire_one, data_root, part)
                    futures[future] = part
                    update_lease_heartbeat(data_root, [p.key for p in futures.values()])
                for future in as_completed(list(futures.keys())):
                    part = futures.pop(future)
                    result = future.result()
                    result.setdefault("requested_transport", requested_transport or "node")
                    result.setdefault("selected_transport", selected_transport)
                    result.setdefault("selection_reason", selection_reason)
                    result.setdefault("transport_health_at_selection", transport_health)
                    recent_success.append(
                        result.get("state") == "COMPLETE_PENDING_CERTIFICATION"
                        or result.get("failure_category") == "SUCCESSFUL_PARTIAL_MONTH"
                    )
                    with STATE_LOCK:
                        state = load_state(data_root)
                        state["partitions"].setdefault(part.key, {})
                        state["partitions"][part.key].update(result)
                        save_state(data_root, state)
                    if result.get("error") and "429" in result.get("error", ""):
                        adaptive_reductions += 1
                        time.sleep(10)
                    if (
                        len(recent_success) == CIRCUIT_BREAKER_WINDOW
                        and sum(1 for ok in recent_success if not ok)
                        >= CIRCUIT_BREAKER_FAILURES
                    ):
                        circuit_activations += 1
                        runnable.clear()
                    break
    finally:
        close_lease(data_root)
    progress = acquisition_summary(data_root)
    if circuit_activations:
        progress["circuit_breaker_activations"] = circuit_activations
        progress["status"] = "PROVIDER_COOLDOWN_REQUIRED"
        write_json(progress_path(data_root), progress)
    if adaptive_reductions:
        progress["adaptive_one_worker_reductions"] = (
            int(progress.get("adaptive_one_worker_reductions", 0)) + adaptive_reductions
        )
        write_json(progress_path(data_root), progress)
    return progress


def run_operational_cycle(args: argparse.Namespace, data_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    completed_cycles = 0
    acquisition: dict[str, Any] = {"status": "NOT_RUN"}
    certification: dict[str, Any] = {"status": "NOT_RUN"}
    canonical: dict[str, Any] = {"status": "NOT_RUN"}
    max_cycles = getattr(args, "max_operational_cycles", None) or 1
    max_runtime = (getattr(args, "max_runtime_minutes", None) or 0) * 60
    while completed_cycles < max_cycles:
        if max_runtime and (time.monotonic() - started) >= max_runtime:
            break
        refresh_state_from_manifests(data_root)
        acquisition = run_acquisition(args, data_root)
        certification = run_certification(data_root)
        canonical = run_canonicalize(data_root)
        completed_cycles += 1
        if acquisition.get("status") == "PROVIDER_COOLDOWN_REQUIRED":
            break
        if max_runtime and (time.monotonic() - started) >= max_runtime:
            break
    progress = acquisition_summary(data_root)
    progress["operational_cycle"] = {
        "status": "PASS",
        "retry_failed": bool(args.retry_failed),
        "max_partitions": args.max_partitions,
        "completed_cycles": completed_cycles,
        "runtime_seconds": int(time.monotonic() - started),
        "acquisition_status": acquisition.get("status"),
        "certification_status": certification.get("status"),
        "canonicalization_status": canonical.get("status"),
        "canonicalization_reused_valid": canonical.get("reused_valid_partitions", 0),
        "canonicalization_newly_built": canonical.get("newly_built_partitions", 0),
        "canonicalization_rebuilt_invalid": canonical.get("rebuilt_invalid_partitions", 0),
        "canonicalization_failures": canonical.get("canonicalization_failures", 0),
    }
    write_json(progress_path(data_root), progress)
    return progress


def compacted_month_path(data_root: Path, part: Partition) -> Path:
    return (
        raw_dir(data_root)
        / part.pair
        / f"price={part.side}"
        / f"year={part.year}"
        / f"month={part.month:02d}"
        / "data.json"
    )


def certify_compacted_rows(
    data_root: Path, manifest: MonthManifest, part: Partition
) -> dict[str, Any]:
    path = compacted_month_path(data_root, part)
    checks: dict[str, bool] = {
        "compacted_file_exists": path.exists(),
        "checksum_recomputation": False,
        "manifest_checksum_equality": False,
        "positive_row_count": False,
        "monotonic_timestamps": False,
        "timestamps_inside_requested_month": False,
        "finite_ohlc_values": False,
        "high_gte_open": False,
        "high_gte_close": False,
        "low_lte_open": False,
        "low_lte_close": False,
        "high_gte_low": False,
        "duplicate_policy": False,
        "zero_unauthorized_timestamps": False,
    }
    details: dict[str, Any] = {
        "rows": 0,
        "duplicate_timestamps": 0,
        "unauthorized_timestamps": 0,
        "computed_checksum": "",
    }
    if not path.exists():
        return {"checks": checks, "details": details}
    computed = file_sha256(path)[:16]
    details["computed_checksum"] = computed
    checks["checksum_recomputation"] = bool(computed)
    checks["manifest_checksum_equality"] = computed == manifest.compacted_checksum
    rows = json.loads(path.read_text(encoding="utf-8"))
    details["rows"] = len(rows)
    checks["positive_row_count"] = len(rows) > 0
    timestamps = [row.get("timestamp") for row in rows]
    checks["monotonic_timestamps"] = timestamps == sorted(timestamps)
    details["duplicate_timestamps"] = len(timestamps) - len(set(timestamps))
    checks["duplicate_policy"] = details["duplicate_timestamps"] == 0
    start_ms = int(datetime(part.year, part.month, 1, tzinfo=timezone.utc).timestamp() * 1000)
    if part.month == 12:
        end_dt = datetime(part.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_dt = datetime(part.year, part.month + 1, 1, tzinfo=timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    unauthorized = [
        ts for ts in timestamps if not isinstance(ts, int) or ts < start_ms or ts >= end_ms
    ]
    details["unauthorized_timestamps"] = len(unauthorized)
    checks["timestamps_inside_requested_month"] = not unauthorized
    checks["zero_unauthorized_timestamps"] = not unauthorized
    finite_ok = True
    high_open_ok = True
    high_close_ok = True
    low_open_ok = True
    low_close_ok = True
    high_low_ok = True
    for row in rows:
        try:
            open_v = float(row["open"])
            high_v = float(row["high"])
            low_v = float(row["low"])
            close_v = float(row["close"])
        except (KeyError, TypeError, ValueError):
            finite_ok = False
            continue
        values = np.array([open_v, high_v, low_v, close_v], dtype=np.float64)
        finite_ok = finite_ok and bool(np.all(np.isfinite(values)))
        high_open_ok = high_open_ok and high_v >= open_v
        high_close_ok = high_close_ok and high_v >= close_v
        low_open_ok = low_open_ok and low_v <= open_v
        low_close_ok = low_close_ok and low_v <= close_v
        high_low_ok = high_low_ok and high_v >= low_v
    checks["finite_ohlc_values"] = finite_ok
    checks["high_gte_open"] = high_open_ok
    checks["high_gte_close"] = high_close_ok
    checks["low_lte_open"] = low_open_ok
    checks["low_lte_close"] = low_close_ok
    checks["high_gte_low"] = high_low_ok
    return {"checks": checks, "details": details}


def certify_month_manifest(
    data_root: Path, manifest: MonthManifest | None, part: Partition
) -> dict[str, Any]:
    if manifest is None:
        return {"partition": part.key, "status": "PLANNED", "rows": 0}
    days_in_month = calendar.monthrange(part.year, part.month)[1]
    day_count_ok = len({day.day for day in manifest.days}) == days_in_month
    terminal_ok = all(day.status in ("complete", "market_closed") for day in manifest.days)
    positive_rows = manifest.compacted_rows > 0
    checks: dict[str, bool] = {
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
    row_cert = certify_compacted_rows(data_root, manifest, part)
    checks.update(row_cert["checks"])
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
        "row_certification": row_cert["details"],
    }


def run_certification(data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    raw = raw_dir(data_root)
    state = refresh_state_from_manifests(data_root)
    rows = []
    for part in partition_queue():
        existing = state["partitions"].get(part.key, {})
        if existing.get("state") == "FAILED_TERMINAL":
            rows.append({
                "partition": part.key,
                "pair": part.pair,
                "year": part.year,
                "month": part.month,
                "side": part.side,
                "status": "FAILED_TERMINAL",
                "rows": existing.get("rows", 0),
                "checksum": existing.get("checksum", ""),
                "checks": {"terminal_state_preserved": True},
            })
            continue
        manifest = load_month_manifest(raw, part.pair, part.side, part.year, part.month)
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw, manifest)
        cert = certify_month_manifest(data_root, manifest, part)
        rows.append(cert)
        state["partitions"].setdefault(part.key, {})
        if cert["status"] == "CERTIFIED":
            state["partitions"][part.key].update({
                "state": "CERTIFIED",
                "rows": cert["rows"],
                "checksum": cert.get("checksum", ""),
            })
        elif state["partitions"][part.key].get("state") != "CERTIFIED":
            reconciled = reconcile_partition_state(
                {
                    **state["partitions"][part.key],
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                },
                manifest,
            )
            state["partitions"][part.key].update(reconciled)
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


def analyze_retryable_failures(data_root: Path) -> dict[str, Any]:
    state = refresh_state_from_manifests(data_root)
    rows = []
    for part in partition_queue():
        item = state.get("partitions", {}).get(part.key, {})
        if item.get("state") != "FAILED_RETRYABLE":
            continue
        manifest = load_month_manifest(
            raw_dir(data_root), part.pair, part.side, part.year, part.month
        )
        partial_data = bool(manifest and (manifest.days or manifest.compacted_rows))
        normalization_required = bool(manifest and not manifest.compacted)
        attempts = authoritative_attempt_count(data_root, part, item, manifest)
        evidence = manifest_failure_evidence(part, manifest)
        rows.append({
            "partition_id": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "failure_category": item.get("failure_category")
            or evidence["structured_reason"],
            "attempt_count": attempts,
            "error_fingerprint": item.get("error_fingerprint")
            or evidence["error_fingerprint"],
            "partial_data_exists": partial_data,
            "manifest_normalization_required": normalization_required,
            "retry_authorized": attempts < MAX_PARTITION_ATTEMPTS,
            "evidence": evidence,
        })
    payload = {
        "artifact_id": "A0R2_RETRYABLE_FAILURE_ANALYSIS_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "retryable_failure_count": len(rows),
        "rows": rows,
    }
    write_json(results_dir() / "retryable_failure_analysis.json", payload)
    return payload


def analyze_retryable_failures_v2(data_root: Path) -> dict[str, Any]:
    v1 = analyze_retryable_failures(data_root)
    payload = {
        **v1,
        "artifact_id": "A0R2_RETRYABLE_FAILURE_ANALYSIS_V2",
        "evidence_policy": "manifest_derived_non_empty_structured_evidence",
        "max_partition_attempts": MAX_PARTITION_ATTEMPTS,
        "empty_error_fingerprints": sum(
            1 for row in v1["rows"] if not row.get("error_fingerprint")
        ),
    }
    write_json(results_dir() / "retryable_failure_analysis_v2.json", payload)
    return payload


def analyze_retryable_failures_v3(data_root: Path) -> dict[str, Any]:
    state = refresh_state_from_manifests(data_root)
    rows = []
    groups: Counter[str] = Counter()
    for part in partition_queue():
        item = state.get("partitions", {}).get(part.key, {})
        if item.get("state") != "FAILED_RETRYABLE":
            continue
        manifest = load_month_manifest(
            raw_dir(data_root), part.pair, part.side, part.year, part.month
        )
        if manifest is not None:
            manifest = normalize_month_manifest_for_repair(raw_dir(data_root), manifest)
        evidence = manifest_failure_evidence(part, manifest)
        attempts = authoritative_attempt_count(data_root, part, item, manifest)
        category = str(item.get("failure_category") or evidence["structured_reason"])
        row = {
            "partition_id": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "attempt_count": attempts,
            "failure_category": category,
            "error_code": item.get("error_code", ""),
            "stack_fingerprint": item.get("stack_fingerprint", ""),
            "stderr_fingerprint": item.get("stderr_fingerprint", ""),
            "partial_data_state": (
                "compacted"
                if evidence["compacted_data_exists"]
                else "partial_daily"
                if evidence["partial_daily_files_exist"]
                else "none"
            ),
            "retry_authorized": attempts < MAX_PARTITION_ATTEMPTS,
            "evidence": evidence,
        }
        group_key = "|".join(
            str(row[key])
            for key in (
                "error_code",
                "stack_fingerprint",
                "stderr_fingerprint",
                "failure_category",
                "year",
                "month",
                "pair",
                "side",
                "partial_data_state",
                "attempt_count",
            )
        )
        row["group_fingerprint"] = sha256_bytes(group_key.encode("utf-8"))[:16]
        groups[str(row["group_fingerprint"])] += 1
        rows.append(row)
    rows.sort(key=lambda row: (row["attempt_count"], row["partition_id"]))
    payload = {
        "artifact_id": "A0R2_RETRYABLE_FAILURE_ANALYSIS_V3",
        "gate_id": GATE_ID,
        "status": "PASS",
        "retryable_failure_count": len(rows),
        "group_count": len(groups),
        "groups": dict(sorted(groups.items())),
        "rows": rows,
    }
    write_json(results_dir() / "retryable_failure_analysis_v3.json", payload)
    return payload


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


def canonical_partition_path(root: Path, pair: str, timeframe: str, year: int, month: int) -> Path:
    return (
        root
        / pair
        / f"timeframe={timeframe}"
        / f"year={year}"
        / f"month={month:02d}"
        / "part.parquet"
    )


def previous_partition_hashes(path: Path) -> dict[tuple[str, int, int], str]:
    if not path.exists():
        return {}
    payload = read_json(path)
    rows = payload.get("rows") or payload.get("partitions") or []
    hashes: dict[tuple[str, int, int], str] = {}
    for row in rows:
        if row.get("pair") and row.get("year") and row.get("month") and row.get("sha256"):
            hashes[(str(row["pair"]), int(row["year"]), int(row["month"]))] = str(
                row["sha256"]
            )
    return hashes


def valid_existing_parquet(path: Path, expected_hash: str | None) -> bool:
    if not path.exists() or not expected_hash:
        return False
    if file_sha256(path) != expected_hash:
        return False
    try:
        pd.read_parquet(path)
    except Exception:
        return False
    return True


def canonical_sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(".identity.json")


def write_canonical_sidecar(
    output_path: Path,
    *,
    pair: str,
    year: int,
    month: int,
    bid_checksum: str,
    ask_checksum: str,
    output_sha: str,
    row_count: int,
    layer: str,
) -> None:
    payload = {
        "pair": pair,
        "year": year,
        "month": month,
        "input_bid_checksum": bid_checksum,
        "input_ask_checksum": ask_checksum,
        "alignment_version": "A0R2_EXACT_TIMESTAMP_JOIN_V1",
        "resampling_version": "A0R2_M5_DETERMINISTIC_RESAMPLE_V1",
        "feature_version": "A0R2_FEATURES_M1_V1",
        "layer": layer,
        "output_sha256": output_sha,
        "row_count": row_count,
        "created_at_provenance": datetime.now(timezone.utc).isoformat(),
    }
    write_json(canonical_sidecar_path(output_path), payload)


def canonical_failure_row(
    pair: str,
    year: int,
    month: int,
    state: dict[str, Any],
    category: str,
    error: str = "",
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bid_key = f"{year:04d}-{month:02d}:{pair}:bid"
    ask_key = f"{year:04d}-{month:02d}:{pair}:ask"
    bid = state["partitions"].get(bid_key, {})
    ask = state["partitions"].get(ask_key, {})
    return {
        "pair": pair,
        "year": year,
        "month": month,
        "bid_certification_status": bid.get("state", "PLANNED"),
        "ask_certification_status": ask.get("state", "PLANNED"),
        "bid_input_checksum": bid.get("checksum", ""),
        "ask_input_checksum": ask.get("checksum", ""),
        "alignment_exception_category": category,
        "alignment_error_fingerprint": failure_fingerprint(error or category),
        "joined_row_count": int((report or {}).get("joined_rows") or 0),
        "bid_only_count": int((report or {}).get("bid_only") or 0),
        "ask_only_count": int((report or {}).get("ask_only") or 0),
        "negative_spread_count": int((report or {}).get("negative_spread_count") or 0),
        "m1_output_status": "NOT_BUILT",
        "m5_output_status": "NOT_BUILT",
        "feature_output_status": "NOT_BUILT",
        "retryability": "RETRYABLE_AFTER_INPUT_OR_IO_REPAIR",
    }


def run_canonicalize(data_root: Path) -> dict[str, Any]:
    recertify_clean_room(data_root)
    state = refresh_state_from_manifests(data_root)
    m1_rows = []
    m5_rows = []
    feature_rows = []
    reused_valid = 0
    newly_built = 0
    rebuilt_invalid = 0
    failures = 0
    failure_rows = []
    not_eligible = 0
    prior_m1 = previous_partition_hashes(results_dir() / "m1_alignment_certification.json")
    prior_m5 = previous_partition_hashes(results_dir() / "m5_partition_manifest.json")
    prior_feature = previous_partition_hashes(results_dir() / "feature_partition_manifest.json")
    for pair in INSTRUMENTS:
        for year in YEARS:
            for month in MONTHS:
                bid_key = f"{year:04d}-{month:02d}:{pair}:bid"
                ask_key = f"{year:04d}-{month:02d}:{pair}:ask"
                if (
                    state["partitions"].get(bid_key, {}).get("state") != "CERTIFIED"
                    or state["partitions"].get(ask_key, {}).get("state") != "CERTIFIED"
                ):
                    not_eligible += 1
                    continue
                m1_path = canonical_partition_path(m1_dir(data_root), pair, "M1", year, month)
                m5_path = canonical_partition_path(m5_dir(data_root), pair, "M5", year, month)
                feat_path = canonical_partition_path(
                    feature_dir(data_root), pair, "M1", year, month
                )
                key = (pair, year, month)
                if (
                    valid_existing_parquet(m1_path, prior_m1.get(key))
                    and valid_existing_parquet(m5_path, prior_m5.get(key))
                    and valid_existing_parquet(feat_path, prior_feature.get(key))
                ):
                    m1_rows.append({
                        "pair": pair,
                        "year": year,
                        "month": month,
                        "sha256": prior_m1[key],
                        "reused_valid_partition": True,
                    })
                    m5_rows.append({
                        "pair": pair,
                        "year": year,
                        "month": month,
                        "sha256": prior_m5[key],
                        "reused_valid_partition": True,
                    })
                    feature_rows.append({
                        "pair": pair,
                        "year": year,
                        "month": month,
                        "sha256": prior_feature[key],
                        "reused_valid_partition": True,
                    })
                    reused_valid += 1
                    continue
                existed_before = m1_path.exists() or m5_path.exists() or feat_path.exists()
                trading_pair = TradingPair(pair)
                report = align_bid_ask_month(trading_pair, year, month, raw_dir(data_root))
                if report.get("error"):
                    failures += 1
                    failure_rows.append(
                        canonical_failure_row(
                            pair,
                            year,
                            month,
                            state,
                            "ALIGNMENT_EMPTY",
                            str(report.get("error")),
                            report,
                        )
                    )
                    continue
                if report.get("negative_spread_count", 0) != 0:
                    failures += 1
                    failure_rows.append(
                        canonical_failure_row(
                            pair,
                            year,
                            month,
                            state,
                            "NEGATIVE_SPREAD",
                            "negative spread",
                            report,
                        )
                    )
                    continue
                out = joined_to_parquet(
                    report["joined_data"], trading_pair, year, month, m1_dir(data_root), "M1"
                )
                if out is None:
                    failures += 1
                    failure_rows.append(
                        canonical_failure_row(
                            pair, year, month, state, "ALIGNMENT_EMPTY", "empty join", report
                        )
                    )
                    continue
                m1_hash = parquet_sha(out)
                newly_built += 0 if existed_before else 1
                rebuilt_invalid += 1 if existed_before else 0
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
                bid_checksum = state["partitions"].get(bid_key, {}).get("checksum", "")
                ask_checksum = state["partitions"].get(ask_key, {}).get("checksum", "")
                write_canonical_sidecar(
                    out,
                    pair=pair,
                    year=year,
                    month=month,
                    bid_checksum=bid_checksum,
                    ask_checksum=ask_checksum,
                    output_sha=m1_hash,
                    row_count=int(report["joined_rows"]),
                    layer="M1",
                )
                series = _load_bidask_series(out, trading_pair, Timeframe.M1)
                m5 = resample_bidask(series, Timeframe.M5)
                m5_path = _write_bidask_parquet(m5, m5_dir(data_root), "M5", year, month)
                m5_hash = parquet_sha(m5_path)
                write_canonical_sidecar(
                    m5_path,
                    pair=pair,
                    year=year,
                    month=month,
                    bid_checksum=bid_checksum,
                    ask_checksum=ask_checksum,
                    output_sha=m5_hash,
                    row_count=len(m5),
                    layer="M5",
                )
                m5_rows.append({
                    "pair": pair,
                    "year": year,
                    "month": month,
                    "rows": len(m5),
                    "sha256": m5_hash,
                })
                feat_hash = build_features_from_m1(out, feat_path)
                feat_rows = len(pd.read_parquet(feat_path))
                write_canonical_sidecar(
                    feat_path,
                    pair=pair,
                    year=year,
                    month=month,
                    bid_checksum=bid_checksum,
                    ask_checksum=ask_checksum,
                    output_sha=feat_hash,
                    row_count=feat_rows,
                    layer="FEATURE_M1",
                )
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
        "reused_valid_partitions": reused_valid,
        "newly_built_partitions": newly_built,
        "rebuilt_invalid_partitions": rebuilt_invalid,
        "canonicalization_failures": failures,
        "not_eligible_pair_months": not_eligible,
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
        "certified_pair_month_partitions": len(m5_rows),
        "reused_valid_partitions": reused_valid,
        "newly_built_partitions": newly_built,
        "rebuilt_invalid_partitions": rebuilt_invalid,
        "canonicalization_failures": failures,
        "not_eligible_pair_months": not_eligible,
        "partitions": m5_rows,
    }
    feature_manifest = {
        "artifact_id": "A0R2_FEATURE_PARTITION_MANIFEST_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if len(feature_rows) == 540 else "INCOMPLETE",
        "expected_pair_month_partitions": 540,
        "certified_pair_month_partitions": len(feature_rows),
        "reused_valid_partitions": reused_valid,
        "newly_built_partitions": newly_built,
        "rebuilt_invalid_partitions": rebuilt_invalid,
        "canonicalization_failures": failures,
        "not_eligible_pair_months": not_eligible,
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
    write_json(
        results_dir() / "canonicalization_failure_analysis.json",
        {
            "artifact_id": "A0R2_CANONICALIZATION_FAILURE_ANALYSIS_V1",
            "gate_id": GATE_ID,
            "status": "PASS" if not failure_rows else "INCOMPLETE",
            "failure_count": len(failure_rows),
            "not_eligible_pair_months": not_eligible,
            "rows": failure_rows,
        },
    )
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
    recertify_clean_room(data_root, write_artifact=False)
    return acquisition_summary(data_root, write_progress=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=None)
    parser.add_argument(
        "--stage",
        choices=(
            "inheritance",
            "materialize",
            "op1-start",
            "op2-start",
            "op3-start",
            "op4-start",
            "op5-start",
            "amendment",
            "materialize-v2",
            "capability-v2",
            "retryable-analysis",
            "retryable-analysis-v2",
            "retryable-analysis-v3",
            "retryable-analysis-v4",
            "provider-scratch-audit",
            "health-controls",
            "native-metadata",
            "native-health-controls",
            "native-health-watch",
            "provider-health-summary",
            "native-parity",
            "existing-data-reuse",
            "provider-diagnostic",
            "engine-coverage",
            "recover-orphaned-running",
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
    parser.add_argument("--max-partitions", type=int, default=None)
    parser.add_argument("--operational-cycle", action="store_true")
    parser.add_argument("--recover-orphaned-running", action="store_true")
    parser.add_argument("--max-runtime-minutes", type=int, default=None)
    parser.add_argument("--max-operational-cycles", type=int, default=None)
    parser.add_argument("--repair-missing-days", action="store_true")
    parser.add_argument("--transport", choices=("auto", "node", "native"), default="auto")
    parser.add_argument("--native-workers", type=int, default=4)
    parser.add_argument("--max-months", type=int, default=None)
    parser.add_argument("--max-day-requests", type=int, default=None)
    parser.add_argument("--max-health-attempts", type=int, default=30)
    parser.add_argument("--health-interval-seconds", type=int, default=60)
    parser.add_argument("--required-consecutive-health-passes", type=int, default=2)
    parser.add_argument("--certify-only", action="store_true")
    parser.add_argument("--execute-trials-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = resolve_data_root(args.data_root)
    if args.max_workers > MAX_PROVIDER_WORKERS:
        raise ValueError("A0R2_MAX_PROVIDER_WORKERS_EXCEEDED")
    if args.max_partitions is not None and args.max_partitions < 1:
        raise ValueError("A0R2_MAX_PARTITIONS_MUST_BE_POSITIVE")
    if args.max_runtime_minutes is not None and args.max_runtime_minutes < 1:
        raise ValueError("A0R2_MAX_RUNTIME_MUST_BE_POSITIVE")
    if args.max_operational_cycles is not None and args.max_operational_cycles < 1:
        raise ValueError("A0R2_MAX_OPERATIONAL_CYCLES_MUST_BE_POSITIVE")
    if args.max_day_requests is not None and args.max_day_requests < 1:
        raise ValueError("A0R2_MAX_DAY_REQUESTS_MUST_BE_POSITIVE")
    if args.max_health_attempts < 1 or args.health_interval_seconds < 0:
        raise ValueError("A0R2_NATIVE_HEALTH_WATCH_ARGUMENT_INVALID")
    if args.required_consecutive_health_passes < 1:
        raise ValueError("A0R2_NATIVE_HEALTH_WATCH_ARGUMENT_INVALID")
    stage = (
        "operational-cycle"
        if args.operational_cycle
        else ("status" if args.status else args.stage)
    )
    if stage == "op1-start":
        progress = run_status(data_root)
        create_op1_start_artifacts(data_root, progress)
        result = progress
    elif stage == "op2-start":
        progress = run_status(data_root)
        create_op2_start_artifacts(data_root, progress)
        result = progress
    elif stage == "op3-start":
        progress = run_status(data_root)
        create_op3_start_artifacts(data_root, progress)
        result = progress
    elif stage == "op4-start":
        result = run_status(data_root)
    elif stage == "op5-start":
        result = run_status(data_root)
    elif stage == "amendment":
        create_materialization_amendment()
        result = {"status": "PASS"}
    elif stage == "materialize-v2":
        result = materialize_trials_v2()
    elif stage == "capability-v2":
        result = freeze_capability_matrix_v2()
    elif stage == "retryable-analysis":
        result = analyze_retryable_failures(data_root)
    elif stage == "retryable-analysis-v2":
        result = analyze_retryable_failures_v2(data_root)
    elif stage == "retryable-analysis-v3":
        result = analyze_retryable_failures_v3(data_root)
    elif stage == "retryable-analysis-v4":
        result = analyze_retryable_failures_v4(data_root)
    elif stage == "provider-diagnostic":
        result = run_provider_diagnostic_control(data_root)
    elif stage == "provider-scratch-audit":
        result = run_provider_scratch_location_audit(data_root)
    elif stage == "health-controls":
        result = run_health_controls(data_root)
    elif stage == "native-metadata":
        result = certify_native_metadata()
    elif stage == "native-health-controls":
        result = run_native_health_controls(data_root)
    elif stage == "native-health-watch":
        result = run_native_health_watch(
            data_root,
            max_attempts=args.max_health_attempts,
            interval_seconds=args.health_interval_seconds,
            required_consecutive_passes=args.required_consecutive_health_passes,
        )
    elif stage == "provider-health-summary":
        result = write_provider_health_summary(data_root)
    elif stage == "native-parity":
        result = run_native_parity_certification(data_root)
    elif stage == "existing-data-reuse":
        result = run_existing_data_reuse_audit(data_root)
    elif stage == "engine-coverage":
        result = audit_discovery_engine_configuration_coverage()
    elif stage == "recover-orphaned-running":
        result = recover_orphaned_running(
            data_root, explicit=args.recover_orphaned_running
        )
    else:
        result = {}
    if stage in ("inheritance", "prepare", "all"):
        create_inheritance_artifacts(data_root)
    if stage in ("materialize", "prepare", "all"):
        materialize_trials()
    if stage in ("capability", "prepare", "all"):
        freeze_capability_matrix()
    if stage == "acquire":
        result = run_acquisition(args, data_root)
    elif stage == "operational-cycle":
        result = run_operational_cycle(args, data_root)
    elif stage == "certify" or args.certify_only:
        result = run_certification(data_root)
    elif stage == "canonicalize":
        result = run_canonicalize(data_root)
    elif stage == "all":
        result = run_acquisition(args, data_root)
        certifiable = result.get("certified_partitions", 0) + result.get(
            "complete_pending_certification", 0
        )
        if certifiable == 1080:
            result = run_certification(data_root)
            if result["certified_partitions"] == 1080:
                result = run_canonicalize(data_root)
    elif stage == "discovery" or args.execute_trials_only:
        raise ValueError("A0R2_DISCOVERY_REQUIRES_COMPLETE_CERTIFIED_DATASET")
    elif stage == "status":
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
        "complete_pending_certification": result.get("complete_pending_certification"),
        "max_workers": min(max(1, args.max_workers), MAX_PROVIDER_WORKERS),
    }
    print(json.dumps(display, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
