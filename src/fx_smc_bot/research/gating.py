"""Deployment gating: formal threshold-based promotion from research to live.

Implements a multi-criterion gate evaluation and a strategy candidate
registry with promotion state machine (RESEARCH -> CANDIDATE -> PAPER_TESTING
-> APPROVED | REJECTED | RETIRED).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

class GateSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


class GateVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL = "conditional"


@dataclass(frozen=True, slots=True)
class GateCriterion:
    name: str
    threshold: float
    actual_value: float
    passed: bool
    severity: GateSeverity = GateSeverity.BLOCKING

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "threshold": self.threshold,
            "actual": round(self.actual_value, 4),
            "passed": self.passed, "severity": self.severity.value,
        }


@dataclass(slots=True)
class GateResult:
    criteria: list[GateCriterion] = field(default_factory=list)
    verdict: GateVerdict = GateVerdict.FAIL
    blocking_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
            "recommendation": self.recommendation,
            "criteria": [c.to_dict() for c in self.criteria],
        }


class DeploymentGateConfig(BaseModel):
    """Configurable thresholds for deployment readiness gate."""
    min_sharpe: float = Field(default=0.3, description="Minimum Sharpe ratio")
    min_profit_factor: float = Field(default=1.1, description="Minimum profit factor")
    max_drawdown_pct: float = Field(default=0.20, description="Maximum drawdown percentage")
    min_trade_count: int = Field(default=30, description="Minimum number of trades")
    min_win_rate: float = Field(default=0.35, description="Minimum win rate")
    max_cost_degradation_pct: float = Field(default=0.50, description="Max PnL loss under cost stress")
    min_stability: float = Field(default=0.3, description="Minimum stability score (0-1)")
    min_robustness: float = Field(default=0.3, description="Minimum robustness score (0-1)")
    min_oos_consistency: float = Field(default=0.5, description="Minimum OOS consistency (0-1)")
    min_diversification: float = Field(default=0.2, description="Minimum pair diversification (0-1)")


def evaluate_deployment_gate(
    metrics: dict[str, Any],
    gate_config: DeploymentGateConfig | None = None,
    scores: dict[str, float] | None = None,
) -> GateResult:
    """Evaluate a strategy against deployment gate criteria."""
    cfg = gate_config or DeploymentGateConfig()
    scores = scores or {}
    criteria: list[GateCriterion] = []

    def _add(name: str, actual: float, threshold: float, higher_better: bool = True,
             severity: GateSeverity = GateSeverity.BLOCKING) -> None:
        passed = actual >= threshold if higher_better else actual <= threshold
        criteria.append(GateCriterion(name, threshold, actual, passed, severity))

    _add("sharpe_ratio", metrics.get("sharpe_ratio", 0.0), cfg.min_sharpe)
    _add("profit_factor", metrics.get("profit_factor", 0.0), cfg.min_profit_factor)
    _add("max_drawdown_pct", metrics.get("max_drawdown_pct", 1.0), cfg.max_drawdown_pct, higher_better=False)
    _add("trade_count", metrics.get("total_trades", 0), cfg.min_trade_count)
    _add("win_rate", metrics.get("win_rate", 0.0), cfg.min_win_rate)

    if "cost_degradation_pct" in scores:
        _add("cost_degradation", scores["cost_degradation_pct"],
             cfg.max_cost_degradation_pct, higher_better=False)

    if "stability" in scores:
        _add("stability", scores["stability"], cfg.min_stability, severity=GateSeverity.WARNING)
    if "robustness" in scores:
        _add("robustness", scores["robustness"], cfg.min_robustness, severity=GateSeverity.WARNING)
    if "oos_consistency" in scores:
        _add("oos_consistency", scores["oos_consistency"], cfg.min_oos_consistency, severity=GateSeverity.WARNING)
    if "diversification" in scores:
        _add("diversification", scores["diversification"], cfg.min_diversification, severity=GateSeverity.WARNING)

    blocking = [c.name for c in criteria if not c.passed and c.severity == GateSeverity.BLOCKING]
    warns = [c.name for c in criteria if not c.passed and c.severity == GateSeverity.WARNING]

    if blocking:
        verdict = GateVerdict.FAIL
        rec = f"BLOCKED: fails {', '.join(blocking)}. Not ready for promotion."
    elif warns:
        verdict = GateVerdict.CONDITIONAL
        rec = f"CONDITIONAL: passes blocking gates but warnings on {', '.join(warns)}. Review before promoting."
    else:
        verdict = GateVerdict.PASS
        rec = "PASS: all deployment criteria met. Eligible for paper testing promotion."

    return GateResult(
        criteria=criteria, verdict=verdict,
        blocking_failures=blocking, warnings=warns,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Strategy candidate promotion state machine
# ---------------------------------------------------------------------------

class PromotionState(str, Enum):
    RESEARCH = "research"
    CANDIDATE = "candidate"
    PAPER_TESTING = "paper_testing"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"


_VALID_TRANSITIONS: dict[PromotionState, set[PromotionState]] = {
    PromotionState.RESEARCH: {PromotionState.CANDIDATE, PromotionState.REJECTED},
    PromotionState.CANDIDATE: {PromotionState.PAPER_TESTING, PromotionState.REJECTED, PromotionState.RETIRED},
    PromotionState.PAPER_TESTING: {PromotionState.APPROVED, PromotionState.REJECTED, PromotionState.RETIRED},
    PromotionState.APPROVED: {PromotionState.RETIRED},
    PromotionState.REJECTED: {PromotionState.RESEARCH},
    PromotionState.RETIRED: set(),
}


@dataclass(slots=True)
class StrategyCandidate:
    config_hash: str
    label: str = ""
    run_ids: list[str] = field(default_factory=list)
    state: PromotionState = PromotionState.RESEARCH
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    champion: bool = False
    created_at: str = ""
    last_updated: str = ""
    notes: str = ""

    def promote(self, new_state: PromotionState, gate_result: GateResult | None = None) -> bool:
        """Attempt state transition. Returns True if valid."""
        if new_state not in _VALID_TRANSITIONS.get(self.state, set()):
            return False
        self.state = new_state
        self.last_updated = datetime.utcnow().isoformat()
        if gate_result:
            self.gate_results.append(gate_result.to_dict())
        return True


class StrategyRegistry:
    """Track strategy candidates with promotion state and gate results."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._candidates: dict[str, StrategyCandidate] = {}
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        with open(self._path) as f:
            data = json.load(f)
        for entry in data.get("candidates", []):
            entry["state"] = PromotionState(entry["state"])
            c = StrategyCandidate(**entry)
            self._candidates[c.config_hash] = c

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        for c in self._candidates.values():
            d = asdict(c)
            d["state"] = c.state.value
            entries.append(d)
        with open(self._path, "w") as f:
            json.dump({"candidates": entries}, f, indent=2, default=str)

    def register(self, config_hash: str, label: str = "", run_id: str = "") -> StrategyCandidate:
        if config_hash in self._candidates:
            cand = self._candidates[config_hash]
            if run_id and run_id not in cand.run_ids:
                cand.run_ids.append(run_id)
                self._save()
            return cand

        cand = StrategyCandidate(
            config_hash=config_hash, label=label,
            run_ids=[run_id] if run_id else [],
            created_at=datetime.utcnow().isoformat(),
            last_updated=datetime.utcnow().isoformat(),
        )
        self._candidates[config_hash] = cand
        self._save()
        return cand

    def promote(
        self,
        config_hash: str,
        new_state: PromotionState,
        gate_result: GateResult | None = None,
    ) -> bool:
        cand = self._candidates.get(config_hash)
        if not cand:
            return False
        ok = cand.promote(new_state, gate_result)
        if ok:
            self._save()
        return ok

    def set_champion(self, config_hash: str) -> None:
        for c in self._candidates.values():
            c.champion = c.config_hash == config_hash
        self._save()

    def get_champion(self) -> StrategyCandidate | None:
        for c in self._candidates.values():
            if c.champion:
                return c
        return None

    def list_candidates(self, state: PromotionState | None = None) -> list[StrategyCandidate]:
        cands = list(self._candidates.values())
        if state:
            cands = [c for c in cands if c.state == state]
        return cands

    def get(self, config_hash: str) -> StrategyCandidate | None:
        return self._candidates.get(config_hash)
