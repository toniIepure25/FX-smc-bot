"""Gate P0 strategy-alpha research helpers.

This module deliberately works on source/configuration files and compact
aggregate artifacts only. It does not enumerate or open market-data storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from fx_smc_bot.data.holdout_access import AccessPurpose, guard_holdout

PROGRAM_ID = "FX_SMC_STRATEGY_ALPHA_V1"
LINEAGE_ID = "FX_SMC_STRATEGY_ALPHA_PROSPECTIVE_LINEAGE_V1"
LEGACY_LINEAGE_ID = "USDJPY_ACCEPTANCE_RESEARCH_LINEAGE_V1"
LEGACY_SEAL_HASH = "00581da471f6c7c7d06d10d59c2b58fd03fab7a654bf4dac792451a829e4b1e4"
LEGACY_MANIFEST_HASH = "9b3d806fec2a5730c30854b82cdf57f1f17b8cf185f6a6826658e3bf394808bb"
MERGE_COMMIT = "ada8177c738b08f9a119d28a3e8b1fdeea7ef0b2"

FORBIDDEN_HOLDOUT_YEARS = {"2023", "2024", "2025"}
HISTORICAL_WINDOWS = {
    "engineering": ("2015-01-01", "2018-12-31"),
    "historical_replay": ("2019-01-01", "2019-12-31"),
    "historical_stress": ("2020-01-01", "2022-12-31"),
    "combined": ("2015-01-01", "2022-12-31"),
}
SEEDS = [1729, 1729, 1729]


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    candidate_id: str
    strategy_family: str
    config_path: str
    config_raw_hash: str
    config_canonical_hash: str
    instruments: list[str]
    sessions: list[str]
    signal_timestamp: str
    entry_rule: str
    order_type: str
    order_expiry: str
    stop_loss_rule: str
    take_profit_rule: str
    time_exit: str
    maximum_holding_time: str
    risk_normalization: str
    overlap_rule: str
    maximum_concurrent_exposure: int
    cost_assumptions: dict[str, Any]
    invalid_data_behavior: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate_id: str
    period: str
    label: str
    trade_count: int
    gross_r: float
    net_r: float
    mean_net_r: float
    median_net_r: float
    win_rate: float
    average_win: float
    average_loss: float
    payoff_ratio: float
    profit_factor: float
    sharpe: float
    probabilistic_sharpe: float
    deflated_sharpe: float
    sortino: float
    calmar: float
    max_drawdown_r: float
    max_drawdown_pct: float
    cost_drag_r: float
    stress_1_5x_mean_net_r: float
    stress_2_0x_mean_net_r: float
    matched_benchmark_alpha: float
    matched_benchmark_p: float
    day_cluster_ci: tuple[float, float]
    week_cluster_ci: tuple[float, float]
    best_trade_share: float
    best_5_trade_share: float
    best_month_share: float
    best_year_share: float
    leave_one_year_out_positive: bool
    status: str
    reason: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def canonical_yaml_sha256(path: Path) -> str:
    return canonical_json_sha256(load_yaml(path))


def assert_no_sealed_holdout_path(path: Path | str) -> None:
    """Reject paths that point at registered sealed holdout years or directories."""
    text = Path(path).as_posix().lower()
    if "holdout" in text or any(
        f"/{year}" in text or year in Path(text).name for year in FORBIDDEN_HOLDOUT_YEARS
    ):
        raise ValueError(f"sealed holdout path is not permitted in P0: {path}")


def assert_historical_window(start: str, end: str) -> None:
    guard_holdout(start, end, AccessPurpose.STRATEGY_BACKTEST)


def load_candidate_specs(repo: Path) -> list[CandidateSpec]:
    specs = []
    candidates = [
        (
            "SMC_A_SWEEP_REVERSAL_V1",
            "liquidity_sweep_mss_fvg_reversal",
            "configs/research/intraday_smc/sweep_reversal.yaml",
            ["london", "new_york"],
            "limit order at FVG retracement after sweep, reclaim, MSS and displacement are final",
        ),
        (
            "SMC_B_ACCEPTANCE_CONTINUATION_V1",
            "liquidity_acceptance_fvg_continuation",
            "configs/research/intraday_smc/acceptance_continuation.yaml",
            ["london", "new_york"],
            "limit order at FVG retracement after acceptance and displacement bars are final",
        ),
        (
            "SMC_C_LONDON_OPENING_RANGE_V1",
            "opening_range_displacement_fvg_retest",
            "configs/research/intraday_smc/opening_range.yaml",
            ["london"],
            "limit order at FVG retracement after London opening-range breakout is final",
        ),
        (
            "SMC_C_NEWYORK_OPENING_RANGE_V1",
            "opening_range_displacement_fvg_retest",
            "configs/research/intraday_smc/opening_range.yaml",
            ["new_york"],
            "limit order at FVG retracement after New York opening-range breakout is final",
        ),
    ]
    for candidate_id, family, config_path, sessions, entry_rule in candidates:
        path = repo / config_path
        payload = load_yaml(path)
        execution = payload.get("execution", {})
        risk = payload.get("risk", {})
        instruments = payload.get("instruments", {})
        primary = list(instruments.get("primary", []))
        control = list(instruments.get("control", []))
        specs.append(
            CandidateSpec(
                candidate_id=candidate_id,
                strategy_family=family,
                config_path=config_path,
                config_raw_hash=raw_sha256(path),
                config_canonical_hash=canonical_yaml_sha256(path),
                instruments=[*primary, *control],
                sessions=sessions,
                signal_timestamp="bar-close after all required signal-bar values are final",
                entry_rule=entry_rule,
                order_type="LIMIT",
                order_expiry=f"{_max_order_bars(payload)} bars",
                stop_loss_rule="configured ATR/spread/pip buffer beyond invalidation level",
                take_profit_rule="configured target_r multiple of initial risk",
                time_exit="session cutoff or maximum holding/order bars where implemented",
                maximum_holding_time=(
                    "bounded by strategy runtime/session cutoff; audited as PARTIAL"
                ),
                risk_normalization="1R equals initial stop-loss distance including entry costs",
                overlap_rule="max one active same-instrument position per candidate",
                maximum_concurrent_exposure=int(risk.get("max_concurrent_positions", 1)),
                cost_assumptions={
                    "spread": "actual bid/ask when certified, conservative fallback otherwise",
                    "slippage_pips": execution.get("slippage_pips"),
                    "commission_per_lot": execution.get("commission_per_lot"),
                    "swap": "default conservative swap table for overnight holds",
                },
                invalid_data_behavior="NO_TRADE_WITH_RECORDED_REASON",
            )
        )
    return specs


def _max_order_bars(payload: dict[str, Any]) -> int:
    for value in payload.values():
        if isinstance(value, dict) and "max_order_bars" in value:
            return int(value["max_order_bars"])
    return 20


def capability_matrix() -> dict[str, dict[str, str]]:
    return {
        "signal_timestamping": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "CausalBarContext carries bar_idx and timestamp.",
        },
        "entry_timing": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Pending orders are processed on subsequent bars in the engine loop.",
        },
        "market_and_limit_orders": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "FillEngine and BidAskFillEngine implement MARKET/LIMIT/STOP.",
        },
        "bid_ask_execution": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "BidAskFillEngine uses ask for long entry and bid for short entry.",
        },
        "same_bar_ambiguity": {
            "status": "CERTIFIED",
            "evidence": "Conservative fill policy resolves SL before TP.",
        },
        "spread": {
            "status": "PARTIAL",
            "evidence": "Native bid/ask embeds actual spread; fallback fixed spread exists.",
        },
        "slippage": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Fixed and native bid/ask slippage models exist.",
        },
        "commission": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "TradeLedger has commission_per_lot.",
        },
        "swap": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "SwapCalculator exists for overnight positions.",
        },
        "position_sizing": {
            "status": "PARTIAL",
            "evidence": "Portfolio state exists; 1R normalized P0 layer required.",
        },
        "overlapping_positions": {
            "status": "PARTIAL",
            "evidence": "Portfolio state exists; candidate-level overlap guard required.",
        },
        "maximum_exposure": {
            "status": "PARTIAL",
            "evidence": "Configs define max_concurrent_positions.",
        },
        "session_cutoffs": {
            "status": "PARTIAL",
            "evidence": "Session classification exists; hard cutoff enforcement varies by runtime.",
        },
        "dst_handling": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Timezone/session utilities exist.",
        },
        "weekend_handling": {
            "status": "PARTIAL",
            "evidence": "Data-quality handling exists; P0 no-trade policy freezes missing periods.",
        },
        "missing_bars": {
            "status": "PARTIAL",
            "evidence": "Provenance records missing intervals; P0 freezes no interpolation.",
        },
        "partial_fills": {"status": "MISSING", "evidence": "Order model fills all units."},
        "order_expiry": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Orders expire via expires_at.",
        },
        "trade_ledger": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "TradeLedger exists; P0 commits aggregate-only outputs.",
        },
        "equity_curve": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "BacktestResult and metrics consume equity curve.",
        },
        "drawdown": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Performance metrics compute max drawdown.",
        },
        "deterministic_replay": {
            "status": "PARTIAL",
            "evidence": "Seeded components exist; P0 adds deterministic aggregate replay audit.",
        },
        "random_seed_control": {
            "status": "IMPLEMENTED_NOT_CERTIFIED",
            "evidence": "Campaign and fill engines accept seeds.",
        },
        "benchmark_generation": {
            "status": "MISSING",
            "evidence": "P0 must freeze benchmarks before alpha claims.",
        },
        "block_bootstrap_inference": {
            "status": "PARTIAL",
            "evidence": (
                "Research inference utilities exist; strategy-level inference is P0 scoped."
            ),
        },
    }


def execution_model_spec() -> dict[str, Any]:
    return {
        "signal_availability": "orders may be placed only after signal bar t is final",
        "market_entry": {
            "long": "ask at first executable bar after signal",
            "short": "bid at first executable bar after signal",
        },
        "exit": {"long": "bid", "short": "ask"},
        "limit_orders": "executable side must reach price after order creation",
        "same_bar_ambiguity_primary": "adverse-first",
        "same_bar_optimistic_sensitivity": "reported but never primary",
        "costs_primary": ["spread", "commission", "slippage", "swap"],
        "slippage_scenarios": {"base": 1.0, "stress_1": 1.5, "stress_2": 2.0},
        "position_sizing": ["1R normalized", "0.25% fixed fractional", "0.50% fixed fractional"],
        "exposure": "config max concurrent, one active same-instrument position per candidate",
        "data_failure": "NO_TRADE_WITH_RECORDED_REASON",
    }


def empty_candidate_result(candidate_id: str, period: str) -> CandidateResult:
    label = "EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY"
    return CandidateResult(
        candidate_id=candidate_id,
        period=period,
        label=label,
        trade_count=0,
        gross_r=0.0,
        net_r=0.0,
        mean_net_r=0.0,
        median_net_r=0.0,
        win_rate=0.0,
        average_win=0.0,
        average_loss=0.0,
        payoff_ratio=0.0,
        profit_factor=0.0,
        sharpe=0.0,
        probabilistic_sharpe=0.0,
        deflated_sharpe=0.0,
        sortino=0.0,
        calmar=0.0,
        max_drawdown_r=0.0,
        max_drawdown_pct=0.0,
        cost_drag_r=0.0,
        stress_1_5x_mean_net_r=0.0,
        stress_2_0x_mean_net_r=0.0,
        matched_benchmark_alpha=0.0,
        matched_benchmark_p=1.0,
        day_cluster_ci=(0.0, 0.0),
        week_cluster_ci=(0.0, 0.0),
        best_trade_share=0.0,
        best_5_trade_share=0.0,
        best_month_share=0.0,
        best_year_share=0.0,
        leave_one_year_out_positive=False,
        status="INSUFFICIENT_CERTIFIED_HISTORICAL_EXECUTION_SAMPLE",
        reason=(
            "P0 did not access market-data storage; no certified aggregate-only "
            "strategy trade sample exists for this new lineage."
        ),
    )


def evaluate_candidates_aggregate_only(candidates: list[CandidateSpec]) -> dict[str, Any]:
    results: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        candidate_results = []
        for period, (start, end) in HISTORICAL_WINDOWS.items():
            assert_historical_window(start, end)
            candidate_results.append(
                empty_candidate_result(candidate.candidate_id, period).to_record()
            )
        results[candidate.candidate_id] = candidate_results
    return {
        "created_at_utc": now_utc(),
        "label": "EXPLORATORY_HISTORICAL_STRATEGY_FEASIBILITY",
        "storage_policy": "no market-data storage enumerated; committed aggregates only",
        "results": results,
        "status": "PASS",
    }


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    total = len(ordered)
    running = 0.0
    for rank, (name, p_value) in enumerate(ordered, start=1):
        running = max(running, min(1.0, p_value * (total - rank + 1)))
        adjusted[name] = running
    return adjusted


def adjudicate(candidates: list[CandidateSpec], evaluation: dict[str, Any]) -> dict[str, Any]:
    adjudications = []
    p_values = {candidate.candidate_id: 1.0 for candidate in candidates}
    adjusted = holm_adjust(p_values)
    for candidate in candidates:
        combined = next(
            item
            for item in evaluation["results"][candidate.candidate_id]
            if item["period"] == "combined"
        )
        sample_ok = combined["trade_count"] >= 100
        tier_a = {
            "minimum_sample": sample_ok,
            "mean_net_r_positive": combined["mean_net_r"] > 0,
            "ci_lower_positive": combined["day_cluster_ci"][0] > 0,
            "profit_factor": combined["profit_factor"] > 1.05,
            "cost_stress": combined["stress_1_5x_mean_net_r"] > 0,
            "loo_positive": combined["leave_one_year_out_positive"],
            "concentration": combined["best_year_share"] < 0.50
            and combined["best_5_trade_share"] < 0.35,
            "drawdown": combined["max_drawdown_r"] <= 20,
            "benchmark_alpha": combined["matched_benchmark_alpha"] > 0
            and adjusted[candidate.candidate_id] < 0.05,
        }
        tier_b = {
            "minimum_sample": sample_ok,
            "mean_net_r_positive": combined["mean_net_r"] > 0,
            "ci_lower_not_worse_than_minus_0_05": combined["day_cluster_ci"][0] >= -0.05,
            "profit_factor": combined["profit_factor"] > 1.0,
            "cost_stress": combined["stress_1_5x_mean_net_r"] >= 0,
            "window_stability": False,
            "concentration": combined["best_year_share"] < 0.60,
            "drawdown": combined["max_drawdown_r"] <= 25,
            "benchmark_alpha": combined["matched_benchmark_alpha"] > 0,
        }
        final_tier = (
            "TIER_A_PRIMARY_ELIGIBLE"
            if all(tier_a.values())
            else "TIER_B_SECONDARY_ELIGIBLE"
            if all(tier_b.values())
            else "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST"
        )
        adjudications.append(
            {
                "candidate_id": candidate.candidate_id,
                "sample_eligibility": sample_ok,
                "tier_a_criteria": tier_a,
                "tier_b_criteria": tier_b,
                "failed_criteria": [
                    name for name, passed in {**tier_a, **tier_b}.items() if not passed
                ],
                "holm_adjusted_p": adjusted[candidate.candidate_id],
                "final_tier": final_tier,
                "forward_test_eligibility": final_tier
                != "TIER_C_NOT_ELIGIBLE_FOR_PROSPECTIVE_FORWARD_TEST",
            }
        )
    return {
        "created_at_utc": now_utc(),
        "adjudications": adjudications,
        "primary_candidate": None,
        "secondary_candidate": None,
        "status": "PASS",
    }


def deterministic_replay_hash(payload: Any) -> str:
    return canonical_json_sha256(payload)


def prospective_start_after_commit(commit_time: datetime) -> str:
    next_day = commit_time.astimezone(UTC).date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return date.isoformat(next_day)


def aggregate_contains_row_level_fields(payload: Any) -> bool:
    row_keys = {"timestamp", "entry", "exit", "entry_price", "exit_price", "trade_id", "pnl"}

    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            keys = {str(key).lower() for key in value}
            if keys & row_keys and "trade_count" not in keys:
                return True
            return any(walk(child) for child in value.values())
        if isinstance(value, list):
            return any(walk(child) for child in value)
        return False

    return walk(payload)
