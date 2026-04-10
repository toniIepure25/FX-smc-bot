"""Baseline strategies for benchmarking SMC/ICT signal value-add.

All baselines implement the SetupDetector protocol from setup_families.py,
making them plug-compatible with the existing alpha/backtest pipeline.
"""

from fx_smc_bot.alpha.baselines.momentum import MomentumDetector
from fx_smc_bot.alpha.baselines.session_breakout import SessionBreakoutDetector
from fx_smc_bot.alpha.baselines.mean_reversion import MeanReversionDetector

__all__ = [
    "MomentumDetector",
    "SessionBreakoutDetector",
    "MeanReversionDetector",
]
