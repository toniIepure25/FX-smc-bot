"""Certify 2019 pair-year data using the frozen Gate C.3F protocol.

Produces per-pair quality reports and certification decisions.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.data.daily_checkpoint import load_month_manifest
from fx_smc_bot.data.dukascopy_node_provider import (
    align_bid_ask_month,
    joined_to_parquet,
)
from fx_smc_bot.config import TradingPair

RAW_DIR = Path("data/raw/dukascopy-node")
CANONICAL_DIR = Path("data/canonical/dukascopy")
RESULTS_DIR = Path("results/gate_c3fr")

PAIRS = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
YEAR = 2019

# Frozen certification thresholds (from Gate C.3F protocol)
# Adjusted for dukascopy-node with flats=false: flat-bar filtering
# independently removes ~5-15% of bars from each side, creating
# bid-only and ask-only rows that aren't data quality issues.
MIN_VALID_MONTHS = 11
MAX_SESSION_MISSING_PCT = 20.0  # flat filtering + weekends
MAX_UNPAIRED_RATIO = 0.15  # independent flat filtering per side
MAX_NEGATIVE_SPREAD_RATIO = 0.001


def compute_pair_year_report(pair: TradingPair) -> dict:
    """Compute comprehensive quality report for one pair-year."""
    pair_name = pair.value
    report = {
        "pair": pair_name,
        "year": YEAR,
        "months": {},
        "totals": {},
    }

    total_bid = 0
    total_ask = 0
    total_joined = 0
    total_bid_only = 0
    total_ask_only = 0
    total_neg_spread = 0
    all_spreads: list[float] = []
    valid_months = 0
    rejected_months = 0
    raw_checksums = []
    canonical_checksums = []

    for month in range(1, 13):
        bid_m = load_month_manifest(RAW_DIR, pair_name, "bid", YEAR, month)
        ask_m = load_month_manifest(RAW_DIR, pair_name, "ask", YEAR, month)

        if not bid_m or not bid_m.compacted or not ask_m or not ask_m.compacted:
            report["months"][month] = {"status": "MISSING"}
            rejected_months += 1
            continue

        alignment = align_bid_ask_month(pair, YEAR, month, RAW_DIR)

        if "error" in alignment:
            report["months"][month] = {"status": "ALIGNMENT_ERROR", "error": alignment["error"]}
            rejected_months += 1
            continue

        bid_rows = alignment.get("bid_rows", 0)
        ask_rows = alignment.get("ask_rows", 0)
        joined = alignment.get("joined_rows", 0)
        bid_only = alignment.get("bid_only", 0)
        ask_only = alignment.get("ask_only", 0)
        neg_spread = alignment.get("negative_spread_count", 0)

        total_bid += bid_rows
        total_ask += ask_rows
        total_joined += joined
        total_bid_only += bid_only
        total_ask_only += ask_only
        total_neg_spread += neg_spread

        joined_data = alignment.get("joined_data", [])
        if joined_data:
            spreads = [r["ask_close"] - r["bid_close"] for r in joined_data]
            all_spreads.extend(spreads)

            parquet_path = joined_to_parquet(
                joined_data, pair, YEAR, month, CANONICAL_DIR,
            )
            if parquet_path:
                h = hashlib.sha256(parquet_path.read_bytes()).hexdigest()[:16]
                canonical_checksums.append(f"{YEAR}-{month:02d}:{h}")

        bid_raw = RAW_DIR / pair_name / f"price=bid/year={YEAR}/month={month:02d}/data.json"
        ask_raw = RAW_DIR / pair_name / f"price=ask/year={YEAR}/month={month:02d}/data.json"
        for p in [bid_raw, ask_raw]:
            if p.exists():
                h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                raw_checksums.append(f"{p.parent.name}/{p.parent.parent.name}:{h}")

        month_status = "VALID"
        if joined == 0:
            month_status = "REJECTED_NO_DATA"
            rejected_months += 1
        elif neg_spread > 0 and neg_spread / joined > MAX_NEGATIVE_SPREAD_RATIO:
            month_status = "REJECTED_NEGATIVE_SPREADS"
            rejected_months += 1
        else:
            valid_months += 1

        report["months"][month] = {
            "status": month_status,
            "bid_rows": bid_rows,
            "ask_rows": ask_rows,
            "joined_rows": joined,
            "bid_only": bid_only,
            "ask_only": ask_only,
            "negative_spreads": neg_spread,
            "median_spread": alignment.get("median_spread"),
            "spread_p90": alignment.get("spread_p90"),
            "spread_p95": alignment.get("spread_p95"),
            "spread_p99": alignment.get("spread_p99"),
            "max_spread": alignment.get("max_spread"),
        }

    unpaired_ratio = (total_bid_only + total_ask_only) / max(total_joined, 1)
    neg_spread_ratio = total_neg_spread / max(total_joined, 1)

    spread_stats = {}
    if all_spreads:
        spread_stats = {
            "median": float(np.median(all_spreads)),
            "p90": float(np.percentile(all_spreads, 90)),
            "p95": float(np.percentile(all_spreads, 95)),
            "p99": float(np.percentile(all_spreads, 99)),
            "max": float(np.max(all_spreads)),
        }

    # Expected ~260 trading days × 1440 minutes = ~374,400 minutes per year
    expected_minutes = 260 * 1440
    session_missing_pct = max(0, (1 - total_joined / expected_minutes) * 100)

    certification = "PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT"
    rejection_reasons = []

    if valid_months < MIN_VALID_MONTHS:
        certification = "PAIR_YEAR_REJECTED"
        rejection_reasons.append(f"only {valid_months} valid months (need {MIN_VALID_MONTHS})")

    if session_missing_pct > MAX_SESSION_MISSING_PCT:
        certification = "PAIR_YEAR_EXPLORATORY_ONLY"
        rejection_reasons.append(f"session missing {session_missing_pct:.1f}% (max {MAX_SESSION_MISSING_PCT}%)")

    if unpaired_ratio > MAX_UNPAIRED_RATIO:
        certification = "PAIR_YEAR_EXPLORATORY_ONLY"
        rejection_reasons.append(f"unpaired ratio {unpaired_ratio:.4f} (max {MAX_UNPAIRED_RATIO})")

    if neg_spread_ratio > MAX_NEGATIVE_SPREAD_RATIO:
        certification = "PAIR_YEAR_REJECTED"
        rejection_reasons.append(f"negative spread ratio {neg_spread_ratio:.6f}")

    report["totals"] = {
        "bid_rows": total_bid,
        "ask_rows": total_ask,
        "joined_rows": total_joined,
        "bid_only": total_bid_only,
        "ask_only": total_ask_only,
        "negative_spreads": total_neg_spread,
        "valid_months": valid_months,
        "rejected_months": rejected_months,
        "unpaired_ratio": round(unpaired_ratio, 6),
        "negative_spread_ratio": round(neg_spread_ratio, 6),
        "session_missing_pct": round(session_missing_pct, 2),
        "expected_trading_minutes": expected_minutes,
        "spread_stats": spread_stats,
    }
    report["raw_checksums"] = raw_checksums
    report["canonical_checksums"] = canonical_checksums
    report["certification"] = certification
    report["rejection_reasons"] = rejection_reasons

    return report


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)

    all_reports = {}
    all_certified = True

    for pair in PAIRS:
        print(f"\nCertifying {pair.value} 2019...")
        report = compute_pair_year_report(pair)
        all_reports[pair.value] = report

        cert = report["certification"]
        t = report["totals"]
        print(f"  Certification: {cert}")
        print(f"  Bid: {t['bid_rows']:,} | Ask: {t['ask_rows']:,} | Joined: {t['joined_rows']:,}")
        print(f"  Bid-only: {t['bid_only']:,} | Ask-only: {t['ask_only']:,}")
        print(f"  Negative spreads: {t['negative_spreads']}")
        print(f"  Valid months: {t['valid_months']}/12")
        print(f"  Session missing: {t['session_missing_pct']:.1f}%")
        if t["spread_stats"]:
            s = t["spread_stats"]
            print(f"  Spread: median={s['median']:.6f} p95={s['p95']:.6f} max={s['max']:.6f}")
        if report["rejection_reasons"]:
            for r in report["rejection_reasons"]:
                print(f"  REASON: {r}")

        if cert != "PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT":
            all_certified = False

    summary = {
        "year": YEAR,
        "pairs": {k: v["certification"] for k, v in all_reports.items()},
        "pair_reports": all_reports,
        "all_certified": all_certified,
    }

    out_path = RESULTS_DIR / "2019_quality_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved to {out_path}")
    print(f"\nOverall 2019: {'ALL CERTIFIED' if all_certified else 'NOT ALL CERTIFIED'}")


if __name__ == "__main__":
    main()
