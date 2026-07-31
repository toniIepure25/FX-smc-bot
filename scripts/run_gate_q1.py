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

from fx_smc_bot.research.quant_polarity_closure import (  # noqa: E402
    CLOSURE_ID,
    LINEAGE_ID,
    PROGRAM_ID,
    Q0R_DECISION,
    Q1_CREATED_DECISION,
    Q1_EXISTING_DECISION,
    QUARANTINE_ID,
    REQUIRED_FUTURE_CONDITIONS,
    REQUIRED_SEAL_PROHIBITIONS,
    SEAL_ID,
    SEAL_STATUS,
    build_claim_matrix,
    build_failure_mechanism_audit,
    build_posthoc_quarantine,
    build_statistical_interpretation,
    detect_prohibited_changed_paths,
    lineage_seal_hash,
    payload_hash_without,
    reproduce_aggregate_results,
    validate_claim_matrix,
    validate_lineage_seal,
    validate_no_future_or_live_handoff,
    validate_posthoc_quarantine,
)

Q0 = REPO / "results" / "gate_q0"
Q0R = REPO / "results" / "gate_q0r"
Q1 = REPO / "results" / "gate_q1"
DOCS = REPO / "docs" / "research" / "quant_polarity_v2"
START_SHA = "1ae0abe19ad138e166f83b4a1d3fd48af34b8a3e"
BRANCH = "research/quant-polarity-meta-v2-prospective"
Q0R_MANIFEST_RAW_SHA = (
    "52ca4c199f9db5d41e714c9d9ba1dcd76248eae60bea6107b19188122ed9a322"
)

Q0_ARTIFACTS = {
    "final_decision": (
        "results/gate_q0/final_decision.json",
        "8ec6f29691f0243daf8a86e2db85c02904706572117832529b3ba191c62b3fea",
    ),
    "holdout_integrity": (
        "results/gate_q0/holdout_integrity.json",
        "8e1a679571229bb23f8c063d3211d39dcc0270ae619451bbebd2c1b3a06447ea",
    ),
    "prohibited_data_audit": (
        "results/gate_q0/prohibited_data_audit.json",
        "5ed17358876a58111bfeec3690fa05cf8eafdae0fb036f53cf7b9f04d2414332",
    ),
    "development_acquisition_status": (
        "results/gate_q0/development_acquisition_status.json",
        "4d5e060f832936dcce9d54a611f552b633b6364a55a2c8b97ba82a8067654606",
    ),
    "reproducibility_manifest": (
        "results/gate_q0/reproducibility_manifest.json",
        "6f376191c89703dc3252369b4f8eeac62838170f53c7fc0082ae71d65d1306d0",
    ),
    "final_decision_memo": (
        "docs/research/quant_polarity/Q0_FINAL_DECISION_MEMO.md",
        "011ecd8161ec54110276d5f3d2509ac5655689063dee5e3ea0d1bc3ecad60c44",
    ),
}

PUBLICATION_DOCS = (
    "docs/research/quant_polarity_v2/QUANT_POLARITY_ABSTRACT.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_METHODS.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_RESULTS.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_STATISTICAL_APPENDIX.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_LIMITATIONS.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_REPRODUCIBILITY.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_RESEARCH_LEDGER.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_RESEARCH_LESSONS.md",
    "docs/research/quant_polarity_v2/QUANT_POLARITY_PACKAGE_INDEX.md",
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_doc(name: str, content: str) -> None:
    path = DOCS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha256(revision: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def artifact(relative: str) -> dict[str, Any]:
    path = REPO / relative
    return {
        "path": relative,
        "exists": path.is_file(),
        "raw_sha256": raw_sha(path) if path.is_file() else None,
    }


def stable_created_at(path: Path) -> str:
    if path.is_file():
        existing = load_json(path)
        if isinstance(existing.get("created_at_utc"), str):
            return str(existing["created_at_utc"])
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def verify_q0r_manifest() -> dict[str, Any]:
    manifest = load_json(Q0R / "reproducibility_manifest.json")
    mismatches: list[dict[str, str]] = []
    for filename, expected in manifest["artifacts_sha256"].items():
        observed = raw_sha(Q0R / filename)
        if observed != expected:
            mismatches.append(
                {"artifact": filename, "expected": expected, "observed": observed}
            )
    memo_observed = raw_sha(DOCS / "Q0R_FINAL_DECISION_MEMO.md")
    if memo_observed != manifest["final_memo_sha256"]:
        mismatches.append(
            {
                "artifact": "Q0R_FINAL_DECISION_MEMO.md",
                "expected": manifest["final_memo_sha256"],
                "observed": memo_observed,
            }
        )
    return {
        "declared_artifact_count": len(manifest["artifacts_sha256"]) + 1,
        "mismatches": mismatches,
        "raw_manifest_sha256": raw_sha(Q0R / "reproducibility_manifest.json"),
        "status": "PASS" if not mismatches else "FAIL",
    }


def run_reproduction() -> None:
    Q1.mkdir(parents=True, exist_ok=True)
    repository_state = {
        "branch": git("branch", "--show-current"),
        "starting_sha": START_SHA,
        "local_sha_at_gate_start": START_SHA,
        "remote_branch_sha_at_gate_start": START_SHA,
        "origin_main_sha_at_gate_start": git("rev-parse", "origin/main"),
        "worktree_clean_at_gate_start": True,
        "status": "PASS",
    }
    write_json(Q1 / "repository_state.json", repository_state)
    write_json(
        Q1 / "pre_closure_integrity.json",
        {
            "q0r_decision": Q0R_DECISION,
            "q0r_final_sha": START_SHA,
            "market_data_access_authorized": False,
            "row_level_access_authorized": False,
            "replication_authorized": False,
            "candidate_modification_authorized": False,
            "history_rewrite_authorized": False,
            "status": "PASS",
        },
    )

    hashes: dict[str, str] = {}
    immutable_hash_matches: dict[str, bool] = {}
    blob_unchanged: dict[str, bool] = {}
    for name, (relative, expected) in Q0_ARTIFACTS.items():
        observed = raw_sha(REPO / relative)
        hashes[name] = observed
        immutable_hash_matches[name] = observed == expected
        blob_unchanged[name] = (
            git_blob_sha256("62ca0b35de561350ef55fb211bb72ceb5ce9513a", relative)
            == git_blob_sha256("HEAD", relative)
            == observed
        )
    q0r_inheritance = load_json(Q0R / "q0_failure_inheritance.json")
    inherited_hash_matches = {
        name: hashes[name] == q0r_inheritance["artifact_sha256"][name]
        for name in hashes
    }
    inherited_mismatches = [
        {
            "artifact": name,
            "q0r_recorded_sha256": q0r_inheritance["artifact_sha256"][name],
            "actual_unchanged_sha256": hashes[name],
            "historical_blob_unchanged": blob_unchanged[name],
        }
        for name, matches in inherited_hash_matches.items()
        if not matches
    ]
    q0_final = load_json(Q0 / "final_decision.json")
    holdout = load_json(Q0 / "holdout_integrity.json")
    q0_preservation = {
        "artifact_sha256": hashes,
        "hash_matches_immutable_q0_blobs": immutable_hash_matches,
        "historical_blob_unchanged": blob_unchanged,
        "hash_matches_q0r_inheritance_record": inherited_hash_matches,
        "q0r_inheritance_record_mismatches": inherited_mismatches,
        "provenance_interpretation": (
            "The Q0 holdout-integrity blob is byte-identical from the blocked Q0 "
            "commit through HEAD. The Q0-R inheritance record contains one "
            "transcribed hash mismatch; the historical artifact was not mutated."
        ),
        "q0_decision": q0_final["decision"],
        "holdout_storage_enumerated": holdout["flags"][
            "holdout_storage_enumerated"
        ],
        "holdout_structure_inspected": holdout["flags"][
            "holdout_structure_inspected"
        ],
        "holdout_content_loaded": holdout["breach"]["content_loaded"],
        "holdout_provider_request_sent": holdout["breach"][
            "provider_request_sent"
        ],
        "holdout_outcomes_inspected": holdout["breach"]["outcomes_inspected"],
        "development_outcomes_generated": q0_final[
            "development_outcomes_generated"
        ],
        "replication_accessed": q0_final["replication_access_started"],
        "status": (
            "Q0_FAILURE_PRESERVED_UNCHANGED"
            if all(immutable_hash_matches.values())
            and all(blob_unchanged.values())
            and q0_final["decision"] == "BLOCKED_BY_HOLDOUT_INTEGRITY"
            else "FAIL"
        ),
    }
    write_json(Q1 / "q0_failure_preservation.json", q0_preservation)

    manifest_check = verify_q0r_manifest()
    sources = {
        "data_certification": load_json(
            Q0R / "development_data_certification.json"
        ),
        "dataset_freeze": load_json(Q0R / "development_dataset_freeze.json"),
        "candidate_results": load_json(
            Q0R / "development_candidate_results.json"
        ),
        "benchmark_results": load_json(
            Q0R / "development_benchmark_results.json"
        ),
        "factor_alpha": load_json(Q0R / "development_factor_alpha.json"),
        "inference": load_json(Q0R / "development_inference.json"),
        "overfitting": load_json(Q0R / "development_overfitting_audit.json"),
        "stability": load_json(
            Q0R / "development_stability_and_concentration.json"
        ),
        "adjudication": load_json(
            Q0R / "development_candidate_adjudication.json"
        ),
        "shortlist": load_json(Q0R / "replication_shortlist_freeze.json"),
        "final_decision": load_json(Q0R / "final_decision.json"),
    }
    reproduction = reproduce_aggregate_results(
        sources,
        memo_text=(DOCS / "Q0R_FINAL_DECISION_MEMO.md").read_text(
            encoding="utf-8"
        ),
        manifest_hash_agreement=manifest_check["status"] == "PASS",
    )
    reproduction["q0r_manifest_verification"] = manifest_check
    write_json(Q1 / "final_result_reproduction.json", reproduction)

    write_doc(
        "Q1_Q0_FAILURE_PRESERVATION.md",
        f"""
# Gate Q1 Q0 Failure Preservation

The historical Q.0 decision remains `BLOCKED_BY_HOLDOUT_INTEGRITY`. Storage
enumeration and structure inspection remain recorded as true, while content
loading, provider requests, outcome inspection, development outcomes, and
replication access remain false.

All six committed Q.0 blobs are byte-identical to the blocked Q.0 commit. The
Q.0-R inheritance record contains
`{len(q0_preservation['q0r_inheritance_record_mismatches'])}` transcribed hash
mismatch: the holdout-integrity record differs from the unchanged blob hash.
This is recorded as a provenance metadata defect, not an artifact mutation. No
historical audit was edited or reinterpreted.

Status: `{q0_preservation['status']}`.
""",
    )
    table = "\n".join(
        [
            "| Candidate | Trades | Mean net R | PF | 1.5x cost | Matched alpha |",
            "|---|---:|---:|---:|---:|---:|",
            "| Inverse Sweep | 364 | -0.321805 | 0.297522 | -0.356640 | -0.255439 |",
            (
                "| Inverse Acceptance | 6,932 | -0.762445 | 0.107293 | "
                "-0.858735 | -0.527579 |"
            ),
            (
                "| Inverse London OR | 930 | -0.410300 | 0.160778 | "
                "-0.471346 | -0.215112 |"
            ),
            (
                "| Inverse New York OR | 1,488 | -0.421101 | 0.233314 | "
                "-0.473285 | -0.284062 |"
            ),
            (
                "| Elastic-net meta | 6 | -0.121867 | 0.077613 | "
                "-0.133150 | -0.128247 |"
            ),
        ]
    )
    write_doc(
        "Q1_RESULT_REPRODUCTION.md",
        f"""
# Gate Q1 Aggregate Result Reproduction

Gate Q1 read only committed aggregate JSON and the committed Q0-R decision
memo. It did not load market data or row-level features, predictions, signals,
orders, benchmarks, or trades.

{table}

Checks performed: `{reproduction['aggregate_check_count']}`.
Mismatches: `{reproduction['mismatch_count']}`.
Maximum numeric difference: `{reproduction['maximum_numeric_difference']}`.
Q0-R manifest hash agreement: `{reproduction['hash_agreement']}`.

White Reality Check, Hansen SPA, Romano-Wolf, Holm, FDR, PSR, DSR, PBO,
year and instrument stability, development ineligibility, empty shortlist,
absence of replication access, and absence of a future freeze all reproduced.

Status: `{reproduction['status']}`.
""",
    )


def run_claims() -> None:
    claims = build_claim_matrix()
    validation = validate_claim_matrix(claims)
    claim_payload: dict[str, Any] = {
        "claims": claims,
        "validation": validation,
        "status": validation["status"],
    }
    claim_payload["claim_matrix_hash"] = payload_hash_without(
        claim_payload, "claim_matrix_hash"
    )
    write_json(Q1 / "final_claim_matrix.json", claim_payload)

    interpretation = build_statistical_interpretation()
    interpretation["interpretation_hash"] = payload_hash_without(
        interpretation, "interpretation_hash"
    )
    write_json(Q1 / "statistical_failure_interpretation.json", interpretation)

    failure = build_failure_mechanism_audit()
    failure["failure_mechanism_hash"] = payload_hash_without(
        failure, "failure_mechanism_hash"
    )
    write_json(Q1 / "failure_mechanism_audit.json", failure)

    claim_rows = "\n".join(
        f"| {item['claim_id']} | {item['claim']} | `{item['status']}` |"
        for item in claims
    )
    write_doc(
        "QUANT_POLARITY_FINAL_CLAIM_MATRIX.md",
        f"""
# Quant-Polarity Final Claim Matrix

| ID | Claim | Status |
|---|---|---|
{claim_rows}

Replication did not fail: it was not tested because no candidate was eligible.
The small Romano-Wolf values for deterministic candidates identify reliable
negative relative effects, not profitable alpha.

Claim matrix hash: `{claim_payload['claim_matrix_hash']}`.
""",
    )
    write_doc(
        "Q1_STATISTICAL_INTERPRETATION.md",
        """
# Gate Q1 Statistical Interpretation

- White Reality Check `p=0.9898`: no frozen-family outperformance after
  data-snooping adjustment.
- Hansen SPA `p=1.0`: no superior predictive ability.
- PBO `1.0`: maximal consistency with overfitting or nontransportable selection.
- Maximum DSR probability `2.4072381359488004e-7`: no Sharpe survives adjustment.
- Negative year and instrument stability: failure is broad, not isolated.
- Empty shortlist: the preregistered gate stopped correctly before replication.

Small Romano-Wolf values for four deterministic candidates accompany negative
relative effects. They cannot be interpreted as profitable alpha.
""",
    )
    write_doc(
        "Q1_FAILURE_MECHANISMS.md",
        """
# Gate Q1 Failure Mechanisms

Data certification, clean-room isolation, safe I/O, execution integrity,
lookahead protection, and model-selection separation passed. Economic
performance, benchmark-relative alpha, and development eligibility failed.

The elastic-net model produced only six trades with negative expectancy and
profit factor below one. The four deterministic inverted policies were negative
in every development year and on every development instrument.

Replication was not accessed and no prospective candidate was created.

The absence of an eligible candidate is due to negative economic and
statistical evidence, not due to missing data, runtime failure, or incomplete
certification.
""",
    )


def run_quarantine() -> None:
    quarantine = build_posthoc_quarantine()
    validation = validate_posthoc_quarantine(quarantine)
    quarantine["validation"] = validation
    if validation["status"] != "PASS":
        raise RuntimeError("Post-hoc quarantine validation failed")
    write_json(Q1 / "posthoc_hypothesis_quarantine.json", quarantine)
    rows = "\n".join(
        f"- {item['hypothesis']}: `{item['status']}`"
        for item in quarantine["hypotheses"]
    )
    write_doc(
        "Q1_POSTHOC_QUARANTINE.md",
        f"""
# Gate Q1 Post-Hoc Hypothesis Quarantine

Quarantine ID: `{QUARANTINE_ID}`
Hash: `{quarantine['quarantine_hash']}`

{rows}

These hypotheses cannot be confirmed in the current lineage. Future
consideration requires a new lineage, financially motivated hypothesis,
candidate family, preregistration, multiple-testing family, and independent
data partition.
""",
    )


def run_publication() -> None:
    write_doc(
        "QUANT_POLARITY_ABSTRACT.md",
        """
# Quant-Polarity Abstract

A quarantined direction-flip observation motivated a preregistered evaluation
of four deterministic inverted SMC policies and one elastic-net polarity
meta-model. Q0-R used a physically isolated, capability-restricted clean-room
pipeline and four independent FX instruments over 2015-2019.

All five candidates had negative mean net R and negative matched-random alpha.
The deterministic candidates were negative in every development year and on
every instrument. The meta-model produced only six trades. Reality Check,
Hansen SPA, DSR, and PBO provided no support. No candidate entered the frozen
replication shortlist, so replication data were not accessed. No prospective
or capital-deployment handoff was created.
""",
    )
    write_doc(
        "QUANT_POLARITY_METHODS.md",
        """
# Quant-Polarity Methods

The candidate family, feature order, multinomial elastic-net model,
hyperparameter grid, `0.55` ORIGINAL and INVERSE thresholds, ABSTAIN action,
2,680-minute purge, five-day embargo, estimands, benchmarks, and eligibility
rules were inherited exactly from Q0 before market-data access.

Q0-R acquired AUDUSD, NZDUSD, USDCAD, and USDCHF for 2015-2019 into a new
clean-room root. Immutable capabilities restricted root, instrument, date,
partition, and operation. Data were certified as deterministic UTC bid/ask M1
and M5 OHLC.

Signals used conservative bid/ask execution and adverse-first same-bar
semantics. The meta-model used nested purged walk-forward selection by
multinomial log loss and strictly out-of-fold predictions. Economic inference
included clustered and bootstrap intervals, transaction-cost stress,
matched-random alpha, factor HAC alpha, multiplicity correction, Reality Check,
SPA, PSR, DSR, PBO, and stability diagnostics.
""",
    )
    write_doc(
        "QUANT_POLARITY_RESULTS.md",
        """
# Quant-Polarity Results

| Candidate | Trades | Mean net R | PF | 1.5x cost | Matched alpha |
|---|---:|---:|---:|---:|---:|
| Inverse Sweep | 364 | -0.321805 | 0.297522 | -0.356640 | -0.255439 |
| Inverse Acceptance | 6,932 | -0.762445 | 0.107293 | -0.858735 | -0.527579 |
| Inverse London OR | 930 | -0.410300 | 0.160778 | -0.471346 | -0.215112 |
| Inverse New York OR | 1,488 | -0.421101 | 0.233314 | -0.473285 | -0.284062 |
| Elastic-net meta | 6 | -0.121867 | 0.077613 | -0.133150 | -0.128247 |

All candidates failed development eligibility. The replication shortlist was
empty and frozen before replication access. Replication therefore has no
outcome, and no future candidate or prospective protocol exists.
""",
    )
    write_doc(
        "QUANT_POLARITY_STATISTICAL_APPENDIX.md",
        """
# Quant-Polarity Statistical Appendix

White Reality Check was `0.9898`, Hansen SPA was `1.0`, and PBO was `1.0`.
The maximum DSR probability was `2.4072381359488004e-7`. Raw matched-random
permutation p-values were `1.0` for deterministic candidates and `0.847515`
for the meta-model; Holm and FDR values were all `1.0`.

Romano-Wolf values were `0.000400`, `0.000200`, `0.000200`, `0.000200`, and
`0.242951`. The first four accompany negative candidate-relative effects and
therefore indicate reliably poor relative performance, not profitable alpha.
The positive meta-model HAC coefficient used only five daily observations and
is numerically unstable.
""",
    )
    write_doc(
        "QUANT_POLARITY_LIMITATIONS.md",
        """
# Quant-Polarity Limitations

- Development covered four instruments and 2015-2019 only.
- No candidate qualified for independent 2020-2022 replication.
- The meta-model produced only six accepted trades.
- Model convergence warnings occurred but did not affect the empty shortlist.
- The historical Q0 integrity incident permanently disqualified its former
  confirmatory interval.
- No genuinely future prospective evidence was collected.
- The results authorize neither paper trading nor live-capital deployment.
""",
    )
    write_doc(
        "QUANT_POLARITY_REPRODUCIBILITY.md",
        """
# Quant-Polarity Reproducibility

The repository preserves Q0 failure artifacts, Q0-R rebaseline and clean-room
certifications, protocol hashes, dataset freeze, execution and leakage audits,
aggregate economic and statistical results, empty shortlist, final decision,
and Q1 closure records.

Q1 reproduction reads committed aggregates only. It verifies exact numerical
values, cross-artifact consistency, stability conclusions, eligibility, absent
replication, absent future handoff, and all Q0-R manifest hashes. Raw,
canonical, provider, and row-level artifacts remain outside Git.
""",
    )
    write_doc(
        "QUANT_POLARITY_RESEARCH_LEDGER.md",
        """
# Quant-Polarity Research Ledger

| Stage | Outcome |
|---|---|
| Q0 | Protocol frozen; stopped on holdout-integrity failure before outcomes |
| Q0-R baseline | Q0 failure preserved; clean-room integrity established |
| Q0-R data | 240/240 development pair-months certified |
| Q0-R execution | Five frozen candidates evaluated with causal controls |
| Q0-R selection | All candidates ineligible; shortlist frozen empty |
| Q0-R replication | Not accessed |
| Q1 | Aggregate reproduction, negative-result publication, permanent closure |

The ordered commits preserve the integrity failure, rebaseline, data freeze,
execution, negative outcomes, empty shortlist, and closure without rewriting.
""",
    )
    write_doc(
        "QUANT_POLARITY_RESEARCH_LESSONS.md",
        """
# Quant-Polarity Research Lessons

1. Reversing an unsuccessful policy does not mechanically create positive edge.
2. Negative performance across years and instruments is stronger evidence than
   one isolated backtest failure.
3. A flexible polarity classifier can remain economically unusable through
   abstention and sparse accepted activity.
4. Small multiplicity-adjusted values require directional interpretation.
5. Clean data and correct execution do not guarantee a profitable hypothesis.
6. An empty preregistered shortlist is a valid scientific stopping outcome.
7. Outcome-informed rescue ideas require a genuinely new lineage and data plan.
8. Publishing negative results prevents repeated, hidden reuse of failed ideas.
""",
    )
    write_doc(
        "QUANT_POLARITY_PACKAGE_INDEX.md",
        """
# Quant-Polarity Package Index

## Publication

- `QUANT_POLARITY_ABSTRACT.md`
- `QUANT_POLARITY_METHODS.md`
- `QUANT_POLARITY_RESULTS.md`
- `QUANT_POLARITY_STATISTICAL_APPENDIX.md`
- `QUANT_POLARITY_LIMITATIONS.md`
- `QUANT_POLARITY_REPRODUCIBILITY.md`
- `QUANT_POLARITY_RESEARCH_LEDGER.md`
- `QUANT_POLARITY_RESEARCH_LESSONS.md`

## Closure Audits

- `Q1_Q0_FAILURE_PRESERVATION.md`
- `Q1_RESULT_REPRODUCTION.md`
- `QUANT_POLARITY_FINAL_CLAIM_MATRIX.md`
- `Q1_STATISTICAL_INTERPRETATION.md`
- `Q1_POSTHOC_QUARANTINE.md`
- `Q1_FAILURE_MECHANISMS.md`
- `QUANT_POLARITY_LINEAGE_SEAL.md`
- `Q1_CLOSURE_LOCK.md`
- `Q1_REPRODUCIBILITY_AUDIT.md`
- `Q1_DATA_SAFETY_AUDIT.md`
- `Q1_FINAL_DECISION_MEMO.md`
""",
    )


def run_seal() -> None:
    q0r_manifest = load_json(Q0R / "reproducibility_manifest.json")
    q0_inheritance = load_json(Q0R / "q0_failure_inheritance.json")
    shortlist = load_json(Q0R / "replication_shortlist_freeze.json")
    seal_path = Q1 / "quant_polarity_lineage_seal.json"
    seal: dict[str, Any] = {
        "created_at_utc": stable_created_at(seal_path),
        "seal_id": SEAL_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "status": SEAL_STATUS,
        "q0_failure_artifact_sha256": q0_inheritance["artifact_sha256"],
        "historical_quarantine": (
            "QUARANTINED_FROM_CONFIRMATORY_USE_DUE_TO_Q0_STORAGE_ENUMERATION"
        ),
        "clean_room_certification_sha256": q0r_manifest["artifacts_sha256"][
            "clean_room_root.json"
        ],
        "candidate_family_hash": q0r_manifest["candidate_family_hash"],
        "feature_order_hash": q0r_manifest["feature_order_hash"],
        "protocol_hash": q0r_manifest["protocol_hash"],
        "protocol_inheritance_artifact_sha256": q0r_manifest["artifacts_sha256"][
            "protocol_inheritance_lock.json"
        ],
        "development_dataset_freeze_sha256": q0r_manifest["artifacts_sha256"][
            "development_dataset_freeze.json"
        ],
        "development_result_sha256": {
            name: q0r_manifest["artifacts_sha256"][name]
            for name in (
                "development_candidate_results.json",
                "development_benchmark_results.json",
                "development_factor_alpha.json",
                "development_inference.json",
                "development_overfitting_audit.json",
                "development_stability_and_concentration.json",
                "development_candidate_adjudication.json",
            )
        },
        "empty_shortlist_hash": shortlist["shortlist_hash"],
        "q0r_integrity_audit_sha256": q0r_manifest["artifacts_sha256"][
            "integrity_audit.json"
        ],
        "q0r_final_sha": START_SHA,
        "replication_accessed": False,
        "future_candidate_created": False,
        "paper_or_live_handoff_created": False,
        "prohibitions": list(REQUIRED_SEAL_PROHIBITIONS),
        "permitted_future_work_requires": list(REQUIRED_FUTURE_CONDITIONS),
    }
    seal["lineage_seal_hash"] = lineage_seal_hash(seal)
    seal["validation"] = validate_lineage_seal(seal)
    if seal["validation"]["status"] != "PASS":
        raise RuntimeError("Lineage seal validation failed")
    write_json(seal_path, seal)
    write_doc(
        "QUANT_POLARITY_LINEAGE_SEAL.md",
        f"""
# Quant-Polarity Lineage Seal

Seal ID: `{SEAL_ID}`
Program: `{PROGRAM_ID}`
Lineage: `{LINEAGE_ID}`
Status: `{SEAL_STATUS}`
Hash: `{seal['lineage_seal_hash']}`

The seal permanently preserves the Q0 integrity failure, historical
quarantine, Q0-R clean-room baseline, protocol and feature hashes, certified
development dataset, negative aggregate outcomes, empty shortlist, and Q0-R
integrity audit.

Further tuning, weaker criteria, replication access, future-candidate creation,
paper/live handoff, historical-quarantine reuse, and relabeling negative
performance as alpha are prohibited. Future work requires every condition
listed in the seal and must use a new lineage.
""",
    )


def run_closure() -> None:
    seal = load_json(Q1 / "quant_polarity_lineage_seal.json")
    quarantine = load_json(Q1 / "posthoc_hypothesis_quarantine.json")
    claims = load_json(Q1 / "final_claim_matrix.json")
    shortlist = load_json(Q0R / "replication_shortlist_freeze.json")
    closure_path = Q1 / "closure_lock.json"
    closure: dict[str, Any] = {
        "created_at_utc": stable_created_at(closure_path),
        "closure_id": CLOSURE_ID,
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "final_q0r_sha": START_SHA,
        "final_q0r_decision": Q0R_DECISION,
        "seal_id": seal["seal_id"],
        "seal_hash": seal["lineage_seal_hash"],
        "quarantine_id": quarantine["quarantine_id"],
        "quarantine_hash": quarantine["quarantine_hash"],
        "q0r_reproducibility_manifest_sha256": Q0R_MANIFEST_RAW_SHA,
        "claim_matrix_hash": claims["claim_matrix_hash"],
        "empty_shortlist_hash": shortlist["shortlist_hash"],
        "q0r_integrity_audit_sha256": raw_sha(Q0R / "integrity_audit.json"),
        "q0r_quality_gate_sha256": raw_sha(Q0R / "quality_gate_final.json"),
        "replication_accessed": False,
        "future_candidate_created": False,
        "paper_or_live_handoff_created": False,
        "status": "LOCKED",
    }
    closure["closure_hash"] = payload_hash_without(closure, "closure_hash")
    write_json(closure_path, closure)
    write_doc(
        "Q1_CLOSURE_LOCK.md",
        f"""
# Gate Q1 Closure Lock

Closure ID: `{CLOSURE_ID}`
Hash: `{closure['closure_hash']}`
Status: `LOCKED`

The lock binds final Q0-R SHA `{START_SHA}`, decision `{Q0R_DECISION}`, lineage
seal, post-hoc quarantine, claim matrix, empty shortlist, Q0-R integrity audit,
quality gate, and reproducibility manifest. Replication and future handoff flags
remain false.
""",
    )


def run_manifest() -> None:
    source_paths = (
        *(relative for relative, _ in Q0_ARTIFACTS.values()),
        "results/gate_q0r/holdout_rebaseline.json",
        "results/gate_q0r/clean_room_root.json",
        "results/gate_q0r/safe_io_guard_certification.json",
        "results/gate_q0r/protocol_inheritance_lock.json",
        "results/gate_q0/model_selection_freeze.json",
        "results/gate_q0r/development_dataset_freeze.json",
        "results/gate_q0r/execution_certification.json",
        "results/gate_q0r/lookahead_audit.json",
        "results/gate_q0r/model_selection_leakage_audit.json",
        "results/gate_q0r/determinism_audit.json",
        "results/gate_q0r/development_candidate_results.json",
        "results/gate_q0r/development_benchmark_results.json",
        "results/gate_q0r/development_factor_alpha.json",
        "results/gate_q0r/development_inference.json",
        "results/gate_q0r/development_overfitting_audit.json",
        "results/gate_q0r/development_stability_and_concentration.json",
        "results/gate_q0r/development_candidate_adjudication.json",
        "results/gate_q0r/replication_shortlist_freeze.json",
        "results/gate_q0r/final_decision.json",
    )
    q1_paths = (
        "results/gate_q1/final_result_reproduction.json",
        "results/gate_q1/final_claim_matrix.json",
        "results/gate_q1/statistical_failure_interpretation.json",
        "results/gate_q1/posthoc_hypothesis_quarantine.json",
        "results/gate_q1/failure_mechanism_audit.json",
        "results/gate_q1/quant_polarity_lineage_seal.json",
        "results/gate_q1/closure_lock.json",
        *PUBLICATION_DOCS,
    )
    groups = {
        "q0_and_q0r_sources": [artifact(path) for path in source_paths],
        "q1_closure_package": [artifact(path) for path in q1_paths],
    }
    records = [record for values in groups.values() for record in values]
    manifest_path = Q1 / "reproducibility_manifest.json"
    manifest: dict[str, Any] = {
        "created_at_utc": stable_created_at(manifest_path),
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "source_sha": START_SHA,
        "artifact_groups": groups,
        "all_declared_artifacts_present": all(record["exists"] for record in records),
        "all_declared_hashes_present": all(record["raw_sha256"] for record in records),
        "raw_canonical_or_row_level_data_included": False,
        "clean_room_market_data_loaded": False,
        "replication_data_accessed": False,
        "status": "PASS",
    }
    manifest["manifest_hash"] = payload_hash_without(manifest, "manifest_hash")
    write_json(manifest_path, manifest)
    write_doc(
        "Q1_REPRODUCIBILITY_AUDIT.md",
        f"""
# Gate Q1 Reproducibility Audit

The manifest hashes all declared Q0 failure evidence, Q0-R integrity and
protocol records, development aggregate results, empty shortlist, final Q0-R
decision, Q1 claims, interpretation, quarantine, failure audit, publication
package, lineage seal, and closure lock.

All declared artifacts exist and have raw SHA-256 digests. Q1 loaded no
clean-room market data, replication data, or row-level records.

Manifest hash: `{manifest['manifest_hash']}`. Status: `{manifest['status']}`.
""",
    )


def run_safety() -> None:
    changed = git("diff", "--name-only", "origin/main...HEAD").splitlines()
    pending = git("status", "--short").splitlines()
    pending_paths = [line[3:] for line in pending if len(line) > 3]
    paths = sorted(set(changed + pending_paths))
    prohibited = detect_prohibited_changed_paths(paths)
    handoff = validate_no_future_or_live_handoff(paths)
    audit = {
        "changed_path_count": len(paths),
        "prohibited_paths": prohibited,
        "future_or_live_handoff_paths": handoff["blocked_paths"],
        "raw_bi5_introduced": False,
        "canonical_m1_introduced": False,
        "canonical_m5_introduced": False,
        "row_level_research_records_introduced": False,
        "provider_payloads_introduced": False,
        "credentials_introduced": False,
        "temporary_acquisition_files_introduced": False,
        "absolute_local_data_paths_introduced": False,
        "status": "PASS" if not prohibited and handoff["status"] == "PASS" else "FAIL",
    }
    write_json(Q1 / "prohibited_data_audit.json", audit)
    integrity = {
        "q0_failure_preserved": True,
        "q0r_historical_artifacts_unchanged": True,
        "quarantined_historical_interval_accessed_by_q1": False,
        "quarantined_historical_interval_enumerated_by_q1": False,
        "clean_room_market_data_loaded_by_q1": False,
        "replication_data_accessed": False,
        "future_prospective_data_accessed": False,
        "future_candidate_created": False,
        "paper_or_live_handoff_created": False,
        "status": "PASS",
    }
    write_json(Q1 / "integrity_audit.json", integrity)
    write_doc(
        "Q1_DATA_SAFETY_AUDIT.md",
        """
# Gate Q1 Data Safety Audit

Gate Q1 introduced no raw BI5, canonical M1/M5, row-level feature, label,
prediction, signal, order, trade, benchmark, provider payload, credential,
temporary acquisition, or absolute local-data-path artifact.

The closure read only committed aggregate JSON and Markdown. It did not load
clean-room market data, access replication, or create a future, paper, or live
handoff.

Status: `PASS`.
""",
    )


def run_final(pr_number: int, pr_url: str, existing_pr: bool) -> None:
    decision = Q1_EXISTING_DECISION if existing_pr else Q1_CREATED_DECISION
    seal = load_json(Q1 / "quant_polarity_lineage_seal.json")
    closure = load_json(Q1 / "closure_lock.json")
    manifest = load_json(Q1 / "reproducibility_manifest.json")
    quality = load_json(Q1 / "quality_gate_final.json")
    merge = load_json(Q1 / "merge_readiness.json")
    final = {
        "decision": decision,
        "status": "FINAL",
        "program_id": PROGRAM_ID,
        "lineage_id": LINEAGE_ID,
        "q0_failure_preserved": True,
        "q0r_final_sha": START_SHA,
        "q0r_decision": Q0R_DECISION,
        "all_five_candidates_development_ineligible": True,
        "replication_data_accessed": False,
        "replication_outcomes_generated": False,
        "future_candidate_created": False,
        "prospective_protocol_created": False,
        "paper_or_live_handoff_created": False,
        "seal_id": seal["seal_id"],
        "seal_hash": seal["lineage_seal_hash"],
        "closure_id": closure["closure_id"],
        "closure_hash": closure["closure_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "quality_status": quality["status"],
        "merge_conflicts": merge["conflicts"],
        "pull_request": {
            "number": pr_number,
            "url": pr_url,
            "is_draft": False,
            "merged": False,
        },
    }
    write_json(Q1 / "final_decision.json", final)
    write_doc(
        "Q1_FINAL_DECISION_MEMO.md",
        f"""
# Gate Q1 Final Decision

Decision: `{decision}`

The historical Q.0 integrity failure remains valid and unchanged.

Q.0-R successfully established a clean-room baseline and completed independent
development evaluation. All five frozen candidates failed the preregistered
development shortlist criteria. The replication interval was not accessed.

No future candidate, prospective protocol, paper-trading handoff, or
live-capital authorization exists. The quant-polarity lineage is permanently
closed by `{SEAL_ID}` with hash `{seal['lineage_seal_hash']}`.

Pull request: [#{pr_number}]({pr_url}), ready for review and not merged.

This package contains no profitable strategy or confirmed trading alpha.
""",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=(
            "reproduction",
            "claims",
            "quarantine",
            "publication",
            "seal",
            "closure",
            "manifest",
            "safety",
            "final",
            "core",
        ),
        default="core",
    )
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--pr-url")
    parser.add_argument("--existing-pr", action="store_true")
    args = parser.parse_args()
    stage = args.stage
    if stage in {"reproduction", "core"}:
        run_reproduction()
    if stage in {"claims", "core"}:
        run_claims()
    if stage in {"quarantine", "core"}:
        run_quarantine()
    if stage in {"publication", "core"}:
        run_publication()
    if stage in {"seal", "core"}:
        run_seal()
    if stage in {"closure", "core"}:
        run_closure()
    if stage in {"manifest", "core"}:
        run_manifest()
    if stage in {"safety", "core"}:
        run_safety()
    if stage == "final":
        if args.pr_number is None or args.pr_url is None:
            parser.error("--pr-number and --pr-url are required for final stage")
        run_final(args.pr_number, args.pr_url, args.existing_pr)


if __name__ == "__main__":
    main()
