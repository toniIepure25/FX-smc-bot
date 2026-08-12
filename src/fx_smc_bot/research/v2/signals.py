"""Per-family signal generators for V2.

Each generator maps a canonical frame + :class:`StrategySpec` to a ``{-1, 0, +1}``
integer signal series aligned to the frame index. The signal at bar ``t`` is formed from
information available at the close of ``t``; the execution kernel then enforces a
one-completed-bar latency, so the earliest possible fill is the open of ``t+1``.

Regime (F11) and ML-abstention (F12) families use strictly causal expanding-window
estimation with explicit purge and embargo between the training label window and the
prediction bar, so no forward information ever enters a prediction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression, Ridge  # type: ignore[import-untyped]
from sklearn.mixture import GaussianMixture  # type: ignore[import-untyped]

from fx_smc_bot.research.v2 import features as fx
from fx_smc_bot.research.v2.spec import (
    Direction,
    FeatureKind,
    MLTarget,
    ModelClass,
    StrategySpec,
)


def _apply_direction(raw: pd.Series, direction: Direction) -> pd.Series:
    return -raw if direction is Direction.REVERSAL else raw


def _threshold(raw: pd.Series, threshold: float, index: pd.Index) -> pd.Series:
    arr = np.where(raw >= threshold, 1, np.where(raw <= -threshold, -1, 0))
    return pd.Series(arr.astype(int), index=index)


def signal_session_momentum(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    lb = spec.feature.lookback_bars
    ret = fx.mid_return_over(frame, lb)
    vol = fx.realized_vol(frame, lb).replace(0.0, np.nan)
    scale = vol.fillna(frame["mid_return"].std() or 1e-9).clip(lower=1e-9)
    raw = (ret / scale).where(fx.session_mask(frame, spec.signal.session_filter), 0.0)
    raw = _apply_direction(raw, spec.signal.direction)
    return _threshold(raw, spec.signal.entry_threshold, frame.index)


def signal_signed_return_run(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    raw = fx.primary_feature(
        frame, FeatureKind.SIGNED_RETURN_RUN, {"lookback_bars": spec.feature.lookback_bars}
    )
    raw = _apply_direction(raw, spec.signal.direction)
    return _threshold(raw, spec.signal.entry_threshold, frame.index)


def signal_volatility_breakout(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    lb = spec.feature.lookback_bars
    expansion = fx.primary_feature(frame, FeatureKind.VOLATILITY_BREAKOUT, {"lookback_bars": lb})
    prior_high = frame["mid_high"].shift(1).rolling(lb, min_periods=2).max()
    prior_low = frame["mid_low"].shift(1).rolling(lb, min_periods=2).min()
    close = frame["mid_close"]
    up_break = (close > prior_high) & (expansion >= spec.signal.entry_threshold)
    down_break = (close < prior_low) & (expansion >= spec.signal.entry_threshold)
    raw = pd.Series(np.where(up_break, 1.0, np.where(down_break, -1.0, 0.0)), index=frame.index)
    raw = _apply_direction(raw, spec.signal.direction)
    return raw.astype(int)


def signal_range_compression(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    lb = spec.feature.lookback_bars
    comp = fx.range_compression(frame, max(lb // 2, 2), lb * 3)
    prior_high = frame["mid_high"].shift(1).rolling(lb, min_periods=2).max()
    prior_low = frame["mid_low"].shift(1).rolling(lb, min_periods=2).min()
    close = frame["mid_close"]
    coiled = comp <= (1.0 - spec.signal.entry_threshold)
    up_break = coiled & (close > prior_high)
    down_break = coiled & (close < prior_low)
    raw = pd.Series(np.where(up_break, 1.0, np.where(down_break, -1.0, 0.0)), index=frame.index)
    raw = _apply_direction(raw, spec.signal.direction)
    return raw.astype(int)


def signal_liquidity_shock(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    lb = spec.feature.lookback_bars
    spread_z = fx.spread_zscore(frame, lb, max(5, lb // 3))
    abn_ret_z = fx.rolling_zscore(frame["mid_return"].abs(), lb, max(3, lb // 3))
    shock = (spread_z >= spec.signal.entry_threshold) & (
        abn_ret_z >= spec.signal.entry_threshold
    )
    shock_dir = np.sign(frame["mid_return"])
    # Mean-reversion after a completed shock bar: fade the shock-bar move.
    raw = pd.Series(np.where(shock, -shock_dir, 0.0), index=frame.index)
    raw = _apply_direction(raw, spec.signal.direction)
    return raw.astype(int)


def _forecast_spread(frame: pd.DataFrame, method: str, lb: int) -> pd.Series:
    spread = fx.spread_bps(frame)
    if method == "seasonal_median":
        hour = fx.ny_local(frame).dt.hour
        df = pd.DataFrame({"hour": hour.to_numpy(), "spread": spread.to_numpy()})
        # expanding prior-only median per hour, shifted to exclude the current bar
        df["cum_count"] = df.groupby("hour").cumcount()
        prior_median = (
            df.groupby("hour")["spread"]
            .apply(lambda s: s.shift(1).expanding(min_periods=1).median())
            .reset_index(level=0, drop=True)
        )
        return prior_median.reindex(frame.index).fillna(spread.expanding(min_periods=1).mean())
    if method == "har_linear":
        short = spread.rolling(lb, min_periods=1).mean()
        med = spread.rolling(lb * 4, min_periods=1).mean()
        long = spread.rolling(lb * 16, min_periods=1).mean()
        fallback = spread.iloc[0] if len(spread) else 0.0
        return (0.5 * short + 0.3 * med + 0.2 * long).shift(1).fillna(fallback)
    raise ValueError(f"unknown spread forecaster {method!r}")


def signal_spread_gated(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """F05: a base momentum signal gated off when forecast spread is in its costly regime."""

    base = signal_session_momentum(frame, spec)
    method = dict(spec.feature.extra).get("forecaster", "seasonal_median")
    lb = spec.feature.lookback_bars
    forecast = _forecast_spread(frame, str(method), lb)
    gate_pct = float(dict(spec.feature.extra).get("gate_percentile", 0.8))
    threshold = forecast.expanding(min_periods=20).quantile(gate_pct).shift(1)
    tradeable = forecast <= threshold.fillna(forecast.max() if len(forecast) else 0.0)
    return (base * tradeable.astype(int)).astype(int)


def signal_seasonality(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """F10: prior-only expanding cell mean of realised 1-bar returns; trade its sign."""

    cell_kind = str(dict(spec.feature.extra).get("cell", "hour_of_session"))
    cell = fx.calendar_cell(frame, cell_kind)
    ret = frame["mid_return"]
    df = pd.DataFrame({"cell": cell.to_numpy(), "ret": ret.to_numpy()})
    prior_mean = (
        df.groupby("cell")["ret"]
        .apply(lambda s: s.shift(1).expanding(min_periods=20).mean())
        .reset_index(level=0, drop=True)
    )
    prior_mean = prior_mean.reindex(frame.index).fillna(0.0)
    scale = ret.abs().expanding(min_periods=20).mean().replace(0.0, np.nan).fillna(1e-9)
    raw = _apply_direction(prior_mean / scale, spec.signal.direction)
    return _threshold(raw, spec.signal.entry_threshold, frame.index)


def _regime_labels(feature: pd.Series, spec: StrategySpec) -> np.ndarray:
    """Causal regime assignment (0=calm ... k-1=turbulent) by prior-only estimation."""

    assert spec.model is not None
    model = spec.model
    values = feature.to_numpy(dtype=float)
    n = len(values)
    labels = np.zeros(n, dtype=int)
    k = int(model.n_components_or_bins)
    tau = model.min_train_observations
    while tau < n:
        block_end = min(n, tau + model.retrain_cadence_bars)
        train = values[:tau].reshape(-1, 1)
        if model.model_class is ModelClass.QUANTILE_BINS:
            edges = np.quantile(train.ravel(), np.linspace(0, 1, k + 1)[1:-1])
            labels[tau:block_end] = np.searchsorted(edges, values[tau:block_end])
        else:  # GAUSSIAN_MIXTURE
            gmm = GaussianMixture(
                n_components=k, covariance_type="full", random_state=model.seed, n_init=1
            )
            gmm.fit(train)
            order = np.argsort(gmm.means_.ravel())
            rank = np.argsort(order)
            raw_labels = gmm.predict(values[tau:block_end].reshape(-1, 1))
            labels[tau:block_end] = rank[raw_labels]
        tau = block_end
    return labels


def signal_regime_trend(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """F11: momentum in the turbulent (high-vol) regime, fade in the calm regime."""

    assert spec.model is not None
    lb = spec.feature.lookback_bars
    vol = fx.realized_vol(frame, lb)
    labels = _regime_labels(vol, spec)
    mom = fx.mid_return_over(frame, lb)
    k = int(spec.model.n_components_or_bins)
    turbulent = labels >= (k - 1)
    calm = labels <= 0
    raw = np.where(turbulent, np.sign(mom), np.where(calm, -np.sign(mom), 0.0))
    raw_series = _apply_direction(pd.Series(raw, index=frame.index), spec.signal.direction)
    # gate by threshold on standardized momentum magnitude
    mom_z = fx.rolling_zscore(mom, lb * 5, max(5, lb)).abs()
    gated = np.where(mom_z >= spec.signal.entry_threshold, raw_series.to_numpy(), 0.0)
    return pd.Series(gated.astype(int), index=frame.index)


def _label_horizon(spec: StrategySpec) -> int:
    assert spec.model is not None
    hp = dict(spec.model.hyperparameters)
    return int(hp.get("label_horizon_bars", spec.execution.holding_bars))


def _ml_label(frame: pd.DataFrame, spec: StrategySpec) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(label, forward_ret_bps)`` where label semantics follow the spec target."""

    assert spec.model is not None
    horizon = _label_horizon(spec)
    close = frame["mid_close"].to_numpy(dtype=float)
    n = len(close)
    fwd = np.full(n, np.nan)
    for t in range(n - horizon):
        fwd[t] = (close[t + horizon] - close[t]) / close[t] * 10_000.0
    cost = 2.0 * spec.cost.base_commission_slippage_bps_per_fill
    if spec.model.target is MLTarget.GROSS_MOVE_EXCEEDS_COST:
        label = (np.abs(fwd) > cost).astype(float)
    else:  # NET_RETURN_SIGN
        label = (fwd > 0).astype(float)
    label[np.isnan(fwd)] = np.nan
    return label, fwd


def signal_ml_abstention(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """F12: causal walk-forward linear model with long/short/abstain action mapping."""

    assert spec.model is not None
    model = spec.model
    panel = fx.model_feature_panel(frame, spec.feature.lookback_bars)
    x = panel.to_numpy(dtype=float)
    label, fwd = _ml_label(frame, spec)
    horizon = _label_horizon(spec)
    mom = np.sign(fx.mid_return_over(frame, spec.feature.lookback_bars).to_numpy())
    n = len(frame)
    scores = np.full(n, np.nan)
    guard = horizon + model.purge_bars + model.embargo_bars
    tau = model.min_train_observations + guard
    band = model.abstention_band or (0.5, 0.5)
    while tau < n:
        block_end = min(n, tau + model.retrain_cadence_bars)
        train_end = tau - guard  # exclusive upper bound of usable training rows
        mask = ~np.isnan(label[:train_end])
        x_tr, y_tr = x[:train_end][mask], label[:train_end][mask]
        if len(y_tr) >= model.min_train_observations and len(np.unique(y_tr)) > 1:
            if model.standardize_features:
                mu, sd = x_tr.mean(0), x_tr.std(0)
                sd = np.where(sd > 0, sd, 1.0)
            else:
                mu, sd = np.zeros(x.shape[1]), np.ones(x.shape[1])
            x_tr_s = (x_tr - mu) / sd
            x_blk = (x[tau:block_end] - mu) / sd
            if model.model_class is ModelClass.LOGISTIC_REGRESSION:
                # liblinear: deterministic and avoids the scipy L-BFGS-B disp deprecation.
                clf = LogisticRegression(
                    max_iter=200, random_state=model.seed, C=1.0, solver="liblinear"
                )
                clf.fit(x_tr_s, y_tr.astype(int))
                scores[tau:block_end] = clf.predict_proba(x_blk)[:, 1]
            else:  # RIDGE_REGRESSION on forward return
                reg = Ridge(alpha=1.0, random_state=model.seed)
                y_reg = fwd[:train_end][mask]
                reg.fit(x_tr_s, y_reg)
                scores[tau:block_end] = reg.predict(x_blk)
        tau = block_end

    out = np.zeros(n, dtype=int)
    for t in range(n):
        s = scores[t]
        if np.isnan(s):
            continue
        if model.model_class is ModelClass.LOGISTIC_REGRESSION:
            if model.target is MLTarget.NET_RETURN_SIGN:
                if s >= band[1]:
                    out[t] = 1
                elif s <= band[0]:
                    out[t] = -1
            else:  # gross move exceeds cost -> confidence gate on momentum direction
                if s >= band[1] and mom[t] != 0:
                    out[t] = int(mom[t])
        else:  # ridge predicts forward bps
            if s >= band[1]:
                out[t] = 1
            elif s <= band[0]:
                out[t] = -1
    signal = _apply_direction(pd.Series(out, index=frame.index), spec.signal.direction)
    return signal.astype(int)


_DISPATCH = {
    FeatureKind.SESSION_MOMENTUM: signal_session_momentum,
    FeatureKind.SIGNED_RETURN_RUN: signal_signed_return_run,
    FeatureKind.VOLATILITY_BREAKOUT: signal_volatility_breakout,
    FeatureKind.RANGE_COMPRESSION_EXPANSION: signal_range_compression,
    FeatureKind.SPREAD_ZSCORE: signal_spread_gated,
    FeatureKind.LIQUIDITY_SHOCK_M1: signal_liquidity_shock,
    FeatureKind.SEASONALITY_CELL: signal_seasonality,
    FeatureKind.REGIME_TREND: signal_regime_trend,
    FeatureKind.ML_ABSTENTION: signal_ml_abstention,
}


def generate_signal(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    """Dispatch to the family signal generator for a compiled, admissible spec."""

    frame = fx.ensure_derived(frame)
    generator = _DISPATCH.get(spec.feature.kind)
    if generator is None:
        raise ValueError(f"no signal generator for feature kind {spec.feature.kind!r}")
    return generator(frame, spec).astype(int)
