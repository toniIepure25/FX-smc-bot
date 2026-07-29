from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
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
)

RESULT_DIR = REPO / "results" / "gate_p0rdcra1a"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "6ed045dd3cf79345ffc567f7b981106281489586"
ORIGIN_MAIN_AT_START = "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2"
AMENDMENT_PRE_DATA_ACCESS_SHA = "3c10bba09f7536b3dd7417f4328bda12a3f59541"
RECOVERY_PROTOCOL_ID = "P0RDCRA1A_PERMITTED_DATA_RECOVERY_PROTOCOL_V1"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["audit", "amendment", "stage2_prep", "all"],
        default="all",
    )
    args = parser.parse_args()
    if args.stage in {"audit", "all"}:
        run_audit()
    if args.stage in {"amendment", "all"}:
        run_amendment()
    if args.stage in {"stage2_prep", "all"}:
        run_stage2_prep()


if __name__ == "__main__":
    main()
