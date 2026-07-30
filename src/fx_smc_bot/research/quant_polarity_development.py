"""Aggregate-only Gate Q.0 development evaluation and shortlist adjudication."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.config import PAIR_PIP_INFO
from fx_smc_bot.research.overfitting import cscv_pbo, whites_reality_check
from fx_smc_bot.research.quant_polarity import (
    DEVELOPMENT_CRITERIA,
    DEVELOPMENT_INSTRUMENTS,
    canonical_json_sha256,
)
from fx_smc_bot.research.quant_polarity_execution import (
    EVENT_QUALITY_SCALARS,
    load_development_m5_window,
)
from fx_smc_bot.research.quant_polarity_inference import (
    corrected_p_values,
    hansen_spa_p_value,
    matched_entry_permutation_p_value,
    newey_west_factor_alpha,
    romano_wolf_max_t,
)
from fx_smc_bot.research.quant_polarity_model import (
    LabeledSignal,
    PolarityAction,
    build_feature_frame,
    construct_label,
    nested_oof_predictions,
    select_final_development_model,
)
from fx_smc_bot.research.statistical_inference import stationary_bootstrap
from fx_smc_bot.research.strategy_alpha_aggregation import (
    paired_cluster_signflip_p,
    performance_metrics,
)
from fx_smc_bot.research.strategy_alpha_execution import is_amended_session_bar
from fx_smc_bot.utils.math import atr as compute_atr

PURGE_DEPENDENCY = timedelta(minutes=2_680)
INVERSE_CANDIDATE_BY_SOURCE = {
    "SMC_A_SWEEP_REVERSAL_V1": "Q0_INV_SWEEP_V1",
    "SMC_B_ACCEPTANCE_CONTINUATION_V1": "Q0_INV_ACCEPTANCE_V1",
    "SMC_C_LONDON_OPENING_RANGE_V1": "Q0_INV_LONDON_OR_V1",
    "SMC_C_NEWYORK_OPENING_RANGE_V1": "Q0_INV_NEWYORK_OR_V1",
}
META_CANDIDATE_ID = "Q0_META_POLARITY_ELASTIC_NET_V1"
CANDIDATE_IDS = (*INVERSE_CANDIDATE_BY_SOURCE.values(), META_CANDIDATE_ID)
TRADE_COLUMNS = (
    "candidate_id",
    "position_id",
    "signal_id",
    "instrument",
    "session",
    "direction",
    "entry_time",
    "exit_time",
    "entry_bar",
    "exit_bar",
    "holding_bars",
    "units",
    "commission_cash",
    "spread_cash",
    "slippage_cash",
    "initial_risk_cash",
    "gross_r",
    "net_r",
    "stress_1_5x_net_r",
    "stress_2_0x_net_r",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame_schema_hash(frame: pd.DataFrame) -> str:
    return canonical_json_sha256(
        [
            {"column": str(column), "dtype": str(frame[column].dtype)}
            for column in frame.columns
        ]
    )


def _load_signal_ledgers(root: Path, execution_manifest: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for unit in execution_manifest["units"]:
        candidate_id = str(unit["candidate_id"])
        year = int(unit["year"])
        if os.environ.get("FX_Q0R_EXECUTION") == "1":
            from fx_smc_bot.research.quant_polarity_q0r_data import q0r_derived_root

            path = (
                q0r_derived_root(root)
                / "gate_q0r"
                / "development_ledgers"
                / f"{candidate_id}__{year}.parquet"
            )
        else:
            path = (
                root
                / "data"
                / "acquisition_state"
                / "gate_q0"
                / "development_ledgers"
                / f"{candidate_id}__{year}.parquet"
            )
        if _sha256(path) != unit["ledger_sha256"]:
            raise ValueError(f"Development signal ledger hash mismatch: {candidate_id}/{year}")
        frames.append(pd.read_parquet(path))
    frame = pd.concat(frames, ignore_index=True)
    return frame.sort_values(
        ["decision_time", "source_candidate_id", "instrument", "session", "signal_id"]
    ).reset_index(drop=True)


def _labeled_signals(frame: pd.DataFrame) -> tuple[LabeledSignal, ...]:
    signals: list[LabeledSignal] = []
    for row in frame.itertuples(index=False):
        signals.append(
            LabeledSignal(
                decision_time=pd.Timestamp(row.decision_time).to_pydatetime(),
                label_end_time=pd.Timestamp(row.label_end_time).to_pydatetime(),
                instrument=str(row.instrument),
                features=json.loads(str(row.features_json)),
                label=construct_label(float(row.original_net_r), float(row.inverse_net_r)),
            )
        )
    return tuple(signals)


def _variant_trade_row(row: Any, variant: str, candidate_id: str) -> dict[str, Any] | None:
    if not bool(getattr(row, f"{variant}_completed")):
        return None
    return {
        "candidate_id": candidate_id,
        "position_id": str(row.signal_id),
        "signal_id": str(row.signal_id),
        "instrument": str(row.instrument),
        "session": str(row.session),
        "direction": str(getattr(row, f"{variant}_direction")),
        "entry_time": getattr(row, f"{variant}_entry_time"),
        "exit_time": getattr(row, f"{variant}_exit_time"),
        "entry_bar": int(getattr(row, f"{variant}_entry_bar")),
        "exit_bar": int(getattr(row, f"{variant}_exit_bar")),
        "holding_bars": int(getattr(row, f"{variant}_holding_bars")),
        "units": float(getattr(row, f"{variant}_units")),
        "commission_cash": float(getattr(row, f"{variant}_commission_cash")),
        "spread_cash": float(getattr(row, f"{variant}_spread_cash")),
        "slippage_cash": float(getattr(row, f"{variant}_slippage_cash")),
        "initial_risk_cash": float(getattr(row, f"{variant}_initial_risk_cash")),
        "gross_r": float(getattr(row, f"{variant}_gross_r")),
        "net_r": float(getattr(row, f"{variant}_net_r")),
        "stress_1_5x_net_r": float(getattr(row, f"{variant}_stress_1_5x_net_r")),
        "stress_2_0x_net_r": float(getattr(row, f"{variant}_stress_2_0x_net_r")),
    }


def _candidate_trade_frames(
    signals: pd.DataFrame,
    oof: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for source_id, candidate_id in INVERSE_CANDIDATE_BY_SOURCE.items():
        rows = [
            trade
            for row in signals.loc[signals["source_candidate_id"] == source_id].itertuples(
                index=False
            )
            if (trade := _variant_trade_row(row, "inverse", candidate_id)) is not None
        ]
        frames[candidate_id] = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    prediction_by_signal = {
        str(row.signal_id): str(row.action) for row in oof.itertuples(index=False)
    }
    meta_rows: list[dict[str, Any]] = []
    for row in signals.itertuples(index=False):
        action = prediction_by_signal.get(str(row.signal_id), PolarityAction.ABSTAIN.value)
        if action == PolarityAction.ORIGINAL.value:
            trade = _variant_trade_row(row, "original", META_CANDIDATE_ID)
        elif action == PolarityAction.INVERSE.value:
            trade = _variant_trade_row(row, "inverse", META_CANDIDATE_ID)
        else:
            trade = None
        if trade is not None:
            meta_rows.append(trade)
    frames[META_CANDIDATE_ID] = pd.DataFrame(meta_rows, columns=TRADE_COLUMNS)
    return frames


def _benchmark_trade_r(
    series: Any,
    entry_idx: int,
    holding_bars: int,
    direction: str,
    units: float,
    commission_cash: float,
    initial_risk_cash: float,
) -> float:
    exit_idx = entry_idx + holding_bars
    if entry_idx < 0 or exit_idx >= len(series):
        raise ValueError("Matched benchmark holding interval is outside certified data")
    slip = 0.3 * PAIR_PIP_INFO[series.pair][0]
    if direction == "long":
        entry = float(series.ask_open[entry_idx]) + slip
        exit_price = float(series.bid_close[exit_idx]) - slip
        pnl = (exit_price - entry) * units
    else:
        entry = float(series.bid_open[entry_idx]) - slip
        exit_price = float(series.ask_close[exit_idx]) + slip
        pnl = (entry - exit_price) * units
    return float((pnl - commission_cash) / initial_risk_cash)


def _quartile_bins(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    boundaries = np.unique(np.quantile(finite, [0.25, 0.50, 0.75]))
    return np.digitize(values, boundaries, right=True)


def add_matched_random_benchmark(root: Path, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.assign(matched_random_entry_r=pd.Series(dtype=float))
    enriched: list[dict[str, Any]] = []
    for (year, instrument), group in frame.groupby(
        [pd.to_datetime(frame["entry_time"]).dt.year, "instrument"], sort=True
    ):
        series = load_development_m5_window(
            root,
            str(instrument),
            date(int(year), 1, 1),
            date(int(year), 12, 31),
        )
        timestamp_ns = series.timestamps.astype("datetime64[ns]").astype("int64")
        index_by_timestamp = {int(stamp): index for index, stamp in enumerate(timestamp_ns)}
        mid = series.to_mid_series()
        volatility_bins = _quartile_bins(
            np.asarray(compute_atr(mid.high, mid.low, mid.close, 14), dtype=float)
        )
        spread_bins = _quartile_bins(series.ask_close - series.bid_close)
        session_indices = {
            session: np.asarray(
                [
                    index
                    for index, stamp in enumerate(series.timestamps)
                    if is_amended_session_bar(
                        stamp.astype("datetime64[us]").astype(datetime), session
                    )
                ],
                dtype=np.int64,
            )
            for session in ("london", "new_york")
        }
        session_membership = {
            session: np.isin(np.arange(len(series)), indices)
            for session, indices in session_indices.items()
        }
        weekdays = np.asarray(
            [
                stamp.astype("datetime64[D]").astype(object).weekday()
                for stamp in series.timestamps
            ],
            dtype=np.int8,
        )
        base_pool_cache: dict[tuple[Any, ...], np.ndarray] = {}
        pool_cache: dict[tuple[Any, ...], np.ndarray] = {}
        for row in group.sort_values("entry_time").itertuples(index=False):
            entry_stamp = int(np.datetime64(row.entry_time, "ns").astype("int64"))
            entry_idx = index_by_timestamp.get(entry_stamp)
            if entry_idx is None:
                raise ValueError("Trade entry is absent from certified M5 data")
            holding = max(1, int(row.holding_bars))
            weekday = int(weekdays[entry_idx])
            base_key = (
                str(row.session),
                weekday,
                int(volatility_bins[entry_idx]),
                int(spread_bins[entry_idx]),
            )
            key = (
                *base_key,
                holding,
            )
            if key not in pool_cache:
                if base_key not in base_pool_cache:
                    session_pool = session_indices[str(row.session)]
                    base_pool_cache[base_key] = session_pool[
                        (weekdays[session_pool] == weekday)
                        & (volatility_bins[session_pool] == key[2])
                        & (spread_bins[session_pool] == key[3])
                    ]
                valid = base_pool_cache[base_key]
                valid = valid[valid + holding < len(series)]
                valid = valid[
                    session_membership[str(row.session)][valid + holding]
                ]
                pool_cache[key] = valid
            pool = pool_cache[key]
            pool = pool[pool != entry_idx]
            if len(pool) == 0:
                raise ValueError(f"Empty exact matched-random pool: {key}")
            seed_text = f"1729|{row.candidate_id}|{row.signal_id}|{year}|{instrument}"
            seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16)
            random_idx = int(pool[np.random.default_rng(seed).integers(0, len(pool))])
            record = row._asdict()
            record["matched_random_entry_r"] = _benchmark_trade_r(
                series,
                random_idx,
                holding,
                str(row.direction),
                float(row.units),
                float(row.commission_cash),
                float(row.initial_risk_cash),
            )
            enriched.append(record)
    return pd.DataFrame(enriched).sort_values(
        ["entry_time", "instrument", "signal_id"]
    ).reset_index(drop=True)


def _daily_factor_frame(root: Path) -> pd.DataFrame:
    closes: dict[str, pd.Series] = {}
    for instrument in DEVELOPMENT_INSTRUMENTS:
        series = load_development_m5_window(
            root, instrument, date(2015, 1, 1), date(2019, 12, 31)
        )
        index = pd.to_datetime(series.timestamps, utc=True)
        mid_close = pd.Series((series.bid_close + series.ask_close) / 2.0, index=index)
        closes[instrument] = mid_close.resample("1D").last().dropna()
    close = pd.DataFrame(closes).dropna(how="all")
    returns = close.pct_change(fill_method=None)
    momentum_sign = np.sign(close.pct_change(60, fill_method=None).shift(1))
    momentum = (momentum_sign * returns).mean(axis=1)
    reversal = (-np.sign(returns.shift(1)) * returns).mean(axis=1)
    usd = pd.DataFrame(
        {
            "AUDUSD": -returns["AUDUSD"],
            "NZDUSD": -returns["NZDUSD"],
            "USDCAD": returns["USDCAD"],
            "USDCHF": returns["USDCHF"],
        }
    ).mean(axis=1)
    volatility = returns.abs().mean(axis=1)
    return pd.DataFrame(
        {
            "fx_time_series_momentum": momentum,
            "short_term_reversal": reversal,
            "broad_usd_direction": usd,
            "realized_volatility": volatility,
        }
    ).dropna()


def _family_bootstrap_statistics(excess: np.ndarray, iterations: int = 5_000) -> np.ndarray:
    rng = np.random.default_rng(1729)
    observations, candidates = excess.shape
    centered = excess - np.mean(excess, axis=0)
    standard_error = np.std(excess, axis=0, ddof=1) / np.sqrt(observations)
    standard_error = np.where(standard_error > 0, standard_error, np.inf)
    block_size = min(5, observations)
    block_count = int(np.ceil(observations / block_size))
    result = np.empty((iterations, candidates), dtype=float)
    for iteration in range(iterations):
        starts = rng.integers(0, observations - block_size + 1, size=block_count)
        sample = np.concatenate(
            [centered[start : start + block_size] for start in starts], axis=0
        )[:observations]
        result[iteration] = np.mean(sample, axis=0) / standard_error
    return result


def run_development_analysis(
    root: Path,
    execution_manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    signal_frame = _load_signal_ledgers(root, execution_manifest)
    labeled = _labeled_signals(signal_frame)
    feature_frame, _ = build_feature_frame(
        [signal.features for signal in labeled],
        event_quality_names=EVENT_QUALITY_SCALARS,
    )
    predictions, selections = nested_oof_predictions(
        labeled,
        purge_dependency=PURGE_DEPENDENCY,
        event_quality_names=EVENT_QUALITY_SCALARS,
    )
    prediction_rows = [
        {
            **asdict(prediction),
            "action": prediction.action.value,
            "signal_id": str(signal_frame.iloc[prediction.signal_index]["signal_id"]),
        }
        for prediction in predictions
    ]
    prediction_frame = pd.DataFrame(prediction_rows)
    if os.environ.get("FX_Q0R_EXECUTION") == "1":
        from fx_smc_bot.research.quant_polarity_q0r_data import q0r_derived_root

        local_root = q0r_derived_root(root) / "gate_q0r"
    else:
        local_root = root / "data" / "acquisition_state" / "gate_q0"
    local_root.mkdir(parents=True, exist_ok=True)
    prediction_path = local_root / "development_oof_predictions.parquet"
    prediction_frame.to_parquet(prediction_path, index=False, engine="pyarrow")
    pipeline, final_selection, final_model_hash = select_final_development_model(
        labeled,
        purge_dependency=PURGE_DEPENDENCY,
        event_quality_names=EVENT_QUALITY_SCALARS,
    )
    model_path = local_root / "development_final_meta_model.joblib"
    joblib.dump(pipeline, model_path)

    trade_frames = _candidate_trade_frames(signal_frame, prediction_frame)
    raw_trade_ledger = pd.concat(trade_frames.values(), ignore_index=True)
    enriched_ledger = add_matched_random_benchmark(root, raw_trade_ledger)
    enriched = {
        candidate_id: enriched_ledger.loc[
            enriched_ledger["candidate_id"] == candidate_id
        ].reset_index(drop=True)
        for candidate_id in CANDIDATE_IDS
    }
    combined_ledger = pd.concat(enriched.values(), ignore_index=True)
    combined_path = local_root / "development_candidate_trades.parquet"
    combined_ledger.to_parquet(combined_path, index=False, engine="pyarrow")
    factors = _daily_factor_frame(root)
    metrics: dict[str, Any] = {}
    benchmark_results: dict[str, Any] = {}
    inference: dict[str, Any] = {}
    raw_p_values: list[float] = []
    daily_excess_by_candidate: dict[str, pd.Series] = {}
    for candidate_id in CANDIDATE_IDS:
        frame = enriched[candidate_id]
        candidate_metrics = performance_metrics(frame, n_trials=5, seed=1729)
        metrics[candidate_id] = candidate_metrics
        if frame.empty:
            raw_p_values.append(1.0)
            benchmark_results[candidate_id] = {
                "trade_count": 0,
                "strategy_mean_net_r": None,
                "matched_random_mean_net_r": None,
                "matched_random_alpha": 0.0,
                "raw_permutation_p_value": 1.0,
                "day_cluster_signflip_p_value": 1.0,
                "status": "INSUFFICIENT_SAMPLE",
            }
            daily_excess_by_candidate[candidate_id] = pd.Series(dtype=float)
            inference[candidate_id] = {
                "factor_adjusted_hac": {
                    "alpha": 0.0,
                    "standard_error": 0.0,
                    "t_statistic": 0.0,
                    "p_value": 1.0,
                    "lag": 5,
                    "observations": 0,
                },
                "stationary_bootstrap_mean_ci": [0.0, 0.0],
                "status": "INSUFFICIENT_SAMPLE",
            }
            continue
        differences = (
            frame["net_r"] - frame["matched_random_entry_r"]
        ).to_numpy(dtype=float)
        days = pd.to_datetime(frame["entry_time"], utc=True).dt.strftime("%Y-%m-%d")
        raw_p = matched_entry_permutation_p_value(
            frame["net_r"].to_numpy(dtype=float),
            frame["matched_random_entry_r"].to_numpy(dtype=float),
        )
        raw_p_values.append(raw_p)
        benchmark_results[candidate_id] = {
            "trade_count": len(frame),
            "strategy_mean_net_r": float(frame["net_r"].mean()),
            "matched_random_mean_net_r": float(frame["matched_random_entry_r"].mean()),
            "matched_random_alpha": float(np.mean(differences)),
            "raw_permutation_p_value": raw_p,
            "day_cluster_signflip_p_value": paired_cluster_signflip_p(
                differences, days.to_numpy(), seed=1729
            ),
        }
        daily = frame.assign(day=pd.to_datetime(frame["entry_time"], utc=True).dt.floor("D"))
        strategy_daily = daily.groupby("day")["net_r"].sum()
        random_daily = daily.groupby("day")["matched_random_entry_r"].sum()
        daily_excess_by_candidate[candidate_id] = strategy_daily.subtract(
            random_daily, fill_value=0.0
        )
        aligned = pd.concat([strategy_daily.rename("strategy"), factors], axis=1).dropna()
        hac = newey_west_factor_alpha(
            aligned["strategy"].to_numpy(dtype=float),
            aligned[list(factors.columns)].to_numpy(dtype=float),
        )
        stationary = stationary_bootstrap(
            strategy_daily.to_numpy(dtype=float),
            np.mean,
            n_bootstrap=5_000,
            expected_block_length=5,
            seed=1729,
        )
        inference[candidate_id] = {
            "factor_adjusted_hac": asdict(hac),
            "stationary_bootstrap_mean_ci": [stationary.lower, stationary.upper],
        }
    corrections = corrected_p_values(raw_p_values)
    for index, candidate_id in enumerate(CANDIDATE_IDS):
        benchmark_results[candidate_id]["holm_adjusted_p_value"] = corrections["holm"][index]
        benchmark_results[candidate_id]["fdr_adjusted_p_value"] = corrections[
            "benjamini_hochberg"
        ][index]
    all_days = sorted(
        set().union(*(series.index for series in daily_excess_by_candidate.values()))
    )
    excess_matrix = np.column_stack(
        [
            daily_excess_by_candidate[candidate_id].reindex(all_days, fill_value=0.0)
            for candidate_id in CANDIDATE_IDS
        ]
    )
    observed_se = np.std(excess_matrix, axis=0, ddof=1) / np.sqrt(len(excess_matrix))
    observed_t = np.divide(
        np.mean(excess_matrix, axis=0),
        observed_se,
        out=np.zeros(len(CANDIDATE_IDS)),
        where=observed_se > 0,
    )
    bootstrap_statistics = _family_bootstrap_statistics(excess_matrix)
    romano = romano_wolf_max_t(observed_t, bootstrap_statistics)
    for index, candidate_id in enumerate(CANDIDATE_IDS):
        benchmark_results[candidate_id]["romano_wolf_adjusted_p_value"] = romano[index]
    white_p = whites_reality_check(
        np.zeros(len(excess_matrix)),
        [excess_matrix[:, index] for index in range(excess_matrix.shape[1])],
        n_bootstrap=5_000,
        block_size=5,
        seed=1729,
    )
    spa_p = hansen_spa_p_value(excess_matrix, iterations=5_000, block_size=5)
    daily_candidate = combined_ledger.assign(
        day=pd.to_datetime(combined_ledger["entry_time"], utc=True).dt.floor("D")
    ).pivot_table(index="day", columns="candidate_id", values="net_r", aggfunc="sum").fillna(0.0)
    daily_candidate = daily_candidate.reindex(columns=CANDIDATE_IDS, fill_value=0.0)
    pbo = cscv_pbo(daily_candidate.to_numpy(dtype=float), n_splits=8, seed=1729)
    overfitting = {
        "white_reality_check_p_value": white_p,
        "hansen_spa_p_value": spa_p,
        "pbo": pbo,
        "candidate_trial_count": 5,
        "parameter_search_count": 9,
        "status": "PASS",
    }
    model = {
        "oof_prediction_rows": len(prediction_frame),
        "oof_prediction_sha256": _sha256(prediction_path),
        "outer_fold_selections": [asdict(selection) for selection in selections],
        "outer_fold_selection_hashes": [selection.selection_hash for selection in selections],
        "outer_fold_model_hashes": sorted(
            {str(prediction.model_hash) for prediction in predictions}
        ),
        "selected_hyperparameters": {
            "inverse_regularization_c": final_selection.inverse_regularization_c,
            "l1_ratio": final_selection.l1_ratio,
        },
        "final_selection_hash": final_selection.selection_hash,
        "final_model_hash": final_model_hash,
        "final_model_file_sha256": _sha256(model_path),
        "purge_dependency_minutes": int(PURGE_DEPENDENCY.total_seconds() // 60),
        "embargo_fx_trading_days": 5,
        "in_sample_performance_used": False,
        "status": "PASS",
    }
    integrity = {
        "signal_ledger_rows": len(signal_frame),
        "signal_ledger_hash": canonical_json_sha256(
            sorted(str(value) for value in signal_frame["signal_id"])
        ),
        "signal_ledger_schema_hash": _frame_schema_hash(signal_frame),
        "feature_matrix_rows": len(feature_frame),
        "feature_matrix_columns": list(feature_frame.columns),
        "feature_matrix_sha256": canonical_json_sha256(
            feature_frame.to_dict(orient="records")
        ),
        "feature_matrix_schema_hash": _frame_schema_hash(feature_frame),
        "oof_prediction_schema_hash": _frame_schema_hash(prediction_frame),
        "candidate_trade_ledger_rows": len(combined_ledger),
        "candidate_trade_ledger_sha256": _sha256(combined_path),
        "candidate_trade_ledger_schema_hash": _frame_schema_hash(combined_ledger),
        "implementation_hash": execution_manifest["implementation_hash"],
        "source_candidate_config_hashes": {
            candidate_id: sorted(
                {
                    str(unit["candidate_config_hash"])
                    for unit in execution_manifest["units"]
                    if unit["candidate_id"] == candidate_id
                }
            )
            for candidate_id in INVERSE_CANDIDATE_BY_SOURCE
        },
        "row_level_committed": False,
    }
    return {
        "candidate_results": metrics,
        "benchmark_results": benchmark_results,
        "inference": inference,
        "overfitting": overfitting,
        "model": model,
        "integrity": integrity,
    }


def adjudicate_development(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    pbo = float(results["overfitting"]["pbo"])
    for candidate_id in CANDIDATE_IDS:
        metrics = results["candidate_results"][candidate_id]
        benchmark = results["benchmark_results"][candidate_id]
        yearly = {int(year): value for year, value in metrics.get("yearly_mean_net_r", {}).items()}
        positive_years = sum(yearly.get(year, 0.0) > 0 for year in range(2015, 2020))
        net_values = []
        for omitted in range(2015, 2020):
            included = [value for year, value in yearly.items() if year != omitted]
            net_values.append(float(np.mean(included)) if included else 0.0)
        checks = {
            "completed_trades_gte": metrics.get("trade_count", 0)
            >= DEVELOPMENT_CRITERIA["completed_trades_gte"],
            "mean_net_r_gt": metrics.get("mean_net_r", 0.0) > 0,
            "profit_factor_gt": (metrics.get("profit_factor") or 0.0) > 1.03,
            "stress_1_5x_mean_net_r_gte": metrics.get(
                "mean_stress_1_5x_net_r", -np.inf
            )
            >= 0,
            "day_cluster_ci_lower_gte": metrics.get("day_cluster_ci", [-np.inf])[0]
            >= -0.03,
            "positive_years_gte": positive_years >= 3,
            "positive_leave_one_year_out_gte": sum(value > 0 for value in net_values) >= 4,
            "matched_random_alpha_gt": benchmark["matched_random_alpha"] > 0,
            "pbo_lt": pbo < 0.50,
        }
        rows.append(
            {
                "candidate_id": candidate_id,
                "checks": checks,
                "eligible": all(checks.values()),
                "ranking": {
                    "day_cluster_ci_lower": metrics.get("day_cluster_ci", [-np.inf])[0],
                    "stress_1_5x_mean": metrics.get("mean_stress_1_5x_net_r", -np.inf),
                    "maximum_drawdown_r": metrics.get("maximum_drawdown_r", np.inf),
                    "pbo": pbo,
                },
            }
        )
    eligible = sorted(
        (row for row in rows if row["eligible"]),
        key=lambda row: (
            -row["ranking"]["day_cluster_ci_lower"],
            -row["ranking"]["stress_1_5x_mean"],
            row["ranking"]["maximum_drawdown_r"],
            row["ranking"]["pbo"],
        ),
    )[:2]
    return {
        "candidates": rows,
        "selected_candidates": [row["candidate_id"] for row in eligible],
        "maximum_shortlist": 2,
        "manual_override": False,
        "status": "PASS",
    }
