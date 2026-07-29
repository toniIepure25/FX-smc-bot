"""Gate C.2 synthetic control campaign.

Runs all four canonical runtime variants on deterministic synthetic data
to verify runtime operation. Reports event-state funnels, order counts,
fill counts, cancellation counts, lifecycle reconciliation, and
determinism across repeated runs.

Does NOT rank strategies by synthetic Sharpe or PnL.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.alpha.intraday.factory import create_runtime
from fx_smc_bot.backtesting.intraday_engine import IntradayBacktestEngine


def make_synthetic_series(
    pair: TradingPair,
    n: int = 500,
    base_price: float | None = None,
    seed: int = 42,
) -> BarSeries:
    """Create deterministic synthetic M5 data."""
    rng = np.random.default_rng(seed)

    if base_price is None:
        base_price = {
            TradingPair.EURUSD: 1.1000,
            TradingPair.GBPUSD: 1.2700,
            TradingPair.USDJPY: 140.00,
        }.get(pair, 1.1000)

    from fx_smc_bot.config import PAIR_PIP_INFO
    pip = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]

    start = datetime(2023, 6, 15, 8, 0, 0)
    delta = timedelta(minutes=5)
    timestamps = np.array(
        [np.datetime64(start + delta * i) for i in range(n)],
        dtype="datetime64[ns]",
    )

    close = np.zeros(n, dtype=np.float64)
    close[0] = base_price
    for i in range(1, n):
        close[i] = close[i - 1] + rng.normal(0, pip * 5)

    open_ = np.zeros(n, dtype=np.float64)
    open_[0] = base_price
    for i in range(1, n):
        open_[i] = close[i - 1] + rng.normal(0, pip)

    high = np.maximum(open_, close) + rng.uniform(0, pip * 10, n)
    low = np.minimum(open_, close) - rng.uniform(0, pip * 10, n)
    spread = np.full(n, pip * 1.5, dtype=np.float64)

    return BarSeries(
        pair=pair,
        timeframe=Timeframe.M5,
        timestamps=timestamps,
        open=open_, high=high, low=low, close=close,
        spread=spread,
    )


def run_campaign(seed: int = 42) -> dict:
    """Run all four canonical runtimes and collect funnels."""
    cfg = AppConfig()
    engine = IntradayBacktestEngine(config=cfg)

    runtimes = [
        ("liquidity_sweep_mss_fvg_reversal", TradingPair.EURUSD, "london"),
        ("liquidity_acceptance_fvg_continuation", TradingPair.EURUSD, "london"),
        ("opening_range_displacement_fvg_retest", TradingPair.EURUSD, "london"),
        ("opening_range_displacement_fvg_retest", TradingPair.EURUSD, "new_york"),
    ]

    for family, pair, session in runtimes:
        config = {}
        if family == "opening_range_displacement_fvg_retest":
            if session == "london":
                config = {
                    "range_start_local": "08:00",
                    "range_end_local": "08:30",
                    "session_cutoff_local": "12:00",
                    "session_timezone": "Europe/London",
                }
            else:
                config = {
                    "range_start_local": "09:30",
                    "range_end_local": "10:00",
                    "session_cutoff_local": "15:00",
                    "session_timezone": "America/New_York",
                }
        rt = create_runtime(family, pair, session, config)
        engine.add_runtime(rt)

    data = {
        TradingPair.EURUSD: make_synthetic_series(
            TradingPair.EURUSD, n=500, seed=seed,
        ),
    }

    result = engine.run(data)

    funnels = engine.get_funnels()
    recon = engine.reconcile()
    trades = engine.get_trade_records()

    report = {
        "seed": seed,
        "bars": 500,
        "pair": "EURUSD",
        "config_hash": result.config_hash,
        "funnels": {},
        "reconciliation": {
            "filled_with_matching_trade": recon.filled_with_matching_trade,
            "closed_with_matching_close": recon.closed_with_matching_close,
            "expired_without_fill": recon.expired_without_fill,
            "violations": recon.violations,
        },
        "trade_count": len(trades),
        "final_equity": result.final_equity,
    }

    for idx, funnel in funnels.items():
        report["funnels"][f"{funnel.family}_{funnel.session}"] = {
            "bars_processed": funnel.bars_processed,
            "intents_generated": funnel.intents_generated,
            "orders_accepted": funnel.orders_accepted,
            "orders_filled": funnel.orders_filled,
            "orders_cancelled": funnel.orders_cancelled,
            "orders_expired": funnel.orders_expired,
            "positions_closed": funnel.positions_closed,
            "sl_exits": funnel.sl_exits,
            "tp_exits": funnel.tp_exits,
        }

    return report


def main() -> None:
    print("Gate C.2 Synthetic Control Campaign")
    print("=" * 50)

    report1 = run_campaign(seed=42)
    report2 = run_campaign(seed=42)

    h1 = hashlib.sha256(
        json.dumps(report1, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    h2 = hashlib.sha256(
        json.dumps(report2, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    deterministic = h1 == h2

    report1["determinism_check"] = {
        "run1_hash": h1,
        "run2_hash": h2,
        "deterministic": deterministic,
    }

    output_dir = Path("results/gate_c2/synthetic_control")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "campaign_report.json"
    with open(output_path, "w") as f:
        json.dump(report1, f, indent=2, default=str)

    print(f"\nDeterministic: {deterministic}")
    print(f"Trade count: {report1['trade_count']}")
    print(f"Config hash: {report1['config_hash']}")
    print(f"\nFunnels:")
    for name, funnel in report1["funnels"].items():
        print(f"  {name}:")
        print(f"    bars: {funnel['bars_processed']}")
        print(f"    intents: {funnel['intents_generated']}")
        print(f"    fills: {funnel['orders_filled']}")
        print(f"    expired: {funnel['orders_expired']}")
        print(f"    closed: {funnel['positions_closed']}")

    print(f"\nReconciliation:")
    recon = report1["reconciliation"]
    print(f"  Violations: {recon['violations']}")
    print(f"\nSaved to: {output_path}")

    if not deterministic:
        print("\nERROR: Non-deterministic results!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
