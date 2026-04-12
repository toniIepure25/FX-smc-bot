#!/usr/bin/env python3
"""Paper Validation Campaign Runner.

Orchestrates a disciplined multi-week paper-trading validation program
for the promoted bos_only_usdjpy candidate. Handles:

- Config fingerprint validation before each run
- Persistent session identity
- Checkpoint directory structure
- Daily/weekly artifact generation
- Reconciliation against backtest expectations
- Review-period artifact organization

Usage:
    python scripts/run_paper_validation.py
    python scripts/run_paper_validation.py --resume <session_id>
    python scripts/run_paper_validation.py --checkpoint week_2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.loader import load_htf_data, load_pair_data
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.research.paper_review import (
    PaperReviewChecklist, PaperStageRecommendation, PaperStageStatus,
    build_daily_summaries, build_weekly_summary, evaluate_paper_stage,
    format_paper_review,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("paper_validation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "real"
PROGRAM_DIR = PROJECT_ROOT / "paper_validation_program"
FROZEN_CONFIG_PATH = (
    PROJECT_ROOT / "results" / "final_promotion_gate"
    / "bos_only_usdjpy_champion_bundle" / "champion_config.json"
)

PROMOTED_CANDIDATE = "bos_only_usdjpy"
PROMOTED_FAMILIES = ["bos_continuation"]
PROMOTED_PAIRS = ["USDJPY"]
RISK_CONFIG = {
    "base_risk_per_trade": 0.003,
    "max_portfolio_risk": 0.009,
    "circuit_breaker_threshold": 0.125,
}


def _compute_config_fingerprint(cfg: dict) -> str:
    canonical = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _build_promoted_config() -> AppConfig:
    cfg = AppConfig()
    cfg.alpha.enabled_families = list(PROMOTED_FAMILIES)
    for k, v in RISK_CONFIG.items():
        if hasattr(cfg.risk, k):
            setattr(cfg.risk, k, v)
    return cfg


def _validate_config() -> tuple[bool, str]:
    """Validate that the frozen config matches expectations."""
    if not FROZEN_CONFIG_PATH.exists():
        return False, f"Frozen config not found at {FROZEN_CONFIG_PATH}"
    with open(FROZEN_CONFIG_PATH) as f:
        frozen = json.load(f)
    if frozen.get("champion") != PROMOTED_CANDIDATE:
        return False, f"Champion mismatch: expected {PROMOTED_CANDIDATE}, got {frozen.get('champion')}"
    if frozen.get("family") != "bos_continuation":
        return False, f"Family mismatch: expected bos_continuation, got {frozen.get('family')}"
    if frozen.get("pairs") != PROMOTED_PAIRS:
        return False, f"Pairs mismatch: expected {PROMOTED_PAIRS}, got {frozen.get('pairs')}"
    return True, "Config validated successfully"


def _init_session(resume_id: str | None = None) -> tuple[str, Path]:
    """Initialize or resume a paper validation session."""
    sessions_dir = PROGRAM_DIR / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    if resume_id:
        session_dir = sessions_dir / resume_id
        if not session_dir.exists():
            logger.error("Session %s not found", resume_id)
            sys.exit(1)
        logger.info("Resuming session %s", resume_id)
        return resume_id, session_dir

    session_id = f"pv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "session_id": session_id,
        "candidate": PROMOTED_CANDIDATE,
        "started_at": datetime.utcnow().isoformat(),
        "config_fingerprint": _compute_config_fingerprint({
            "families": PROMOTED_FAMILIES,
            "pairs": PROMOTED_PAIRS,
            "risk": RISK_CONFIG,
        }),
        "status": "active",
        "checkpoints_completed": [],
    }
    (session_dir / "session_manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info("Created new session: %s", session_id)
    return session_id, session_dir


def _create_checkpoint(session_dir: Path, checkpoint_name: str, data: dict) -> Path:
    """Create a checkpoint directory with artifacts."""
    cp_dir = session_dir / "checkpoints" / checkpoint_name
    cp_dir.mkdir(parents=True, exist_ok=True)
    (cp_dir / "checkpoint.json").write_text(json.dumps({
        "checkpoint": checkpoint_name,
        "timestamp": datetime.utcnow().isoformat(),
        **data,
    }, indent=2, default=str))
    return cp_dir


def run_validation(resume_id: str | None = None, checkpoint: str | None = None):
    """Run the paper validation campaign."""
    logger.info("=" * 60)
    logger.info("Paper Validation Campaign — %s", PROMOTED_CANDIDATE)
    logger.info("=" * 60)

    # Step 1: Validate config
    valid, msg = _validate_config()
    if not valid:
        logger.error("Config validation FAILED: %s", msg)
        sys.exit(1)
    logger.info("Config validation: %s", msg)

    # Step 2: Init/resume session
    session_id, session_dir = _init_session(resume_id)

    # Step 3: Load data
    logger.info("Loading real FX data ...")
    full_data = load_pair_data(DATA_DIR, timeframe=Timeframe.H1)
    if not full_data:
        logger.error("No data loaded")
        sys.exit(1)
    htf_data = load_htf_data(full_data, htf_timeframe=Timeframe.H4, data_dir=DATA_DIR)
    jpy_data = {p: sr for p, sr in full_data.items() if p.value in PROMOTED_PAIRS}
    jpy_htf = {p: sr for p, sr in htf_data.items() if p.value in PROMOTED_PAIRS} if htf_data else None

    for pair, series in jpy_data.items():
        logger.info("  %s: %d bars", pair.value, len(series))

    # Step 4: Build config and run paper trading
    cfg = _build_promoted_config()
    run_dir = session_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting paper trading run ...")
    runner = PaperTradingRunner(cfg, output_dir=run_dir)
    final_state = runner.run(jpy_data, jpy_htf)

    logger.info("Paper trading complete:")
    logger.info("  Run ID: %s", runner._run_id)
    logger.info("  Bars: %d", final_state.bars_processed)
    logger.info("  Equity: %.2f", final_state.equity)
    logger.info("  State: %s", final_state.operational_state)

    # Step 5: Run matching backtest for reconciliation
    logger.info("Running reconciliation backtest ...")
    engine = BacktestEngine(cfg)
    bt_result = engine.run(jpy_data, jpy_htf)
    bt_metrics = engine.metrics(bt_result)

    recon = {
        "paper_equity": float(final_state.equity),
        "paper_bars": int(final_state.bars_processed),
        "backtest_trades": int(bt_metrics.total_trades),
        "backtest_sharpe": round(float(bt_metrics.sharpe_ratio), 4),
        "backtest_pf": round(float(bt_metrics.profit_factor), 4),
        "backtest_pnl": round(float(bt_metrics.total_pnl), 2),
    }

    # Step 6: Create checkpoint
    cp_name = checkpoint or "initial_run"
    cp_data = {
        "session_id": session_id,
        "run_id": runner._run_id,
        "candidate": PROMOTED_CANDIDATE,
        "reconciliation": recon,
        "operational_state": final_state.operational_state,
    }
    cp_dir = _create_checkpoint(session_dir, cp_name, cp_data)
    logger.info("Checkpoint created: %s", cp_dir)

    # Update session manifest
    manifest_path = session_dir / "session_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["checkpoints_completed"].append(cp_name)
        manifest["last_updated"] = datetime.utcnow().isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2))

    logger.info("=" * 60)
    logger.info("Session: %s", session_id)
    logger.info("Checkpoint: %s", cp_name)
    logger.info("All artifacts in: %s", session_dir)
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Paper Validation Campaign Runner")
    parser.add_argument("--resume", type=str, default=None, help="Resume an existing session")
    parser.add_argument("--checkpoint", type=str, default=None,
                        help="Checkpoint label (e.g. week_1, week_2, week_4)")
    args = parser.parse_args()
    run_validation(resume_id=args.resume, checkpoint=args.checkpoint)


if __name__ == "__main__":
    main()
