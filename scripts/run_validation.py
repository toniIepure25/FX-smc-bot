#!/usr/bin/env python3
"""Full validation campaign CLI.

Orchestrates: freeze configs -> train/val/holdout split -> full evaluation
-> ranking -> holdout on shortlist -> decision memo -> optional paper campaign.

Usage
-----
    python scripts/run_validation.py --data-dir data/ --output-dir results/validation

    python scripts/run_validation.py \
        --data-dir data/ \
        --config configs/base.yaml \
        --candidates configs/campaigns/full_validation.yaml \
        --output-dir results/validation
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.frozen_config import (
    ConfigStatus,
    DataSplitPolicy,
    freeze_config,
)
from fx_smc_bot.research.validation import ValidationCampaign
from fx_smc_bot.research.candidate_selection import (
    format_ranking_table,
    format_selection_report,
    rank_candidates,
    select_champion,
)
from fx_smc_bot.research.decision_memo import (
    EvidencePackage,
    format_decision_memo,
    generate_decision_memo,
)
from fx_smc_bot.research.gating import DeploymentGateConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("run_validation")


def _load_config(path: str | None) -> AppConfig:
    if path and Path(path).exists():
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f)
        return AppConfig(**raw) if raw else AppConfig()
    return AppConfig()


def _build_candidates(
    base: AppConfig,
    candidates_path: str | None,
    split_policy: DataSplitPolicy,
) -> list:
    """Build frozen candidates from a YAML candidates file or defaults."""
    from fx_smc_bot.research.frozen_config import FrozenCandidate

    candidates = []

    if candidates_path and Path(candidates_path).exists():
        import yaml
        with open(candidates_path) as f:
            specs = yaml.safe_load(f) or []

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
    else:
        candidates.append(freeze_config(
            base, label="full_smc", data_split=split_policy,
        ))
        reduced = base.model_copy(deep=True)
        reduced.alpha.enabled_families = ["sweep_reversal"]
        candidates.append(freeze_config(
            reduced, label="sweep_only", data_split=split_policy,
        ))

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full validation campaign")
    parser.add_argument("--data-dir", required=True, help="Directory with CSV data files")
    parser.add_argument("--output-dir", default="results/validation", help="Output directory")
    parser.add_argument("--config", default=None, help="Base config YAML path")
    parser.add_argument("--candidates", default=None, help="Candidates YAML list")
    parser.add_argument("--holdout", action="store_true", help="Run holdout evaluation on shortlist")
    parser.add_argument("--paper", action="store_true", help="Run paper campaign on champion")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = _load_config(args.config)
    gate_config = base_config.deployment_gate if hasattr(base_config, "deployment_gate") else DeploymentGateConfig()

    split_policy = DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.8, embargo_bars=10)

    logger.info("Loading data from %s", args.data_dir)
    data = load_pair_data(Path(args.data_dir))
    if not data:
        logger.error("No data loaded")
        return

    logger.info("Generating HTF context data")
    htf_data = load_htf_data(data, data_dir=Path(args.data_dir))

    logger.info("Building frozen candidates")
    candidates = _build_candidates(base_config, args.candidates, split_policy)
    logger.info("Created %d candidates", len(candidates))

    logger.info("Running full evaluation campaign")
    campaign = ValidationCampaign(
        candidates=candidates,
        data=data,
        htf_data=htf_data,
        gate_config=gate_config,
    )
    runs = campaign.run_full_evaluation()

    logger.info("Ranking candidates")
    scorecards = rank_candidates(runs)
    ranking_md = format_ranking_table(scorecards)
    (output_dir / "ranking.md").write_text(ranking_md)
    logger.info("Ranking saved to %s", output_dir / "ranking.md")

    champion, challengers = select_champion(scorecards)
    rejected = [sc for sc in scorecards if sc.gate_verdict == "fail"]
    selection_md = format_selection_report(champion, challengers, rejected)
    (output_dir / "selection.md").write_text(selection_md)

    holdout_runs = None
    if args.holdout and champion:
        logger.info("Running holdout evaluation on shortlist")
        shortlist_configs = [r.candidate for r in runs
                            if r.gate_result and r.gate_result.verdict.value in ("pass", "conditional")]
        holdout_runs = campaign.run_holdout_evaluation(shortlist_configs)

    # Simplification analysis
    from fx_smc_bot.research.simplification import analyze_simplification, format_simplification_report
    logger.info("Analyzing strategy simplification")
    simplification = analyze_simplification(scorecards, runs)
    (output_dir / "simplification_report.md").write_text(format_simplification_report(simplification))

    # Leaderboards
    from fx_smc_bot.research.campaign_aggregator import (
        build_leaderboard, build_per_candidate_evidence,
        format_fragility_leaderboard, format_leaderboard,
        format_stability_leaderboard, generate_executive_summary,
    )
    leaderboard = build_leaderboard(scorecards)
    (output_dir / "leaderboard.md").write_text(format_leaderboard(leaderboard))
    (output_dir / "fragility_leaderboard.md").write_text(format_fragility_leaderboard(scorecards))
    (output_dir / "stability_leaderboard.md").write_text(format_stability_leaderboard(scorecards))
    (output_dir / "executive_summary.md").write_text(
        generate_executive_summary(scorecards, runs, holdout_runs)
    )

    # Per-candidate evidence directories
    build_per_candidate_evidence(runs, scorecards, output_dir / "candidates")

    # Decision memo
    logger.info("Generating decision memo")
    evidence = EvidencePackage(
        candidate_runs=runs,
        scorecards=scorecards,
        holdout_results=holdout_runs,
        gate_results=[r.gate_result for r in runs if r.gate_result],
    )
    decision = generate_decision_memo(evidence, gate_config)
    memo_md = format_decision_memo(decision, evidence)
    (output_dir / "decision_memo.md").write_text(memo_md)
    logger.info("Decision: %s (confidence: %s)", decision.decision.value, decision.confidence)

    # Champion bundle
    from fx_smc_bot.research.champion_bundle import build_champion_bundle, save_champion_bundle
    champion_bundle = None
    if champion:
        champ_run = next((r for r in runs if r.candidate.label == champion.label), None)
        if champ_run:
            try:
                champion_bundle = build_champion_bundle(champ_run.candidate, champ_run, champion)
                save_champion_bundle(champion_bundle, output_dir)
                logger.info("Champion bundle saved for %s", champion.label)
            except ValueError as e:
                logger.warning("Could not build champion bundle: %s", e)

    # Final research package
    from fx_smc_bot.research.final_package import (
        generate_continuation_recommendation, save_final_package,
    )
    holdout_passed = bool(holdout_runs and any(
        r.gate_result and r.gate_result.verdict.value in ("pass", "conditional")
        for r in holdout_runs
    ))
    continuation = generate_continuation_recommendation(
        decision, simplification, champion, challengers[0] if challengers else None,
        holdout_passed=holdout_passed,
    )
    save_final_package(
        output_dir / "final_package", continuation, decision, simplification,
        champion_bundle=champion_bundle, scorecards=scorecards,
    )
    logger.info("Final recommendation: %s (confidence: %s)",
                continuation.outcome.value, continuation.confidence)

    # Save full campaign data as JSON
    campaign.save_campaign(runs, output_dir, holdout_runs)

    logger.info("All artifacts saved to %s", output_dir)


if __name__ == "__main__":
    main()
