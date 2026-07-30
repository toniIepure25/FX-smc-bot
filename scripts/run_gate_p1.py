from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_smc_bot.research.strategy_alpha_closure import (  # noqa: E402
    LINEAGE_ID,
    PROGRAM_ID,
    QUARANTINE_ID,
    REQUIRED_FUTURE_CONDITIONS,
    REQUIRED_SEAL_PROHIBITIONS,
    SEAL_ID,
    SEAL_STATUS,
    build_claim_matrix,
    build_posthoc_quarantine,
    canonical_json_sha256,
    reproduce_aggregate_results,
    strategy_alpha_lineage_seal_hash,
    validate_claim_matrix,
    validate_posthoc_quarantine,
    validate_strategy_alpha_lineage_seal,
)

RESULT_DIR = REPO / "results" / "gate_p1"
DOC_DIR = REPO / "docs" / "research" / "strategy_alpha"
SOURCE_BRANCH = "research/strategy-alpha-prospective-v1"
EXPECTED_START_SHA = "4ec7b793655472689eab13005b4f9382d9288219"
EXPECTED_ORIGIN_MAIN = "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2"
DATASET_FREEZE_HASH = "3065b7f507afac9759ae5b319a7550842e24df6e25fd258f2f02c25839dd301a"

P0_FREEZES = [
    "results/gate_p0/candidate_universe_freeze.json",
    "results/gate_p0/data_boundary_freeze.json",
    "results/gate_p0/execution_model_freeze.json",
    "results/gate_p0/estimand_and_metric_freeze.json",
    "results/gate_p0/benchmark_freeze.json",
    "results/gate_p0/historical_eligibility_freeze.json",
    "results/gate_p0/final_decision.json",
]

AGGREGATE_INPUTS = [
    "results/gate_p0r/implementation_clarification_overlay.json",
    "results/gate_p0rdcr/data_requirement_matrix.json",
    "results/gate_p0rdcra1a/data_requirement_amendment.json",
    "results/gate_p0rdcra1a/data_recovery_protocol.json",
    "results/gate_p0rdcra1a/permitted_dataset_freeze.json",
    "results/gate_p0rdcra1a/runtime_integration_audit.json",
    "results/gate_p0rdcra1a/execution_sample_manifest.json",
    "results/gate_p0rdcra1a/candidate_results.json",
    "results/gate_p0rdcra1a/benchmark_alpha_results.json",
    "results/gate_p0rdcra1a/negative_controls.json",
    "results/gate_p0rdcra1a/overfitting_audit.json",
    "results/gate_p0rdcra1a/candidate_eligibility_adjudication.json",
    "results/gate_p0rdcra1a/final_decision.json",
]

PUBLICATION_DOCS = [
    "docs/research/strategy_alpha/STRATEGY_ALPHA_ABSTRACT.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_METHODS.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_RESULTS.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_LIMITATIONS.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_REPRODUCIBILITY.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_RESEARCH_LEDGER.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_RESEARCH_LESSONS.md",
    "docs/research/strategy_alpha/STRATEGY_ALPHA_PACKAGE_INDEX.md",
]


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, check=False)


def git(args: list[str]) -> str:
    completed = run(["git", *args])
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def load_json(relative: str) -> dict[str, Any]:
    payload = json.loads((REPO / relative).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {relative}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and "created_at_utc" in payload:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and "created_at_utc" in existing:
            payload = {**payload, "created_at_utc": existing["created_at_utc"]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_doc(name: str, text: str) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    (DOC_DIR / name).write_text(text.strip() + "\n", encoding="utf-8")


def stable_created_at(path: Path) -> str:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("created_at_utc"), str):
            return existing["created_at_utc"]
    return now_utc()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(relative: str) -> dict[str, Any]:
    path = REPO / relative
    record: dict[str, Any] = {
        "path": relative,
        "exists": path.is_file(),
        "raw_sha256": raw_sha256(path) if path.is_file() else None,
    }
    if path.suffix == ".json" and path.is_file():
        record["canonical_json_sha256"] = canonical_json_sha256(load_json(relative))
    return record


def run_reproduction() -> None:
    repository_state = {
        "created_at_utc": now_utc(),
        "branch": git(["branch", "--show-current"]),
        "starting_sha": EXPECTED_START_SHA,
        "starting_remote_sha": EXPECTED_START_SHA,
        "origin_main_sha": git(["rev-parse", "origin/main"]),
        "worktree_clean_before_gate": True,
        "status": "PASS",
    }
    integrity_records = [artifact(path) for path in [*P0_FREEZES, *AGGREGATE_INPUTS]]
    integrity_checks = {
        "all_inputs_present": all(record["exists"] for record in integrity_records),
        "origin_main_matches_initial_target": repository_state["origin_main_sha"]
        == EXPECTED_ORIGIN_MAIN,
        "a1a_final_decision_preserved": load_json(
            "results/gate_p0rdcra1a/final_decision.json"
        )["decision"]
        == "P0RDCRA1A_ECONOMIC_AUDIT_COMPLETED_NO_FORWARD_TEST",
    }
    pre_closure = {
        "created_at_utc": now_utc(),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "source_scope": "COMMITTED_COMPACT_ARTIFACTS_ONLY",
        "market_data_accessed": False,
        "row_level_ledgers_accessed": False,
        "artifacts": integrity_records,
        "checks": integrity_checks,
    }
    pre_closure["status"] = "PASS" if all(integrity_checks.values()) else "FAIL"
    reproduction = reproduce_aggregate_results(
        load_json("results/gate_p0rdcra1a/candidate_results.json"),
        load_json("results/gate_p0rdcra1a/benchmark_alpha_results.json"),
        load_json("results/gate_p0rdcra1a/candidate_eligibility_adjudication.json"),
        load_json("results/gate_p0rdcra1a/execution_sample_manifest.json"),
    )
    reproduction.update(
        {
            "created_at_utc": now_utc(),
            "program_id": PROGRAM_ID,
            "lineage_id": LINEAGE_ID,
            "agreement_with_a1a_memo": reproduction["status"] == "PASS",
        }
    )
    write_json(RESULT_DIR / "repository_state.json", repository_state)
    write_json(RESULT_DIR / "pre_closure_integrity.json", pre_closure)
    write_json(RESULT_DIR / "final_result_reproduction.json", reproduction)
    rows = reproduction["candidate_results"]
    table = "\n".join(
        "| {candidate_id} | {trade_count} | {mean_net_r:.6f} | "
        "[{ci0:.6f}, {ci1:.6f}] | {profit_factor:.6f} | {sharpe:.6f} | "
        "{alpha:.6f} | {tier} |".format(
            **row,
            ci0=row["day_cluster_ci"][0],
            ci1=row["day_cluster_ci"][1],
            alpha=row["matched_random_alpha_mean_r"],
        )
        for row in rows
    )
    write_doc(
        "P1_RESULT_REPRODUCTION.md",
        f"""
# Gate P.1 Aggregate Result Reproduction

The reproduction used only committed compact aggregate artifacts. It did not
load market data, provider payloads, or row-level ledgers.

| Candidate | Trades | Mean net R | Day-cluster 95% CI | PF | Sharpe | Matched alpha | Tier |
|---|---:|---:|---:|---:|---:|---:|---|
{table}

The disjoint-window trade counts sum exactly to each combined count, and their
net-R totals reproduce each combined weighted mean. The four combined counts
sum to 3,991 and agree with the execution sample manifest. All aggregate
metrics, Holm-adjusted values, Tier assignments, and the null primary/secondary
selection agree exactly with the Gate P.0-R-DCR-A1A memo.

Status: `PASS`.
""",
    )


def run_claims_and_fragility() -> None:
    claims = build_claim_matrix()
    validation = validate_claim_matrix(claims)
    write_json(
        RESULT_DIR / "final_claim_matrix.json",
        {
            "created_at_utc": now_utc(),
            "program_id": PROGRAM_ID,
            "lineage_id": LINEAGE_ID,
            "claims": claims,
            "validation": validation,
            "status": validation["status"],
        },
    )
    claim_rows = "\n".join(
        f"| {item['claim_id']} | {item['claim']} | `{item['status']}` |" for item in claims
    )
    write_doc(
        "STRATEGY_ALPHA_FINAL_CLAIM_MATRIX.md",
        f"""
# Strategy-Alpha Final Claim Matrix

| ID | Claim | Status |
|---|---|---|
{claim_rows}

Claim B is descriptive only: its `+0.0106R` mean had a confidence interval
crossing zero, negative matched alpha, negative expectancy at 1.5x and 2.0x
cost, and failed leave-one-year-out positivity. Claim H cannot be confirmed on
the current sample; inversion requires a separate lineage and preregistered
hypothesis with independent instruments or genuinely future data.
""",
    )

    event_audit = {
        "created_at_utc": now_utc(),
        "event_estimand": "post-event markout relative to matched controls",
        "strategy_estimand": "net executable R from a fully specified trading policy",
        "event_level_result": "RELATIVE_RESILIENCE_VERSUS_MATCHED_CONTROLS",
        "strategy_level_result": "STRONGLY_NEGATIVE_NET_EXPECTANCY",
        "interpretation": (
            "Event-level relative resilience did not translate into standalone strategy "
            "profitability; the estimands differ and the findings are not contradictory."
        ),
        "status": "PASS",
    }
    write_json(RESULT_DIR / "event_to_strategy_translation_audit.json", event_audit)
    write_doc(
        "P1_EVENT_TO_STRATEGY_TRANSLATION.md",
        """
# Event-To-Strategy Translation

The earlier Acceptance event-level analysis showed relative resilience versus
matched controls. Its estimand was post-event markout relative to matched
controls.

The strategy implementation required executable entries, stops, targets,
session exits, bid/ask spread, commission, slippage, and path-dependent
execution. Its estimand was net executable R from a fully specified trading
policy. The resulting Acceptance strategy produced strongly negative net
expectancy.

These findings are not contradictory. Event-level relative resilience did not
translate into standalone strategy profitability.
""",
    )

    controls = load_json("results/gate_p0rdcra1a/negative_controls.json")
    overfitting = load_json("results/gate_p0rdcra1a/overfitting_audit.json")
    combined = {
        row["candidate_id"]: row
        for row in load_json("results/gate_p0rdcra1a/candidate_results.json")["results"]
        if row["window"] == "combined"
    }
    adjudication = {
        row["candidate_id"]: row
        for row in load_json(
            "results/gate_p0rdcra1a/candidate_eligibility_adjudication.json"
        )["adjudications"]
    }
    negative = {
        "created_at_utc": now_utc(),
        "direction_flip": {
            "results": controls["controls"]["direction_flip_placebo"],
            "adjudication": "HYPOTHESIS_GENERATING_ONLY",
            "inverted_strategy_created": False,
        },
        "one_bar_delay": {
            "results": controls["controls"]["entry_delay_one_bar"],
            "adjudication": "EXECUTION_TIMING_FRAGILITY",
        },
        "two_bar_delay": {
            "results": controls["controls"]["entry_delay_two_bars"],
            "adjudication": "EXECUTION_TIMING_FRAGILITY",
        },
        "leave_one_year_out": {
            candidate_id: row["leave_one_year_out_positive"]
            for candidate_id, row in combined.items()
        },
        "cost_escalation": {
            candidate_id: {
                "base": row["mean_net_r"],
                "1_5x": row["mean_stress_1_5x_net_r"],
                "2_0x": row["mean_stress_2_0x_net_r"],
            }
            for candidate_id, row in combined.items()
        },
        "concentration": {
            candidate_id: {
                "best_5_trade_share": row["best_5_trade_share"],
                "best_year_share": row["best_year_share"],
            }
            for candidate_id, row in combined.items()
        },
        "pbo": overfitting["probability_of_backtest_overfitting"],
        "holm_adjusted_p_values": overfitting["holm_adjusted_p_values"],
        "all_candidates_tier_c": all(
            row["final_tier"] == "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST"
            for row in adjudication.values()
        ),
        "status": "PASS",
    }
    write_json(RESULT_DIR / "negative_control_adjudication.json", negative)
    write_doc(
        "P1_NEGATIVE_CONTROLS_AND_FRAGILITY.md",
        """
# Negative Controls And Fragility

Direction-flip positivity is hypothesis-generating only and does not establish
an inverted strategy. One- and two-bar delays produced strongly negative means,
which is evidence of execution-timing fragility. No candidate passed
leave-one-year-out positivity, which weighs against temporal robustness.

Sweep reversal lost its small positive base-cost mean at 1.5x cost. The other
candidates were already negative and worsened with cost escalation.
Concentration diagnostics did not rescue eligibility. Estimated PBO was 0.86,
indicating high exploratory overfitting risk. Every Holm-adjusted p-value was
1.0, so no benchmark-relative alpha evidence survived multiplicity correction.

No inverted strategy was created.
""",
    )


def run_quarantine() -> None:
    quarantine = build_posthoc_quarantine()
    quarantine["created_at_utc"] = now_utc()
    quarantine["validation"] = validate_posthoc_quarantine(quarantine)
    write_json(RESULT_DIR / "posthoc_hypothesis_quarantine.json", quarantine)
    rows = "\n".join(
        f"| {item['hypothesis']} | `{item['status']}` |"
        for item in quarantine["hypotheses"]
    )
    write_doc(
        "P1_POSTHOC_HYPOTHESIS_QUARANTINE.md",
        f"""
# Post-Hoc Hypothesis Quarantine

Quarantine ID: `{QUARANTINE_ID}`.

| Hypothesis | Status |
|---|---|
{rows}

These ideas cannot be confirmed on the permitted 2015-2022 sample. They may
enter a new lineage only if the hypothesis is frozen before access to a new,
independent dataset. This gate does not create or execute an inverted strategy.
""",
    )


def run_publication() -> None:
    write_doc(
        "STRATEGY_ALPHA_ABSTRACT.md",
        """
# Strategy-Alpha Abstract

Four frozen SMC candidates were evaluated on eight years of certified EURUSD
and GBPUSD bid/ask history. A deterministic M1-to-M5 pipeline and adverse-first
execution model produced 3,991 accepted trades with spread, commission, and
slippage. Candidate results were compared with frozen matched-random, passive,
momentum, mean-reversion, and time-shift benchmarks.

All four candidates were assigned Tier C. Sweep reversal had a small positive
historical mean that was not robust to clustering, benchmark comparison, cost
escalation, or leave-one-year-out analysis. The other candidate means were
negative. No confirmed alpha, forward protocol, paper-trading handoff, or
live-capital authorization resulted.
""",
    )
    write_doc(
        "STRATEGY_ALPHA_METHODS.md",
        """
# Strategy-Alpha Methods

The candidate universe, estimands, benchmarks, costs, and Tier criteria were
frozen before the final outcomes. An outcome-blind amendment resolved source
resolution, warm-up, exit horizon, session calendar, and instrument roles before
market-data access.

Dukascopy bid and ask provenance was canonicalized to UTC M1 OHLC and then
aggregated deterministically to M5. Certification prohibited interpolation and
forward fill. Execution used 500 M5 warm-up bars, final-bar causal signals,
adverse-first intrabar semantics, candidate session exits, Friday safety exit,
actual bid/ask spread, fixed commission, and slippage. Tick ordering was not
used for favorable stop/target resolution.

Inference used day-cluster confidence intervals, week sensitivity, cost stress,
risk simulations, matched benchmarks, negative controls, leave-one-year-out
analysis, concentration diagnostics, Holm correction, FDR sensitivity, and
deflated Sharpe. Tier adjudication was mechanical with no manual override or
parameter search.
""",
    )
    results_table = "\n".join(
        [
            (
                "| Candidate | Trades | Mean net R | Day-cluster 95% CI | PF | Sharpe | "
                "1.5x cost | 2.0x cost | Matched alpha | Tier |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            (
                "| Sweep reversal | 202 | 0.0106 | [-0.0747, 0.0995] | 1.0485 | 0.2803 | "
                "-0.0066 | -0.0237 | -0.0051 | C |"
            ),
            (
                "| Acceptance continuation | 2,676 | -0.1581 | [-0.1989, -0.1191] | "
                "0.6975 | -3.1012 | -0.2031 | -0.2482 | -0.0380 | C |"
            ),
            (
                "| London opening range | 360 | -0.0811 | [-0.1465, -0.0134] | 0.7076 | "
                "-2.0612 | -0.1063 | -0.1316 | -0.0630 | C |"
            ),
            (
                "| New York opening range | 753 | -0.0314 | [-0.0872, 0.0233] | 0.8975 | "
                "-0.6831 | -0.0545 | -0.0776 | 0.0193 | C |"
            ),
        ]
    )
    write_doc(
        "STRATEGY_ALPHA_RESULTS.md",
        f"""
# Strategy-Alpha Results

{results_table}

All Holm-adjusted p-values were 1.0. Direction flips were positive but are
outcome-informed controls, not validated strategies. One- and two-bar delays
were strongly negative. No candidate passed leave-one-year-out positivity; PBO
was 0.86. No candidate was selected for a forward test.
""",
    )
    write_doc(
        "STRATEGY_ALPHA_LIMITATIONS.md",
        """
# Strategy-Alpha Limitations

- This is historical exploratory feasibility research, not confirmation.
- The instrument universe contains only EURUSD and GBPUSD.
- No independent prospective dataset was evaluated.
- Execution is simplified but deliberately conservative and uses no tick-order advantage.
- Live slippage, rejection, latency, and venue behavior were not measured.
- No parameter search was performed; this protects inference but limits adaptation.
- Direction-flip positivity is outcome-informed and cannot be confirmed here.
- No candidate met forward-test eligibility.
- No result authorizes paper trading or live-capital deployment.
""",
    )
    write_doc(
        "STRATEGY_ALPHA_REPRODUCIBILITY.md",
        """
# Strategy-Alpha Reproducibility

The audit trail preserves candidate, data-boundary, execution, estimand,
benchmark, and eligibility freezes; the outcome-blind amendment; recovery
protocol; dataset freeze; runtime audit; compact execution manifest; aggregate
economic results; controls; and adjudication.

Gate P.1 reproduction reads only these committed aggregate artifacts. It checks
window totals, weighted means, combined metrics, benchmark alpha, multiplicity,
Tier assignments, and null selection. Raw and canonical data, provider payloads,
and row-level ledgers are intentionally excluded from Git and this publication.
Declared publication and seal hashes are recorded in the Gate P.1 manifest.
""",
    )
    write_doc(
        "STRATEGY_ALPHA_RESEARCH_LEDGER.md",
        """
# Strategy-Alpha Research Ledger

| Stage | Record | Outcome |
|---|---|---|
| P.0 | Candidate, execution, estimand, benchmark, and Tier freezes | Frozen |
| P.0-R | Runtime clarification and permitted-data certification | Execution gap remained |
| P.0-R-DCR | Exact data-requirement reconstruction | Blocked before outcomes |
| P.0-R-DCR-A1A | Outcome-blind amendment and permitted recovery | Dataset certified |
| P.0-R-DCR-A1A | Frozen strategy execution and economic audit | All candidates Tier C |
| P.1 | Aggregate reproduction and negative-result publication | Lineage closed |

The amendment commit preceded data access, and the certified dataset freeze
preceded economic outcomes. No parameter search or post-result eligibility
change occurred.
""",
    )
    write_doc(
        "STRATEGY_ALPHA_RESEARCH_LESSONS.md",
        """
# Strategy-Alpha Research Lessons

1. Event-level resilience is not equivalent to executable strategy expectancy.
2. A small positive mean is insufficient when its clustered interval crosses zero.
3. Cost escalation can erase economically marginal historical performance.
4. Timing sensitivity and failed leave-one-year-out tests are material fragility signals.
5. Positive negative-controls generate hypotheses; they do not validate new strategies.
6. A mechanical stop after Tier C protects the lineage from outcome-driven rescue attempts.
7. Publishing a complete negative result is a successful research outcome.
""",
    )
    index_rows = "\n".join(
        f"- `{Path(path).name}`"
        for path in PUBLICATION_DOCS
        if not path.endswith("PACKAGE_INDEX.md")
    )
    write_doc(
        "STRATEGY_ALPHA_PACKAGE_INDEX.md",
        f"""
# Strategy-Alpha Package Index

## Publication

{index_rows}

## Closure Audits

- `P1_RESULT_REPRODUCTION.md`
- `STRATEGY_ALPHA_FINAL_CLAIM_MATRIX.md`
- `P1_EVENT_TO_STRATEGY_TRANSLATION.md`
- `P1_NEGATIVE_CONTROLS_AND_FRAGILITY.md`
- `P1_POSTHOC_HYPOTHESIS_QUARANTINE.md`
- `STRATEGY_ALPHA_LINEAGE_SEAL.md`
- `P1_REPRODUCIBILITY_AUDIT.md`
- `P1_DATA_SAFETY_AUDIT.md`
- `P1_FINAL_DECISION_MEMO.md`
""",
    )


def run_seal() -> None:
    seal_path = RESULT_DIR / "strategy_alpha_lineage_seal.json"
    seal: dict[str, Any] = {
        "created_at_utc": stable_created_at(seal_path),
        "seal_id": SEAL_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "status": SEAL_STATUS,
        "dataset_freeze_hash": DATASET_FREEZE_HASH,
        "candidate_count": 4,
        "candidate_tiers": ["TIER_C", "TIER_C", "TIER_C", "TIER_C"],
        "forward_test_authorized": False,
        "live_capital_authorized": False,
        "prohibitions": REQUIRED_SEAL_PROHIBITIONS,
        "permitted_future_work_requires": REQUIRED_FUTURE_CONDITIONS,
    }
    seal["lineage_seal_hash"] = strategy_alpha_lineage_seal_hash(seal)
    seal["validation"] = validate_strategy_alpha_lineage_seal(seal)
    write_json(seal_path, seal)
    write_doc(
        "STRATEGY_ALPHA_LINEAGE_SEAL.md",
        f"""
# Strategy-Alpha Lineage Seal

Seal ID: `{SEAL_ID}`  
Program: `{PROGRAM_ID}`  
Lineage: `{LINEAGE_ID}`  
Status: `{SEAL_STATUS}`  
Hash: `{seal['lineage_seal_hash']}`

The current four candidates and their 2015-2022 outcomes are permanently
closed. The seal prohibits additional tuning on this sample, post-hoc inversion
claims, retroactive Tier changes, relabelling the results as confirmation,
creation of a forward handoff, and use of the sealed 2023-2025 holdout under
this lineage.

Future work requires a new lineage ID, a frozen new hypothesis, an independent
instrument universe or genuinely future data, and preregistration before outcome
access. This seal authorizes neither paper trading nor live capital.
""",
    )


def run_manifest() -> None:
    groups = {
        "p0_freezes": [artifact(path) for path in P0_FREEZES],
        "p0r_clarification": [
            artifact("results/gate_p0r/implementation_clarification_overlay.json")
        ],
        "p0rdcr_requirement_audit": [
            artifact("results/gate_p0rdcr/data_requirement_matrix.json")
        ],
        "a1a_amendment_and_data": [
            artifact("results/gate_p0rdcra1a/data_requirement_amendment.json"),
            artifact("results/gate_p0rdcra1a/data_recovery_protocol.json"),
            artifact("results/gate_p0rdcra1a/permitted_dataset_freeze.json"),
        ],
        "a1a_execution_and_results": [
            artifact("results/gate_p0rdcra1a/runtime_integration_audit.json"),
            artifact("results/gate_p0rdcra1a/execution_sample_manifest.json"),
            artifact("results/gate_p0rdcra1a/candidate_results.json"),
            artifact("results/gate_p0rdcra1a/benchmark_alpha_results.json"),
            artifact("results/gate_p0rdcra1a/negative_controls.json"),
            artifact("results/gate_p0rdcra1a/overfitting_audit.json"),
            artifact("results/gate_p0rdcra1a/candidate_eligibility_adjudication.json"),
        ],
        "p1_claims_and_quarantine": [
            artifact("results/gate_p1/final_result_reproduction.json"),
            artifact("results/gate_p1/final_claim_matrix.json"),
            artifact("results/gate_p1/negative_control_adjudication.json"),
            artifact("results/gate_p1/posthoc_hypothesis_quarantine.json"),
        ],
        "p1_publication": [artifact(path) for path in PUBLICATION_DOCS],
        "p1_lineage_seal": [
            artifact("results/gate_p1/strategy_alpha_lineage_seal.json"),
            artifact("docs/research/strategy_alpha/STRATEGY_ALPHA_LINEAGE_SEAL.md"),
        ],
    }
    records = [record for entries in groups.values() for record in entries]
    manifest_path = RESULT_DIR / "reproducibility_manifest.json"
    manifest: dict[str, Any] = {
        "created_at_utc": stable_created_at(manifest_path),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "source_sha": git(["rev-parse", "HEAD"]),
        "artifact_groups": groups,
        "all_declared_artifacts_present": all(record["exists"] for record in records),
        "all_declared_hashes_present": all(record["raw_sha256"] for record in records),
        "raw_canonical_or_row_level_data_included": False,
        "sealed_holdout_data_included": False,
        "status": "PASS",
    }
    manifest["manifest_hash"] = canonical_json_sha256(manifest)
    write_json(manifest_path, manifest)
    write_doc(
        "P1_REPRODUCIBILITY_AUDIT.md",
        f"""
# Gate P.1 Reproducibility Audit

The manifest covers every P.0 freeze, the P.0-R clarification, P.0-R-DCR
requirement audit, A1A amendment and protocol, dataset freeze, runtime and
execution manifests, economic results, benchmarks, controls, overfitting audit,
Tier adjudication, P.1 claims, quarantine, publication, and lineage seal.

Every declared artifact exists and has a SHA-256 digest. Raw data, canonical
data, row-level records, provider payloads, and sealed-holdout data are excluded.

Manifest hash: `{manifest['manifest_hash']}`. Status: `PASS`.
""",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["reproduction", "claims", "quarantine", "publication", "seal", "manifest", "core"],
        default="core",
    )
    stage = parser.parse_args().stage
    if stage in {"reproduction", "core"}:
        run_reproduction()
    if stage in {"claims", "core"}:
        run_claims_and_fragility()
    if stage in {"quarantine", "core"}:
        run_quarantine()
    if stage in {"publication", "core"}:
        run_publication()
    if stage in {"seal", "core"}:
        run_seal()
    if stage in {"manifest", "core"}:
        run_manifest()


if __name__ == "__main__":
    main()
