"""Gate A0-R1 clean-room bootstrap and preregistration runner.

This runner is intentionally conservative. It resolves and certifies the A0R1
clean room, freezes storage, trial and request plans, and refuses implicit
repository-local market data fallbacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


GATE_ID = "A0R1_CLEAN_ROOM_AND_EMPIRICAL_DISCOVERY_V1"
PROGRAM_ID = "FX_INTRADAY_ALPHA_DISCOVERY_V1"
LINEAGE_ID = "FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1"
STARTING_SHA = "c9221477bbe74142a81efe554e1868cfca32871d"
CLEAN_ROOM_ID = "FX_A0R1_CLEAN_ROOM_V1"
LOCK_ID = "A0R1_EXACT_SCIENTIFIC_PROTOCOL_INHERITANCE_V1"

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
FAMILIES = (
    "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
    "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION",
    "F03_VOLATILITY_BREAKOUT",
    "F04_LIQUIDITY_SHOCK_REVERSAL",
    "F05_SPREAD_AWARE_EXECUTION_GATING",
    "F06_CROSS_PAIR_LEAD_LAG",
    "F07_CURRENCY_FACTOR_RESIDUALS",
    "F08_TRIANGULAR_CONSISTENCY_RESIDUALS",
    "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL",
    "F10_INTRADAY_SEASONALITY",
    "F11_REGIME_CONDITIONED_TREND_REVERSAL",
    "F12_COST_SENSITIVE_ML_ABSTENTION",
)
SUBDIRS = (
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


@dataclass(frozen=True)
class CleanRoomInfo:
    root: Path
    path_hash: str
    identity_hash: str
    free_bytes: int
    collision_result: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def default_data_root() -> Path:
    root = repo_root()
    return root.parent / "FX-smc-bot-local-data" / "a0_intraday_discovery_v1_c922147"


def resolve_data_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_value = os.environ.get("FX_A0_DATA_ROOT")
    if env_value:
        return Path(env_value).expanduser().resolve()
    raise ValueError("FX_A0_DATA_ROOT_NOT_CONFIGURED_AND_NO_EXPLICIT_DATA_ROOT")


def assert_root_is_outside_repo(data_root: Path) -> None:
    root = repo_root().resolve()
    resolved = data_root.resolve()
    if resolved == root:
        raise ValueError("DATA_ROOT_EQUALS_REPOSITORY")
    if root in resolved.parents:
        raise ValueError("DATA_ROOT_INSIDE_REPOSITORY")
    if resolved in root.parents:
        raise ValueError("DATA_ROOT_ANCESTOR_OF_REPOSITORY")


def expected_identity() -> dict[str, Any]:
    return {
        "clean_room_id": CLEAN_ROOM_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "starting_sha": STARTING_SHA,
        "authorized_first_date": "2010-01-01",
        "initially_authorized_last_date": "2014-12-31",
        "authorized_instruments": list(INSTRUMENTS),
        "NZD_authorized": False,
        "years_2023_2025_authorized": False,
        "empirical_outcomes_created": False,
    }


def certify_or_create_clean_room(data_root: Path) -> CleanRoomInfo:
    assert_root_is_outside_repo(data_root)
    identity_path = data_root / ".clean_room_identity.json"
    allowed = {".clean_room_identity.json", *SUBDIRS}
    collision_result = "ABSENT_CREATED"
    if data_root.exists():
        unknown = [item.name for item in data_root.iterdir() if item.name not in allowed]
        if unknown:
            raise ValueError("A0R1_CLEAN_ROOM_COLLISION_UNKNOWN_FILES")
        collision_result = "EXISTS_EMPTY_OR_COMPATIBLE"
        if identity_path.exists():
            existing = read_json(identity_path)
            if (
                existing.get("clean_room_id") != CLEAN_ROOM_ID
                or existing.get("starting_sha") != STARTING_SHA
                or existing.get("program_id") != PROGRAM_ID
            ):
                raise ValueError("A0R1_CLEAN_ROOM_COLLISION_INCOMPATIBLE_IDENTITY")
            if existing.get("empirical_outcomes_created") not in (False, None):
                raise ValueError("A0R1_CLEAN_ROOM_COLLISION_EMPIRICAL_OUTCOMES")
            collision_result = "EXISTS_COMPATIBLE_IDENTITY_NO_OUTCOMES"
    data_root.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (data_root / name).mkdir(exist_ok=True)
    if not identity_path.exists():
        write_json(identity_path, expected_identity())
    usage = shutil.disk_usage(data_root)
    return CleanRoomInfo(
        root=data_root,
        path_hash=sha256_bytes(str(data_root).encode("utf-8")),
        identity_hash=sha256_bytes(identity_path.read_bytes()),
        free_bytes=int(usage.free),
        collision_result=collision_result,
    )


def storage_budget(info: CleanRoomInfo) -> dict[str, Any]:
    gib = 1024**3
    estimates = {
        "estimated_raw_bi5_bytes": 9_500_000_000,
        "estimated_canonical_m1_bytes": 4_800_000_000,
        "estimated_canonical_m5_bytes": 1_100_000_000,
        "estimated_quote_feature_bytes": 2_400_000_000,
        "temporary_decompression_peak_bytes": 3_800_000_000,
        "model_and_outcome_scratch_bytes": 2_000_000_000,
        "manifest_overhead_bytes": 600_000_000,
    }
    estimated_peak = int(sum(estimates.values()))
    reserve = max(12 * gib, int(info.free_bytes * 0.25))
    return {
        "artifact_id": "A0R1_STORAGE_BUDGET_V1",
        "gate_id": GATE_ID,
        "status": "PASS" if estimated_peak + reserve <= info.free_bytes else "FAIL",
        "scope": {
            "start": "2010-01-01",
            "end": "2014-12-31",
            "instrument_count": len(INSTRUMENTS),
        },
        "free_bytes": info.free_bytes,
        **estimates,
        "estimated_peak_bytes": estimated_peak,
        "required_reserve_bytes": reserve,
        "estimated_peak_plus_reserve_bytes": estimated_peak + reserve,
    }


def trial_allocations() -> dict[str, int]:
    # Sums to 1200 and keeps broad families slightly larger without changing
    # the frozen scientific space.
    return {
        "F01_SESSION_OPENING_MOMENTUM_REVERSAL": 120,
        "F02_QUOTE_RUN_CONTINUATION_EXHAUSTION": 96,
        "F03_VOLATILITY_BREAKOUT": 96,
        "F04_LIQUIDITY_SHOCK_REVERSAL": 96,
        "F05_SPREAD_AWARE_EXECUTION_GATING": 84,
        "F06_CROSS_PAIR_LEAD_LAG": 120,
        "F07_CURRENCY_FACTOR_RESIDUALS": 96,
        "F08_TRIANGULAR_CONSISTENCY_RESIDUALS": 84,
        "F09_CROSS_SECTIONAL_INTRADAY_MOMENTUM_REVERSAL": 96,
        "F10_INTRADAY_SEASONALITY": 84,
        "F11_REGIME_CONDITIONED_TREND_REVERSAL": 108,
        "F12_COST_SENSITIVE_ML_ABSTENTION": 120,
    }


def planned_trials() -> list[dict[str, Any]]:
    allocations = trial_allocations()
    records: list[dict[str, Any]] = []
    seed_base = 1729
    for family_index, family_id in enumerate(FAMILIES, start=1):
        for index in range(allocations[family_id]):
            trial_id = f"A0R1-{family_index:02d}-{index + 1:04d}"
            seed = seed_base + family_index * 10_000 + index
            config = {
                "family_id": family_id,
                "index": index,
                "seed": seed,
                "stage": "DISCOVERY_2011_2014",
            }
            records.append(
                {
                    "trial_id": trial_id,
                    "family_id": family_id,
                    "configuration_hash": sha256_json(config),
                    "signal_hash": sha256_json({"signal": family_id, "index": index}),
                    "feature_set_hash": sha256_json({"features": family_id, "seed": seed}),
                    "target_hash": sha256_json({"target": "A0_FROZEN_TARGETS", "index": index % 5}),
                    "execution_contract_hash": sha256_json({"contract": "A0_INTRADAY_NO_ROLLOVER"}),
                    "cost_model_hash": sha256_json({"cost": "A0_BASE_STRESS_1_STRESS_2"}),
                    "random_seed": seed,
                    "authorized_temporal_stage": "DISCOVERY_2011_2014",
                    "parameter_neighborhood_group": f"{family_id}:N{index // 8:03d}",
                    "candidate_equivalent_weight": 1,
                    "status": "REGISTERED",
                }
            )
    return records


def write_trial_plan(results_dir: Path) -> dict[str, Any]:
    records = planned_trials()
    registry_path = results_dir / "trial_registry.jsonl"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    allocations = trial_allocations()
    allocation_payload = {
        "artifact_id": "A0R1_TRIAL_BUDGET_ALLOCATION_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "global_candidate_equivalent_budget": 1200,
        "allocations": allocations,
        "candidate_equivalent_trial_count": sum(allocations.values()),
    }
    manifest = {
        "artifact_id": "A0R1_TRIAL_PLAN_MANIFEST_V1",
        "gate_id": GATE_ID,
        "status": "PASS",
        "planned_trial_count": len(records),
        "candidate_equivalent_trial_count": sum(
            int(item["candidate_equivalent_weight"]) for item in records
        ),
        "trials_per_family": allocations,
        "model_seeds_per_family": {
            family_id: allocations[family_id] for family_id in allocations
        },
        "target_horizons_per_family": {
            family_id: [5, 15, 30, 60, 120] for family_id in allocations
        },
        "registry_sha256": sha256_bytes(registry_path.read_bytes()),
    }
    write_json(results_dir / "trial_budget_allocation.json", allocation_payload)
    write_json(results_dir / "trial_plan_manifest.json", manifest)
    return manifest


def discovery_request_plan(results_dir: Path) -> dict[str, Any]:
    months = []
    for year in range(2010, 2015):
        for month in range(1, 13):
            months.append({"year": year, "month": month})
    plan = {
        "artifact_id": "A0R1_DISCOVERY_REQUEST_PLAN_V1",
        "gate_id": GATE_ID,
        "status": "FROZEN_PRE_PROVIDER_REQUEST",
        "provider": "Dukascopy BI5 bid/ask",
        "instruments": list(INSTRUMENTS),
        "start": "2010-01-01",
        "end": "2014-12-31",
        "roles": {"2010": "warm-up only", "2011-2014": "broad discovery only"},
        "sides": ["bid", "ask"],
        "month_count": len(months),
        "instrument_month_side_partitions": len(INSTRUMENTS) * len(months) * 2,
        "prohibited": {
            "2015_onward_before_shortlist": True,
            "2023_2025": True,
            "NZD": True,
            "NZDUSD": True,
        },
    }
    write_json(results_dir / "discovery_request_plan.json", plan)
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--stage", default="bootstrap")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--pair", choices=INSTRUMENTS, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--certify-only", action="store_true")
    parser.add_argument("--register-trials-only", action="store_true")
    parser.add_argument("--execute-trials-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = resolve_data_root(args.data_root)
    info = certify_or_create_clean_room(data_root)
    results_dir = repo_root() / "results" / "gate_a0r1"
    budget = storage_budget(info)
    write_json(results_dir / "storage_budget.json", budget)
    if args.stage in {"trial-plan", "all"} or args.register_trials_only:
        write_trial_plan(results_dir)
    if args.stage in {"request-plan", "all"}:
        discovery_request_plan(results_dir)
    display = {
        "clean_room_id": CLEAN_ROOM_ID,
        "path_hash": info.path_hash,
        "free_bytes": info.free_bytes,
        "authorized_date_range": "2010-01-01..2014-12-31",
        "stage": args.stage,
        "dry_run": args.dry_run,
        "git_sha": git_sha(),
    }
    print(json.dumps(display, sort_keys=True))
    return 0 if budget["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
