"""Campaign result aggregation, leaderboards, and artifact indexing.

Consolidates outputs from validation campaigns into global leaderboards,
per-candidate evidence directories, and executive summary tables.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun

from fx_smc_bot.research.candidate_selection import CandidateScorecard

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LeaderboardEntry:
    rank: int
    label: str
    composite: float
    sharpe: float
    stressed_sharpe: float
    fragility: float
    pnl: float
    trades: int
    gate: str
    families: int
    stability: float
    robustness: float
    recommendation: str


@dataclass(slots=True)
class CampaignArtifactIndex:
    """Tracks all output artifacts from a campaign for review."""
    campaign_id: str = ""
    timestamp: str = ""
    output_dir: str = ""
    files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "timestamp": self.timestamp,
            "output_dir": self.output_dir,
            "files": self.files,
        }


def build_leaderboard(scorecards: list[CandidateScorecard]) -> list[LeaderboardEntry]:
    """Convert ranked scorecards into a leaderboard."""
    return [
        LeaderboardEntry(
            rank=sc.rank, label=sc.label,
            composite=sc.composite_score, sharpe=sc.raw_sharpe,
            stressed_sharpe=sc.stressed_sharpe, fragility=sc.fragility_penalty,
            pnl=sc.total_pnl, trades=sc.total_trades, gate=sc.gate_verdict,
            families=sc.n_families, stability=sc.stability_score,
            robustness=sc.robustness_score, recommendation=sc.recommendation,
        )
        for sc in scorecards
    ]


def format_leaderboard(entries: list[LeaderboardEntry], title: str = "Candidate Leaderboard") -> str:
    """Format leaderboard as markdown."""
    lines = [
        f"# {title}",
        "",
        "| Rank | Label | Composite | Sharpe | Stressed | Fragility | PnL | Trades | Families | Gate | Recommendation |",
        "|------|-------|-----------|--------|----------|-----------|-----|--------|----------|------|----------------|",
    ]
    for e in entries:
        lines.append(
            f"| {e.rank} | {e.label} | {e.composite:.3f} | {e.sharpe:.3f} | "
            f"{e.stressed_sharpe:.3f} | {e.fragility:.2f} | {e.pnl:,.0f} | "
            f"{e.trades} | {e.families} | {e.gate} | {e.recommendation} |"
        )
    return "\n".join(lines)


def format_fragility_leaderboard(scorecards: list[CandidateScorecard]) -> str:
    """Rank by execution fragility (least fragile first)."""
    sorted_sc = sorted(scorecards, key=lambda s: s.fragility_penalty)
    lines = [
        "# Fragility Leaderboard (least fragile first)",
        "",
        "| Rank | Label | Fragility | Sharpe | Stressed Sharpe | Gate |",
        "|------|-------|-----------|--------|-----------------|------|",
    ]
    for i, sc in enumerate(sorted_sc, 1):
        lines.append(
            f"| {i} | {sc.label} | {sc.fragility_penalty:.3f} | "
            f"{sc.raw_sharpe:.3f} | {sc.stressed_sharpe:.3f} | {sc.gate_verdict} |"
        )
    return "\n".join(lines)


def format_stability_leaderboard(scorecards: list[CandidateScorecard]) -> str:
    """Rank by stability score (most stable first)."""
    sorted_sc = sorted(scorecards, key=lambda s: s.stability_score, reverse=True)
    lines = [
        "# Stability Leaderboard (most stable first)",
        "",
        "| Rank | Label | Stability | Robustness | Diversification | Gate |",
        "|------|-------|-----------|------------|-----------------|------|",
    ]
    for i, sc in enumerate(sorted_sc, 1):
        lines.append(
            f"| {i} | {sc.label} | {sc.stability_score:.3f} | "
            f"{sc.robustness_score:.3f} | {sc.diversification_score:.3f} | {sc.gate_verdict} |"
        )
    return "\n".join(lines)


def build_per_candidate_evidence(
    runs: list[CandidateRun],
    scorecards: list[CandidateScorecard],
    output_dir: Path,
) -> CampaignArtifactIndex:
    """Save per-candidate evidence directories and return artifact index."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index = CampaignArtifactIndex(
        campaign_id=f"campaign_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        timestamp=datetime.utcnow().isoformat(),
        output_dir=str(output_dir),
    )

    sc_map = {sc.label: sc for sc in scorecards}

    for run in runs:
        cand_dir = output_dir / run.candidate.label
        cand_dir.mkdir(parents=True, exist_ok=True)

        # Run data
        run_path = cand_dir / "run.json"
        with open(run_path, "w") as f:
            json.dump(run.to_dict(), f, indent=2, default=str)
        index.files[f"{run.candidate.label}/run.json"] = str(run_path)

        # Scorecard
        sc = sc_map.get(run.candidate.label)
        if sc:
            sc_path = cand_dir / "scorecard.json"
            with open(sc_path, "w") as f:
                json.dump(sc.to_dict(), f, indent=2)
            index.files[f"{run.candidate.label}/scorecard.json"] = str(sc_path)

        # Frozen candidate config
        fc_path = cand_dir / "frozen_candidate.json"
        with open(fc_path, "w") as f:
            json.dump(run.candidate.to_dict(), f, indent=2, default=str)
        index.files[f"{run.candidate.label}/frozen_candidate.json"] = str(fc_path)

    # Save index
    idx_path = output_dir / "artifact_index.json"
    with open(idx_path, "w") as f:
        json.dump(index.to_dict(), f, indent=2)
    index.files["artifact_index.json"] = str(idx_path)

    return index


def generate_executive_summary(
    scorecards: list[CandidateScorecard],
    runs: list[CandidateRun],
    holdout_runs: list[CandidateRun] | None = None,
) -> str:
    """Generate a markdown executive summary of the validation campaign."""
    n_total = len(scorecards)
    n_pass = sum(1 for sc in scorecards if sc.gate_verdict in ("pass", "conditional"))
    n_fail = n_total - n_pass
    best = scorecards[0] if scorecards else None

    lines = [
        "# Validation Campaign Executive Summary",
        "",
        f"**Candidates evaluated**: {n_total}",
        f"**Gate pass/conditional**: {n_pass}",
        f"**Gate fail**: {n_fail}",
        "",
    ]

    if best:
        lines.append(f"**Top candidate**: {best.label} (composite={best.composite_score:.3f}, "
                      f"Sharpe={best.raw_sharpe:.3f}, gate={best.gate_verdict})")
        lines.append("")

    # Trade volume summary
    total_trades = sum(sc.total_trades for sc in scorecards)
    lines.append(f"**Total trades across all candidates**: {total_trades}")

    # Family coverage
    family_counts: dict[int, int] = {}
    for sc in scorecards:
        family_counts[sc.n_families] = family_counts.get(sc.n_families, 0) + 1
    lines.append(f"**Family distribution**: {dict(sorted(family_counts.items()))}")
    lines.append("")

    # Holdout summary
    if holdout_runs:
        lines.append("## Holdout Results")
        lines.append("")
        for hr in holdout_runs:
            m = hr.metrics
            gate = hr.gate_result
            sharpe_str = f"{m.sharpe_ratio:.3f}" if m else "N/A"
            trades_str = str(m.total_trades) if m else "0"
            gate_str = gate.verdict.value if gate else "N/A"
            lines.append(
                f"- **{hr.candidate.label}**: "
                f"Sharpe={sharpe_str}, trades={trades_str}, gate={gate_str}"
            )
        lines.append("")

    # Fragility overview
    fragile = [sc for sc in scorecards if sc.fragility_penalty > 0.3]
    if fragile:
        lines.append("## Fragility Concerns")
        lines.append("")
        for sc in fragile:
            lines.append(f"- {sc.label}: fragility={sc.fragility_penalty:.2f}")
        lines.append("")

    return "\n".join(lines)
