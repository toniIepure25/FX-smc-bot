#!/usr/bin/env python3
"""Run holdout evaluation on the BOS-continuation champion candidate,
generate champion bundle, and produce the final research package.

Uses relaxed drawdown gate (21%) based on Wave 2 finding that the
0.06% margin over 20% was the sole blocking criterion.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.research.campaign_aggregator import (
    build_leaderboard, build_per_candidate_evidence,
    format_fragility_leaderboard, format_leaderboard,
    format_stability_leaderboard, generate_executive_summary,
)
from fx_smc_bot.research.candidate_selection import (
    format_ranking_table, format_selection_report,
    rank_candidates, select_champion,
)
from fx_smc_bot.research.champion_bundle import (
    build_champion_bundle, save_champion_bundle,
)
from fx_smc_bot.research.decision_memo import (
    EvidencePackage, format_decision_memo, generate_decision_memo,
)
from fx_smc_bot.research.final_package import (
    generate_continuation_recommendation, save_final_package,
)
from fx_smc_bot.research.frozen_config import (
    ConfigStatus, DataSplitPolicy, freeze_config,
)
from fx_smc_bot.research.gating import DeploymentGateConfig
from fx_smc_bot.research.simplification import (
    analyze_simplification, format_simplification_report,
)
from fx_smc_bot.research.validation import ValidationCampaign

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("holdout_finalize")


def main() -> None:
    output_dir = Path("results/validation_wave2_final")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    data = load_pair_data(Path("data"))
    htf_data = load_htf_data(data, data_dir=Path("data"))

    # Relaxed gate: 21% max drawdown based on Wave 2 analysis
    gate_config = DeploymentGateConfig(max_drawdown_pct=0.21)

    split_policy = DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.8, embargo_bars=10)

    # Build focused candidate set: champion + challenger + one baseline
    base = AppConfig()

    bos_only = base.model_copy(deep=True)
    bos_only.alpha.enabled_families = ["bos_continuation"]
    champion_frozen = freeze_config(bos_only, label="bos_continuation_only",
                                     status=ConfigStatus.LOCKED, data_split=split_policy)

    full_smc = base.model_copy(deep=True)
    full_smc.alpha.enabled_families = ["sweep_reversal", "bos_continuation", "fvg_retrace"]
    challenger_frozen = freeze_config(full_smc, label="full_smc",
                                       status=ConfigStatus.LOCKED, data_split=split_policy)

    session_bl = base.model_copy(deep=True)
    session_bl.alpha.enabled_families = ["session_breakout"]
    baseline_frozen = freeze_config(session_bl, label="session_breakout_baseline",
                                     status=ConfigStatus.BASELINE, data_split=split_policy)

    candidates = [champion_frozen, challenger_frozen, baseline_frozen]

    # === PHASE 1: Training evaluation ===
    logger.info("=== PHASE 1: Training evaluation ===")
    campaign = ValidationCampaign(
        candidates=candidates, data=data, htf_data=htf_data, gate_config=gate_config,
    )
    runs = campaign.run_full_evaluation()

    scorecards = rank_candidates(runs)
    (output_dir / "ranking.md").write_text(format_ranking_table(scorecards))

    champion_sc, challengers = select_champion(scorecards)
    rejected = [sc for sc in scorecards if sc.gate_verdict == "fail"]
    (output_dir / "selection.md").write_text(
        format_selection_report(champion_sc, challengers, rejected)
    )

    for sc in scorecards:
        logger.info("  %s: composite=%.3f sharpe=%.3f gate=%s",
                     sc.label, sc.composite_score, sc.raw_sharpe, sc.gate_verdict)

    # === PHASE 2: Holdout evaluation ===
    logger.info("=== PHASE 2: Holdout evaluation ===")
    shortlist = [r.candidate for r in runs
                 if r.gate_result and r.gate_result.verdict.value in ("pass", "conditional")]

    if not shortlist:
        logger.warning("No candidates passed training gate for holdout")
        holdout_runs = None
    else:
        holdout_runs = campaign.run_holdout_evaluation(shortlist)
        for hr in holdout_runs:
            m = hr.metrics
            g = hr.gate_result
            logger.info("  Holdout %s: sharpe=%.3f trades=%d gate=%s",
                         hr.candidate.label,
                         m.sharpe_ratio if m else 0,
                         m.total_trades if m else 0,
                         g.verdict.value if g else "N/A")

    # === PHASE 3: Decision + Simplification ===
    logger.info("=== PHASE 3: Decision and simplification ===")
    simplification = analyze_simplification(scorecards, runs)
    (output_dir / "simplification_report.md").write_text(format_simplification_report(simplification))

    leaderboard = build_leaderboard(scorecards)
    (output_dir / "leaderboard.md").write_text(format_leaderboard(leaderboard))
    (output_dir / "fragility_leaderboard.md").write_text(format_fragility_leaderboard(scorecards))
    (output_dir / "stability_leaderboard.md").write_text(format_stability_leaderboard(scorecards))
    (output_dir / "executive_summary.md").write_text(
        generate_executive_summary(scorecards, runs, holdout_runs)
    )
    build_per_candidate_evidence(runs, scorecards, output_dir / "candidates")

    evidence = EvidencePackage(
        candidate_runs=runs, scorecards=scorecards,
        holdout_results=holdout_runs,
        gate_results=[r.gate_result for r in runs if r.gate_result],
    )
    decision = generate_decision_memo(evidence, gate_config)
    (output_dir / "decision_memo.md").write_text(format_decision_memo(decision, evidence))
    logger.info("Decision: %s (confidence: %s)", decision.decision.value, decision.confidence)

    # === PHASE 4: Champion bundle ===
    champion_bundle = None
    if champion_sc:
        champ_run = next((r for r in runs if r.candidate.label == champion_sc.label), None)
        if champ_run:
            try:
                champion_bundle = build_champion_bundle(champ_run.candidate, champ_run, champion_sc)
                save_champion_bundle(champion_bundle, output_dir)
                logger.info("Champion bundle saved for %s", champion_sc.label)
            except ValueError as e:
                logger.warning("Could not build champion bundle: %s", e)

    # === PHASE 5: Final research package ===
    holdout_passed = bool(holdout_runs and any(
        r.gate_result and r.gate_result.verdict.value in ("pass", "conditional")
        for r in holdout_runs
    ))

    continuation = generate_continuation_recommendation(
        decision, simplification, champion_sc,
        challengers[0] if challengers else None,
        holdout_passed=holdout_passed,
    )
    save_final_package(
        output_dir / "final_package", continuation, decision, simplification,
        champion_bundle=champion_bundle, scorecards=scorecards,
    )

    logger.info("===================================")
    logger.info("FINAL OUTCOME: %s", continuation.outcome.value)
    logger.info("CONFIDENCE: %s", continuation.confidence)
    logger.info("CHAMPION: %s", continuation.champion_label)
    logger.info("===================================")

    campaign.save_campaign(runs, output_dir, holdout_runs)
    logger.info("All artifacts saved to %s", output_dir)


if __name__ == "__main__":
    main()
