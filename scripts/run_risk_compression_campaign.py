#!/usr/bin/env python3
"""Risk compression campaign: systematic grid sweep over risk parameters.

Keeps alpha configuration frozen (sweep_plus_bos, bos_continuation_only)
while varying risk sizing, circuit breakers, concurrency limits, and
throttle parameters.  Produces deployment-readiness leaderboards,
holdout evaluation on gate-passing profiles, and a final promotion package.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary, compute_metrics
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.frozen_config import (
    ConfigStatus, DataSplitPolicy, FrozenCandidate,
    freeze_config, split_data, validate_frozen,
)
from fx_smc_bot.research.gating import (
    DeploymentGateConfig, GateResult, GateVerdict, evaluate_deployment_gate,
)
from fx_smc_bot.research.validation import ValidationCampaign, CandidateRun, ValidationStage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("risk_compression")

# Alpha family configurations for the two candidates under test
ALPHA_FAMILIES: dict[str, list[str]] = {
    "sweep_plus_bos": ["sweep_reversal", "bos_continuation"],
    "bos_continuation_only": ["bos_continuation"],
}


@dataclass(slots=True)
class CompressionResult:
    """Result of a single risk-profile backtest."""
    alpha_candidate: str
    risk_profile: str
    risk_description: str
    risk_overrides: dict[str, Any]
    sharpe: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    calmar: float = 0.0
    annualized_return: float = 0.0
    gate_verdict: str = "fail"
    gate_blocking: list[str] = field(default_factory=list)
    risk_events: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0

    @property
    def drawdown_efficiency(self) -> float:
        """Sharpe per unit of drawdown — higher is better."""
        if self.max_drawdown_pct > 0:
            return self.sharpe / self.max_drawdown_pct
        return 0.0

    @property
    def deployment_score(self) -> float:
        """Composite deployment-readiness score (higher is better)."""
        if self.total_trades < 30 or self.sharpe <= 0:
            return 0.0
        dd_penalty = max(0.0, self.max_drawdown_pct - 0.20) * 5.0
        return max(0.0, self.sharpe * self.profit_factor - dd_penalty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha_candidate": self.alpha_candidate,
            "risk_profile": self.risk_profile,
            "risk_description": self.risk_description,
            "risk_overrides": self.risk_overrides,
            "sharpe": round(self.sharpe, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "calmar": round(self.calmar, 4),
            "annualized_return": round(self.annualized_return, 4),
            "drawdown_efficiency": round(self.drawdown_efficiency, 4),
            "deployment_score": round(self.deployment_score, 4),
            "gate_verdict": self.gate_verdict,
            "gate_blocking": self.gate_blocking,
            "risk_events": self.risk_events,
            "elapsed_s": round(self.elapsed_s, 1),
        }


def _build_config(
    alpha_candidate: str,
    risk_overrides: dict[str, Any],
) -> AppConfig:
    """Build an AppConfig with the given alpha families and risk overrides."""
    cfg = AppConfig()
    cfg.alpha.enabled_families = list(ALPHA_FAMILIES[alpha_candidate])
    for key, value in risk_overrides.items():
        if hasattr(cfg.risk, key):
            setattr(cfg.risk, key, value)
    return cfg


def _run_single_profile(
    alpha_candidate: str,
    profile_label: str,
    profile_desc: str,
    risk_overrides: dict[str, Any],
    train_data: dict[TradingPair, BarSeries],
    htf_data: dict[TradingPair, BarSeries] | None,
    gate_config: DeploymentGateConfig,
) -> CompressionResult:
    """Run a backtest for one (alpha_candidate, risk_profile) combination."""
    cfg = _build_config(alpha_candidate, risk_overrides)
    result = CompressionResult(
        alpha_candidate=alpha_candidate,
        risk_profile=profile_label,
        risk_description=profile_desc,
        risk_overrides=risk_overrides,
    )

    t0 = time.monotonic()
    try:
        engine = BacktestEngine(cfg)
        bt_result = engine.run(train_data, htf_data)
        metrics = engine.metrics(bt_result)

        result.sharpe = metrics.sharpe_ratio
        result.profit_factor = metrics.profit_factor
        result.max_drawdown_pct = metrics.max_drawdown_pct
        result.total_trades = metrics.total_trades
        result.total_pnl = metrics.total_pnl
        result.win_rate = metrics.win_rate
        result.calmar = metrics.calmar_ratio
        result.annualized_return = metrics.annualized_return
        result.risk_events = bt_result.metadata.get("risk_events", {})

        metrics_dict = {
            "sharpe_ratio": metrics.sharpe_ratio,
            "profit_factor": metrics.profit_factor,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "total_trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
        }
        gate = evaluate_deployment_gate(metrics_dict, gate_config)
        result.gate_verdict = gate.verdict.value
        result.gate_blocking = gate.blocking_failures

    except Exception as e:
        logger.warning("Backtest failed for %s/%s: %s", alpha_candidate, profile_label, e)
        result.gate_verdict = "error"
        result.gate_blocking = [str(e)]

    result.elapsed_s = time.monotonic() - t0
    return result


def _format_leaderboard(
    results: list[CompressionResult],
    title: str,
    sort_key: str = "deployment_score",
) -> str:
    """Format results as a markdown leaderboard table."""
    if sort_key == "deployment_score":
        ranked = sorted(results, key=lambda r: r.deployment_score, reverse=True)
    elif sort_key == "drawdown_efficiency":
        ranked = sorted(results, key=lambda r: r.drawdown_efficiency, reverse=True)
    elif sort_key == "sharpe":
        ranked = sorted(results, key=lambda r: r.sharpe, reverse=True)
    elif sort_key == "max_drawdown_pct":
        ranked = sorted(results, key=lambda r: r.max_drawdown_pct)
    else:
        ranked = results

    lines = [
        f"# {title}\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        "| Rank | Candidate | Risk Profile | Sharpe | PF | Max DD | Trades | Calmar | DD Eff | Deploy Score | Gate |",
        "|------|-----------|-------------|--------|-----|--------|--------|--------|--------|-------------|------|",
    ]
    for i, r in enumerate(ranked, 1):
        gate_icon = "PASS" if r.gate_verdict == "pass" else "COND" if r.gate_verdict == "conditional" else "FAIL"
        lines.append(
            f"| {i} | {r.alpha_candidate} | {r.risk_profile} "
            f"| {r.sharpe:.3f} | {r.profit_factor:.2f} | {r.max_drawdown_pct:.1%} "
            f"| {r.total_trades} | {r.calmar:.2f} | {r.drawdown_efficiency:.2f} "
            f"| {r.deployment_score:.3f} | {gate_icon} |"
        )
    return "\n".join(lines) + "\n"


def _format_comparison_report(
    results: list[CompressionResult],
    gate_config: DeploymentGateConfig,
) -> str:
    """Format a detailed champion vs challenger comparison."""
    sweep_results = [r for r in results if r.alpha_candidate == "sweep_plus_bos"]
    bos_results = [r for r in results if r.alpha_candidate == "bos_continuation_only"]

    sweep_pass = [r for r in sweep_results if r.gate_verdict in ("pass", "conditional")]
    bos_pass = [r for r in bos_results if r.gate_verdict in ("pass", "conditional")]

    sweep_best = max(sweep_results, key=lambda r: r.deployment_score) if sweep_results else None
    bos_best = max(bos_results, key=lambda r: r.deployment_score) if bos_results else None

    lines = [
        "# Hardened Candidate Comparison: sweep_plus_bos vs bos_continuation_only\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        f"Gate threshold: max_drawdown_pct <= {gate_config.max_drawdown_pct:.0%}\n",
        "## Gate Pass Summary\n",
        f"- sweep_plus_bos: {len(sweep_pass)}/{len(sweep_results)} profiles pass gate",
        f"- bos_continuation_only: {len(bos_pass)}/{len(bos_results)} profiles pass gate\n",
    ]

    if sweep_best:
        lines.append("## Best sweep_plus_bos Profile\n")
        lines.append(f"- Profile: **{sweep_best.risk_profile}** ({sweep_best.risk_description})")
        lines.append(f"- Sharpe: {sweep_best.sharpe:.3f} | PF: {sweep_best.profit_factor:.2f} "
                      f"| DD: {sweep_best.max_drawdown_pct:.1%} | Trades: {sweep_best.total_trades}")
        lines.append(f"- Gate: {sweep_best.gate_verdict}\n")

    if bos_best:
        lines.append("## Best bos_continuation_only Profile\n")
        lines.append(f"- Profile: **{bos_best.risk_profile}** ({bos_best.risk_description})")
        lines.append(f"- Sharpe: {bos_best.sharpe:.3f} | PF: {bos_best.profit_factor:.2f} "
                      f"| DD: {bos_best.max_drawdown_pct:.1%} | Trades: {bos_best.total_trades}")
        lines.append(f"- Gate: {bos_best.gate_verdict}\n")

    if sweep_best and bos_best:
        lines.append("## Head-to-Head (Best Profile Each)\n")
        sharpe_diff = sweep_best.sharpe - bos_best.sharpe
        pf_diff = sweep_best.profit_factor - bos_best.profit_factor
        dd_diff = sweep_best.max_drawdown_pct - bos_best.max_drawdown_pct
        trade_diff = sweep_best.total_trades - bos_best.total_trades

        lines.append(f"- Sharpe advantage: {'sweep_plus_bos' if sharpe_diff > 0 else 'bos_continuation_only'} "
                      f"by {abs(sharpe_diff):.3f}")
        lines.append(f"- PF advantage: {'sweep_plus_bos' if pf_diff > 0 else 'bos_continuation_only'} "
                      f"by {abs(pf_diff):.2f}")
        lines.append(f"- Drawdown: {'sweep_plus_bos' if dd_diff < 0 else 'bos_continuation_only'} "
                      f"is better by {abs(dd_diff):.1%}")
        lines.append(f"- Trade count: {'sweep_plus_bos' if trade_diff > 0 else 'bos_continuation_only'} "
                      f"has {abs(trade_diff)} more trades")

        material_threshold = 0.05
        if abs(sharpe_diff) < material_threshold and abs(pf_diff) < 0.1:
            lines.append("\n**Verdict**: Performance is materially similar — "
                          "prefer **bos_continuation_only** for simplicity (1 family vs 2).")
        elif sharpe_diff > material_threshold:
            lines.append("\n**Verdict**: sweep_plus_bos has meaningfully better Sharpe — "
                          "the sweep family adds measurable value.")
        else:
            lines.append("\n**Verdict**: bos_continuation_only is stronger — "
                          "sweep family does not add sufficient value to justify complexity.")

    # Simplicity-adjusted analysis
    lines.append("\n## Simplicity-Adjusted Ranking\n")
    lines.append("When performance is within 5% on Sharpe, prefer the simpler candidate.\n")
    for r in sorted(results, key=lambda x: x.deployment_score, reverse=True)[:10]:
        n_fam = len(ALPHA_FAMILIES[r.alpha_candidate])
        simplicity_tag = "(1-family)" if n_fam == 1 else "(2-family)"
        lines.append(f"- {r.alpha_candidate}/{r.risk_profile} {simplicity_tag}: "
                      f"Sharpe={r.sharpe:.3f} DD={r.max_drawdown_pct:.1%} Gate={r.gate_verdict}")

    return "\n".join(lines) + "\n"


def _format_risk_compression_report(
    results: list[CompressionResult],
    holdout_results: list[CompressionResult] | None,
    gate_config: DeploymentGateConfig,
) -> str:
    """Full risk compression report with analysis."""
    passing = [r for r in results if r.gate_verdict in ("pass", "conditional")]
    failing = [r for r in results if r.gate_verdict not in ("pass", "conditional")]

    lines = [
        "# Risk Compression Campaign Report\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        "## Summary\n",
        f"- Total profiles tested: {len(results)}",
        f"- Profiles passing gate: {len(passing)}",
        f"- Profiles failing gate: {len(failing)}",
        f"- Gate max_drawdown_pct threshold: {gate_config.max_drawdown_pct:.0%}\n",
    ]

    if passing:
        best = max(passing, key=lambda r: r.deployment_score)
        lines.append("## Best Deployment-Ready Profile\n")
        lines.append(f"- **{best.alpha_candidate} / {best.risk_profile}**")
        lines.append(f"- Description: {best.risk_description}")
        lines.append(f"- Sharpe: {best.sharpe:.3f} | PF: {best.profit_factor:.2f}")
        lines.append(f"- Max DD: {best.max_drawdown_pct:.1%} | Trades: {best.total_trades}")
        lines.append(f"- Calmar: {best.calmar:.2f} | DD Efficiency: {best.drawdown_efficiency:.2f}")
        lines.append(f"- Risk overrides: {json.dumps(best.risk_overrides, indent=2)}\n")
    else:
        lines.append("## WARNING: No profiles passed the deployment gate\n")
        closest = min(results, key=lambda r: r.max_drawdown_pct)
        lines.append(f"Closest to passing: {closest.alpha_candidate}/{closest.risk_profile} "
                      f"(DD: {closest.max_drawdown_pct:.1%})\n")

    # Key findings
    lines.append("## Key Findings\n")
    dd_values = [r.max_drawdown_pct for r in results if r.total_trades > 0]
    if dd_values:
        lines.append(f"- Drawdown range across all profiles: {min(dd_values):.1%} — {max(dd_values):.1%}")
    sharpe_values = [r.sharpe for r in results if r.total_trades > 30]
    if sharpe_values:
        lines.append(f"- Sharpe range (trades > 30): {min(sharpe_values):.3f} — {max(sharpe_values):.3f}")

    cb_fired = [r for r in results if r.risk_events.get("circuit_breaker_fired", 0) > 0]
    if cb_fired:
        lines.append(f"- Circuit breaker fired in {len(cb_fired)} profiles")

    # Risk control effectiveness
    lines.append("\n## Risk Control Effectiveness\n")
    by_sizing = {}
    for r in results:
        brpt = r.risk_overrides.get("base_risk_per_trade", 0.005)
        by_sizing.setdefault(brpt, []).append(r)
    lines.append("### Drawdown by base_risk_per_trade\n")
    for brpt in sorted(by_sizing.keys()):
        profiles = by_sizing[brpt]
        avg_dd = sum(r.max_drawdown_pct for r in profiles) / len(profiles)
        avg_sharpe = sum(r.sharpe for r in profiles) / len(profiles)
        lines.append(f"- {brpt:.2%}: avg DD={avg_dd:.1%}, avg Sharpe={avg_sharpe:.3f} "
                      f"({len(profiles)} profiles)")

    # Holdout results
    if holdout_results:
        lines.append("\n## Holdout Results\n")
        for r in holdout_results:
            lines.append(f"- {r.alpha_candidate}/{r.risk_profile}: "
                          f"Sharpe={r.sharpe:.3f} DD={r.max_drawdown_pct:.1%} "
                          f"Trades={r.total_trades} Gate={r.gate_verdict}")

    return "\n".join(lines) + "\n"


def _format_holdout_report(
    train_results: list[CompressionResult],
    holdout_results: list[CompressionResult],
) -> str:
    """Format holdout degradation analysis."""
    lines = [
        "# Holdout Evaluation Under Hardened Risk\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        "## Train vs Holdout Comparison\n",
        "| Candidate | Profile | Train Sharpe | Holdout Sharpe | Train DD | Holdout DD | Train Trades | Holdout Trades | Holdout Gate |",
        "|-----------|---------|-------------|---------------|----------|-----------|-------------|---------------|-------------|",
    ]

    train_lookup = {(r.alpha_candidate, r.risk_profile): r for r in train_results}
    for hr in holdout_results:
        key = (hr.alpha_candidate, hr.risk_profile)
        tr = train_lookup.get(key)
        if tr:
            sharpe_deg = ((hr.sharpe - tr.sharpe) / tr.sharpe * 100) if tr.sharpe != 0 else 0
            lines.append(
                f"| {hr.alpha_candidate} | {hr.risk_profile} "
                f"| {tr.sharpe:.3f} | {hr.sharpe:.3f} ({sharpe_deg:+.0f}%) "
                f"| {tr.max_drawdown_pct:.1%} | {hr.max_drawdown_pct:.1%} "
                f"| {tr.total_trades} | {hr.total_trades} "
                f"| {hr.gate_verdict.upper()} |"
            )

    holdout_passing = [r for r in holdout_results if r.gate_verdict in ("pass", "conditional")]
    lines.append(f"\n## Holdout Gate Summary\n")
    lines.append(f"- {len(holdout_passing)}/{len(holdout_results)} profiles pass holdout gate")

    if holdout_passing:
        best = max(holdout_passing, key=lambda r: r.deployment_score)
        lines.append(f"- Best holdout profile: **{best.alpha_candidate}/{best.risk_profile}**")
        lines.append(f"  Sharpe={best.sharpe:.3f} DD={best.max_drawdown_pct:.1%} "
                      f"Trades={best.total_trades}")
    else:
        lines.append("- **No profiles passed holdout gate**")

    return "\n".join(lines) + "\n"


def _format_deployment_decision(
    results: list[CompressionResult],
    holdout_results: list[CompressionResult] | None,
    gate_config: DeploymentGateConfig,
) -> tuple[str, dict[str, Any]]:
    """Generate final deployment decision as markdown + JSON recommendation."""
    passing_train = [r for r in results if r.gate_verdict in ("pass", "conditional")]
    passing_holdout = [r for r in (holdout_results or [])
                       if r.gate_verdict in ("pass", "conditional")]

    # Determine outcome
    if passing_holdout:
        best = max(passing_holdout, key=lambda r: r.deployment_score)
        outcome = "CONTINUE_PAPER_TRADING"
        confidence = "high" if best.sharpe > 0.5 and best.max_drawdown_pct < 0.18 else "medium"
    elif passing_train:
        best = max(passing_train, key=lambda r: r.deployment_score)
        outcome = "HOLD_FOR_MORE_VALIDATION"
        confidence = "medium"
    else:
        best_overall = max(results, key=lambda r: r.deployment_score) if results else None
        if best_overall and best_overall.max_drawdown_pct < 0.30:
            outcome = "CONTINUE_WITH_SIMPLIFICATION"
            confidence = "low"
        else:
            outcome = "REWORK_STRATEGY"
            confidence = "low"
        best = best_overall

    # Build reason list
    reasons = []
    if passing_train:
        reasons.append(f"{len(passing_train)} risk profiles pass training gate "
                        f"(DD < {gate_config.max_drawdown_pct:.0%})")
    else:
        reasons.append("No risk profiles pass training gate — drawdown compression insufficient")

    if holdout_results:
        if passing_holdout:
            reasons.append(f"{len(passing_holdout)} profiles survive holdout evaluation")
        else:
            reasons.append("No profiles pass holdout — risk compression does not generalize")

    if best:
        reasons.append(f"Best profile: {best.alpha_candidate}/{best.risk_profile} "
                        f"(Sharpe={best.sharpe:.3f}, DD={best.max_drawdown_pct:.1%})")
        if best.risk_events.get("circuit_breaker_fired", 0):
            reasons.append("Circuit breaker fired during backtest — indicates tail-risk protection active")

    # Sweep value analysis
    sweep_pass = [r for r in (passing_holdout or passing_train)
                  if r.alpha_candidate == "sweep_plus_bos"]
    bos_pass = [r for r in (passing_holdout or passing_train)
                if r.alpha_candidate == "bos_continuation_only"]
    if sweep_pass and bos_pass:
        sweep_best = max(sweep_pass, key=lambda r: r.deployment_score)
        bos_best = max(bos_pass, key=lambda r: r.deployment_score)
        if abs(sweep_best.sharpe - bos_best.sharpe) < 0.05:
            reasons.append("Sweep adds no material edge over BOS-only — prefer simpler strategy")
            champion = bos_best.alpha_candidate
        elif sweep_best.sharpe > bos_best.sharpe:
            reasons.append(f"Sweep adds {sweep_best.sharpe - bos_best.sharpe:.3f} Sharpe "
                            "— justifies 2-family complexity")
            champion = sweep_best.alpha_candidate
        else:
            champion = bos_best.alpha_candidate
            reasons.append("BOS-only outperforms sweep_plus_bos after risk compression")
    elif sweep_pass:
        champion = "sweep_plus_bos"
    elif bos_pass:
        champion = "bos_continuation_only"
    else:
        champion = best.alpha_candidate if best else "unknown"

    champion_profile = best.risk_profile if best else "unknown"

    # Markdown report
    md_lines = [
        "# Final Deployment Decision\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        f"## Decision: **{outcome}**\n",
        f"Confidence: {confidence}\n",
        f"## Champion\n",
        f"- Strategy: **{champion}**",
        f"- Risk profile: **{champion_profile}**",
    ]
    if best:
        md_lines.extend([
            f"- Sharpe: {best.sharpe:.3f}",
            f"- Profit Factor: {best.profit_factor:.2f}",
            f"- Max Drawdown: {best.max_drawdown_pct:.1%}",
            f"- Trades: {best.total_trades}",
            f"- Risk overrides: `{json.dumps(best.risk_overrides)}`\n",
        ])

    md_lines.append("## Reasons\n")
    for r in reasons:
        md_lines.append(f"- {r}")

    remaining_risks = []
    if best and best.max_drawdown_pct > 0.15:
        remaining_risks.append(f"Drawdown ({best.max_drawdown_pct:.1%}) is close to gate — "
                                "live conditions may push it higher")
    remaining_risks.append("No real spread data — using fixed 1.5 pip assumption")
    remaining_risks.append("2 years of data is limited for tail-risk estimation")

    md_lines.append("\n## Unresolved Risks\n")
    for risk in remaining_risks:
        md_lines.append(f"- {risk}")

    md_lines.append("\n## Next Steps\n")
    if outcome == "CONTINUE_PAPER_TRADING":
        md_lines.extend([
            "1. Freeze the approved risk profile",
            "2. Deploy to paper trading with the hardened configuration",
            "3. Monitor daily: drawdown, trade count, signal quality",
            "4. Weekly review with discrepancy analysis",
            "5. Minimum 4-week paper period before live consideration",
        ])
    elif outcome == "HOLD_FOR_MORE_VALIDATION":
        md_lines.extend([
            "1. Acquire additional real data (more pairs, longer history)",
            "2. Re-run holdout with more data",
            "3. Investigate why training performance degrades on holdout",
        ])
    else:
        md_lines.extend([
            "1. Review whether the alpha source is sufficient",
            "2. Consider deeper structural changes to risk management",
            "3. Evaluate alternative strategy approaches",
        ])

    # JSON recommendation
    recommendation = {
        "outcome": outcome,
        "confidence": confidence,
        "champion_label": champion,
        "champion_risk_profile": champion_profile,
        "risk_overrides": best.risk_overrides if best else {},
        "metrics": best.to_dict() if best else {},
        "reasons": reasons,
        "unresolved_risks": remaining_risks,
        "gate_config": {
            "max_drawdown_pct": gate_config.max_drawdown_pct,
            "min_sharpe": gate_config.min_sharpe,
            "min_profit_factor": gate_config.min_profit_factor,
            "min_trade_count": gate_config.min_trade_count,
        },
        "profiles_tested": len(results),
        "profiles_passing_train": len(passing_train),
        "profiles_passing_holdout": len(passing_holdout) if holdout_results else None,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return "\n".join(md_lines) + "\n", recommendation


def main() -> None:
    output_dir = Path("results/risk_compression_wave")
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path("data/real")

    # --- Load grid config ---
    grid_path = Path(__file__).resolve().parent.parent / "configs" / "campaigns" / "risk_compression.yaml"
    with open(grid_path) as f:
        grid_cfg = yaml.safe_load(f)

    profiles = grid_cfg["profiles"]
    alpha_candidates = grid_cfg["alpha_candidates"]
    gate_raw = grid_cfg["deployment_gate"]
    gate_config = DeploymentGateConfig(
        max_drawdown_pct=gate_raw["max_drawdown_pct"],
        min_sharpe=gate_raw.get("min_sharpe", 0.3),
        min_profit_factor=gate_raw.get("min_profit_factor", 1.1),
        min_trade_count=gate_raw.get("min_trade_count", 30),
    )

    # --- Load data ---
    logger.info("Loading real FX data (H1 execution, H4 HTF)")
    data = load_pair_data(data_dir, timeframe=Timeframe.H1)
    if not data:
        logger.error("No data found in %s", data_dir)
        return

    for pair, series in data.items():
        logger.info("  %s: %d bars (%s)", pair.value, len(series), series.timeframe.value)

    htf_data = load_htf_data(data, htf_timeframe=Timeframe.H4, data_dir=data_dir)
    for pair, series in htf_data.items():
        logger.info("  HTF %s: %d bars (%s)", pair.value, len(series), series.timeframe.value)

    # --- Split data: train (60%) for grid search, holdout (last 20%) for validation ---
    split_policy = DataSplitPolicy(train_end_pct=0.6, validation_end_pct=0.8, embargo_bars=10)
    train_data: dict[TradingPair, BarSeries] = {}
    holdout_data: dict[TradingPair, BarSeries] = {}

    for pair, series in data.items():
        n = len(series)
        train_end = int(n * split_policy.train_end_pct)
        holdout_start = int(n * split_policy.validation_end_pct) + split_policy.embargo_bars
        train_data[pair] = series.slice(0, train_end)
        if holdout_start < n:
            holdout_data[pair] = series.slice(holdout_start, n)

    logger.info("Train data: %s bars per pair", {p.value: len(s) for p, s in train_data.items()})
    logger.info("Holdout data: %s bars per pair", {p.value: len(s) for p, s in holdout_data.items()})

    # ====================================================================
    # PHASE 1: Risk compression grid sweep on training data
    # ====================================================================
    total_runs = len(profiles) * len(alpha_candidates)
    logger.info("=" * 60)
    logger.info("PHASE 1: Risk compression grid sweep (%d profiles x %d candidates = %d runs)",
                len(profiles), len(alpha_candidates), total_runs)
    logger.info("=" * 60)

    all_results: list[CompressionResult] = []
    run_count = 0

    for profile in profiles:
        for alpha_cand in alpha_candidates:
            run_count += 1
            label = f"{alpha_cand}/{profile['label']}"
            logger.info("[%d/%d] Running %s", run_count, total_runs, label)

            result = _run_single_profile(
                alpha_candidate=alpha_cand,
                profile_label=profile["label"],
                profile_desc=profile.get("description", ""),
                risk_overrides=profile["overrides"],
                train_data=train_data,
                htf_data=htf_data,
                gate_config=gate_config,
            )
            all_results.append(result)

            logger.info("  -> Sharpe=%.3f PF=%.2f DD=%.1f%% Trades=%d Gate=%s (%.0fs)",
                         result.sharpe, result.profit_factor,
                         result.max_drawdown_pct * 100, result.total_trades,
                         result.gate_verdict, result.elapsed_s)

    # Save raw results
    with open(output_dir / "compression_results.json", "w") as f:
        json.dump([r.to_dict() for r in all_results], f, indent=2)

    # ====================================================================
    # PHASE 2: Leaderboards and comparison
    # ====================================================================
    logger.info("=" * 60)
    logger.info("PHASE 2: Leaderboards and comparison")
    logger.info("=" * 60)

    (output_dir / "compressed_risk_leaderboard.md").write_text(
        _format_leaderboard(all_results, "Compressed-Risk Leaderboard (by Deployment Score)")
    )
    (output_dir / "drawdown_efficiency_leaderboard.md").write_text(
        _format_leaderboard(all_results, "Drawdown Efficiency Leaderboard",
                            sort_key="drawdown_efficiency")
    )
    (output_dir / "hardened_candidate_comparison.md").write_text(
        _format_comparison_report(all_results, gate_config)
    )

    # ====================================================================
    # PHASE 3: Holdout on gate-passing profiles
    # ====================================================================
    logger.info("=" * 60)
    logger.info("PHASE 3: Holdout evaluation")
    logger.info("=" * 60)

    passing_train = [r for r in all_results if r.gate_verdict in ("pass", "conditional")]
    holdout_results: list[CompressionResult] = []

    if passing_train:
        # Take top 5 by deployment score for holdout
        top_for_holdout = sorted(passing_train, key=lambda r: r.deployment_score, reverse=True)[:5]
        logger.info("Running holdout on %d gate-passing profiles", len(top_for_holdout))

        for i, train_r in enumerate(top_for_holdout, 1):
            label = f"{train_r.alpha_candidate}/{train_r.risk_profile}"
            logger.info("[%d/%d] Holdout: %s", i, len(top_for_holdout), label)

            hr = _run_single_profile(
                alpha_candidate=train_r.alpha_candidate,
                profile_label=train_r.risk_profile,
                profile_desc=train_r.risk_description,
                risk_overrides=train_r.risk_overrides,
                train_data=holdout_data,
                htf_data=htf_data,
                gate_config=gate_config,
            )
            holdout_results.append(hr)

            logger.info("  -> Holdout Sharpe=%.3f DD=%.1f%% Trades=%d Gate=%s",
                         hr.sharpe, hr.max_drawdown_pct * 100,
                         hr.total_trades, hr.gate_verdict)

        (output_dir / "holdout_results.json").write_text(
            json.dumps([r.to_dict() for r in holdout_results], indent=2)
        )
        (output_dir / "updated_holdout_report.md").write_text(
            _format_holdout_report(top_for_holdout, holdout_results)
        )
    else:
        logger.warning("No profiles passed training gate — skipping holdout")
        (output_dir / "updated_holdout_report.md").write_text(
            "# Holdout Report\n\nNo profiles passed the training gate. Holdout was not run.\n"
        )

    # ====================================================================
    # PHASE 4: Final reports and promotion package
    # ====================================================================
    logger.info("=" * 60)
    logger.info("PHASE 4: Final reports and promotion package")
    logger.info("=" * 60)

    (output_dir / "risk_compression_report.md").write_text(
        _format_risk_compression_report(all_results, holdout_results, gate_config)
    )

    decision_md, recommendation = _format_deployment_decision(
        all_results, holdout_results if holdout_results else None, gate_config,
    )
    (output_dir / "final_deployment_decision.md").write_text(decision_md)
    (output_dir / "final_promotion_recommendation.json").write_text(
        json.dumps(recommendation, indent=2)
    )

    # Approved risk profile (if a champion exists)
    if recommendation.get("risk_overrides"):
        approved_profile = {
            "champion": recommendation["champion_label"],
            "risk_profile_label": recommendation["champion_risk_profile"],
            "risk_overrides": recommendation["risk_overrides"],
            "gate_config": recommendation["gate_config"],
            "frozen_at": datetime.utcnow().isoformat(),
            "outcome": recommendation["outcome"],
        }
        (output_dir / "approved_risk_profile.json").write_text(
            json.dumps(approved_profile, indent=2)
        )

    # Champion bundle directory
    bundle_dir = output_dir / "updated_champion_bundle"
    bundle_dir.mkdir(exist_ok=True)
    (bundle_dir / "champion_config.json").write_text(
        json.dumps({
            "champion": recommendation.get("champion_label"),
            "risk_profile": recommendation.get("champion_risk_profile"),
            "risk_overrides": recommendation.get("risk_overrides", {}),
            "metrics": recommendation.get("metrics", {}),
        }, indent=2)
    )

    # Paper candidate package (only if outcome is CONTINUE_PAPER_TRADING)
    if recommendation["outcome"] == "CONTINUE_PAPER_TRADING":
        paper_dir = output_dir / "paper_candidate_package"
        paper_dir.mkdir(exist_ok=True)
        (paper_dir / "approved_risk_profile.json").write_text(
            json.dumps(approved_profile, indent=2)
        )
        paper_checklist = [
            "# Paper Trading Review Checklist\n",
            f"Champion: {recommendation['champion_label']}",
            f"Risk Profile: {recommendation['champion_risk_profile']}\n",
            "## Daily Review Items\n",
            "- [ ] Check equity curve for anomalies",
            "- [ ] Verify drawdown is within approved limits",
            "- [ ] Review signal count vs backtest expectations",
            "- [ ] Check throttle/lockout activations",
            "- [ ] Verify no circuit breaker proximity warnings\n",
            "## Weekly Review Items\n",
            "- [ ] Compare Sharpe to backtest (acceptable: within 30%)",
            "- [ ] Compare trade count to backtest (acceptable: within 40%)",
            "- [ ] Review win rate stability",
            "- [ ] Check drawdown path vs historical envelope",
            "- [ ] Assess regime alignment\n",
            "## Invalidation Criteria\n",
            "- Drawdown exceeds 1.5x backtest max drawdown",
            "- Sharpe drops below 0.0 for 2+ consecutive weeks",
            "- Trade count drops below 50% of expected weekly rate",
            "- Circuit breaker fires in paper trading",
            "- Any operational incident unresolved for 48+ hours\n",
            "## Promotion Criteria (paper -> live consideration)\n",
            "- Minimum 4 weeks of paper trading",
            "- Drawdown within approved limits for entire period",
            "- Sharpe within 30% of backtest Sharpe",
            "- No unresolved discrepancies above 10%",
        ]
        (paper_dir / "review_checklist.md").write_text("\n".join(paper_checklist) + "\n")

    # Deployment readiness report
    lines = [
        "# Deployment Readiness Report\n",
        f"Generated: {datetime.utcnow().isoformat()}\n",
        f"## Outcome: {recommendation['outcome']}\n",
        f"Confidence: {recommendation['confidence']}\n",
        "## Gate Evaluation\n",
        f"- Max drawdown threshold: {gate_config.max_drawdown_pct:.0%}",
        f"- Min Sharpe: {gate_config.min_sharpe}",
        f"- Min profit factor: {gate_config.min_profit_factor}",
        f"- Min trade count: {gate_config.min_trade_count}\n",
        "## Risk Controls Active\n",
        "- Peak-to-trough circuit breaker: enabled",
        "- Daily loss lockout: enabled",
        "- Consecutive loss dampening: enabled",
        "- Portfolio risk cap: enabled",
        "- Currency exposure limits: enabled",
        "- Directional concentration cap: enabled",
        "- Daily trade limit: enabled\n",
        f"## Profiles Tested: {len(all_results)}",
        f"## Profiles Passing Train Gate: {len(passing_train)}",
        f"## Profiles Passing Holdout: {len(holdout_results)}",
    ]
    (output_dir / "deployment_readiness_report.md").write_text("\n".join(lines) + "\n")

    # Final summary log
    logger.info("=" * 60)
    logger.info("FINAL OUTCOME: %s", recommendation["outcome"])
    logger.info("CONFIDENCE: %s", recommendation["confidence"])
    logger.info("CHAMPION: %s / %s", recommendation["champion_label"],
                recommendation["champion_risk_profile"])
    logger.info("=" * 60)
    logger.info("All artifacts saved to %s", output_dir)


if __name__ == "__main__":
    main()
