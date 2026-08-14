"""Frozen V3 missing-observation contract: CLOCK vs OBSERVED vs EXECUTABLE quote.

The fleet parity work found that a Dukascopy native M1 candle may contain a flat
carry-forward bar for a minute with no underlying tick observation. A regular clock grid is
useful, but such a row MUST NOT silently become a real quote. This contract formalises three
distinct concepts and the downstream policies that keep the already-frozen V3 strategies
scientifically correct without changing any strategy, parameter or hypothesis.

* **CLOCK MINUTE** -- a regular M1 grid timestamp; may exist with no market observation.
* **OBSERVED MARKET QUOTE** -- a minute with genuine underlying tick observation.
* **EXECUTABLE QUOTE** -- session-valid AND both bid and ask observed.

The native observation rule (``volume > 0``) is *empirically certified* against the tick
reference (not assumed). The frozen execution contract's ``missing_quote_policy =
no_synthetic_fill`` is honoured: nothing fills on an imputed minute.
"""

from __future__ import annotations

from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash

OBSERVATION_CONTRACT: dict[str, Any] = {
    "artifact_id": "V3_MISSING_OBSERVATION_CONTRACT_V1",
    "frozen_pre_outcome": True,
    "no_v3_pnl_or_performance_used": True,
    "concepts": {
        "CLOCK_MINUTE": "regular M1 grid timestamp; may exist with no market observation",
        "OBSERVED_MARKET_QUOTE": "minute with genuine underlying tick observation",
        "EXECUTABLE_QUOTE": "session_valid AND both bid and ask observed",
    },
    "certified_native_observation_rule": {
        "rule": "native observed minute := native candle volume > 0 (per side)",
        "sides": "bid_observed := bid_volume > 0 ; ask_observed := ask_volume > 0",
        "certification": "measured vs tick_count>0 on the fleet parity panel: 1680/1680 "
                         "minutes agree (100.000%). Certified against the tick reference, "
                         "NOT assumed.",
    },
    "tick_observation_rule": "tick observed minute := tick_count > 0 (from tick->M1 aggregation)",
    "imputation": {
        "carry_forward": "no-observation minutes may carry a flat last-close bar for clock "
                         "alignment (fill_session_grid).",
        "must_mark_imputed": True,
        "imputed_is_never_a_real_quote": True,
        "staleness_minutes": "minutes since the last observed quote (0 on observed minutes).",
    },
    "execution_invariant": {
        "rule": "NO entry/exit/stop/target/mandatory-exit/delayed fill may execute on an "
                "imputed / non-observed minute.",
        "on_missing_quote": "advance clock time to the next session-valid EXECUTABLE (observed "
                            "bid+ask) minute; time advances but execution does not.",
        "latency": "frozen one-completed-M1 latency preserved; missing_quote_policy="
                   "no_synthetic_fill; never manufacture a fill at a carry-forward price.",
    },
    "feature_policy": {
        "rule": "an imputed row does not update stateful market features and is NOT a zero "
                "market return.",
        "stateful_market_features_update_only_on_observation": [
            "realized_vol", "atr_range_estimators", "compression_expansion", "momentum",
            "moving_average", "zscore", "ou_estimation", "kalman_update", "regime_estimation",
            "spread_statistics", "ml_training_example",
        ],
        "clock_features_may_advance_with_time": ["session_cell", "calendar_cell", "time_of_day"],
    },
    "cross_pair_synchronization": {
        "rule": "a synchronized cross-pair/triangular observation at t requires EVERY leg "
                "observed at t (contemporaneous). A stale/imputed leg breaks synchronization.",
        "default": "contemporaneously observed prices only, unless a frozen family explicitly "
                   "defines another causal synchronization rule.",
        "forbidden": "treating a carry-forward quote as fresh merely because it shares a "
                     "timestamp row (applies to triangular residuals, currency factors, "
                     "cross-sectional momentum, cross-pair residuals, cointegration inputs).",
    },
    "mtf_provenance": {
        "rule": "M5/M15/H1 bars carry observed_minutes, imputed_minutes and coverage_fraction; "
                "N carry-forward minutes are NOT N independent market observations.",
    },
    "volume_use": {
        "permitted": "quote-observation provenance / data-quality metadata only.",
        "forbidden": "any V3 alpha feature; does NOT enable TICK_QUOTE_ARRIVAL_RATE capability.",
    },
}


def observation_contract_payload() -> dict[str, Any]:
    payload = dict(OBSERVATION_CONTRACT)
    payload["contract_hash"] = canonical_hash(OBSERVATION_CONTRACT)
    return payload


def observation_contract_hash() -> str:
    return canonical_hash(OBSERVATION_CONTRACT)
