"""Portfolio risk diagnostics: concentration, exposure history, risk contribution."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from fx_smc_bot.config import PAIR_CURRENCIES, RiskConfig
from fx_smc_bot.domain import ClosedTrade, Direction, Position
from fx_smc_bot.risk.exposure import compute_currency_exposures


@dataclass(slots=True)
class PortfolioDiagnostics:
    risk_by_pair: dict[str, float] = field(default_factory=dict)
    risk_by_family: dict[str, float] = field(default_factory=dict)
    currency_exposures: dict[str, float] = field(default_factory=dict)
    directional_balance: dict[str, int] = field(default_factory=dict)
    portfolio_heat: float = 0.0
    concentration_score: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Portfolio Heat: {self.portfolio_heat:.4f}",
            f"Concentration Score: {self.concentration_score:.3f}",
            "Risk by Pair:",
        ]
        for pair, risk in sorted(self.risk_by_pair.items()):
            lines.append(f"  {pair}: {risk:.4f}")
        lines.append("Risk by Family:")
        for fam, risk in sorted(self.risk_by_family.items()):
            lines.append(f"  {fam}: {risk:.4f}")
        lines.append("Currency Exposures:")
        for ccy, exp in sorted(self.currency_exposures.items()):
            lines.append(f"  {ccy}: {exp:+,.0f}")
        return "\n".join(lines)


def compute_portfolio_diagnostics(
    positions: list[Position],
    equity: float,
) -> PortfolioDiagnostics:
    """Compute portfolio risk diagnostics from open positions."""
    open_pos = [p for p in positions if p.is_open]
    diag = PortfolioDiagnostics()

    if equity <= 0:
        return diag

    diag.currency_exposures = compute_currency_exposures(open_pos)

    pair_risk: dict[str, float] = defaultdict(float)
    family_risk: dict[str, float] = defaultdict(float)
    long_count = 0
    short_count = 0
    total_heat = 0.0

    for p in open_pos:
        risk_per_unit = abs(p.entry_price - p.stop_loss)
        pos_risk = risk_per_unit * p.units / equity
        pair_risk[p.pair.value] += pos_risk
        family_name = p.candidate.family.value if p.candidate else "unknown"
        family_risk[family_name] += pos_risk
        total_heat += pos_risk

        if p.direction == Direction.LONG:
            long_count += 1
        else:
            short_count += 1

    diag.risk_by_pair = dict(pair_risk)
    diag.risk_by_family = dict(family_risk)
    diag.portfolio_heat = total_heat
    diag.directional_balance = {"long": long_count, "short": short_count}

    total_pos = long_count + short_count
    if total_pos > 0:
        max_dir = max(long_count, short_count)
        diag.concentration_score = max_dir / total_pos
    else:
        diag.concentration_score = 0.0

    return diag


def trade_history_diagnostics(
    trades: list[ClosedTrade],
) -> dict[str, float]:
    """Compute aggregate risk stats from closed trades."""
    if not trades:
        return {}

    by_pair: dict[str, list[float]] = defaultdict(list)
    by_family: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_pair[t.pair.value].append(t.pnl)
        by_family[t.family.value].append(t.pnl)

    stats: dict[str, float] = {}
    for pair, pnls in by_pair.items():
        stats[f"pair_{pair}_total_pnl"] = sum(pnls)
        stats[f"pair_{pair}_trade_count"] = len(pnls)
    for fam, pnls in by_family.items():
        stats[f"family_{fam}_total_pnl"] = sum(pnls)
        stats[f"family_{fam}_trade_count"] = len(pnls)

    return stats
