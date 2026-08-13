"""V3 research family/archetype registry.

Each family begins from an economic or statistical *hypothesis* -- never an arbitrary
indicator combination. A family declares its horizon, the mechanism it bets on, the exact
causal feature-DAG nodes it consumes, the capability keys it needs, its parameter families,
its expected turnover and cost sensitivity, a plausible failure mode and a falsification
criterion. Complexity is admitted only where the hypothesis needs it.

Some listed families deliberately require UNSUPPORTED signal inputs (true tick arrival,
order-book depth). They are kept in the registry so the compiler can *reject* them
pre-outcome -- demonstrating that admission is a real gate, not a rubber stamp, and that
tick semantics are never faked from M1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.horizons import HorizonClass


@dataclass(frozen=True, slots=True)
class Family:
    family_id: str
    domain: str  # single-letter domain code A..M
    horizon: HorizonClass
    hypothesis: str
    mechanism: str
    feature_nodes: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    instrument_scope: str  # "self" | "panel" | "triangle" | named subset
    parameter_scales: tuple[str, ...]
    expected_turnover: str  # "very_high" | "high" | "medium" | "low"
    cost_sensitivity: str  # "extreme" | "high" | "medium" | "low"
    failure_mode: str
    falsification: str
    # Conditioning families (regime/state) are never traded standalone; they register
    # candidates only inside composition archetypes. standalone=False marks them.
    standalone: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "domain": self.domain,
            "horizon": self.horizon.value,
            "hypothesis": self.hypothesis,
            "mechanism": self.mechanism,
            "feature_nodes": list(self.feature_nodes),
            "required_capabilities": list(self.required_capabilities),
            "instrument_scope": self.instrument_scope,
            "parameter_scales": list(self.parameter_scales),
            "expected_turnover": self.expected_turnover,
            "cost_sensitivity": self.cost_sensitivity,
            "failure_mode": self.failure_mode,
            "falsification": self.falsification,
            "standalone": self.standalone,
        }


H0 = HorizonClass.H0_MICRO_INTRADAY
H1 = HorizonClass.H1_SESSION_DAILY
H2 = HorizonClass.H2_INTRAWEEK
H3 = HorizonClass.H3_INTRAMONTH

FAMILIES: tuple[Family, ...] = (
    # --- A: classical technical structure ---
    Family(
        "V3_A_DONCHIAN_BREAKOUT_POST_COMPRESSION", "A", H0,
        "Breakouts of a causal Donchian channel are informative only when they follow a "
        "range-compression regime, not in already-trending noise.",
        "Enter on close beyond the prior N-bar high/low conditioned on range_compression "
        "being in a low percentile; exit on time or opposite channel.",
        ("mid_close", "range_compression", "atr"),
        ("M1_BIDASK_OHLC", "RANGE_ESTIMATORS_M1"),
        "self", ("lookback_bars_intraday", "entry_threshold_sigma"),
        "high", "high",
        "Breakout is a liquidity vacuum that immediately reverts (failed breakout).",
        "No positive net edge over cost after compression-conditioning across folds.",
    ),
    # --- B: time-series momentum / trend ---
    Family(
        "V3_B_MULTISCALE_TSMOM_VOLSCALED", "B", H1,
        "Volatility-scaled multi-scale trend persists intraday within a session.",
        "Sign-consistent OLS slope t-stat across two lookbacks, position scaled by inverse "
        "realized vol; flat by NY close.",
        ("trend_slope", "mom_zscore", "realized_vol"),
        ("M1_BIDASK_OHLC", "M1_RETURNS", "M1_REALIZED_VOL"),
        "self", ("lookback_bars_intraday", "entry_threshold_sigma"),
        "medium", "medium",
        "Trend is already priced; slope t-stat is autocorrelation of noise.",
        "Slope-sign edge indistinguishable from zero after vol-scaling and cost.",
    ),
    Family(
        "V3_B_TREND_PULLBACK_ENTRY", "B", H1,
        "A longer-horizon trend with a shorter-horizon counter-move gives a better entry "
        "than chasing the breakout.",
        "Gate on positive multi-hour trend_slope; enter on short-horizon mom_zscore pullback "
        "against the trend; exit on trend resumption or time.",
        ("trend_slope", "mom_zscore"),
        ("M1_BIDASK_OHLC", "M1_RETURNS"),
        "self", ("lookback_bars_intraday", "entry_threshold_sigma"),
        "medium", "medium",
        "Pullback is the start of a reversal, not a continuation.",
        "Pullback entries do not beat trend-only entries net of cost.",
    ),
    # --- C: mean reversion ---
    Family(
        "V3_C_ZSCORE_OVERSHOOT_REVERSION", "C", H0,
        "Short-horizon overshoots beyond a rolling equilibrium mean-revert.",
        "Enter against dist_from_ewma z-score beyond a band; exit on reversion to zero or "
        "time; abstain in high-vol regime.",
        ("dist_from_ewma", "realized_vol"),
        ("M1_BIDASK_OHLC", "M1_RETURNS"),
        "self", ("halflife_bars", "entry_threshold_sigma"),
        "very_high", "extreme",
        "Overshoot is trend continuation in a regime shift; reversion never comes.",
        "No reversion edge survives spread cost at realistic entry thresholds.",
    ),
    Family(
        "V3_C_OU_HALFLIFE_REVERSION", "C", H1,
        "Series with a short estimated OU half-life revert predictably; long half-life does "
        "not.",
        "Estimate rolling OU half-life; trade reversion only when half-life is inside a "
        "tradeable band; size by distance in z-units.",
        ("dist_from_ewma",),
        ("M1_BIDASK_OHLC", "M1_RETURNS"),
        "self", ("halflife_bars", "entry_threshold_sigma"),
        "high", "high",
        "Half-life estimate is unstable and look-back biased.",
        "Reversion conditioned on half-life is no better than unconditional.",
    ),
    # --- D: volatility / range structure ---
    Family(
        "V3_D_COMPRESSION_EXPANSION_BREAK", "D", H0,
        "Volatility compression precedes directional expansion (regime transition).",
        "Detect low parkinson_vol percentile; arm a straddle-style directional break; enter "
        "on first expansion bar in the break direction.",
        ("parkinson_vol", "range_compression", "atr"),
        ("M1_BIDASK_OHLC", "RANGE_ESTIMATORS_M1"),
        "self", ("lookback_bars_intraday", "entry_threshold_sigma"),
        "high", "high",
        "Expansion direction is random; compression only predicts magnitude not sign.",
        "Directional expansion edge is zero after cost; only |move| is predictable.",
    ),
    # --- E: microstructure (M1-supported) ---
    Family(
        "V3_E_SPREAD_STATE_GATED_REVERSAL", "E", H0,
        "Reversals are only tradeable when the quoted spread is compressed; abnormal spread "
        "marks toxic liquidity to avoid.",
        "Compute spread_zscore; gate mean-reversion entries to low-spread state; veto during "
        "abnormal-spread spikes.",
        ("spread_zscore", "dist_from_ewma"),
        ("M1_BIDASK_OHLC", "M1_SPREAD", "M1_RETURNS"),
        "self", ("entry_threshold_sigma", "halflife_bars"),
        "high", "extreme",
        "Spread state is endogenous to the move; gating removes the profitable tail.",
        "Spread-gating does not improve net edge vs ungated reversion.",
    ),
    # --- E (rejected): requires true tick microstructure, never faked from M1 ---
    Family(
        "V3_E_TICK_ARRIVAL_INTENSITY", "E", H0,
        "Quote-arrival clustering (event-time intensity) predicts short-horizon direction.",
        "Requires true tick arrival times / durations; not derivable from M1 bars.",
        (),
        ("M1_BIDASK_OHLC", "TICK_QUOTE_ARRIVAL_RATE"),
        "self", ("lookback_bars_intraday",),
        "very_high", "extreme",
        "M1 volume is a tick-volume proxy, not a quote count.",
        "REJECTED pre-outcome: tick arrival unsupported; never faked from M1.",
    ),
    Family(
        "V3_E_ORDER_BOOK_IMBALANCE", "E", H0,
        "Top-of-book size imbalance predicts micro-price drift.",
        "Requires L2 depth; not present in the acquired dataset.",
        (),
        ("M1_BIDASK_OHLC", "ORDER_BOOK_DEPTH"),
        "self", ("lookback_bars_intraday",),
        "very_high", "extreme",
        "No order-book depth exists in Dukascopy M1/tick.",
        "REJECTED pre-outcome: order-book depth unsupported.",
    ),
    # --- F: seasonality as conditioning ---
    Family(
        "V3_F_SESSION_OPEN_CONDITIONED_MOMENTUM", "F", H0,
        "Directional edge concentrates around London/NY session opens; the calendar cell is "
        "a conditioning variable, not a standalone signal.",
        "Use session_cell to gate a momentum trigger to the open window; cost-gate entries.",
        ("session_cell", "mom_zscore", "spread_zscore"),
        ("M1_BIDASK_OHLC", "SESSION_TIME_OF_DAY", "M1_RETURNS", "M1_SPREAD"),
        "self", ("lookback_bars_intraday", "entry_threshold_sigma", "cost_edge_multiple"),
        "medium", "high",
        "Open-window edge is an artefact of wide spreads at the open.",
        "No residual edge once open-window spread cost is charged.",
    ),
    # --- G: cross-pair / currency structure ---
    Family(
        "V3_G_USD_FACTOR_RESIDUAL_REVERSION", "G", H1,
        "After removing the common USD factor, single-pair residuals mean-revert.",
        "Build synchronized return panel; extract usd_factor; trade factor_residual reversion "
        "on a beta-neutral basis.",
        ("cross_return_panel", "usd_factor", "factor_residual"),
        ("M1_BIDASK_OHLC", "CROSS_PAIR_SYNC", "CURRENCY_FACTOR_PANEL", "M1_RETURNS"),
        "panel", ("lookback_bars_intraday", "entry_threshold_sigma"),
        "high", "high",
        "Factor estimated with error; residual carries factor leakage.",
        "Beta-neutral residual reversion is zero net of cost across the panel.",
    ),
    Family(
        "V3_G_CROSS_SECTIONAL_MOMENTUM", "G", H2,
        "Relative momentum across the currency cross-section continues over days.",
        "Rank pairs by risk-adjusted trailing return; long top / short bottom, currency- and "
        "beta-neutral; rebalance daily.",
        ("cross_return_panel", "usd_factor"),
        ("M1_BIDASK_OHLC", "CROSS_PAIR_SYNC", "CURRENCY_FACTOR_PANEL", "M1_RETURNS"),
        "panel", ("lookback_days_multiday", "entry_threshold_sigma"),
        "medium", "high",
        "Cross-sectional FX momentum is weak and crowded; carry-driven.",
        "No rank-portfolio spread net of cost and (unsupported) financing.",
    ),
    # --- H: statistical arbitrage ---
    Family(
        "V3_H_TRIANGULAR_RESIDUAL_REVERSION", "H", H1,
        "The triangular no-arbitrage residual of three independently-quoted legs reverts.",
        "Compute triangle_residual z-score from three acquired legs; trade reversion when "
        "the residual is stationary (rolling ADF gate); size in z-units.",
        ("triangle_residual", "cross_return_panel"),
        ("M1_BIDASK_OHLC", "TRIANGULAR_RESIDUAL", "CROSS_PAIR_SYNC", "M1_RETURNS"),
        "triangle", ("halflife_bars", "entry_threshold_sigma"),
        "high", "extreme",
        "Residual is dominated by non-synchronous quotes and spread, not arbitrage.",
        "Residual reversion edge disappears once all three legs' spreads are charged.",
    ),
    Family(
        "V3_H_COINTEGRATION_KALMAN_HEDGE", "H", H2,
        "A cointegrated pair with a Kalman-filtered dynamic hedge ratio has a stationary "
        "spread that reverts over days.",
        "Prospectively eligible pairs only; Kalman filter the hedge ratio causally; trade "
        "spread z-score reversion; embargo/purge on refit.",
        ("dist_from_ewma", "cross_return_panel"),
        ("M1_BIDASK_OHLC", "CROSS_PAIR_SYNC", "CURRENCY_FACTOR_PANEL", "M1_RETURNS"),
        "panel", ("halflife_bars", "entry_threshold_sigma"),
        "low", "high",
        "Cointegration is a full-sample artefact; breaks out of sample.",
        "Prospectively-eligible spreads do not revert net of cost and financing.",
    ),
    # --- I: applied math / signal processing ---
    Family(
        "V3_I_KALMAN_STATE_TREND", "I", H1,
        "A local-level/local-trend state-space model extracts a causal trend cleaner than a "
        "moving average.",
        "Filtered (not smoothed) local-trend state from a fixed-parameter Kalman filter; "
        "trade the sign of the filtered slope; vol-scaled.",
        ("trend_slope", "realized_vol"),
        ("M1_BIDASK_OHLC", "M1_RETURNS", "M1_REALIZED_VOL"),
        "self", ("halflife_bars", "entry_threshold_sigma"),
        "medium", "medium",
        "Filter parameters overfit; filtered slope lags.",
        "Filtered-slope edge no better than simple vol-scaled momentum.",
    ),
    Family(
        "V3_I_CHANGEPOINT_REGIME_SHIFT", "I", H1,
        "A causal change-point in the return/vol process marks the start of a tradeable "
        "regime.",
        "Online (filtered) change-point probability from a fixed prior; on a detected shift, "
        "trade the new-regime trend for a bounded holding window.",
        ("realized_vol", "trend_slope"),
        ("M1_BIDASK_OHLC", "M1_RETURNS", "M1_REALIZED_VOL"),
        "self", ("halflife_bars", "entry_threshold_sigma"),
        "medium", "medium",
        "Change-points are detected too late to trade; false positives dominate.",
        "Post-change-point trend edge is zero net of cost.",
    ),
    # --- J: regime conditioning (a conditioning family, composed with others) ---
    Family(
        "V3_J_VOL_REGIME_CONDITION", "J", H1,
        "Signal edge is regime-dependent; a frozen causal volatility-quantile regime selects "
        "when a base signal is active.",
        "Causal expanding volatility quantile bins define regime; used only as a gate on "
        "other families (see composition grammar), never traded alone.",
        ("realized_vol",),
        ("M1_BIDASK_OHLC", "M1_REALIZED_VOL"),
        "self", ("lookback_bars_intraday",),
        "low", "low",
        "Regime is unstable; conditioning adds a hidden degree of freedom.",
        "Regime-conditioning does not improve any base family's net edge.",
        standalone=False,
    ),
    # --- K: cost-aware prediction ---
    Family(
        "V3_K_COST_GATED_SPARSE_ENTRY", "K", H0,
        "Trading is a decision under cost: enter only when expected net edge exceeds expected "
        "round-trip cost plus edge uncertainty.",
        "Compute expected_gross_edge from a base signal, expected_round_trip_cost from live "
        "spread, and an edge-uncertainty band; trade only if edge >= k * cost.",
        ("mom_zscore", "spread_zscore", "realized_vol"),
        ("M1_BIDASK_OHLC", "M1_SPREAD", "M1_RETURNS", "M1_REALIZED_VOL"),
        "self", ("entry_threshold_sigma", "cost_edge_multiple"),
        "low", "medium",
        "Cost gate removes exactly the trades that carried the edge.",
        "Sparse cost-gated entries do not beat the ungated base net of cost.",
    ),
    # --- L: ML (interpretable, controllable) ---
    Family(
        "V3_L_META_LABEL_TRADE_FILTER", "L", H1,
        "A calibrated logistic meta-labeller filters a base signal's trades by predicted "
        "probability that the move exceeds round-trip cost.",
        "Base signal proposes trades; expanding-window logistic model (purged/embargoed, "
        "frozen features/target/seed) predicts cost-exceedance; trade only above a frozen "
        "probability threshold, else abstain.",
        ("mom_zscore", "spread_zscore", "realized_vol", "trend_slope"),
        ("M1_BIDASK_OHLC", "M1_SPREAD", "M1_RETURNS", "M1_REALIZED_VOL"),
        "self", ("entry_threshold_sigma", "cost_edge_multiple"),
        "low", "medium",
        "Meta-model overfits; calibration drifts out of sample.",
        "Meta-filtered net edge no better than a fixed cost gate.",
    ),
)

FAMILY_INDEX: dict[str, Family] = {f.family_id: f for f in FAMILIES}

DOMAIN_NAMES: dict[str, str] = {
    "A": "classical_technical_structure",
    "B": "time_series_momentum_trend",
    "C": "mean_reversion",
    "D": "volatility_range_structure",
    "E": "market_microstructure",
    "F": "seasonality_calendar",
    "G": "cross_pair_currency_structure",
    "H": "statistical_arbitrage",
    "I": "applied_math_signal_processing",
    "J": "regime_modeling",
    "K": "cost_aware_prediction",
    "L": "machine_learning",
    "M": "multi_scale_composition",
}


def family_registry_payload() -> dict[str, Any]:
    by_domain: dict[str, int] = {}
    by_horizon: dict[str, int] = {}
    for f in FAMILIES:
        by_domain[f.domain] = by_domain.get(f.domain, 0) + 1
        by_horizon[f.horizon.value] = by_horizon.get(f.horizon.value, 0) + 1
    return {
        "artifact_id": "V3_FAMILY_REGISTRY_V1",
        "domain_names": DOMAIN_NAMES,
        "family_count": len(FAMILIES),
        "counts_by_domain": by_domain,
        "counts_by_horizon": by_horizon,
        "families": [f.as_dict() for f in FAMILIES],
    }


def family_registry_hash() -> str:
    return canonical_hash(family_registry_payload())
