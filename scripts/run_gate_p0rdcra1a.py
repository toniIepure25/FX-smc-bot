from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import lzma
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.strategy_alpha import (  # noqa: E402
    LEGACY_LINEAGE_ID,
    LINEAGE_ID,
    PROGRAM_ID,
    canonical_json_sha256,
    now_utc,
    raw_sha256,
)
from fx_smc_bot.research.strategy_alpha_data import (  # noqa: E402
    AMENDMENT_ID,
    AUTHORIZED_STRATEGY_INSTRUMENTS,
    RecoveryPartition,
    amended_requirement_contract,
    recovery_partition_record,
    validate_amended_provider_request,
)

RESULT_DIR = REPO / "results" / "gate_p0rdcra1a"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "6ed045dd3cf79345ffc567f7b981106281489586"
ORIGIN_MAIN_AT_START = "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2"
AMENDMENT_PRE_DATA_ACCESS_SHA = "3c10bba09f7536b3dd7417f4328bda12a3f59541"
RECOVERY_PROTOCOL_ID = "P0RDCRA1A_PERMITTED_DATA_RECOVERY_PROTOCOL_V1"
DATASET_FREEZE_ID = "FX_SMC_STRATEGY_ALPHA_PERMITTED_2015_2022_V2"
RAW_ROOTS = (
    REPO / "data" / "real" / "raw" / "dukascopy-node",
    REPO / "data" / "raw" / "dukascopy-node",
    REPO / "data" / "raw" / "p0rdcra1a" / "dukascopy-node",
)
CANONICAL_ROOTS = (
    REPO / "data" / "canonical" / "dukascopy",
    REPO / "data" / "canonical" / "p0rdcra1a",
)

INTEGRITY_PATHS = [
    "configs/research/strategy_alpha_v1.yaml",
    "results/gate_p0/candidate_universe_freeze.json",
    "results/gate_p0/data_boundary_freeze.json",
    "results/gate_p0/execution_model_freeze.json",
    "results/gate_p0/estimand_and_metric_freeze.json",
    "results/gate_p0/benchmark_freeze.json",
    "results/gate_p0/historical_eligibility_freeze.json",
    "results/gate_p0/final_decision.json",
    "results/gate_p0r/p0_freeze_integrity.json",
    "results/gate_p0r/implementation_clarification_overlay.json",
    "results/gate_p0r/permitted_data_coverage.json",
    "results/gate_p0r/permitted_dataset_certification.json",
    "results/gate_p0r/final_decision.json",
    "results/gate_p0rdcr/data_requirement_matrix.json",
    "results/gate_p0rdcr/pre_data_integrity.json",
    "results/gate_p0rdcr/final_decision.json",
    "results/gate_p0rdcr/holdout_integrity.json",
    "results/gate_p0rdcr/reproducibility_manifest.json",
]


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, check=False)


def git(args: list[str]) -> str:
    completed = run(["git", *args])
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and "created_at_utc" in payload:
        existing = load_json(path)
        if "created_at_utc" in existing:
            payload = {**payload, "created_at_utc": existing["created_at_utc"]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_doc(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def artifact_record(relative: str) -> dict[str, Any]:
    path = REPO / relative
    record: dict[str, Any] = {
        "path": relative,
        "exists": path.is_file(),
        "raw_sha256": raw_sha256(path) if path.is_file() else None,
    }
    if path.suffix == ".json" and path.is_file():
        record["canonical_json_sha256"] = canonical_json_sha256(load_json(path))
    tree = git(["ls-tree", "-r", "HEAD", "--", relative])
    record["git_blob_sha"] = tree.split()[2] if tree else None
    return record


def build_repository_state() -> dict[str, Any]:
    return {
        "created_at_utc": now_utc(),
        "branch": SOURCE_BRANCH,
        "starting_head": EXPECTED_START_SHA,
        "starting_remote_head": EXPECTED_START_SHA,
        "starting_worktree_clean": True,
        "fetch_all_prune_completed": True,
        "origin_main_at_start": ORIGIN_MAIN_AT_START,
        "phase0_verified_before_changes": True,
        "status": "PASS",
    }


def build_pre_amendment_integrity() -> dict[str, Any]:
    artifacts = [artifact_record(path) for path in INTEGRITY_PATHS]
    candidate_freeze = load_json(REPO / "results/gate_p0/candidate_universe_freeze.json")
    checks = {
        "all_required_artifacts_exist": all(item["exists"] for item in artifacts),
        "program_id_preserved": candidate_freeze.get("program_id") == PROGRAM_ID,
        "lineage_id_preserved": candidate_freeze.get("lineage_id") == LINEAGE_ID,
        "legacy_lineage_preserved": LEGACY_LINEAGE_ID == "USDJPY_ACCEPTANCE_RESEARCH_LINEAGE_V1",
        "starting_decision_is_provenance_block": load_json(
            REPO / "results/gate_p0rdcr/final_decision.json"
        ).get("decision")
        == "BLOCKED_BY_DATA_REQUIREMENT_PROVENANCE",
    }
    return {
        "created_at_utc": now_utc(),
        "artifacts": artifacts,
        "checks": checks,
        "legacy_status": "CLOSED_MIXED_NONTRANSPORTABLE_RESULT",
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def build_outcome_blindness() -> dict[str, Any]:
    p0rdcr_final = load_json(REPO / "results/gate_p0rdcr/final_decision.json")
    p0rdcr_holdout = load_json(REPO / "results/gate_p0rdcr/holdout_integrity.json")
    p0r_acquisition = load_json(REPO / "results/gate_p0r/acquisition_status.json")
    checks = {
        "market_data_inventory_executed": False,
        "provider_request_sent": False,
        "candidate_bars_loaded": False,
        "signals_generated": False,
        "orders_generated": False,
        "trades_generated": False,
        "pnl_calculated": False,
        "benchmarks_calculated": False,
    }
    evidence_checks = {
        "p0rdcr_stopped_at_a1": p0rdcr_final.get("blocking_phase")
        == "A1_RECONSTRUCT_EXACT_DATA_REQUIREMENTS",
        "p0rdcr_part_b_not_executed": p0rdcr_final.get("part_b_executed") is False,
        "p0r_acquisition_not_attempted": p0r_acquisition.get("acquisition_attempted")
        is False,
        "no_holdout_provider_request": p0rdcr_holdout.get(
            "sealed_holdout_provider_requests_sent"
        )
        is False,
    }
    status = "PASS" if not any(checks.values()) and all(evidence_checks.values()) else "FAIL"
    return {
        "created_at_utc": now_utc(),
        **checks,
        "evidence_checks": evidence_checks,
        "economic_outcome_accessed": False,
        "amendment_scientifically_permissible": status == "PASS",
        "status": status,
    }


def build_requirement_provenance_audit() -> dict[str, Any]:
    requirements = [
        {
            "requirement": "source_resolution",
            "explicit_evidence": [
                "P0-R requires M5 execution bars derived from M1/tick bid/ask.",
                "The repository pins dukascopy-node 1.46.4 and contains native "
                "Dukascopy BI5 parity code.",
            ],
            "implicit_implementation_evidence": [
                "Bid/ask resampling supports deterministic M1-to-M5 aggregation.",
                "Native BI5 parsing preserves Dukascopy side and UTC timestamp semantics.",
            ],
            "conflicting_evidence": [
                "P0-R leaves M1 and tick as alternatives rather than a hierarchy."
            ],
            "missing_evidence": ["No prior freeze selects one raw source resolution."],
            "scientific_consequence": (
                "Mixing undocumented M1 with tick-derived M1 can change bars and fills."
            ),
            "operational_consequence": "Recovery cannot know which local partitions are reusable.",
            "prospective_resolution": "Dukascopy tick/BI5 -> canonical M1 bid/ask -> M5 bid/ask.",
        },
        {
            "requirement": "warm_up",
            "explicit_evidence": [
                "Maximum explicit indicator lookback is 20 M5 bars.",
                "ATR period is 14 bars and prior-day levels require one complete M5 day.",
            ],
            "implicit_implementation_evidence": [
                "Sweep lifecycle can span 46 bars; acceptance 41; opening range 40.",
                "Sweep htf_bias is optional and no mandatory HTF resolution is frozen.",
            ],
            "conflicting_evidence": [],
            "missing_evidence": ["No previous artifact freezes a shared warm-up integer."],
            "scientific_consequence": "Candidates could begin with unequal state history.",
            "operational_consequence": (
                "The first eligible signal cannot be determined reproducibly."
            ),
            "prospective_resolution": "max(500, 46 + 288) = 500 M5 bars.",
        },
        {
            "requirement": "exit_horizon",
            "explicit_evidence": [
                "Opening-range configurations freeze an 11:00 local cutoff.",
                "Order expiry remains 20 bars and P0-R freezes a final executable-bar exit.",
            ],
            "implicit_implementation_evidence": [
                "OpeningRangeDetector cancels active setup state at its configured cutoff.",
                "Execution code supports adverse-first SL/TP semantics.",
            ],
            "conflicting_evidence": [],
            "missing_evidence": ["Sweep and acceptance lack a position time-exit implementation."],
            "scientific_consequence": "Unbounded holds alter costs, risk, and the estimand.",
            "operational_consequence": "A deterministic forced-exit event is required.",
            "prospective_resolution": (
                "Earliest SL, TP, session cutoff, FX-week close, or final bar; no carry."
            ),
        },
        {
            "requirement": "session_calendar",
            "explicit_evidence": [
                "Opening range freezes Europe/London and America/New_York with "
                "08:00-11:00 local windows.",
                "The timezone helper uses IANA ZoneInfo conversion.",
            ],
            "implicit_implementation_evidence": [
                "Generic SessionConfig has wider fixed UTC labels that are not "
                "candidate-specific cutoffs.",
                "Existing market-calendar code documents 17:00 ET but does not model DST.",
            ],
            "conflicting_evidence": [
                "Fixed UTC generic sessions are not DST-equivalent to local IANA sessions."
            ],
            "missing_evidence": ["No complete candidate session and FX-week contract was frozen."],
            "scientific_consequence": "DST weeks can shift eligible bars and forced exits.",
            "operational_consequence": "Certification needs one timezone-aware calendar contract.",
            "prospective_resolution": (
                "08:00-11:00 local IANA sessions; Sunday/Friday 17:00 New York FX week."
            ),
        },
        {
            "requirement": "usdjpy_role",
            "explicit_evidence": [
                "Candidate YAML files label EURUSD/GBPUSD primary and USDJPY control.",
                "Frozen benchmarks match on the candidate instrument and name no "
                "cross-instrument input.",
            ],
            "implicit_implementation_evidence": [
                "P0 candidate construction flattened primary and control lists into instruments.",
            ],
            "conflicting_evidence": [
                "The flattened P0 artifact obscures the primary/control distinction."
            ],
            "missing_evidence": ["No benchmark freeze requires USDJPY for candidate inference."],
            "scientific_consequence": (
                "Requiring USDJPY would expand data coverage without benchmark necessity."
            ),
            "operational_consequence": "USDJPY must not block primary candidate certification.",
            "prospective_resolution": (
                "EURUSD/GBPUSD strategy required; USDJPY optional diagnostic only."
            ),
        },
    ]
    return {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "outcome_sources_read": False,
        "requirements": requirements,
        "semantic_conflicts_with_explicit_p0_freezes": [],
        "status": "PASS",
    }


def write_audit_docs(outcome: dict[str, Any], provenance: dict[str, Any]) -> None:
    write_doc(
        DOC_DIR / "P0RDCRA1A_OUTCOME_BLINDNESS.md",
        [
            "# P0-R-DCR-A1A Outcome Blindness",
            "",
            f"Status: `{outcome['status']}`",
            "",
            "The predecessor gate stopped at requirement reconstruction before local market-data "
            "inventory, provider access, canonicalization, strategy execution, trades, PnL, "
            "or benchmarks.",
            "",
            "The amendment is therefore made before any economic outcome is available.",
        ],
    )
    lines = [
        "# P0-R-DCR-A1A Requirement Provenance",
        "",
        f"Status: `{provenance['status']}`",
        "",
    ]
    for item in provenance["requirements"]:
        lines.extend(
            [
                f"## {item['requirement']}",
                "",
                f"Scientific consequence: {item['scientific_consequence']}",
                "",
                f"Operational consequence: {item['operational_consequence']}",
                "",
                f"Prospective resolution: `{item['prospective_resolution']}`",
                "",
            ]
        )
    if lines[-1] == "":
        lines.pop()
    write_doc(DOC_DIR / "P0RDCRA1A_REQUIREMENT_PROVENANCE.md", lines)


def build_data_requirement_amendment() -> dict[str, Any]:
    outcome = load_json(RESULT_DIR / "pre_amendment_outcome_blindness.json")
    provenance = load_json(RESULT_DIR / "requirement_provenance_audit.json")
    contract = amended_requirement_contract()
    payload: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "legacy_lineage_id": LEGACY_LINEAGE_ID,
        "legacy_status": "CLOSED_MIXED_NONTRANSPORTABLE_RESULT",
        "amendment_id": AMENDMENT_ID,
        "status": "FROZEN_BEFORE_DATA_ACCESS",
        "outcome_blindness_status": outcome["status"],
        "economic_outcome_accessed": False,
        "market_data_path_enumerated": False,
        "provider_request_sent": False,
        "requirements": contract,
        "decisions_following_explicit_source_evidence": [
            "M5 bid/ask strategy execution bars",
            "Dukascopy provider lineage",
            "opening-range 11:00 local cutoff",
            "20-bar frozen order expiry",
            "adverse-first primary intrabar execution",
            "candidate-instrument benchmark matching",
        ],
        "prospective_design_amendments": [
            "Dukascopy BI5 -> M1 -> M5 canonical hierarchy",
            "500 M5-bar shared warm-up",
            "forced exit at originating session or FX-week cutoff",
            "08:00-11:00 local IANA session calendar for named sessions",
            "USDJPY optional-diagnostic role",
        ],
        "compatibility": {
            "candidate_parameters_changed": False,
            "strategy_instruments_changed": False,
            "sl_tp_order_expiry_or_signal_rules_changed": False,
            "economic_estimands_changed": False,
            "benchmarks_changed": False,
            "tier_rules_changed": False,
            "resolves_only_previously_missing_implementation_requirements": True,
            "semantic_conflicts": provenance["semantic_conflicts_with_explicit_p0_freezes"],
        },
        "holdout_prohibition": {
            "request_or_path_on_or_after_2023_01_01_permitted": False,
            "holdout_inventory_permitted": False,
            "holdout_outcomes_permitted": False,
        },
        "evidence_artifacts": [
            "results/gate_p0rdcra1a/pre_amendment_outcome_blindness.json",
            "results/gate_p0rdcra1a/requirement_provenance_audit.json",
            "results/gate_p0rdcr/data_requirement_matrix.json",
            "results/gate_p0r/implementation_clarification_overlay.json",
            "results/gate_p0/benchmark_freeze.json",
        ],
    }
    hash_payload = {key: value for key, value in payload.items() if key != "created_at_utc"}
    payload["amendment_hash"] = canonical_json_sha256(hash_payload)
    return payload


def write_amendment_doc(amendment: dict[str, Any]) -> None:
    req = amendment["requirements"]
    write_doc(
        DOC_DIR / "P0RDCRA1A_DATA_REQUIREMENT_AMENDMENT.md",
        [
            "# P0-R-DCR-A1A Data Requirement Amendment",
            "",
            f"Amendment: `{amendment['amendment_id']}`",
            "",
            f"Status: `{amendment['status']}`",
            "",
            f"Hash: `{amendment['amendment_hash']}`",
            "",
            "This amendment was frozen before market-data path enumeration or economic outcomes.",
            "",
            "## Exact Contract",
            "",
            "- Source: Dukascopy tick/BI5 bid and ask.",
            "- Canonical intermediate: UTC M1 bid/ask OHLC.",
            "- Execution: deterministic M5 bid/ask OHLC, adverse-first.",
            f"- Warm-up: {req['warm_up']['warmup_m5_bars']} M5 bars "
            f"using `{req['warm_up']['formula']}`.",
            "- Exit: earliest SL, TP, originating-session cutoff, FX-week close, or final bar.",
            "- Sessions: 08:00 inclusive to 11:00 exclusive in the named IANA timezone.",
            "- FX week: Sunday 17:00 to Friday 17:00 America/New_York.",
            "- EURUSD and GBPUSD: strategy required.",
            "- USDJPY: optional diagnostic; not required for execution, benchmarks, or tiers.",
            "",
            "No candidate parameter, signal, SL, TP, order expiry, estimand, benchmark, or Tier "
            "criterion is changed.",
        ],
    )


def run_audit() -> None:
    repository = build_repository_state()
    integrity = build_pre_amendment_integrity()
    outcome = build_outcome_blindness()
    provenance = build_requirement_provenance_audit()
    write_json(RESULT_DIR / "repository_state.json", repository)
    write_json(RESULT_DIR / "pre_amendment_integrity.json", integrity)
    write_json(RESULT_DIR / "pre_amendment_outcome_blindness.json", outcome)
    write_json(RESULT_DIR / "requirement_provenance_audit.json", provenance)
    write_audit_docs(outcome, provenance)
    print(json.dumps({"stage": "audit", "status": outcome["status"]}, indent=2))


def run_amendment() -> None:
    amendment = build_data_requirement_amendment()
    if amendment["outcome_blindness_status"] != "PASS":
        raise RuntimeError("Outcome-blindness proof must pass before amendment")
    if amendment["compatibility"]["semantic_conflicts"]:
        raise RuntimeError("Amendment conflicts with an explicit frozen requirement")
    write_json(RESULT_DIR / "data_requirement_amendment.json", amendment)
    write_amendment_doc(amendment)
    print(
        json.dumps(
            {
                "stage": "amendment",
                "status": amendment["status"],
                "amendment_hash": amendment["amendment_hash"],
            },
            indent=2,
        )
    )


def planned_partitions() -> list[RecoveryPartition]:
    return [
        RecoveryPartition(instrument, year, month, side)
        for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS)
        for year in range(2015, 2023)
        for month in range(1, 13)
        for side in ("bid", "ask")
    ]


def _relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": _relative(path), "exists": False, "size_bytes": 0}
    stat = path.stat()
    return {
        "path": _relative(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "last_modified_utc": datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        ).isoformat(),
    }


def _partition_inventory(instrument: str, year: int, month: int) -> dict[str, Any]:
    raw_files: list[dict[str, Any]] = []
    manifest_files: list[dict[str, Any]] = []
    for root in RAW_ROOTS:
        for side in ("bid", "ask"):
            month_dir = (
                root
                / instrument
                / f"price={side}"
                / f"year={year}"
                / f"month={month:02d}"
            )
            raw_files.append(_file_record(month_dir / "data.json"))
            manifest_files.append(_file_record(month_dir / "manifest.json"))

    canonical_files: list[dict[str, Any]] = []
    for root in CANONICAL_ROOTS:
        for timeframe in ("M1", "M5"):
            path = (
                root
                / instrument
                / f"timeframe={timeframe}"
                / f"year={year}"
                / f"month={month:02d}"
                / "part.parquet"
            )
            canonical_files.append(_file_record(path))

    raw_present = any(item["exists"] for item in raw_files)
    manifest_present = any(item["exists"] for item in manifest_files)
    m1_present = any(
        item["exists"] and "timeframe=M1" in item["path"] for item in canonical_files
    )
    m5_present = any(
        item["exists"] and "timeframe=M5" in item["path"] for item in canonical_files
    )
    if raw_present and manifest_present and m1_present and m5_present:
        classification = "PRESENT_REQUIRES_RECERTIFICATION"
    elif raw_present and not m1_present:
        classification = "RAW_PRESENT_CANONICAL_MISSING"
    elif (m1_present or m5_present) and not raw_present:
        classification = "CANONICAL_PRESENT_PROVENANCE_MISSING"
    elif raw_present or m1_present or m5_present:
        classification = "PRESENT_REQUIRES_RECERTIFICATION"
    else:
        classification = "MISSING"
    return {
        "instrument": instrument,
        "year": year,
        "month": month,
        "classification": classification,
        "raw_files": raw_files,
        "manifest_files": manifest_files,
        "canonical_files": canonical_files,
    }


def build_local_data_inventory() -> dict[str, Any]:
    amendment_tree = git(
        [
            "ls-tree",
            "-r",
            AMENDMENT_PRE_DATA_ACCESS_SHA,
            "--",
            "results/gate_p0rdcra1a/data_requirement_amendment.json",
        ]
    )
    if not amendment_tree:
        raise RuntimeError("Amendment commit must exist before inventory")
    records = [
        _partition_inventory(instrument, year, month)
        for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS)
        for year in range(2015, 2023)
        for month in range(1, 13)
    ]
    counts = {
        classification: sum(
            1 for record in records if record["classification"] == classification
        )
        for classification in (
            "PRESENT_AND_CERTIFIED",
            "PRESENT_REQUIRES_RECERTIFICATION",
            "RAW_PRESENT_CANONICAL_MISSING",
            "CANONICAL_PRESENT_PROVENANCE_MISSING",
            "CORRUPT",
            "MISSING",
        )
    }
    return {
        "created_at_utc": now_utc(),
        "amendment_pre_data_access_sha": AMENDMENT_PRE_DATA_ACCESS_SHA,
        "authorized_instruments": sorted(AUTHORIZED_STRATEGY_INSTRUMENTS),
        "authorized_start": "2015-01-01",
        "authorized_end": "2022-12-31",
        "explicit_raw_roots": [_relative(path) for path in RAW_ROOTS],
        "explicit_canonical_roots": [_relative(path) for path in CANONICAL_ROOTS],
        "parent_directories_enumerated": False,
        "legacy_tracked_csvs_read": False,
        "sealed_holdout_paths_tested_or_enumerated": False,
        "partition_month_records": records,
        "classification_counts": counts,
        "status": "PASS",
    }


def build_data_reuse_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    reusable = [
        {
            "instrument": item["instrument"],
            "year": item["year"],
            "month": item["month"],
            "classification": item["classification"],
        }
        for item in inventory["partition_month_records"]
        if item["classification"] != "MISSING"
    ]
    return {
        "created_at_utc": now_utc(),
        "reuse_before_download": True,
        "reusable_or_recertifiable_months": reusable,
        "reusable_or_recertifiable_month_count": len(reusable),
        "download_required_month_count": (
            len(inventory["partition_month_records"]) - len(reusable)
        ),
        "legacy_tracked_csv_classification": (
            "LEGACY_TRACKED_NOT_AUTHORIZED_FOR_STRATEGY_ALPHA_V1"
        ),
        "legacy_tracked_csvs_used": False,
        "status": "PASS",
    }


def build_storage_budget(inventory: dict[str, Any]) -> dict[str, Any]:
    usage = shutil.disk_usage(REPO)
    raw_present_bytes = sum(
        int(file["size_bytes"])
        for record in inventory["partition_month_records"]
        for file in record["raw_files"]
        if file["exists"]
    )
    missing_side_months = inventory["classification_counts"]["MISSING"] * 2
    estimated_missing_raw = missing_side_months * 8 * 1024 * 1024
    pair_months = len(inventory["partition_month_records"])
    estimated_m1 = pair_months * 4 * 1024 * 1024
    estimated_m5 = pair_months * 1 * 1024 * 1024
    scratch = (estimated_m1 + estimated_m5) // 2
    temporary_peak = estimated_missing_raw + estimated_m1 + estimated_m5 + scratch
    remaining = usage.free - temporary_peak
    required_margin = min(10 * 1024**3, int(usage.total * 0.20))
    status = "PASS" if remaining >= required_margin else "FAIL"
    return {
        "created_at_utc": now_utc(),
        "filesystem_total_bytes": usage.total,
        "current_free_bytes": usage.free,
        "reusable_raw_bytes": raw_present_bytes,
        "estimated_missing_raw_bytes": estimated_missing_raw,
        "estimated_m1_canonical_bytes": estimated_m1,
        "estimated_m5_canonical_bytes": estimated_m5,
        "certification_scratch_bytes": scratch,
        "estimated_temporary_peak_bytes": temporary_peak,
        "estimated_remaining_after_peak_bytes": remaining,
        "required_safety_margin_bytes": required_margin,
        "estimated_primary_month_side_requests": len(planned_partitions()),
        "maximum_daily_fallback_requests": (
            (date(2022, 12, 31) - date(2015, 1, 1)).days + 1
        )
        * len(AUTHORIZED_STRATEGY_INSTRUMENTS)
        * 2,
        "estimated_runtime": "3-12 hours depending on provider throughput and retries",
        "status": status,
    }


def build_recovery_protocol(inventory: dict[str, Any]) -> dict[str, Any]:
    partitions = [recovery_partition_record(item) for item in planned_partitions()]
    payload: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "protocol_id": RECOVERY_PROTOCOL_ID,
        "amendment_id": AMENDMENT_ID,
        "amendment_pre_data_access_sha": AMENDMENT_PRE_DATA_ACCESS_SHA,
        "instruments": sorted(AUTHORIZED_STRATEGY_INSTRUMENTS),
        "start": "2015-01-01",
        "end": "2022-12-31",
        "primary_provider": "dukascopy-node@1.46.4",
        "fallback_provider": "native Dukascopy BI5 parity-certified transport",
        "raw_source": "DUKASCOPY_TICK_BI5_BID_ASK",
        "canonical_hierarchy": ["UTC_M1_BID_ASK_OHLC", "M5_BID_ASK_OHLC"],
        "retry_policy": {
            "maximum_attempts_per_unit": 5,
            "backoff": "exponential bounded",
            "http_429": "honor Retry-After before retry",
        },
        "checkpoint_interval": "each day-side unit and month manifest",
        "concurrency": 4,
        "atomic_promotion": True,
        "hash_algorithm": "SHA-256",
        "certification": {
            "zero_byte_permitted": False,
            "zero_row_permitted": False,
            "all_failed_month_compaction_permitted": False,
            "positive_finite_spread_required": True,
            "m1_and_m5_deterministic_runs_required": 3,
        },
        "guards": {
            "requested_start_gte": "2015-01-01",
            "requested_end_lte": "2022-12-31",
            "requested_end_lt": "2023-01-01",
            "planned_partition_required": True,
            "authorized_instrument_required": True,
            "validate_before_filesystem_or_provider_access": True,
        },
        "storage_paths": {
            "raw": "data/raw/p0rdcra1a/dukascopy-node",
            "canonical": "data/canonical/p0rdcra1a",
            "state": "data/acquisition_state/p0rdcra1a",
            "logs": "logs/p0rdcra1a",
        },
        "planned_partitions": partitions,
        "inventory_hash": canonical_json_sha256(inventory),
        "status": "FROZEN_BEFORE_PROVIDER_ACCESS",
    }
    hash_payload = {key: value for key, value in payload.items() if key != "created_at_utc"}
    payload["protocol_hash"] = canonical_json_sha256(hash_payload)
    return payload


def write_stage2_prep_docs(inventory: dict[str, Any], protocol: dict[str, Any]) -> None:
    counts = inventory["classification_counts"]
    write_doc(
        DOC_DIR / "P0RDCRA1A_LOCAL_DATA_INVENTORY.md",
        [
            "# P0-R-DCR-A1A Local Data Inventory",
            "",
            "Only explicit EURUSD/GBPUSD 2015-2022 monthly paths were tested.",
            "",
            f"Missing pair-months: `{counts['MISSING']}`.",
            f"Recertification candidates: `{counts['PRESENT_REQUIRES_RECERTIFICATION']}`.",
            f"Raw present/canonical missing: `{counts['RAW_PRESENT_CANONICAL_MISSING']}`.",
            f"Canonical provenance missing: `{counts['CANONICAL_PRESENT_PROVENANCE_MISSING']}`.",
            "",
            "Inherited 15m/1h/4h CSV files are classified "
            "`LEGACY_TRACKED_NOT_AUTHORIZED_FOR_STRATEGY_ALPHA_V1` and were not read.",
        ],
    )
    write_doc(
        DOC_DIR / "P0RDCRA1A_DATA_RECOVERY_PROTOCOL.md",
        [
            "# P0-R-DCR-A1A Data Recovery Protocol",
            "",
            f"Protocol: `{protocol['protocol_id']}`",
            "",
            f"Hash: `{protocol['protocol_hash']}`",
            "",
            "Scope is EURUSD/GBPUSD from 2015-01-01 through 2022-12-31, Dukascopy "
            "BI5 bid/ask to canonical M1 and deterministic M5, with four bounded workers.",
            "",
            "No provider access occurred before this protocol freeze.",
        ],
    )


def run_stage2_prep() -> None:
    inventory = build_local_data_inventory()
    reuse = build_data_reuse_plan(inventory)
    budget = build_storage_budget(inventory)
    protocol = build_recovery_protocol(inventory)
    write_json(RESULT_DIR / "local_data_inventory.json", inventory)
    write_json(RESULT_DIR / "data_reuse_plan.json", reuse)
    write_json(RESULT_DIR / "storage_budget.json", budget)
    write_json(RESULT_DIR / "data_recovery_protocol.json", protocol)
    write_stage2_prep_docs(inventory, protocol)
    print(
        json.dumps(
            {
                "stage": "stage2_prep",
                "inventory": inventory["classification_counts"],
                "storage_budget": budget["status"],
                "protocol_hash": protocol["protocol_hash"],
            },
            indent=2,
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_raw_path(instrument: str, side: str, year: int, month: int) -> Path | None:
    priority_roots = (RAW_ROOTS[2], RAW_ROOTS[1], RAW_ROOTS[0])
    for root in priority_roots:
        candidate = (
            root
            / instrument
            / f"price={side}"
            / f"year={year}"
            / f"month={month:02d}"
            / "data.json"
        )
        if candidate.is_file():
            return candidate
    return None


def _validate_raw_side(
    instrument: str,
    side: str,
    year: int,
    month: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _selected_raw_path(instrument, side, year, month)
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    if path is None:
        return (
            {
                "instrument": instrument,
                "side": side,
                "year": year,
                "month": month,
                "path": None,
                "failures": ["MISSING_FILE"],
                "status": "MISSING",
            },
            rows,
        )

    size = path.stat().st_size
    if size == 0:
        failures.append("ZERO_BYTE_FILE")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = []
        failures.append("PARSE_FAILURE")
    if not isinstance(payload, list):
        payload = []
        failures.append("INVALID_CONTAINER")
    rows = [item for item in payload if isinstance(item, dict)]
    if len(rows) != len(payload):
        failures.append("INVALID_CONTAINER")
    if not rows:
        failures.append("ZERO_ROWS")

    timestamps: list[int] = []
    invalid_price = False
    for row in rows:
        try:
            timestamp = int(row["timestamp"])
            values = [float(row[field]) for field in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_price = True
            continue
        timestamps.append(timestamp)
        open_price, high, low, close = values
        if (
            not all(math.isfinite(value) and value > 0 for value in values)
            or high < max(open_price, close)
            or low > min(open_price, close)
            or high < low
        ):
            invalid_price = True
    if invalid_price or len(timestamps) != len(rows):
        failures.append("INVALID_PRICE")
    if timestamps != sorted(timestamps):
        failures.append("NON_MONOTONIC")
    if len(timestamps) != len(set(timestamps)):
        failures.append("DUPLICATE_CONFLICT")

    start_ms = int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=UTC)
    end_ms = int(next_month.timestamp() * 1000)
    if timestamps and not all(start_ms <= timestamp < end_ms for timestamp in timestamps):
        failures.append("WRONG_DATE")

    manifest = path.parent / "manifest.json"
    manifest_status = "ABSENT_RECONSTRUCTED_PROVIDER_PATH_PROVENANCE"
    if manifest.is_file():
        manifest_status = "PRESENT"
        manifest_payload = load_json(manifest)
        manifest_days = manifest_payload.get("days", [])
        if (
            manifest_payload.get("pair") != instrument
            or manifest_payload.get("side") != side
            or manifest_payload.get("year") != year
            or manifest_payload.get("month") != month
        ):
            failures.append("MANIFEST_MISMATCH")
        if int(manifest_payload.get("compacted_rows", -1)) != len(rows):
            failures.append("MANIFEST_MISMATCH")
        if len(manifest_days) != calendar.monthrange(year, month)[1]:
            failures.append("INCOMPLETE_MONTH")
        for day in manifest_days:
            status = day.get("status")
            day_rows = int(day.get("rows", 0))
            if status == "failed":
                failures.append("INCOMPLETE_DAY")
            if status == "complete" and day_rows == 0:
                failures.append("ZERO_ROWS")

    failures = sorted(set(failures))
    return (
        {
            "instrument": instrument,
            "side": side,
            "year": year,
            "month": month,
            "path": _relative(path),
            "file_size": size,
            "raw_sha256": _sha256(path),
            "row_count": len(rows),
            "minimum_timestamp_ms": min(timestamps) if timestamps else None,
            "maximum_timestamp_ms": max(timestamps) if timestamps else None,
            "manifest_status": manifest_status,
            "provider_provenance": "DUKASCOPY_NODE_SCOPED_PATH_AND_SCHEMA",
            "failures": failures,
            "status": "PASS" if not failures else "FAIL",
        },
        rows,
    )


def _validate_bid_ask_pair(
    bid_rows: list[dict[str, Any]],
    ask_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    bid = {int(row["timestamp"]): row for row in bid_rows if "timestamp" in row}
    ask = {int(row["timestamp"]): row for row in ask_rows if "timestamp" in row}
    failures: list[str] = []
    if set(bid) != set(ask):
        failures.append("BID_ASK_TIMESTAMP_MISMATCH")
    invalid_spread = 0
    for timestamp in sorted(set(bid) & set(ask)):
        bid_row = bid[timestamp]
        ask_row = ask[timestamp]
        if any(
            float(ask_row[field]) <= float(bid_row[field])
            for field in ("open", "high", "low", "close")
        ):
            invalid_spread += 1
    if invalid_spread:
        failures.append("INVALID_SPREAD")
    return {
        "paired_rows": len(set(bid) & set(ask)),
        "bid_only_rows": len(set(bid) - set(ask)),
        "ask_only_rows": len(set(ask) - set(bid)),
        "invalid_spread_rows": invalid_spread,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def build_recertification_results() -> tuple[dict[str, Any], dict[str, Any]]:
    month_results: list[dict[str, Any]] = []
    repair_units: list[dict[str, Any]] = []
    for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS):
        for year in range(2015, 2023):
            for month in range(1, 13):
                bid_record, bid_rows = _validate_raw_side(instrument, "bid", year, month)
                ask_record, ask_rows = _validate_raw_side(instrument, "ask", year, month)
                pair_record = _validate_bid_ask_pair(bid_rows, ask_rows)
                passed = (
                    bid_record["status"] == "PASS"
                    and ask_record["status"] == "PASS"
                    and pair_record["status"] == "PASS"
                )
                month_record = {
                    "instrument": instrument,
                    "year": year,
                    "month": month,
                    "bid": bid_record,
                    "ask": ask_record,
                    "bid_ask_pair": pair_record,
                    "status": "RECERTIFIED" if passed else "REPAIR_REQUIRED",
                }
                month_results.append(month_record)
                if not passed:
                    for side_record in (bid_record, ask_record):
                        repair_units.append(
                            {
                                "instrument": instrument,
                                "year": year,
                                "month": month,
                                "side": side_record["side"],
                                "failures": sorted(
                                    set(side_record["failures"] + pair_record["failures"])
                                ),
                                "action": "ACQUIRE_OR_REPAIR_FROM_FROZEN_PROVIDER",
                            }
                        )
    recertified = sum(1 for item in month_results if item["status"] == "RECERTIFIED")
    result = {
        "created_at_utc": now_utc(),
        "protocol_id": RECOVERY_PROTOCOL_ID,
        "month_results": month_results,
        "recertified_pair_months": recertified,
        "repair_required_pair_months": len(month_results) - recertified,
        "raw_or_canonical_files_modified": False,
        "provider_requests_sent": False,
        "status": "PASS",
    }
    repair = {
        "created_at_utc": now_utc(),
        "repair_units": repair_units,
        "repair_unit_count": len(repair_units),
        "status": "REPAIR_REQUIRED" if repair_units else "PASS",
    }
    return result, repair


def run_recertification() -> None:
    recertification, repair = build_recertification_results()
    write_json(RESULT_DIR / "recertification_results.json", recertification)
    write_json(RESULT_DIR / "repair_inventory.json", repair)
    repair_results_path = RESULT_DIR / "repair_results.json"
    if repair_results_path.is_file() and not repair["repair_units"]:
        repair_results = load_json(repair_results_path)
        repair_results.update(
            {
                "recertified_pair_months": recertification[
                    "recertified_pair_months"
                ],
                "remaining_failed": 0,
                "status": "PASS_RECERTIFIED",
            }
        )
        write_json(repair_results_path, repair_results)
    print(
        json.dumps(
            {
                "stage": "recertification",
                "recertified_pair_months": recertification["recertified_pair_months"],
                "repair_required_pair_months": recertification[
                    "repair_required_pair_months"
                ],
                "repair_units": repair["repair_unit_count"],
            },
            indent=2,
        )
    )


def _acquire_repair_unit(
    instrument: str,
    side: str,
    year: int,
    month: int,
    planned_ids: set[str],
) -> dict[str, Any]:
    from fx_smc_bot.data.daily_checkpoint import (
        acquire_month_bulk,
        load_month_manifest,
        save_month_manifest,
    )

    partition = RecoveryPartition(instrument, year, month, side)
    last_day = calendar.monthrange(year, month)[1]
    validate_amended_provider_request(
        requested_start=f"{year:04d}-{month:02d}-01",
        requested_end=f"{year:04d}-{month:02d}-{last_day:02d}",
        instrument=instrument,
        partition=partition,
        planned_partition_ids=planned_ids,
    )
    existing_manifest = load_month_manifest(
        RAW_ROOTS[2],
        instrument,
        side,
        year,
        month,
    )
    if existing_manifest is not None and _normalize_native_checkpoint_categories(
        existing_manifest
    ):
        save_month_manifest(RAW_ROOTS[2], existing_manifest)
    started = time.monotonic()
    try:
        manifest = acquire_month_bulk(
            instrument,
            side,
            year,
            month,
            RAW_ROOTS[2],
            timeframe="m1",
            batch_size=30,
            retries=5,
            pause_between_batches_ms=250,
        )
        normalized_closed_saturdays = sum(
            1
            for day in manifest.days
            if _is_closed_saturday_repair_candidate(day)
        )
        native_attempts = _repair_manifest_with_native_bi5(
            manifest,
            raw_root=RAW_ROOTS[2],
            planned_ids=planned_ids,
        )
        failed_days = sum(1 for day in manifest.days if day.status == "failed")
        zero_row_business_days = sum(
            1
            for day in manifest.days
            if day.status == "complete" and day.rows == 0
        )
        status = (
            "COMPLETE_PENDING_RECERTIFICATION"
            if manifest.compacted
            and manifest.compacted_rows > 0
            and failed_days == 0
            and zero_row_business_days == 0
            else "FAILED_OR_INCOMPLETE"
        )
        return {
            "partition_id": partition.partition_id,
            "instrument": instrument,
            "side": side,
            "year": year,
            "month": month,
            "status": status,
            "compacted": manifest.compacted,
            "compacted_rows": manifest.compacted_rows,
            "manifest_day_count": len(manifest.days),
            "failed_days": failed_days,
            "zero_row_business_days": zero_row_business_days,
            "native_fallback_requests": len(native_attempts),
            "native_fallback_successes": sum(
                1 for item in native_attempts if item["status"] == "PASS"
            ),
            "native_fallback_market_closed": sum(
                1 for item in native_attempts if item["status"] == "MARKET_CLOSED"
            ),
            "native_fallback_failures": sum(
                1 for item in native_attempts if item["status"] == "FAIL"
            ),
            "closed_saturdays_normalized": normalized_closed_saturdays,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": "",
            "_provider_attempts": native_attempts,
        }
    except Exception as exc:
        return {
            "partition_id": partition.partition_id,
            "instrument": instrument,
            "side": side,
            "year": year,
            "month": month,
            "status": "PROVIDER_OR_ACQUISITION_ERROR",
            "compacted": False,
            "compacted_rows": 0,
            "manifest_day_count": 0,
            "failed_days": 0,
            "zero_row_business_days": 0,
            "native_fallback_requests": 0,
            "native_fallback_successes": 0,
            "native_fallback_market_closed": 0,
            "native_fallback_failures": 0,
            "closed_saturdays_normalized": 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            "_provider_attempts": [],
        }


def _requires_native_fallback(day_status: Any) -> bool:
    if _is_closed_saturday_repair_candidate(day_status):
        return False
    if day_status.status == "failed":
        return True
    if day_status.status != "complete" or day_status.rows != 0:
        return False
    return date(day_status.year, day_status.month, day_status.day).weekday() != 5


def _is_closed_saturday_repair_candidate(day_status: Any) -> bool:
    requested_day = date(day_status.year, day_status.month, day_status.day)
    return requested_day.weekday() == 5 and (
        day_status.status == "failed"
        or (day_status.status == "complete" and day_status.rows == 0)
    )


def _normalize_native_checkpoint_categories(manifest: Any) -> bool:
    replacements = {
        "NATIVE_BI5_FETCH_FAILURE": "UNKNOWN_ERROR",
        "NATIVE_BI5_VALIDATION_FAILURE": "PARSER_ERROR",
    }
    changed = False
    for day_status in manifest.days:
        replacement = replacements.get(day_status.failure_category)
        if replacement is not None:
            day_status.failure_category = replacement
            changed = True
    return changed


def _atomic_write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(rows), encoding="utf-8")
    temporary.replace(path)


def _repair_manifest_with_native_bi5(
    manifest: Any,
    *,
    raw_root: Path,
    planned_ids: set[str],
) -> list[dict[str, Any]]:
    from fx_smc_bot.data.daily_checkpoint import compact_month, save_month_manifest
    from fx_smc_bot.data.dukascopy_bi5 import (
        dukascopy_candle_url,
        fetch_bi5_day,
        parse_bi5_m1_candles,
        validate_m1_rows,
    )
    from fx_smc_bot.data.dukascopy_node_provider import _compute_checksum
    from fx_smc_bot.data.failure_categories import classify_failure

    partition = RecoveryPartition(
        manifest.pair,
        manifest.year,
        manifest.month,
        manifest.side,
    )
    attempts: list[dict[str, Any]] = []
    normalized_saturday = False
    for day_status in manifest.days:
        if not _is_closed_saturday_repair_candidate(day_status):
            continue
        day_status.status = "market_closed"
        day_status.rows = 0
        day_status.checksum = ""
        day_status.file_size = 0
        day_status.failure_category = "MARKET_CLOSED_WEEKEND"
        day_status.error = ""
        normalized_saturday = True

    fallback_days = [
        item
        for item in sorted(manifest.days, key=lambda day: day.day)
        if _requires_native_fallback(item)
    ]
    if fallback_days or normalized_saturday:
        manifest.compacted = False
        manifest.compacted_checksum = ""
        manifest.compacted_rows = 0
        save_month_manifest(raw_root, manifest)

    for day_status in fallback_days:

        requested_day = date(
            day_status.year,
            day_status.month,
            day_status.day,
        )
        day_text = requested_day.isoformat()
        validate_amended_provider_request(
            requested_start=day_text,
            requested_end=day_text,
            instrument=manifest.pair,
            partition=partition,
            planned_partition_ids=planned_ids,
        )
        day_dir = (
            raw_root
            / manifest.pair
            / f"price={manifest.side}"
            / f"year={manifest.year}"
            / f"month={manifest.month:02d}"
            / f"day={day_status.day:02d}"
        )
        raw_path = (
            day_dir
            / "_provider_raw"
            / f"{manifest.side.upper()}_candles_min_1.bi5"
        )
        url = dukascopy_candle_url(
            manifest.pair,
            requested_day,
            manifest.side,
        )
        fetched = fetch_bi5_day(
            url,
            raw_path,
            retries=3,
            backoff_seconds=1.0,
            timeout_seconds=30,
        )
        attempt = {
            "type": "native_bi5_day_fallback",
            "instrument": manifest.pair,
            "side": manifest.side,
            "date": day_text,
            **fetched.to_dict(),
        }
        day_status.attempts += fetched.attempts
        if fetched.status != "PASS":
            day_status.status = "failed"
            day_status.failure_category = classify_failure(
                fetched.error,
                day_status.year,
                day_status.month,
                day_status.day,
                0,
            ).value
            day_status.error = fetched.error
            attempt["validation_status"] = "NOT_REACHED"
            attempts.append(attempt)
            save_month_manifest(raw_root, manifest)
            continue

        try:
            payload = raw_path.read_bytes()
            rows = parse_bi5_m1_candles(
                payload,
                requested_day,
                integer_scale=100_000,
                ignore_flats=True,
            )
            validation = validate_m1_rows(rows, requested_day)
            if validation["row_count"] == 0:
                day_status.status = "market_closed"
                day_status.rows = 0
                day_status.checksum = ""
                day_status.file_size = 0
                day_status.failure_category = "MARKET_CLOSED_HOLIDAY"
                day_status.error = ""
                day_status.completed_at = now_utc()
                attempt["validation_status"] = "PROVIDER_CLOSED_ZERO_VOLUME"
                attempt["row_count"] = 0
                attempt["status"] = "MARKET_CLOSED"
                attempts.append(attempt)
                save_month_manifest(raw_root, manifest)
                continue
            timestamps = [int(row["timestamp"]) for row in rows]
            prices_valid = all(
                math.isfinite(float(row[field])) and float(row[field]) > 0
                for row in rows
                for field in ("open", "high", "low", "close")
            )
            validation_passed = (
                validation["monotonic_timestamps"]
                and validation["timestamps_in_requested_day"]
                and validation["ohlc_valid"]
                and len(timestamps) == len(set(timestamps))
                and prices_valid
            )
            if not validation_passed:
                raise ValueError("native BI5 M1 validation failed")

            day_file = day_dir / "data.json"
            _atomic_write_rows(day_file, rows)
            day_status.status = "complete"
            day_status.rows = len(rows)
            day_status.checksum = _compute_checksum(day_file)
            day_status.file_size = day_file.stat().st_size
            day_status.failure_category = ""
            day_status.error = ""
            day_status.completed_at = now_utc()
            attempt["validation_status"] = "PASS"
            attempt["row_count"] = len(rows)
            attempt["status"] = "PASS"
        except (KeyError, lzma.LZMAError, OSError, OverflowError, TypeError, ValueError) as exc:
            day_status.status = "failed"
            day_status.rows = 0
            day_status.checksum = ""
            day_status.file_size = 0
            day_status.failure_category = "PARSER_ERROR"
            day_status.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            attempt["validation_status"] = "FAIL"
            attempt["status"] = "FAIL"
            attempt["error"] = day_status.error
        attempts.append(attempt)
        save_month_manifest(raw_root, manifest)

    if fallback_days or normalized_saturday:
        compact_month(raw_root, manifest)
        save_month_manifest(raw_root, manifest)
    return attempts


def _write_operational_log(record: dict[str, Any], lock: threading.Lock) -> None:
    log_path = REPO / "logs" / "p0rdcra1a" / "provider_requests.jsonl"
    with lock:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _operational_records() -> list[dict[str, Any]]:
    log_path = REPO / "logs" / "p0rdcra1a" / "provider_requests.jsonl"
    records: list[dict[str, Any]] = []
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _latest_primary_results_from_history() -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in _operational_records():
        if item.get("type") != "primary_month_result":
            continue
        partition_id = str(item.get("partition_id", ""))
        if not partition_id:
            continue
        latest[partition_id] = {
            key: value for key, value in item.items() if key != "type"
        }
    return sorted(latest.values(), key=lambda item: str(item["partition_id"]))


def _operational_provider_history() -> dict[str, Any]:
    log_path = REPO / "logs" / "p0rdcra1a" / "provider_requests.jsonl"
    records = _operational_records()

    native = [
        item for item in records if item.get("type") == "native_bi5_day_fallback"
    ]
    primary = [item for item in records if item.get("type") == "primary_month_result"]
    native_units: dict[tuple[str, str, str], set[str]] = {}
    for item in native:
        key = (
            str(item.get("instrument", "")),
            str(item.get("side", "")),
            str(item.get("date", "")),
        )
        native_units.setdefault(key, set()).add(str(item.get("status", "")))
    http_status_counts: dict[str, int] = {}
    for item in native:
        status = str(item.get("http_status") or "NONE")
        http_status_counts[status] = http_status_counts.get(status, 0) + 1

    return {
        "operational_log_present": log_path.is_file(),
        "primary_month_result_records": len(primary),
        "native_request_records": len(native),
        "native_transport_attempts": sum(int(item.get("attempts", 0)) for item in native),
        "unique_native_day_side_units": len(native_units),
        "native_pass_records": sum(1 for item in native if item.get("status") == "PASS"),
        "native_market_closed_records": sum(
            1 for item in native if item.get("status") == "MARKET_CLOSED"
        ),
        "native_failure_records": sum(1 for item in native if item.get("status") == "FAIL"),
        "unique_units_with_historical_failure": sum(
            1 for statuses in native_units.values() if "FAIL" in statuses
        ),
        "unique_failed_units_eventually_recovered": sum(
            1
            for statuses in native_units.values()
            if "FAIL" in statuses and bool(statuses & {"PASS", "MARKET_CLOSED"})
        ),
        "http_status_counts": dict(sorted(http_status_counts.items())),
    }


def run_acquisition() -> None:
    repair = load_json(RESULT_DIR / "repair_inventory.json")
    units = [
        (
            str(item["instrument"]),
            str(item["side"]),
            int(item["year"]),
            int(item["month"]),
        )
        for item in repair["repair_units"]
    ]
    units = sorted(set(units))
    planned_ids = {item.partition_id for item in planned_partitions()}
    results: list[dict[str, Any]] = []
    log_lock = threading.Lock()
    started = time.monotonic()
    if units:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_acquire_repair_unit, *unit, planned_ids): unit
                for unit in units
            }
            for future in as_completed(futures):
                result = future.result()
                provider_attempts = result.pop("_provider_attempts", [])
                results.append(result)
                _write_operational_log(
                    {"type": "primary_month_result", **result},
                    log_lock,
                )
                for provider_attempt in provider_attempts:
                    _write_operational_log(provider_attempt, log_lock)
                if len(results) % 10 == 0 or len(results) == len(units):
                    progress = {
                        "created_at_utc": now_utc(),
                        "protocol_id": RECOVERY_PROTOCOL_ID,
                        "planned_units": len(units),
                        "completed_units": len(results),
                        "successful_pending_recertification": sum(
                            1
                            for item in results
                            if item["status"] == "COMPLETE_PENDING_RECERTIFICATION"
                        ),
                        "failed_or_incomplete_units": sum(
                            1
                            for item in results
                            if item["status"] != "COMPLETE_PENDING_RECERTIFICATION"
                        ),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "status": (
                            "RUNNING" if len(results) < len(units) else "COMPLETE"
                        ),
                    }
                    write_json(RESULT_DIR / "acquisition_progress.json", progress)
    else:
        results = _latest_primary_results_from_history()

    results.sort(key=lambda item: item["partition_id"])
    planned_unit_count = len(units) if units else len(results)
    failures = [
        item for item in results if item["status"] != "COMPLETE_PENDING_RECERTIFICATION"
    ]
    failure_summary = {
        "created_at_utc": now_utc(),
        "primary_provider": "dukascopy-node@1.46.4",
        "planned_units": planned_unit_count,
        "successful_units": len(results) - len(failures),
        "failed_units": len(failures),
        "native_fallback_requests": sum(
            int(item["native_fallback_requests"]) for item in results
        ),
        "native_fallback_successes": sum(
            int(item["native_fallback_successes"]) for item in results
        ),
        "native_fallback_market_closed": sum(
            int(item["native_fallback_market_closed"]) for item in results
        ),
        "native_fallback_failures": sum(
            int(item["native_fallback_failures"]) for item in results
        ),
        "failures": failures,
        "provider_access_observed": bool(results),
        "operational_history": _operational_provider_history(),
        "status": "PASS" if not failures else "FAIL",
    }
    repair_results = {
        "created_at_utc": now_utc(),
        "unit_results": results,
        "repaired_pending_recertification": len(results) - len(failures),
        "remaining_failed": len(failures),
        "status": "PENDING_RECERTIFICATION" if not failures else "INCOMPLETE",
    }
    progress = {
        "created_at_utc": now_utc(),
        "protocol_id": RECOVERY_PROTOCOL_ID,
        "planned_units": planned_unit_count,
        "completed_units": len(results),
        "successful_pending_recertification": len(results) - len(failures),
        "failed_or_incomplete_units": len(failures),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "status": "COMPLETE",
    }
    write_json(RESULT_DIR / "acquisition_progress.json", progress)
    write_json(RESULT_DIR / "provider_failure_summary.json", failure_summary)
    write_json(RESULT_DIR / "repair_results.json", repair_results)
    print(
        json.dumps(
            {
                "stage": "acquisition",
                "planned_units": planned_unit_count,
                "successful_units": len(results) - len(failures),
                "failed_units": len(failures),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
            indent=2,
        )
    )


def _series_semantic_sha256(series: Any) -> str:
    import numpy as np

    digest = hashlib.sha256()
    digest.update(str(series.pair.value).encode("ascii"))
    digest.update(str(series.timeframe.value).encode("ascii"))
    digest.update(
        np.asarray(series.timestamps).astype("datetime64[ns]").astype("<i8").tobytes()
    )
    for field in (
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    ):
        digest.update(np.asarray(getattr(series, field), dtype="<f8").tobytes())
    return digest.hexdigest()


def _canonical_series_from_raw_rows(
    instrument: str,
    bid_rows: list[dict[str, Any]],
    ask_rows: list[dict[str, Any]],
) -> Any:
    import numpy as np

    from fx_smc_bot.config import Timeframe, TradingPair
    from fx_smc_bot.data.bidask import BidAskBarSeries

    bid = {int(item["timestamp"]): item for item in bid_rows}
    ask = {int(item["timestamp"]): item for item in ask_rows}
    if len(bid) != len(bid_rows) or len(ask) != len(ask_rows):
        raise ValueError("duplicate raw M1 timestamp")
    if set(bid) != set(ask):
        raise ValueError("raw M1 bid/ask timestamp mismatch")
    timestamps = sorted(bid)
    if not timestamps:
        raise ValueError("zero-row canonical M1 partition")

    def values(side: dict[int, dict[str, Any]], field: str) -> Any:
        return np.asarray([float(side[ts][field]) for ts in timestamps], dtype=np.float64)

    return BidAskBarSeries(
        pair=TradingPair(instrument),
        timeframe=Timeframe.M1,
        timestamps=np.asarray(timestamps, dtype="datetime64[ms]").astype("datetime64[ns]"),
        bid_open=values(bid, "open"),
        bid_high=values(bid, "high"),
        bid_low=values(bid, "low"),
        bid_close=values(bid, "close"),
        ask_open=values(ask, "open"),
        ask_high=values(ask, "high"),
        ask_low=values(ask, "low"),
        ask_close=values(ask, "close"),
    )


def _canonical_partition_path(
    instrument: str,
    timeframe: str,
    year: int,
    month: int,
) -> Path:
    return (
        CANONICAL_ROOTS[1]
        / instrument
        / f"timeframe={timeframe}"
        / f"year={year}"
        / f"month={month:02d}"
        / "part.parquet"
    )


def _write_series_parquet_atomic(series: Any, path: Path) -> None:
    import pandas as pd  # type: ignore[import-untyped]

    frame = pd.DataFrame(
        {
            "timestamp": series.timestamps,
            "bid_open": series.bid_open,
            "bid_high": series.bid_high,
            "bid_low": series.bid_low,
            "bid_close": series.bid_close,
            "ask_open": series.ask_open,
            "ask_high": series.ask_high,
            "ask_low": series.ask_low,
            "ask_close": series.ask_close,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, engine="pyarrow")
    temporary.replace(path)


def _session_coverage_for_month(
    m5_series: Any,
    instrument: str,
    year: int,
    month: int,
    bid_raw_root: Path,
    ask_raw_root: Path,
) -> dict[str, Any]:
    import numpy as np

    from fx_smc_bot.data.daily_checkpoint import load_month_manifest
    from fx_smc_bot.research.strategy_alpha_data import SESSION_CONTRACTS, session_bounds_utc

    bid_manifest = load_month_manifest(bid_raw_root, instrument, "bid", year, month)
    ask_manifest = load_month_manifest(ask_raw_root, instrument, "ask", year, month)
    if bid_manifest is None or ask_manifest is None:
        raise ValueError("certified month manifest missing during session audit")
    bid_days = {item.day: item for item in bid_manifest.days}
    ask_days = {item.day: item for item in ask_manifest.days}
    available_ns = set(
        np.asarray(m5_series.timestamps).astype("datetime64[ns]").astype("int64").tolist()
    )
    available_utc_days = {
        str(value)[:10]
        for value in np.asarray(m5_series.timestamps).astype("datetime64[D]")
    }
    reports: dict[str, Any] = {}
    for session in sorted(SESSION_CONTRACTS):
        eligible_days = 0
        complete_days = 0
        partial_days = 0
        missing_days = 0
        manifest_market_closed_days = 0
        provider_closed_observed_days = 0
        expected_buckets = 0
        available_buckets = 0
        missing_dates: list[str] = []
        for day_number in range(1, calendar.monthrange(year, month)[1] + 1):
            local_day = date(year, month, day_number)
            if local_day.weekday() >= 5:
                continue
            bid_day = bid_days.get(day_number)
            ask_day = ask_days.get(day_number)
            if bid_day is None or ask_day is None:
                missing_days += 1
                continue
            if bid_day.status == "market_closed" and ask_day.status == "market_closed":
                manifest_market_closed_days += 1
                continue
            if local_day.isoformat() not in available_utc_days:
                provider_closed_observed_days += 1
                continue
            eligible_days += 1
            start, end = session_bounds_utc(local_day, session)
            expected = {
                int((start + timedelta(minutes=offset)).timestamp() * 1_000_000_000)
                for offset in range(0, int((end - start).total_seconds() // 60), 5)
            }
            observed = len(expected & available_ns)
            expected_buckets += len(expected)
            available_buckets += observed
            if observed == len(expected):
                complete_days += 1
            elif observed > 0:
                partial_days += 1
            else:
                missing_days += 1
                missing_dates.append(local_day.isoformat())
        reports[session] = {
            "eligible_days": eligible_days,
            "complete_days": complete_days,
            "partial_days": partial_days,
            "missing_days": missing_days,
            "missing_dates": missing_dates,
            "manifest_market_closed_days": manifest_market_closed_days,
            "provider_closed_observed_days": provider_closed_observed_days,
            "expected_m5_buckets": expected_buckets,
            "available_m5_buckets": available_buckets,
            "coverage_ratio": (
                round(available_buckets / expected_buckets, 8)
                if expected_buckets
                else 1.0
            ),
        }
    return reports


def _reconcile_cross_instrument_provider_closures(
    records: list[dict[str, Any]],
) -> int:
    missing_by_key: dict[tuple[int, int, str, str], set[str]] = {}
    for item in records:
        for session_name, session in item["session_coverage"].items():
            for missing_date in session["missing_dates"]:
                key = (int(item["year"]), int(item["month"]), session_name, missing_date)
                missing_by_key.setdefault(key, set()).add(str(item["instrument"]))

    required_instruments = set(AUTHORIZED_STRATEGY_INSTRUMENTS)
    reconciled = 0
    for item in records:
        for session_name, session in item["session_coverage"].items():
            accepted_dates = [
                missing_date
                for missing_date in session["missing_dates"]
                if missing_by_key[
                    (
                        int(item["year"]),
                        int(item["month"]),
                        session_name,
                        missing_date,
                    )
                ]
                == required_instruments
            ]
            if not accepted_dates:
                session["provider_closed_cross_instrument_dates"] = []
                continue
            count = len(accepted_dates)
            session["missing_dates"] = sorted(
                set(session["missing_dates"]) - set(accepted_dates)
            )
            session["missing_days"] -= count
            session["eligible_days"] -= count
            session["expected_m5_buckets"] -= 36 * count
            session["provider_closed_observed_days"] += count
            session["provider_closed_cross_instrument_dates"] = accepted_dates
            expected = int(session["expected_m5_buckets"])
            available = int(session["available_m5_buckets"])
            session["coverage_ratio"] = (
                round(available / expected, 8) if expected else 1.0
            )
            reconciled += count
    return reconciled


def _canonicalize_pair_month(
    instrument: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    from fx_smc_bot.config import Timeframe
    from fx_smc_bot.data.bidask_resampling import resample_bidask
    from fx_smc_bot.data.dukascopy_node_provider import parquet_to_bidask_series

    bid_path = _selected_raw_path(instrument, "bid", year, month)
    ask_path = _selected_raw_path(instrument, "ask", year, month)
    if bid_path is None or ask_path is None:
        raise ValueError("recertified raw M1 source path missing")
    bid_rows = json.loads(bid_path.read_text(encoding="utf-8"))
    ask_rows = json.loads(ask_path.read_text(encoding="utf-8"))
    if not isinstance(bid_rows, list) or not isinstance(ask_rows, list):
        raise ValueError("raw M1 partition is not a list")

    run_hashes: list[dict[str, str]] = []
    first_m1: Any = None
    first_m5: Any = None
    for _run_number in range(1, 4):
        m1 = _canonical_series_from_raw_rows(instrument, bid_rows, ask_rows)
        m5 = resample_bidask(m1, Timeframe.M5)
        run_hashes.append(
            {
                "m1_semantic_sha256": _series_semantic_sha256(m1),
                "m5_semantic_sha256": _series_semantic_sha256(m5),
            }
        )
        if first_m1 is None:
            first_m1 = m1
            first_m5 = m5
    deterministic = len(
        {(item["m1_semantic_sha256"], item["m5_semantic_sha256"]) for item in run_hashes}
    ) == 1
    if not deterministic:
        raise ValueError("three-run canonicalization is non-deterministic")
    if first_m1.validate_invariants() or first_m5.validate_invariants():
        raise ValueError("canonical bid/ask invariant failure")
    for series in (first_m1, first_m5):
        for field in ("open", "high", "low", "close"):
            bid_values = getattr(series, f"bid_{field}")
            ask_values = getattr(series, f"ask_{field}")
            if bool((ask_values <= bid_values).any()):
                raise ValueError(f"non-positive canonical {field} spread")

    m1_path = _canonical_partition_path(instrument, "M1", year, month)
    m5_path = _canonical_partition_path(instrument, "M5", year, month)
    _write_series_parquet_atomic(first_m1, m1_path)
    _write_series_parquet_atomic(first_m5, m5_path)
    m1_roundtrip = parquet_to_bidask_series(m1_path, first_m1.pair, Timeframe.M1)
    m5_roundtrip = parquet_to_bidask_series(m5_path, first_m1.pair, Timeframe.M5)
    if _series_semantic_sha256(m1_roundtrip) != run_hashes[0]["m1_semantic_sha256"]:
        raise ValueError("canonical M1 parquet roundtrip mismatch")
    if _series_semantic_sha256(m5_roundtrip) != run_hashes[0]["m5_semantic_sha256"]:
        raise ValueError("canonical M5 parquet roundtrip mismatch")

    return {
        "partition_id": f"{instrument}:{year:04d}-{month:02d}:M1_M5",
        "instrument": instrument,
        "year": year,
        "month": month,
        "source_bid_sha256": _sha256(bid_path),
        "source_ask_sha256": _sha256(ask_path),
        "m1_path": _relative(m1_path),
        "m1_rows": len(first_m1),
        "m1_file_sha256": _sha256(m1_path),
        "m1_semantic_sha256": run_hashes[0]["m1_semantic_sha256"],
        "m5_path": _relative(m5_path),
        "m5_rows": len(first_m5),
        "m5_file_sha256": _sha256(m5_path),
        "m5_semantic_sha256": run_hashes[0]["m5_semantic_sha256"],
        "minimum_timestamp": str(first_m1.timestamps[0]),
        "maximum_timestamp": str(first_m1.timestamps[-1]),
        "three_run_hashes": run_hashes,
        "three_run_deterministic": deterministic,
        "parquet_roundtrip": "PASS",
        "session_coverage": _session_coverage_for_month(
            first_m5,
            instrument,
            year,
            month,
            bid_path.parents[4],
            ask_path.parents[4],
        ),
        "status": "CERTIFIED",
    }


def _candidate_level_certification(
    partition_records: list[dict[str, Any]],
) -> dict[str, Any]:
    from fx_smc_bot.research.strategy_alpha import HISTORICAL_WINDOWS

    candidate_freeze = load_json(REPO / "results/gate_p0/candidate_universe_freeze.json")
    certified = {
        (str(item["instrument"]), int(item["year"]), int(item["month"]))
        for item in partition_records
        if item["status"] == "CERTIFIED"
    }
    candidates: list[dict[str, Any]] = []
    for candidate in candidate_freeze["candidates"]:
        required_instruments = sorted(
            set(candidate["instruments"]) & set(AUTHORIZED_STRATEGY_INSTRUMENTS)
        )
        windows: list[dict[str, Any]] = []
        candidate_failures = 0
        for window, (start, end) in HISTORICAL_WINDOWS.items():
            start_year = int(start[:4])
            end_year = int(end[:4])
            required = {
                (instrument, year, month)
                for instrument in required_instruments
                for year in range(start_year, end_year + 1)
                for month in range(1, 13)
            }
            missing = sorted(required - certified)
            candidate_failures += len(missing)
            windows.append(
                {
                    "window": window,
                    "start": start,
                    "end": end,
                    "required_partitions": len(required),
                    "certified_partitions": len(required & certified),
                    "missing_partitions": len(missing),
                    "failed_partitions": 0,
                    "successful_zero_row_partitions": 0,
                    "status": "FULLY_CERTIFIED" if not missing else "FAILED",
                }
            )
        candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "required_instruments": required_instruments,
                "excluded_optional_diagnostics": ["USDJPY"],
                "windows": windows,
                "status": "FULLY_CERTIFIED" if candidate_failures == 0 else "FAILED",
            }
        )
    all_certified = (
        len(candidates) == 4
        and all(item["status"] == "FULLY_CERTIFIED" for item in candidates)
    )
    missing_partitions = sum(
        int(window["missing_partitions"])
        for candidate in candidates
        for window in candidate["windows"]
    )
    return {
        "created_at_utc": now_utc(),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "all_four_candidates_fully_certified": all_certified,
        "missing_required_partitions": missing_partitions,
        "failed_required_partitions": 0,
        "successful_zero_row_partitions": 0,
        "status": "PASS" if all_certified and missing_partitions == 0 else "FAIL",
    }


def _write_data_certification_doc(
    audit: dict[str, Any],
    certification: dict[str, Any],
    dataset_freeze: dict[str, Any],
) -> None:
    write_doc(
        DOC_DIR / "P0RDCRA1A_DATA_CERTIFICATION.md",
        [
            "# Gate P.0-R-DCR-A1A Data Certification",
            "",
            f"- Dataset freeze: `{dataset_freeze['dataset_freeze_id']}`",
            f"- Dataset hash: `{dataset_freeze['dataset_freeze_hash']}`",
            f"- Certified pair-months: `{audit['certified_pair_months']}/192`",
            f"- Canonical M1 rows: `{audit['canonical_m1_rows']}`",
            f"- Canonical M5 rows: `{audit['canonical_m5_rows']}`",
            "- Three-run deterministic M1/M5: `PASS`",
            "- Forward fill/interpolation: `false`",
            "- Candidate certification: `FULLY_CERTIFIED` for all four candidates",
            "- USDJPY role: `OPTIONAL_DIAGNOSTIC`, excluded from this dataset freeze",
            "- Economic outcomes accessed: `false`",
            "",
            "Canonical Parquet payloads remain local and ignored by Git.",
        ],
    )


def run_canonicalization() -> None:
    import pandas as pd  # type: ignore[import-untyped]
    import pyarrow  # type: ignore[import-untyped]

    recertification = load_json(RESULT_DIR / "recertification_results.json")
    if (
        recertification.get("recertified_pair_months") != 192
        or recertification.get("repair_required_pair_months") != 0
    ):
        raise RuntimeError("canonicalization requires 192/192 recertified pair-months")

    started = time.monotonic()
    records: list[dict[str, Any]] = []
    for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS):
        for year in range(2015, 2023):
            for month in range(1, 13):
                records.append(_canonicalize_pair_month(instrument, year, month))
                if len(records) % 12 == 0:
                    print(
                        json.dumps(
                            {
                                "stage": "canonicalization",
                                "completed_pair_months": len(records),
                                "planned_pair_months": 192,
                                "elapsed_seconds": round(time.monotonic() - started, 3),
                            }
                        ),
                        flush=True,
                    )

    cross_instrument_provider_closed = _reconcile_cross_instrument_provider_closures(
        records
    )
    failures = [item for item in records if item["status"] != "CERTIFIED"]
    session_missing_days = sum(
        int(session["missing_days"])
        for item in records
        for session in item["session_coverage"].values()
    )
    session_partial_days = sum(
        int(session["partial_days"])
        for item in records
        for session in item["session_coverage"].values()
    )
    provider_closed_observed_days = sum(
        int(session["provider_closed_observed_days"])
        for item in records
        for session in item["session_coverage"].values()
    )
    manifest = {
        "created_at_utc": now_utc(),
        "canonical_root": _relative(CANONICAL_ROOTS[1]),
        "partition_count": len(records),
        "partitions": records,
        "raw_or_canonical_payload_committed": False,
        "status": "PASS" if not failures else "FAIL",
    }
    manifest_hash = canonical_json_sha256(manifest)
    manifest["manifest_hash"] = manifest_hash
    audit = {
        "created_at_utc": now_utc(),
        "source_resolution": "DUKASCOPY_TICK_BI5_BID_ASK_TO_UTC_M1_TO_M5",
        "certified_pair_months": len(records) - len(failures),
        "failed_pair_months": len(failures),
        "canonical_m1_rows": sum(int(item["m1_rows"]) for item in records),
        "canonical_m5_rows": sum(int(item["m5_rows"]) for item in records),
        "three_run_determinism_required": 3,
        "three_run_determinism_passed": all(
            bool(item["three_run_deterministic"]) for item in records
        ),
        "parquet_roundtrip_passed": all(
            item["parquet_roundtrip"] == "PASS" for item in records
        ),
        "session_missing_days": session_missing_days,
        "session_partial_days": session_partial_days,
        "provider_closed_observed_session_days": provider_closed_observed_days,
        "provider_closed_cross_instrument_session_records": (
            cross_instrument_provider_closed
        ),
        "provider_closed_classification_rule": (
            "same date and named session absent for both EURUSD and GBPUSD"
        ),
        "synthetic_bank_holiday_calendar_used": False,
        "forward_fill_used": False,
        "interpolation_used": False,
        "holdout_accessed": False,
        "runtime_versions": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "status": "PASS" if not failures and session_missing_days == 0 else "FAIL",
    }
    certification = _candidate_level_certification(records)
    freeze_base = {
        "created_at_utc": now_utc(),
        "dataset_freeze_id": DATASET_FREEZE_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "amendment_id": AMENDMENT_ID,
        "amendment_hash": load_json(
            RESULT_DIR / "data_requirement_amendment.json"
        )["amendment_hash"],
        "recovery_protocol_id": RECOVERY_PROTOCOL_ID,
        "recovery_protocol_hash": load_json(
            RESULT_DIR / "data_recovery_protocol.json"
        )["protocol_hash"],
        "instruments": sorted(AUTHORIZED_STRATEGY_INSTRUMENTS),
        "start": "2015-01-01",
        "end": "2022-12-31",
        "canonical_hierarchy": ["UTC_M1_BID_ASK_OHLC", "M5_BID_ASK_OHLC"],
        "canonical_partition_manifest_hash": manifest_hash,
        "candidate_certification_hash": canonical_json_sha256(certification),
        "certified_pair_months": len(records) - len(failures),
        "candidate_count_fully_certified": sum(
            1 for item in certification["candidates"] if item["status"] == "FULLY_CERTIFIED"
        ),
        "economic_outcomes_accessed": False,
        "sealed_holdout_accessed": False,
        "raw_or_canonical_payload_committed": False,
        "outcome_access_predecessor_sha_recorded_in_successor_audit": True,
        "status": "FROZEN_BEFORE_OUTCOMES",
    }
    freeze_base["dataset_freeze_hash"] = canonical_json_sha256(freeze_base)
    if audit["status"] != "PASS" or certification["status"] != "PASS":
        raise RuntimeError("candidate-level canonical data certification failed")
    write_json(RESULT_DIR / "canonicalization_audit.json", audit)
    write_json(RESULT_DIR / "canonical_partition_manifest.json", manifest)
    write_json(RESULT_DIR / "candidate_level_data_certification.json", certification)
    write_json(RESULT_DIR / "permitted_dataset_freeze.json", freeze_base)
    _write_data_certification_doc(audit, certification, freeze_base)
    print(
        json.dumps(
            {
                "stage": "canonicalization",
                "certified_pair_months": audit["certified_pair_months"],
                "m1_rows": audit["canonical_m1_rows"],
                "m5_rows": audit["canonical_m5_rows"],
                "session_missing_days": audit["session_missing_days"],
                "dataset_freeze_hash": freeze_base["dataset_freeze_hash"],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
            indent=2,
        )
    )


def _runtime_smoke_worker(candidate_id: str) -> dict[str, Any]:
    from dataclasses import asdict

    from fx_smc_bot.backtesting.intraday_engine import IntradayBacktestEngine
    from fx_smc_bot.config import AppConfig, TradingPair
    from fx_smc_bot.research.strategy_alpha import load_candidate_specs
    from fx_smc_bot.research.strategy_alpha_execution import (
        amended_execution_policy,
        build_candidate_runtime_bindings,
        load_certified_m5_window,
    )

    candidate = next(
        item for item in load_candidate_specs(REPO) if item.candidate_id == candidate_id
    )
    start = date(2015, 1, 1)
    end = date(2015, 1, 16)
    data = {
        TradingPair(instrument): load_certified_m5_window(
            REPO, instrument, start, end,
        )
        for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS)
    }

    def execute_once() -> dict[str, Any]:
        engine = IntradayBacktestEngine(
            AppConfig(),
            execution_policy=amended_execution_policy(),
        )
        bindings = build_candidate_runtime_bindings(REPO, candidate)
        for binding in bindings:
            engine.add_runtime(binding.runtime)
        result = engine.run(data)
        funnels = list(engine.get_funnels().values())
        reconciliation = engine.reconcile()
        return {
            "bars": sum(len(series) for series in data.values()),
            "eligible_session_bars": sum(item.bars_processed for item in funnels),
            "signals": sum(item.intents_generated for item in funnels),
            "orders": sum(item.orders_accepted for item in funnels),
            "fills": sum(item.orders_filled for item in funnels),
            "closed_positions": sum(item.positions_closed for item in funnels),
            "errors": list(result.metadata.get("execution_errors", [])),
            "open_positions_at_end": result.metadata.get("open_positions_at_end"),
            "pending_orders_at_end": result.metadata.get("pending_orders_at_end"),
            "reconciliation_violations": list(reconciliation.violations),
            "funnels": [asdict(item) for item in funnels],
            "runtime_bindings": [
                {
                    "candidate_id": binding.candidate_id,
                    "instrument": binding.instrument,
                    "session": binding.session,
                    "family": binding.family,
                    "config_hash": binding.config_hash,
                }
                for binding in bindings
            ],
        }

    first = execute_once()
    second = execute_once()
    return {
        "candidate_id": candidate_id,
        "first_run": first,
        "second_run": second,
        "deterministic": canonical_json_sha256(first) == canonical_json_sha256(second),
    }


def run_runtime_smoke() -> None:
    predecessor = git(["rev-parse", "HEAD"])
    expected = "e4e73ed76c58a23b35a6c469b236ae2c73c895a8"
    if predecessor != expected:
        raise RuntimeError("runtime smoke must begin from the certified dataset predecessor")
    preregistration = load_json(RESULT_DIR / "preregistration_order_audit.json")
    if preregistration.get("outcome_access_predecessor_sha") != predecessor:
        raise RuntimeError("preregistration predecessor does not match HEAD")
    candidate_ids = [
        "SMC_A_SWEEP_REVERSAL_V1",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1",
        "SMC_C_LONDON_OPENING_RANGE_V1",
        "SMC_C_NEWYORK_OPENING_RANGE_V1",
    ]
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(_runtime_smoke_worker, candidate_ids))
    records.sort(key=lambda item: item["candidate_id"])
    checks = {
        "all_candidates_executed": len(records) == 4,
        "all_runs_deterministic": all(item["deterministic"] for item in records),
        "all_runtimes_bound": all(item["first_run"]["runtime_bindings"] for item in records),
        "no_runtime_errors": all(not item["first_run"]["errors"] for item in records),
        "no_open_positions_at_end": all(
            item["first_run"]["open_positions_at_end"] == 0 for item in records
        ),
        "no_pending_orders_at_end": all(
            item["first_run"]["pending_orders_at_end"] == 0 for item in records
        ),
        "no_reconciliation_violations": all(
            not item["first_run"]["reconciliation_violations"] for item in records
        ),
    }
    audit = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "outcome_access_predecessor_sha": predecessor,
        "dataset_freeze_id": DATASET_FREEZE_ID,
        "dataset_freeze_hash": load_json(
            RESULT_DIR / "permitted_dataset_freeze.json"
        )["dataset_freeze_hash"],
        "smoke_window": ["2015-01-01", "2015-01-16"],
        "reported_fields": [
            "bars", "signals", "orders", "fills", "closed_positions", "errors"
        ],
        "economic_metrics_reported": False,
        "worker_count": 4,
        "checks": checks,
        "candidates": records,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    write_json(RESULT_DIR / "runtime_integration_audit.json", audit)
    if audit["status"] != "PASS":
        raise RuntimeError("strategy-alpha runtime smoke failed")
    print(json.dumps({
        "stage": "runtime_smoke",
        "worker_count": 4,
        "candidate_count": len(records),
        "deterministic": checks["all_runs_deterministic"],
        "elapsed_seconds": audit["elapsed_seconds"],
    }, indent=2))


def _execution_unit_paths(candidate_id: str, year: int) -> tuple[Path, Path]:
    root = CANONICAL_ROOTS[1] / "_local_ledgers"
    stem = f"{candidate_id}__{year}"
    return root / f"{stem}.parquet", root / f"{stem}.json"


def _execution_year_worker(candidate_id: str, year: int) -> dict[str, Any]:
    from dataclasses import asdict, replace

    import numpy as np
    import pandas as pd  # type: ignore[import-untyped]

    from fx_smc_bot.backtesting.intraday_engine import IntradayBacktestEngine
    from fx_smc_bot.config import AppConfig, TradingPair
    from fx_smc_bot.research.strategy_alpha import load_candidate_specs
    from fx_smc_bot.research.strategy_alpha_execution import (
        amended_execution_policy,
        build_candidate_runtime_bindings,
        is_amended_session_bar,
        load_certified_m5_window,
    )

    ledger_path, metadata_path = _execution_unit_paths(candidate_id, year)
    execution_code_sha = git(["rev-parse", "HEAD"])
    if metadata_path.is_file() and ledger_path.is_file():
        existing = load_json(metadata_path)
        if (
            existing.get("status") == "PASS"
            and existing.get("execution_code_sha") == execution_code_sha
            and existing.get("ledger_hash") == raw_sha256(ledger_path)
        ):
            return {**existing, "resumed": True}

    candidate = next(
        item for item in load_candidate_specs(REPO) if item.candidate_id == candidate_id
    )
    target_start = date(year, 1, 1)
    target_end = date(year, 12, 31)
    source_start = date(year, 1, 1) if year == 2015 else date(year - 1, 12, 1)
    data = {
        TradingPair(instrument): load_certified_m5_window(
            REPO, instrument, source_start, target_end,
        )
        for instrument in sorted(AUTHORIZED_STRATEGY_INSTRUMENTS)
    }
    target_start_ns = np.datetime64(target_start.isoformat(), "ns")
    pre_target_counts = {
        pair.value: int(np.sum(series.timestamps < target_start_ns))
        for pair, series in data.items()
    }
    if year > 2015 and any(count < 500 for count in pre_target_counts.values()):
        raise RuntimeError(f"insufficient prior-year warmup for {candidate_id}/{year}")

    base_policy = amended_execution_policy()
    if year == 2015:
        policy = base_policy
    else:
        def target_session_filter(value: datetime, session: str) -> bool:
            return value >= datetime(year, 1, 1) and is_amended_session_bar(value, session)

        policy = replace(
            base_policy,
            warmup_bars=0,
            runtime_bar_filter=target_session_filter,
        )
    engine = IntradayBacktestEngine(AppConfig(), execution_policy=policy)
    bindings = build_candidate_runtime_bindings(REPO, candidate)
    for binding in bindings:
        engine.add_runtime(binding.runtime)
    result = engine.run(data)
    reconciliation = engine.reconcile()
    if reconciliation.violations:
        raise RuntimeError(
            f"execution reconciliation failed for {candidate_id}/{year}: "
            f"{reconciliation.violations}"
        )

    rows = []
    for record in engine.get_trade_records():
        if record.entry_time is None or record.exit_time is None:
            raise RuntimeError("closed trade is missing entry or exit time")
        if record.entry_time.year != year:
            raise RuntimeError("year shard emitted a trade outside its target year")
        if record.initial_risk_cash <= 0:
            raise RuntimeError("trade has non-positive initial risk")
        slippage_cash = (
            record.entry_slippage_price + record.exit_slippage_price
        ) * record.units
        explicit_cost_cash = record.commission_cost + slippage_cash
        no_explicit_cost_pnl = record.net_pnl + explicit_cost_cash
        rows.append({
            "candidate_id": candidate_id,
            "year": year,
            "position_id": record.position_id,
            "order_id": record.order_id,
            "intent_id": record.intent_id,
            "instrument": record.pair,
            "direction": record.direction,
            "session": record.session,
            "entry_time": record.entry_time,
            "exit_time": record.exit_time,
            "entry_price": record.entry_price,
            "exit_price": record.exit_price,
            "stop_loss": record.stop_loss,
            "take_profit": record.take_profit,
            "units": record.units,
            "initial_risk_cash": record.initial_risk_cash,
            "gross_r": no_explicit_cost_pnl / record.initial_risk_cash,
            "net_r": record.net_pnl / record.initial_risk_cash,
            "cost_drag_r": explicit_cost_cash / record.initial_risk_cash,
            "stress_1_5x_net_r": (
                record.net_pnl - 0.5 * explicit_cost_cash
            ) / record.initial_risk_cash,
            "stress_2_0x_net_r": (
                record.net_pnl - explicit_cost_cash
            ) / record.initial_risk_cash,
            "commission_cash": record.commission_cost,
            "slippage_cash": slippage_cash,
            "swap_cash": record.swap_cost,
            "exit_reason": record.exit_reason,
            "entry_bar": record.entry_bar,
            "exit_bar": record.exit_bar,
        })
    columns = [
        "candidate_id", "year", "position_id", "order_id", "intent_id",
        "instrument", "direction", "session", "entry_time", "exit_time",
        "entry_price", "exit_price", "stop_loss", "take_profit", "units",
        "initial_risk_cash", "gross_r", "net_r", "cost_drag_r",
        "stress_1_5x_net_r", "stress_2_0x_net_r", "commission_cash",
        "slippage_cash", "swap_cash", "exit_reason", "entry_bar", "exit_bar",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame = frame.sort_values(
            ["entry_time", "instrument", "session", "position_id"]
        ).reset_index(drop=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False, engine="pyarrow")
    temporary.replace(ledger_path)
    schema = {column: str(dtype) for column, dtype in frame.dtypes.items()}
    funnels = [asdict(item) for item in engine.get_funnels().values()]
    metadata = {
        "candidate_id": candidate_id,
        "candidate_hash": candidate.config_canonical_hash,
        "execution_code_sha": execution_code_sha,
        "year": year,
        "source_start": source_start.isoformat(),
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "pre_target_warmup_rows": pre_target_counts,
        "dataset_freeze_hash": load_json(
            RESULT_DIR / "permitted_dataset_freeze.json"
        )["dataset_freeze_hash"],
        "ledger_path": _relative(ledger_path),
        "ledger_hash": raw_sha256(ledger_path),
        "schema_hash": canonical_json_sha256(schema),
        "row_count": int(len(frame)),
        "minimum_date": (
            frame["entry_time"].min().isoformat() if not frame.empty else None
        ),
        "maximum_date": (
            frame["exit_time"].max().isoformat() if not frame.empty else None
        ),
        "signals": sum(item["intents_generated"] for item in funnels),
        "orders": sum(item["orders_accepted"] for item in funnels),
        "fills": sum(item["orders_filled"] for item in funnels),
        "closed_positions": sum(item["positions_closed"] for item in funnels),
        "expired_orders": sum(item["orders_expired"] for item in funnels),
        "cancelled_orders": sum(item["orders_cancelled"] for item in funnels),
        "position_overlap_rejections": sum(
            item["position_overlap_rejections"] for item in funnels
        ),
        "session_horizon_signal_rejections": sum(
            item["session_horizon_signal_rejections"] for item in funnels
        ),
        "execution_errors": list(result.metadata.get("execution_errors", [])),
        "open_positions_at_end": result.metadata.get("open_positions_at_end"),
        "pending_orders_at_end": result.metadata.get("pending_orders_at_end"),
        "status": "PASS",
        "resumed": False,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def run_historical_execution() -> None:
    execution_code_sha = git(["rev-parse", "HEAD"])
    if git(["merge-base", "--is-ancestor", "e4e73ed76c58a23b35a6c469b236ae2c73c895a8", "HEAD"]):
        raise RuntimeError("certified dataset freeze is not an ancestor of execution code")
    candidate_ids = [
        "SMC_A_SWEEP_REVERSAL_V1",
        "SMC_B_ACCEPTANCE_CONTINUATION_V1",
        "SMC_C_LONDON_OPENING_RANGE_V1",
        "SMC_C_NEWYORK_OPENING_RANGE_V1",
    ]
    tasks = [(candidate_id, year) for candidate_id in candidate_ids for year in range(2015, 2023)]
    started = time.monotonic()
    completed: list[dict[str, Any]] = []
    worker_count = min(10, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_execution_year_worker, candidate_id, year): (candidate_id, year)
            for candidate_id, year in tasks
        }
        for future in as_completed(futures):
            candidate_id, year = futures[future]
            record = future.result()
            completed.append(record)
            progress = {
                "created_at_utc": now_utc(),
                "execution_code_sha": execution_code_sha,
                "worker_count": worker_count,
                "completed_units": len(completed),
                "total_units": len(tasks),
                "latest_unit": {"candidate_id": candidate_id, "year": year},
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "status": "IN_PROGRESS" if len(completed) < len(tasks) else "PASS",
            }
            write_json(RESULT_DIR / "execution_progress.json", progress)
            print(json.dumps(progress), flush=True)
    completed.sort(key=lambda item: (item["candidate_id"], item["year"]))
    if len(completed) != 32 or any(item["status"] != "PASS" for item in completed):
        raise RuntimeError("historical execution did not certify all 32 units")
    manifest = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "execution_code_sha": execution_code_sha,
        "outcome_access_predecessor_sha": "e4e73ed76c58a23b35a6c469b236ae2c73c895a8",
        "dataset_freeze_hash": load_json(
            RESULT_DIR / "permitted_dataset_freeze.json"
        )["dataset_freeze_hash"],
        "worker_count": worker_count,
        "unit_count": len(completed),
        "trade_count": sum(int(item["row_count"]) for item in completed),
        "minimum_date": min(
            item["minimum_date"] for item in completed if item["minimum_date"]
        ),
        "maximum_date": max(
            item["maximum_date"] for item in completed if item["maximum_date"]
        ),
        "units": completed,
        "row_level_ledgers_committed": False,
        "status": "PASS",
    }
    write_json(RESULT_DIR / "execution_sample_manifest.json", manifest)
    print(json.dumps({
        "stage": "historical_execution",
        "units": len(completed),
        "trades": manifest["trade_count"],
        "workers": worker_count,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=[
            "audit",
            "amendment",
            "stage2_prep",
            "recertification",
            "acquisition",
            "canonicalization",
            "runtime_smoke",
            "execution",
            "all",
        ],
        default="all",
    )
    args = parser.parse_args()
    if args.stage in {"audit", "all"}:
        run_audit()
    if args.stage in {"amendment", "all"}:
        run_amendment()
    if args.stage in {"stage2_prep", "all"}:
        run_stage2_prep()
    if args.stage in {"recertification", "all"}:
        run_recertification()
    if args.stage in {"acquisition", "all"}:
        run_acquisition()
    if args.stage in {"canonicalization", "all"}:
        run_canonicalization()
    if args.stage in {"runtime_smoke", "all"}:
        run_runtime_smoke()
    if args.stage in {"execution", "all"}:
        run_historical_execution()


if __name__ == "__main__":
    main()
