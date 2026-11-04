"""Market-data audit shared by the CLI and the dashboard.

The audit goes one step beyond ``doctor``'s file counts: it loads the configured
execution timeframes through the normal runner and runs the existing data-quality
diagnostics on every series. It is intentionally read-only and does not touch the
research gates or the sealed holdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fx_smc_bot.config import AppConfig
from fx_smc_bot.data.diagnostics import run_diagnostics
from fx_smc_bot.data.models import BarSeries

QUALITY_WARN_SCORE = 0.80
MISSING_BAR_WARN_PCT = 0.01


@dataclass(frozen=True, slots=True)
class PairAudit:
    """Data-quality summary for one loaded pair."""

    pair: str
    timeframe: str
    bars: int
    quality_score: float
    missing_bar_pct: float
    duplicates: int
    zero_range_bars: int
    stale_sequences: int
    issues: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class DataAudit:
    """Result of auditing one market-data directory."""

    data_dir: str
    configured_pairs: tuple[str, ...]
    loaded_pairs: tuple[str, ...]
    missing_pairs: tuple[str, ...]
    pairs: tuple[PairAudit, ...]
    status: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "data_dir": self.data_dir,
            "configured_pairs": list(self.configured_pairs),
            "loaded_pairs": list(self.loaded_pairs),
            "missing_pairs": list(self.missing_pairs),
            "pairs": [
                {
                    "pair": pair.pair,
                    "timeframe": pair.timeframe,
                    "bars": pair.bars,
                    "quality_score": pair.quality_score,
                    "missing_bar_pct": pair.missing_bar_pct,
                    "duplicates": pair.duplicates,
                    "zero_range_bars": pair.zero_range_bars,
                    "stale_sequences": pair.stale_sequences,
                    "issues": list(pair.issues),
                    "status": pair.status,
                }
                for pair in self.pairs
            ],
            "status": self.status,
            "error": self.error,
        }


def _pair_audit(series: BarSeries) -> PairAudit:
    report = run_diagnostics(series)
    issues = tuple(report.issues)
    warn = (
        report.quality_score < QUALITY_WARN_SCORE
        or report.missing_bar_pct > MISSING_BAR_WARN_PCT
        or report.duplicate_count > 0
        or report.stale_price_sequences > 0
    )
    return PairAudit(
        pair=series.pair.value,
        timeframe=series.timeframe.value,
        bars=report.total_bars,
        quality_score=report.quality_score,
        missing_bar_pct=report.missing_bar_pct,
        duplicates=report.duplicate_count,
        zero_range_bars=report.zero_range_bars,
        stale_sequences=report.stale_price_sequences,
        issues=issues,
        status="warn" if warn else "ok",
    )


def audit_market_data(config: AppConfig, data_dir: str | Path) -> DataAudit:
    """Load and inspect the configured execution data under ``data_dir``.

    ``fail`` means no usable data could be loaded. ``warn`` means data loaded,
    but a configured pair is missing or at least one series failed a quality
    check. The function never writes to the data directory.
    """
    from fx_smc_bot.backtesting.runner import load_market_data

    path = Path(data_dir).expanduser()
    configured = tuple(pair.value for pair in config.data.primary_pairs)
    base = {
        "data_dir": str(path),
        "configured_pairs": configured,
    }

    if not path.is_dir():
        return DataAudit(
            **base,
            loaded_pairs=(),
            missing_pairs=configured,
            pairs=(),
            status="fail",
            error=f"Data directory does not exist: {path}",
        )

    try:
        data = load_market_data(path, config)
    except Exception as exc:  # noqa: BLE001 - surfaced as an audit failure
        return DataAudit(
            **base,
            loaded_pairs=(),
            missing_pairs=configured,
            pairs=(),
            status="fail",
            error=f"{type(exc).__name__}: {exc}",
        )

    loaded = tuple(sorted(pair.value for pair in data))
    missing = tuple(pair for pair in configured if pair not in loaded)
    pairs = tuple(
        _pair_audit(series)
        for _, series in sorted(data.items(), key=lambda item: item[0].value)
    )
    status = "warn" if missing or any(pair.status == "warn" for pair in pairs) else "ok"
    return DataAudit(
        **base,
        loaded_pairs=loaded,
        missing_pairs=missing,
        pairs=pairs,
        status=status,
    )


def format_data_audit(audit: DataAudit) -> str:
    """Render an audit as a compact, ASCII-only terminal report."""
    lines = [
        f"Data directory : {audit.data_dir}",
        f"Configured     : {', '.join(audit.configured_pairs) or '-'}",
        f"Loaded         : {', '.join(audit.loaded_pairs) or '-'}",
        f"Missing        : {', '.join(audit.missing_pairs) or 'none'}",
    ]
    if audit.error:
        lines.extend(["", f"Error: {audit.error}", "", f"Audit: {audit.status.upper()}"])
        return "\n".join(lines)

    lines.extend(
        [
            "",
            f"{'PAIR':<10} {'TF':<5} {'BARS':>8} {'QUALITY':>8} {'STATUS':<6} ISSUES",
            "-" * 76,
        ]
    )
    for pair in audit.pairs:
        issues = "; ".join(pair.issues) if pair.issues else "-"
        lines.append(
            f"{pair.pair:<10} {pair.timeframe:<5} {pair.bars:>8,} "
            f"{pair.quality_score:>8.3f} {pair.status:<6} {issues}"
        )
    lines.extend(["", f"Audit: {audit.status.upper()}"])
    return "\n".join(lines)
