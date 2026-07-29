"""Run intraday SMC validation campaign.

Usage:
    python scripts/run_intraday_smc_campaign.py --strategy sweep_reversal --data-dir data/real
    python scripts/run_intraday_smc_campaign.py --strategy all --pairs EURUSD GBPUSD
    python scripts/run_intraday_smc_campaign.py --strategy sweep_reversal --ablation no_mss
    python scripts/run_intraday_smc_campaign.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import Timeframe, TradingPair

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STRATEGIES = [
    "sweep_reversal",
    "acceptance_continuation",
    "opening_range",
]

_PAIR_LOOKUP = {p.value.upper(): p for p in TradingPair}


def _parse_pairs(pair_strings: list[str]) -> list[TradingPair]:
    result = []
    for s in pair_strings:
        s = s.upper().replace("/", "").replace("_", "")
        if s in _PAIR_LOOKUP:
            result.append(_PAIR_LOOKUP[s])
        else:
            logger.warning("Unknown pair: %s, skipping", s)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Intraday SMC validation campaign runner",
    )
    parser.add_argument(
        "--strategy", choices=STRATEGIES + ["all"], default="all",
        help="Strategy family to evaluate",
    )
    parser.add_argument(
        "--pairs", nargs="+", default=["EURUSD", "GBPUSD"],
        help="Trading pairs",
    )
    parser.add_argument(
        "--sessions", nargs="+", default=["london", "new_york"],
        help="Trading sessions",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/real"),
        help="Directory containing market data",
    )
    parser.add_argument(
        "--exec-tf", default="5m",
        help="Execution timeframe",
    )
    parser.add_argument(
        "--htf", default="1h",
        help="Higher timeframe for context",
    )
    parser.add_argument(
        "--ablation", default=None,
        help="Run a specific ablation variant",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/intraday_smc"),
        help="Output directory for results",
    )
    parser.add_argument(
        "--n-bootstrap", type=int, default=5000,
        help="Number of bootstrap samples for statistical inference",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--statistical-report", action="store_true",
        help="Generate full statistical inference report",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would run without executing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    strategies = STRATEGIES if args.strategy == "all" else [args.strategy]
    pairs = _parse_pairs(args.pairs)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("Campaign run_id=%s strategies=%s pairs=%s", run_id, strategies, [p.value for p in pairs])

    if args.dry_run:
        for strat in strategies:
            for pair in pairs:
                for sess in args.sessions:
                    label = f"{strat}/{pair.value}/{sess}"
                    if args.ablation:
                        label += f"/{args.ablation}"
                    logger.info("Would run: %s", label)
        return 0

    tf_lookup = {t.value: t for t in Timeframe}
    exec_tf = tf_lookup.get(args.exec_tf, Timeframe.M5)
    htf_tf = tf_lookup.get(args.htf, Timeframe.H1)

    if not args.data_dir.exists():
        logger.error("Data directory does not exist: %s", args.data_dir)
        logger.info("Run 'python scripts/ingest_data.py' first to prepare data.")
        logger.info("Or use '--generate-synthetic' for development testing.")
        return 1

    from fx_smc_bot.research.intraday_campaign import (
        build_statistical_report,
        run_campaign,
    )

    campaign = run_campaign(
        strategies=strategies,
        pairs=pairs,
        sessions=args.sessions,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        exec_tf=exec_tf,
        htf_tf=htf_tf,
        ablation=args.ablation,
        seed=args.seed,
    )

    logger.info("Campaign complete: %d runs", len(campaign.runs))
    for run in campaign.runs:
        status = "OK" if run.error is None else f"ERROR: {run.error}"
        logger.info(
            "  %s: trades=%d pnl=%.2f sharpe=%s [%s]",
            run.config.label, run.trade_count, run.net_pnl,
            f"{run.sharpe:.4f}" if run.sharpe is not None else "N/A",
            status,
        )

    if args.statistical_report and any(r.trade_count > 0 for r in campaign.runs):
        logger.info("Generating statistical report (n_bootstrap=%d)...", args.n_bootstrap)
        stat_report = build_statistical_report(
            campaign,
            n_bootstrap=args.n_bootstrap,
            seed=args.seed,
        )
        report_path = args.output_dir / f"statistical_report_{run_id}.json"
        report_path.write_text(json.dumps(stat_report, indent=2, default=str))
        logger.info("Statistical report saved to %s", report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
