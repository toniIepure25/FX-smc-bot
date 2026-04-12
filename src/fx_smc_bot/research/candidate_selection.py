"""Champion/challenger candidate selection and ranking.

Ranks strategy candidates by a composite score that balances raw
performance, robustness, simplicity, OOS consistency, execution
fragility, and diversification. Produces scorecards and selection
reports for disciplined strategy promotion decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from fx_smc_bot.research.gating import GateVerdict

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun


@dataclass(frozen=True, slots=True)
class ScorecardWeights:
    robustness: float = 0.25
    simplicity: float = 0.15
    oos_consistency: float = 0.20
    execution_fragility: float = 0.20
    diversification: float = 0.10
    raw_performance: float = 0.10


@dataclass(slots=True)
class CandidateScorecard:
    label: str
    raw_sharpe: float = 0.0
    stressed_sharpe: float = 0.0
    simplicity_score: float = 0.0
    oos_score: float = 0.0
    diversification_score: float = 0.0
    stability_score: float = 0.0
    robustness_score: float = 0.0
    fragility_penalty: float = 0.0
    composite_score: float = 0.0
    gate_verdict: str = "fail"
    rank: int = 0
    recommendation: str = ""
    total_trades: int = 0
    total_pnl: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    n_families: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "rank": self.rank,
            "composite": round(self.composite_score, 4),
            "raw_sharpe": round(self.raw_sharpe, 3),
            "stressed_sharpe": round(self.stressed_sharpe, 3),
            "simplicity": round(self.simplicity_score, 3),
            "oos": round(self.oos_score, 3),
            "diversification": round(self.diversification_score, 3),
            "stability": round(self.stability_score, 3),
            "robustness": round(self.robustness_score, 3),
            "fragility": round(self.fragility_penalty, 3),
            "gate": self.gate_verdict,
            "recommendation": self.recommendation,
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "profit_factor": round(self.profit_factor, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "n_families": self.n_families,
        }


def rank_candidates(
    runs: list[CandidateRun],
    weights: ScorecardWeights | None = None,
) -> list[CandidateScorecard]:
    """Compute composite scores and rank candidates."""
    w = weights or ScorecardWeights()
    scorecards: list[CandidateScorecard] = []

    for run in runs:
        m = run.metrics
        raw_sharpe = m.sharpe_ratio if m else 0.0

        stressed_sharpe = 0.0
        if run.stress_report and run.stress_report.results:
            conservative = [r for r in run.stress_report.results if r.scenario_name == "conservative"]
            stressed_sharpe = conservative[0].sharpe_ratio if conservative else run.stress_report.results[-1].sharpe_ratio

        fragility = 1.0 - (stressed_sharpe / raw_sharpe) if raw_sharpe > 0 else 1.0
        fragility = max(0.0, min(1.0, fragility))

        scores = run.scores
        simp = scores.simplicity if scores else 0.0
        oos = scores.oos_consistency if scores else 0.0
        div = scores.diversification if scores else 0.0
        stab = scores.stability if scores else 0.0
        rob = scores.robustness if scores else 0.0

        perf_norm = max(0.0, min(1.0, raw_sharpe / 3.0))

        composite = (
            w.robustness * rob
            + w.simplicity * simp
            + w.oos_consistency * oos
            + w.execution_fragility * (1.0 - fragility)
            + w.diversification * div
            + w.raw_performance * perf_norm
        )

        gate_verdict = run.gate_result.verdict.value if run.gate_result else "fail"
        n_fam = len(run.candidate.config.alpha.enabled_families)

        scorecards.append(CandidateScorecard(
            label=run.candidate.label,
            raw_sharpe=raw_sharpe,
            stressed_sharpe=stressed_sharpe,
            simplicity_score=simp,
            oos_score=oos,
            diversification_score=div,
            stability_score=stab,
            robustness_score=rob,
            fragility_penalty=fragility,
            composite_score=composite,
            gate_verdict=gate_verdict,
            total_trades=m.total_trades if m else 0,
            total_pnl=m.total_pnl if m else 0.0,
            profit_factor=m.profit_factor if m else 0.0,
            max_drawdown_pct=m.max_drawdown_pct if m else 0.0,
            n_families=n_fam,
        ))

    scorecards.sort(key=lambda s: s.composite_score, reverse=True)
    for i, sc in enumerate(scorecards):
        sc.rank = i + 1
        sc.recommendation = _recommendation(sc)

    return scorecards


def _recommendation(sc: CandidateScorecard) -> str:
    if sc.gate_verdict == "fail":
        return "REJECT: fails deployment gate"
    if sc.fragility_penalty > 0.5:
        return "CAUTION: high execution fragility"
    if sc.composite_score >= 0.5 and sc.gate_verdict == "pass":
        return "PROMOTE: strong candidate for paper testing"
    if sc.composite_score >= 0.3:
        return "CONDITIONAL: marginal candidate, review before promoting"
    return "DEMOTE: insufficient composite score"


def select_champion(
    scorecards: list[CandidateScorecard],
) -> tuple[CandidateScorecard | None, list[CandidateScorecard]]:
    """Select champion (rank 1 if gate passes) and viable challengers."""
    if not scorecards:
        return None, []

    champion = None
    challengers: list[CandidateScorecard] = []

    for sc in scorecards:
        if sc.gate_verdict in ("pass", "conditional") and champion is None:
            champion = sc
        elif sc.gate_verdict in ("pass", "conditional"):
            challengers.append(sc)

    return champion, challengers


def format_ranking_table(scorecards: list[CandidateScorecard]) -> str:
    """Format scorecards as a markdown comparison table."""
    lines = [
        "# Candidate Ranking",
        "",
        "| Rank | Label | Composite | Sharpe | Stressed | Simplicity | OOS | Fragility | Gate | Recommendation |",
        "|------|-------|-----------|--------|----------|------------|-----|-----------|------|----------------|",
    ]
    for sc in scorecards:
        lines.append(
            f"| {sc.rank} | {sc.label} | {sc.composite_score:.3f} | "
            f"{sc.raw_sharpe:.3f} | {sc.stressed_sharpe:.3f} | "
            f"{sc.simplicity_score:.2f} | {sc.oos_score:.2f} | "
            f"{sc.fragility_penalty:.2f} | {sc.gate_verdict} | {sc.recommendation} |"
        )
    return "\n".join(lines)


def format_selection_report(
    champion: CandidateScorecard | None,
    challengers: list[CandidateScorecard],
    rejected: list[CandidateScorecard],
) -> str:
    """Full selection report with champion/challenger/rejected breakdown."""
    lines = ["# Strategy Selection Report", ""]

    if champion:
        lines.append("## Champion")
        lines.append(f"**{champion.label}** (composite: {champion.composite_score:.3f})")
        lines.append(f"- Sharpe: {champion.raw_sharpe:.3f} (stressed: {champion.stressed_sharpe:.3f})")
        lines.append(f"- Fragility: {champion.fragility_penalty:.2f}")
        lines.append(f"- Simplicity: {champion.simplicity_score:.2f}")
        lines.append(f"- Gate: {champion.gate_verdict}")
        lines.append(f"- Recommendation: {champion.recommendation}")
    else:
        lines.append("## No Champion Selected")
        lines.append("No candidate passed the deployment gate with sufficient composite score.")

    if challengers:
        lines.append("")
        lines.append("## Challengers")
        for ch in challengers:
            lines.append(f"- **{ch.label}**: composite={ch.composite_score:.3f}, "
                         f"sharpe={ch.raw_sharpe:.3f}, gate={ch.gate_verdict}")

    if rejected:
        lines.append("")
        lines.append("## Rejected")
        for rj in rejected:
            lines.append(f"- **{rj.label}**: {rj.recommendation}")

    return "\n".join(lines)
