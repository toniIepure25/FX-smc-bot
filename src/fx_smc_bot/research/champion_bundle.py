"""Champion hardening: evidence bundles, frozen manifests, and re-challenge rules.

Produces a locked champion artifact package that captures the full evidence
chain: config, metrics, gate results, stress results, scorecard, and
invalidation criteria. Supports challenger comparison and champion retirement.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fx_smc_bot.research.validation import CandidateRun

from fx_smc_bot.research.candidate_selection import CandidateScorecard
from fx_smc_bot.research.frozen_config import FrozenCandidate, validate_frozen
from fx_smc_bot.research.gating import GateResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutionProfile:
    """Accepted execution assumptions for the champion."""
    fill_policy: str = "pessimistic"
    slippage_model: str = "volatility"
    spread_model: str = "from_data"
    latency_assumption: str = "next_bar"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_policy": self.fill_policy,
            "slippage_model": self.slippage_model,
            "spread_model": self.spread_model,
            "latency_assumption": self.latency_assumption,
        }


@dataclass(slots=True)
class InvalidationCriteria:
    """Conditions that would retire this champion."""
    max_holdout_drawdown_pct: float = 0.25
    min_holdout_sharpe: float = 0.2
    max_paper_discrepancy_pct: float = 10.0
    max_consecutive_losing_weeks: int = 4
    staleness_days: int = 90

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_holdout_drawdown_pct": self.max_holdout_drawdown_pct,
            "min_holdout_sharpe": self.min_holdout_sharpe,
            "max_paper_discrepancy_pct": self.max_paper_discrepancy_pct,
            "max_consecutive_losing_weeks": self.max_consecutive_losing_weeks,
            "staleness_days": self.staleness_days,
        }


@dataclass(slots=True)
class ChampionBundle:
    """Complete frozen evidence package for a champion strategy."""
    champion_label: str = ""
    config_hash: str = ""
    frozen_at: str = ""
    scorecard: dict[str, Any] = field(default_factory=dict)
    gate_result: dict[str, Any] = field(default_factory=dict)
    stress_summary: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    execution_profile: dict[str, Any] = field(default_factory=dict)
    invalidation_criteria: dict[str, Any] = field(default_factory=dict)
    data_fingerprint: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    bundle_hash: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "champion_label": self.champion_label,
            "config_hash": self.config_hash,
            "frozen_at": self.frozen_at,
            "bundle_hash": self.bundle_hash,
            "scorecard": self.scorecard,
            "gate_result": self.gate_result,
            "stress_summary": self.stress_summary,
            "metrics": self.metrics,
            "execution_profile": self.execution_profile,
            "invalidation_criteria": self.invalidation_criteria,
            "data_fingerprint": self.data_fingerprint,
            "config_snapshot": self.config_snapshot,
            "notes": self.notes,
        }


def build_champion_bundle(
    candidate: FrozenCandidate,
    run: "CandidateRun",
    scorecard: CandidateScorecard,
    execution_profile: ExecutionProfile | None = None,
    invalidation: InvalidationCriteria | None = None,
) -> ChampionBundle:
    """Create a locked champion evidence bundle."""
    if not validate_frozen(candidate):
        raise ValueError(f"Cannot bundle champion {candidate.label}: config hash invalid")

    exec_prof = execution_profile or ExecutionProfile()
    inval = invalidation or InvalidationCriteria()

    metrics_dict: dict[str, Any] = {}
    if run.metrics:
        metrics_dict = {
            "sharpe_ratio": run.metrics.sharpe_ratio,
            "profit_factor": run.metrics.profit_factor,
            "win_rate": run.metrics.win_rate,
            "total_pnl": run.metrics.total_pnl,
            "total_trades": run.metrics.total_trades,
            "max_drawdown_pct": run.metrics.max_drawdown_pct,
        }

    stress_dict: dict[str, Any] = {}
    if run.stress_report:
        stress_dict = run.stress_report.to_dict()

    gate_dict: dict[str, Any] = {}
    if run.gate_result:
        gate_dict = run.gate_result.to_dict()

    config_snapshot = candidate.config.model_dump()

    bundle = ChampionBundle(
        champion_label=candidate.label,
        config_hash=candidate.config_hash,
        frozen_at=datetime.utcnow().isoformat(),
        scorecard=scorecard.to_dict(),
        gate_result=gate_dict,
        stress_summary=stress_dict,
        metrics=metrics_dict,
        execution_profile=exec_prof.to_dict(),
        invalidation_criteria=inval.to_dict(),
        config_snapshot=config_snapshot,
    )

    # Compute bundle hash for integrity verification
    content = json.dumps(bundle.to_dict(), sort_keys=True, default=str)
    bundle.bundle_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    return bundle


def save_champion_bundle(bundle: ChampionBundle, output_dir: Path | str) -> Path:
    """Save the champion bundle to a directory."""
    out = Path(output_dir) / "champion_bundle"
    out.mkdir(parents=True, exist_ok=True)

    bundle_path = out / "champion.json"
    with open(bundle_path, "w") as f:
        json.dump(bundle.to_dict(), f, indent=2, default=str)

    config_path = out / "config_snapshot.json"
    with open(config_path, "w") as f:
        json.dump(bundle.config_snapshot, f, indent=2, default=str)

    manifest_path = out / "MANIFEST.md"
    with open(manifest_path, "w") as f:
        f.write(format_champion_manifest(bundle))

    return out


def check_champion_validity(
    bundle: ChampionBundle,
    current_sharpe: float | None = None,
    current_drawdown_pct: float | None = None,
    paper_discrepancy_pct: float | None = None,
    days_since_frozen: int | None = None,
) -> tuple[bool, list[str]]:
    """Check if the champion is still valid against invalidation criteria."""
    inval = InvalidationCriteria(**bundle.invalidation_criteria) if bundle.invalidation_criteria else InvalidationCriteria()
    issues: list[str] = []

    if current_sharpe is not None and current_sharpe < inval.min_holdout_sharpe:
        issues.append(f"Holdout Sharpe {current_sharpe:.3f} below minimum {inval.min_holdout_sharpe}")

    if current_drawdown_pct is not None and current_drawdown_pct > inval.max_holdout_drawdown_pct:
        issues.append(f"Drawdown {current_drawdown_pct:.2%} exceeds maximum {inval.max_holdout_drawdown_pct:.2%}")

    if paper_discrepancy_pct is not None and paper_discrepancy_pct > inval.max_paper_discrepancy_pct:
        issues.append(f"Paper discrepancy {paper_discrepancy_pct:.1f}% exceeds {inval.max_paper_discrepancy_pct}%")

    if days_since_frozen is not None and days_since_frozen > inval.staleness_days:
        issues.append(f"Bundle is {days_since_frozen} days old (max {inval.staleness_days})")

    return len(issues) == 0, issues


def compare_challenger(
    champion_bundle: ChampionBundle,
    challenger_scorecard: CandidateScorecard,
    min_improvement_pct: float = 10.0,
) -> tuple[bool, str]:
    """Determine if a challenger should replace the champion.

    Returns (should_replace, reason).
    """
    champ_composite = champion_bundle.scorecard.get("composite", 0.0)
    improvement = (challenger_scorecard.composite_score - champ_composite) / max(champ_composite, 0.001) * 100

    if challenger_scorecard.gate_verdict == "fail":
        return False, f"Challenger {challenger_scorecard.label} fails gate"

    if improvement < min_improvement_pct:
        return False, (
            f"Challenger {challenger_scorecard.label} composite improvement "
            f"{improvement:+.1f}% below {min_improvement_pct}% threshold"
        )

    if challenger_scorecard.fragility_penalty > 0.5:
        return False, f"Challenger {challenger_scorecard.label} has unacceptable fragility"

    return True, (
        f"Challenger {challenger_scorecard.label} improves composite by {improvement:+.1f}% "
        f"({champ_composite:.3f} -> {challenger_scorecard.composite_score:.3f})"
    )


def format_champion_manifest(bundle: ChampionBundle) -> str:
    """Generate a markdown manifest for the champion bundle."""
    lines = [
        "# Champion Strategy Manifest",
        "",
        f"**Champion**: {bundle.champion_label}",
        f"**Config Hash**: {bundle.config_hash}",
        f"**Bundle Hash**: {bundle.bundle_hash}",
        f"**Frozen At**: {bundle.frozen_at}",
        "",
        "## Metrics",
        "",
    ]

    for k, v in bundle.metrics.items():
        lines.append(f"- **{k}**: {v}")

    lines.append("")
    lines.append("## Gate Result")
    lines.append("")
    lines.append(f"- Verdict: {bundle.gate_result.get('verdict', 'N/A')}")
    lines.append(f"- Recommendation: {bundle.gate_result.get('recommendation', 'N/A')}")

    lines.append("")
    lines.append("## Execution Profile")
    lines.append("")
    for k, v in bundle.execution_profile.items():
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append("## Invalidation Criteria")
    lines.append("")
    for k, v in bundle.invalidation_criteria.items():
        lines.append(f"- {k}: {v}")

    return "\n".join(lines)
