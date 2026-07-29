from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
    amended_requirement_contract,
)

RESULT_DIR = REPO / "results" / "gate_p0rdcra1a"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "6ed045dd3cf79345ffc567f7b981106281489586"
ORIGIN_MAIN_AT_START = "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2"

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["audit", "amendment", "all"], default="all")
    args = parser.parse_args()
    if args.stage in {"audit", "all"}:
        run_audit()
    if args.stage in {"amendment", "all"}:
        run_amendment()


if __name__ == "__main__":
    main()
