#!/usr/bin/env python3
"""Real-data validation campaign: end-to-end execution.

Runs the full 10-candidate campaign on real H1 FX data with H4 HTF context,
performs holdout evaluation, generates detector diagnostics, champion bundle,
simplification analysis, and final research package.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.alpha.diagnostics import DetectorDiagnostics, format_detector_diagnostics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
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
logger = logging.getLogger("real_data_campaign")


def _build_candidates(base: AppConfig, split_policy: DataSplitPolicy) -> list:
    """Build the full 10-candidate set."""
    import yaml
    candidates_path = Path(__file__).resolve().parent.parent / "configs" / "campaigns" / "full_validation.yaml"

    with open(candidates_path) as f:
        specs = yaml.safe_load(f) or []

    candidates = []
    for spec in specs:
        label = spec.get("label", "unknown")
        overrides = spec.get("overrides", {})
        status = ConfigStatus(spec.get("status", "locked"))
        cfg = base.model_copy(deep=True)
        for dotted_key, value in overrides.items():
            parts = dotted_key.split(".")
            obj = cfg
            for p in parts[:-1]:
                obj = getattr(obj, p)
            setattr(obj, parts[-1], value)
        candidates.append(freeze_config(
            cfg, label=label, status=status, data_split=split_policy,
            assumptions=spec.get("assumptions", {}),
        ))
    return candidates


def main() -> None:
    output_dir = Path("results/real_data_campaign")
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path("data/real")

    # Load real data — H1 as execution TF, H4 as HTF
    from fx_smc_bot.config import Timeframe
    logger.info("Loading real FX data from %s (H1 execution, H4 HTF)", data_dir)
    data = load_pair_data(data_dir, timeframe=Timeframe.H1)
    if not data:
        logger.error("No data loaded")
        return

    for pair, series in data.items():
        logger.info("  %s: %d bars (%s)", pair.value, len(series), series.timeframe.value)

    htf_data = load_htf_data(data, htf_timeframe=Timeframe.H4, data_dir=data_dir)
    for pair, series in htf_data.items():
        logger.info("  HTF %s: %d bars (%s)", pair.value, len(series), series.timeframe.value)

    # Config
    base_config = AppConfig()
    gate_config = DeploymentGateConfig(max_drawdown_pct=0.21)
    split_policy = DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.8, embargo_bars=10)

    candidates = _build_candidates(base_config, split_policy)
    logger.info("Created %d candidates", len(candidates))

    # === PHASE 1: Training campaign with diagnostics ===
    logger.info("=" * 60)
    logger.info("PHASE 1: Training evaluation (%d candidates)", len(candidates))
    logger.info("=" * 60)

    campaign = ValidationCampaign(
        candidates=candidates, data=data, htf_data=htf_data, gate_config=gate_config,
    )
    runs = campaign.run_full_evaluation()

    # === PHASE 2: Ranking ===
    logger.info("=" * 60)
    logger.info("PHASE 2: Ranking and selection")
    logger.info("=" * 60)

    scorecards = rank_candidates(runs)
    (output_dir / "ranking.md").write_text(format_ranking_table(scorecards))

    champion_sc, challengers = select_champion(scorecards)
    rejected = [sc for sc in scorecards if sc.gate_verdict == "fail"]
    (output_dir / "selection.md").write_text(
        format_selection_report(champion_sc, challengers, rejected)
    )

    for sc in scorecards:
        logger.info("  %s: composite=%.3f sharpe=%.3f trades=%d gate=%s",
                     sc.label, sc.composite_score, sc.raw_sharpe,
                     sc.total_trades, sc.gate_verdict)

    # === PHASE 3: Holdout ===
    logger.info("=" * 60)
    logger.info("PHASE 3: Holdout evaluation")
    logger.info("=" * 60)

    shortlist = [r.candidate for r in runs
                 if r.gate_result and r.gate_result.verdict.value in ("pass", "conditional")]
    holdout_runs = None
    if shortlist:
        holdout_runs = campaign.run_holdout_evaluation(shortlist)
        for hr in holdout_runs:
            m = hr.metrics
            g = hr.gate_result
            logger.info("  Holdout %s: sharpe=%.3f trades=%d gate=%s",
                         hr.candidate.label,
                         m.sharpe_ratio if m else 0,
                         m.total_trades if m else 0,
                         g.verdict.value if g else "N/A")
    else:
        logger.warning("No candidates passed training gate for holdout")

    # === PHASE 4: Simplification + Leaderboards ===
    logger.info("=" * 60)
    logger.info("PHASE 4: Simplification and aggregation")
    logger.info("=" * 60)

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

    # === PHASE 5: Decision memo ===
    logger.info("=" * 60)
    logger.info("PHASE 5: Decision memo")
    logger.info("=" * 60)

    evidence = EvidencePackage(
        candidate_runs=runs, scorecards=scorecards,
        holdout_results=holdout_runs,
        gate_results=[r.gate_result for r in runs if r.gate_result],
    )
    decision = generate_decision_memo(evidence, gate_config)
    (output_dir / "decision_memo.md").write_text(format_decision_memo(decision, evidence))
    logger.info("Decision: %s (confidence: %s)", decision.decision.value, decision.confidence)

    # === PHASE 6: Champion bundle ===
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

    # === PHASE 7: Final research package ===
    logger.info("=" * 60)
    logger.info("PHASE 7: Final research package")
    logger.info("=" * 60)

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

    # Save campaign JSON
    campaign.save_campaign(runs, output_dir, holdout_runs)

    logger.info("=" * 60)
    logger.info("FINAL OUTCOME: %s", continuation.outcome.value)
    logger.info("CONFIDENCE: %s", continuation.confidence)
    logger.info("CHAMPION: %s", continuation.champion_label)
    logger.info("=" * 60)
    logger.info("All artifacts saved to %s", output_dir)


if __name__ == "__main__":
    main()
