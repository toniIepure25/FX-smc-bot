"""Run prop-account Monte Carlo simulation.

Uses daily PnL from backtest results to estimate prop challenge pass probabilities.

Usage:
    python scripts/run_prop_monte_carlo.py --campaign-file results/intraday_smc/campaign_*.json
    python scripts/run_prop_monte_carlo.py --daily-pnl-file results/daily_pnl.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prop-account Monte Carlo simulation",
    )
    parser.add_argument(
        "--profile", default="Standard 100K Challenge",
        help="Challenge profile name",
    )
    parser.add_argument(
        "--starting-balance", type=float, default=100_000.0,
        help="Starting account balance",
    )
    parser.add_argument(
        "--profit-target", type=float, default=0.08,
        help="Phase 1 profit target as fraction (e.g. 0.08 = 8%%)",
    )
    parser.add_argument(
        "--daily-max-loss", type=float, default=0.05,
        help="Max daily drawdown fraction",
    )
    parser.add_argument(
        "--total-max-loss", type=float, default=0.10,
        help="Max total drawdown fraction",
    )
    parser.add_argument(
        "--n-paths", type=int, default=10_000,
        help="Number of Monte Carlo paths",
    )
    parser.add_argument(
        "--risk-grid", nargs="+", type=float,
        default=[0.001, 0.0015, 0.002, 0.0025, 0.0035, 0.005],
        help="Risk per trade levels to simulate",
    )
    parser.add_argument(
        "--daily-pnl-file", type=Path, default=None,
        help="Path to CSV with daily PnL series (column: pnl)",
    )
    parser.add_argument(
        "--campaign-file", type=Path, default=None,
        help="Path to campaign results JSON",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/prop_simulation"),
        help="Output directory",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("Prop Monte Carlo run_id=%s profile=%s", run_id, args.profile)

    daily_pnl = None

    if args.daily_pnl_file and args.daily_pnl_file.exists():
        import pandas as pd
        df = pd.read_csv(args.daily_pnl_file)
        if "pnl" in df.columns:
            daily_pnl = df["pnl"].values.astype(np.float64)
            logger.info("Loaded %d daily PnL values from %s", len(daily_pnl), args.daily_pnl_file)
        else:
            logger.error("CSV must contain a 'pnl' column")
            return 1

    if daily_pnl is None:
        logger.info(
            "No daily PnL data provided. Run the campaign first, then provide "
            "--daily-pnl-file or --campaign-file."
        )
        logger.info("Generating example with synthetic daily returns...")
        rng = np.random.default_rng(args.seed)
        daily_pnl = rng.normal(50, 300, 200)
        logger.info("Using %d synthetic daily PnL values (mean=%.0f, std=%.0f)",
                     len(daily_pnl), np.mean(daily_pnl), np.std(daily_pnl))

    from fx_smc_bot.research.prop_simulation import (
        PropAccountProfile,
        simulate_prop_challenge,
    )

    profile = PropAccountProfile(
        name=args.profile,
        starting_balance=args.starting_balance,
        profit_target=args.profit_target,
        daily_max_loss=args.daily_max_loss,
        total_max_loss=args.total_max_loss,
    )

    results_grid = {}
    for risk in args.risk_grid:
        logger.info("Simulating risk=%.4f ...", risk)
        scaled_pnl = daily_pnl * (risk / 0.005) if np.mean(np.abs(daily_pnl)) > 0 else daily_pnl
        sim_result = simulate_prop_challenge(
            profile=profile,
            daily_pnl=scaled_pnl,
            n_simulations=args.n_paths,
            seed=args.seed,
        )
        results_grid[str(risk)] = {
            "risk_per_trade": risk,
            "pass_rate": sim_result.pass_rate,
            "median_days": sim_result.median_days_to_pass,
            "mean_max_dd": round(float(sim_result.mean_max_drawdown), 2),
            "daily_breach_rate": sim_result.daily_breach_rate,
        }
        logger.info(
            "  risk=%.4f pass=%.1f%% median_days=%s mean_max_dd=%.2f%%",
            risk,
            sim_result.pass_rate * 100,
            sim_result.median_days_to_pass or "N/A",
            sim_result.mean_max_drawdown * 100,
        )

    output = {
        "run_id": run_id,
        "profile": {
            "name": profile.name,
            "starting_balance": profile.starting_balance,
            "profit_target": profile.profit_target,
            "daily_max_loss": profile.daily_max_loss,
            "total_max_loss": profile.total_max_loss,
        },
        "n_paths": args.n_paths,
        "seed": args.seed,
        "daily_pnl_stats": {
            "count": len(daily_pnl),
            "mean": round(float(np.mean(daily_pnl)), 2),
            "std": round(float(np.std(daily_pnl)), 2),
            "sharpe_annual": round(float(np.mean(daily_pnl) / np.std(daily_pnl) * np.sqrt(252)), 4)
            if np.std(daily_pnl) > 0 else 0.0,
        },
        "results_by_risk": results_grid,
    }

    out_path = args.output_dir / f"prop_sim_{run_id}.json"
    out_path.write_text(json.dumps(output, indent=2))
    logger.info("Results saved to %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
