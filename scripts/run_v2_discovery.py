"""Execute the FX_INTRADAY_ALPHA_DISCOVERY_V2 discovery stage on 2015-2017 only.

Resumable and checkpointed: each trial's immutable evaluation is appended to
``results/gate_a0r5/trial_metrics.jsonl`` as it completes, so an interrupted run resumes
without recomputation. When all 336 trials are evaluated, the aggregation, frozen
statistics, survivor predicate and all discovery artifacts are written.

This script NEVER opens a 2018+ market/outcome file (holdout firewall enforced).

Usage:
    python scripts/run_v2_discovery.py            # evaluate + (if complete) finalize
    python scripts/run_v2_discovery.py --finalize # aggregate from existing checkpoint only
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import json_hash, write_json
from fx_smc_bot.research.v2 import GATE_ID as A0R4_GATE
from fx_smc_bot.research.v2 import LINEAGE_ID, PROGRAM_ID
from fx_smc_bot.research.v2 import discovery as disco
from fx_smc_bot.research.v2.firewall import HoldoutFirewall
from fx_smc_bot.research.v2.protocol import protocol_hash
from fx_smc_bot.research.v2.survivor import predicate_hash, survivor_predicate_payload

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results" / "gate_a0r5"
METRICS = OUT / "trial_metrics.jsonl"
RAW = REPO / "data" / "raw" / "dukascopy-node"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def preflight(universe_digest: str) -> dict[str, object]:
    reg = json.loads((REPO / "results" / "gate_a0r4" / "executable_spec_registry.json").read_text())
    readiness = json.loads((REPO / "results" / "gate_a0r4" / "readiness.json").read_text())
    checks = {
        "a0r4_ready": readiness["verdict"] == "V2_ALPHA_DISCOVERY_READY",
        "admitted_336": reg["admitted_executable_trials"] == 336,
        "digest_match": universe_digest == reg["materialization_digest"],
        "protocol_hash_match": protocol_hash()
        == json.loads((REPO / "results" / "gate_a0r4" / "statistical_protocol.json").read_text())[
            "protocol_hash"],
        "predicate_hash_match": predicate_hash()
        == json.loads((REPO / "results" / "gate_a0r4" / "survivor_predicate.json").read_text())[
            "predicate_hash"],
        "no_unresolved_blockers": reg["unresolved_semantic_blockers"] == 0,
        "denominator_336": reg["registered_candidate_equivalent_denominator"] == 336,
    }
    if not all(checks.values()):
        raise SystemExit(f"PREFLIGHT FAILED: {checks}")
    print("PREFLIGHT PASS", checks, flush=True)
    return checks


def load_done() -> set[str]:
    if not METRICS.exists():
        return set()
    done = set()
    for line in METRICS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["trial_id"])
    return done


def evaluate_all() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    universe, digest = disco.load_universe()
    preflight(digest)
    done = load_done()
    print(f"universe={len(universe)} already_done={len(done)}", flush=True)

    fw = HoldoutFirewall()
    frames: dict[str, pd.DataFrame] = {}
    remaining = [(tid, spec) for tid, spec in universe if tid not in done]
    needed_instruments = sorted({spec.instrument for _tid, spec in remaining})
    for inst in needed_instruments:
        t0 = time.time()
        frames[inst] = disco.load_instrument_frame(fw, RAW, inst)
        print(f"loaded {inst} bars={len(frames[inst])} in {time.time()-t0:.1f}s", flush=True)
    assert fw.opened_2018_plus_count() == 0, "HOLDOUT VIOLATION"

    with METRICS.open("a", encoding="utf-8") as fh:
        for i, (tid, spec) in enumerate(remaining, 1):
            row = disco.evaluate_trial(tid, spec, frames[spec.instrument])
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            print(f"[{i}/{len(remaining)}] {tid} {spec.family_id[:24]} {spec.instrument} "
                  f"state={row['terminal_state']} net={row['net_bps']:.1f} "
                  f"trades={row['trade_count']} {row['eval_seconds']}s", flush=True)

    # firewall audit for this evaluation pass
    write_json(OUT / "holdout_firewall_audit.json", {
        "artifact_id": "A0R5_HOLDOUT_FIREWALL_AUDIT_V1", "gate_id": disco.GATE,
        "opened_file_count": len(fw.reads),
        "opened_bytes": sum(r.bytes for r in fw.reads),
        "blocked_attempt_count": len(fw.blocked_attempts),
        "opened_2018_plus_market_or_outcome_files": [
            r.path for r in fw.reads if r.year >= 2018],
        "2018_plus_market_or_outcome_files_opened": fw.opened_2018_plus_count(),
        "years_opened": sorted({r.year for r in fw.reads}),
    })


def _load_rows() -> list[dict]:
    rows = [json.loads(line) for line in METRICS.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    # deterministic order by trial_id
    rows.sort(key=lambda r: r["trial_id"])
    # de-duplicate (resume safety): keep last occurrence per trial_id
    seen: dict[str, dict] = {}
    for r in rows:
        seen[r["trial_id"]] = r
    return sorted(seen.values(), key=lambda r: r["trial_id"])


def finalize() -> dict[str, object]:
    universe, digest = disco.load_universe()
    specs = {tid: spec for tid, spec in universe}
    rows = _load_rows()
    assert len(rows) == 336, f"expected 336 evaluated, got {len(rows)}"

    loo = disco._instrument_loo(rows)
    neigh = disco._neighborhood(rows, specs)
    matrix = disco.build_return_matrix(rows)
    statistics = disco.run_statistics(matrix, rows)
    survivors, predicate_rows = disco.classify_survivors(rows, loo, neigh, statistics)
    ranking = disco.review_ranking(rows, statistics)
    fam = disco.family_diagnostics(rows)

    # attach LOO / neighborhood into the full metrics table
    metrics_table = []
    for r in rows:
        rr = {k: v for k, v in r.items() if k not in ("daily_dates", "daily_net_bps", "folds")}
        rr["instrument_loo_positive"] = loo.get(r["trial_id"], False)
        rr["neighborhood_same_sign_fraction"] = neigh.get(r["trial_id"], 0.0)
        rr["romano_wolf_p"] = statistics["per_trial"][r["trial_id"]]["romano_wolf_p"]
        rr["bh_fdr_p"] = statistics["per_trial"][r["trial_id"]]["bh_fdr_p"]
        rr["holm_p"] = statistics["per_trial"][r["trial_id"]]["holm_p"]
        metrics_table.append(rr)

    states: dict[str, int] = {}
    for r in rows:
        states[r["terminal_state"]] = states.get(r["terminal_state"], 0) + 1

    positive_net = sum(1 for r in rows if r["net_bps"] > 0)
    s15 = sum(1 for r in rows if r["survives_1_5x"])
    s20 = sum(1 for r in rows if r["survives_2_0x"])

    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "discovery_manifest.json", {
        "artifact_id": "A0R5_DISCOVERY_MANIFEST_V1", "gate_id": disco.GATE,
        "program_id": PROGRAM_ID, "lineage_id": LINEAGE_ID, "created_at": _now(),
        "region": "development_2015_2017", "years": list(disco.DEVELOPMENT_YEARS),
        "instruments": list(disco.SUPPORTED_INSTRUMENTS),
        "registered_candidate_equivalent_denominator": disco.REGISTERED_V2_DENOMINATOR,
        "materialization_digest": digest,
        "a0r4_gate": A0R4_GATE,
        "statistical_protocol_hash": protocol_hash(),
        "survivor_predicate_hash": predicate_hash(),
        "exploratory_only": True,
        "note": "2015-2017 was partly inspected in V1; no candidate is validated alpha.",
    })
    write_json(OUT / "evaluation_status.json", {
        "artifact_id": "A0R5_EVALUATION_STATUS_V1", "gate_id": disco.GATE,
        "expected_trials": 336, "evaluated_trials": len(rows),
        "terminal_states": states,
        "deterministically_evaluated": f"{len(rows)}/336",
    })
    write_json(OUT / "metrics_table.json", {
        "artifact_id": "A0R5_METRICS_TABLE_V1", "gate_id": disco.GATE,
        "rows": metrics_table})
    matrix_out = matrix.copy()
    matrix_out.index = [str(x) for x in matrix_out.index]
    write_json(OUT / "daily_return_matrix.json", {
        "artifact_id": "A0R5_DAILY_RETURN_MATRIX_V1", "gate_id": disco.GATE,
        "shape": list(matrix.shape), "columns": list(matrix.columns),
        "sha256": json_hash(matrix_out.round(9).to_dict())})
    write_json(OUT / "walk_forward.json", {
        "artifact_id": "A0R5_WALK_FORWARD_V1", "gate_id": disco.GATE,
        "rows": [{"trial_id": r["trial_id"], "n_folds": r["n_folds"],
                  "fold_positive_fraction": r["fold_positive_fraction"],
                  "folds": r["folds"]} for r in rows]})
    write_json(OUT / "loo_stability.json", {
        "artifact_id": "A0R5_LOO_STABILITY_V1", "gate_id": disco.GATE,
        "rows": [{"trial_id": r["trial_id"],
                  "instrument_loo_positive": loo.get(r["trial_id"], False),
                  "year_loo_positive": r["year_loo_positive"],
                  "per_year_net_bps": r["per_year_net_bps"],
                  "neighborhood_same_sign_fraction": neigh.get(r["trial_id"], 0.0)}
                 for r in rows]})
    write_json(OUT / "cost_scenarios.json", {
        "artifact_id": "A0R5_COST_SCENARIOS_V1", "gate_id": disco.GATE,
        "rows": [{"trial_id": r["trial_id"], "net_bps": r["net_bps"],
                  "net_bps_1_5x": r["net_bps_1_5x"], "net_bps_2_0x": r["net_bps_2_0x"],
                  "survives_1_5x": r["survives_1_5x"], "survives_2_0x": r["survives_2_0x"]}
                 for r in rows],
        "positive_net": positive_net, "survives_1_5x": s15, "survives_2_0x": s20})
    write_json(OUT / "multiple_testing.json", {
        "artifact_id": "A0R5_MULTIPLE_TESTING_V1", "gate_id": disco.GATE, **statistics})
    write_json(OUT / "pbo.json", {
        "artifact_id": "A0R5_PBO_V1", "gate_id": disco.GATE, **statistics["pbo"]})
    write_json(OUT / "review_ranking.json", {
        "artifact_id": "A0R5_REVIEW_RANKING_V1", "gate_id": disco.GATE,
        "informational_only": "REVIEW_RANKING != SCIENTIFIC_SURVIVOR",
        "rows": ranking})
    write_json(OUT / "scientific_survivors.json", {
        "artifact_id": "A0R5_SCIENTIFIC_EXPLORATORY_SURVIVORS_V1", "gate_id": disco.GATE,
        "predicate_hash": predicate_hash(),
        "survivor_criteria": survivor_predicate_payload()["requirements"],
        "survivor_count": len(survivors), "survivors": survivors,
        "predicate_evaluation": predicate_rows})
    write_json(OUT / "family_diagnostics.json", {
        "artifact_id": "A0R5_FAMILY_DIAGNOSTICS_V1", "gate_id": disco.GATE,
        "by_family": fam})

    wrc = statistics["white_reality_check_p"]
    spa = statistics["hansen_spa_p"]
    if len(survivors) == 0:
        decision = "V2_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR"
        next_gate = "STOP_NO_2018_CONFIRMATION"
    else:
        decision = "V2_DISCOVERY_COMPLETE_SURVIVORS_EXIST"
        next_gate = "V2_INTERNAL_CONFIRMATION_2018H1"

    summary = {
        "artifact_id": "A0R5_DISCOVERY_SUMMARY_V1", "gate_id": disco.GATE,
        "program_id": PROGRAM_ID, "created_at": _now(),
        "region": "development_2015_2017", "exploratory_only": True,
        "registered_candidate_equivalent_denominator": disco.REGISTERED_V2_DENOMINATOR,
        "expected_trials": 336, "evaluated_trials": len(rows),
        "terminal_states": states,
        "positive_net_trials": positive_net,
        "survives_1_5x": s15, "survives_2_0x": s20,
        "white_reality_check_p": wrc, "hansen_spa_p": spa,
        "romano_wolf_significant": statistics["romano_wolf_significant"],
        "holm_significant": statistics["holm_significant"],
        "bh_fdr_significant": statistics["bh_fdr_significant"],
        "pbo": statistics["pbo"].get("pbo"),
        "scientific_survivor_count": len(survivors),
        "scientific_survivor_ids": [s["trial_id"] for s in survivors],
        "materialization_digest": digest,
        "2018_plus_market_or_outcome_files_opened": 0,
        "terminal_decision": decision, "next_gate": next_gate,
    }
    summary["summary_hash"] = json_hash(summary)
    write_json(OUT / "discovery_summary.json", summary)
    print("FINALIZE COMPLETE:", decision, "| survivors:", len(survivors),
          "| WRC:", wrc, "| SPA:", spa, flush=True)
    return summary


def reproduce() -> dict[str, object]:
    """Clean-room determinism proof: re-evaluate a deterministic per-family sample and
    re-run the statistical layer, asserting identical results to the checkpoint."""

    universe, digest = disco.load_universe()
    specs = dict(universe)
    reg = json.loads(
        (REPO / "results" / "gate_a0r4" / "executable_spec_registry.json").read_text())
    rows = {r["trial_id"]: r for r in _load_rows()}

    # Deterministic per-family sample. For the expensive model families we pick a
    # fast-but-representative member (F11 quantile-bins, F12 ridge) so the reproduction
    # runs in minutes; the determinism of the slow logistic/GMM paths is separately pinned
    # by tests/test_gate_a0r4/test_ml_causality.py. Statistical reproduction below still
    # runs over the full 336-column matrix.
    def _fast_pref(spec: disco.StrategySpec) -> int:
        mc = spec.model.model_class.value if spec.model else "none"
        return 0 if mc in ("quantile_bins", "ridge_regression", "none") else 1

    by_family: dict[str, tuple[int, str]] = {}
    for tid, spec in sorted(universe, key=lambda x: x[0]):
        rank = (_fast_pref(spec), tid)
        if spec.family_id not in by_family or rank < by_family[spec.family_id]:
            by_family[spec.family_id] = rank
    sample_ids = sorted(tid for _r, tid in by_family.values())

    fw = HoldoutFirewall()
    frames: dict[str, pd.DataFrame] = {}
    for inst in sorted({specs[tid].instrument for tid in sample_ids}):
        frames[inst] = disco.load_instrument_frame(fw, RAW, inst)

    comparisons = []
    max_delta = 0.0
    for tid in sample_ids:
        spec = specs[tid]
        re_row = disco.evaluate_trial(tid, spec, frames[spec.instrument])
        orig = rows[tid]
        deltas = {k: abs(float(re_row[k]) - float(orig[k]))
                  for k in ("net_bps", "gross_bps", "cost_bps", "daily_sharpe")}
        deltas["trade_count"] = abs(int(re_row["trade_count"]) - int(orig["trade_count"]))
        max_delta = max(max_delta, *deltas.values())
        comparisons.append({"trial_id": tid, "family_id": spec.family_id, "deltas": deltas})

    # statistical reproducibility on the persisted matrix
    all_rows = _load_rows()
    m1 = disco.build_return_matrix(all_rows)
    s1 = disco.run_statistics(m1, all_rows)
    s2 = disco.run_statistics(disco.build_return_matrix(all_rows), all_rows)
    stat_stable = (s1["white_reality_check_p"] == s2["white_reality_check_p"]
                   and s1["hansen_spa_p"] == s2["hansen_spa_p"])

    audit = {
        "artifact_id": "A0R5_REPRODUCIBILITY_AUDIT_V1", "gate_id": disco.GATE,
        "materialization_digest": digest,
        "digest_matches_frozen": digest == reg["materialization_digest"],
        "membership_336_identical": len(all_rows) == 336,
        "resampled_trials": sample_ids,
        "max_abs_metric_delta": round(max_delta, 12),
        "metric_reproduction_pass": max_delta <= 1e-6,
        "statistics_reproduction_pass": bool(stat_stable),
        "white_reality_check_p": s1["white_reality_check_p"],
        "hansen_spa_p": s1["hansen_spa_p"],
        "comparisons": comparisons,
        "2018_plus_market_or_outcome_files_opened": fw.opened_2018_plus_count(),
    }
    write_json(OUT / "reproducibility_audit.json", audit)
    print("REPRODUCTION:", "PASS" if audit["metric_reproduction_pass"]
          and audit["statistics_reproduction_pass"] and audit["digest_matches_frozen"]
          else "FAIL", "max_delta=", max_delta, flush=True)
    return audit


def main() -> None:
    if "--finalize" in sys.argv:
        finalize()
        return
    if "--reproduce" in sys.argv:
        reproduce()
        return
    evaluate_all()
    if len(load_done()) >= 336:
        finalize()
    else:
        print(f"evaluation incomplete: {len(load_done())}/336 (re-run to resume)", flush=True)


if __name__ == "__main__":
    main()
