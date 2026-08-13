"""FX_INTRADAY_ALPHA_DISCOVERY_V2 discovery-stage evaluator (2015-2017 only).

Evaluates the full frozen universe of 336 ADMITTED_EXECUTABLE trials on the already
inspected 2015-2017 development region, using the frozen canonical execution semantics
(via the bit-for-bit fast path), the frozen statistical protocol and the frozen survivor
predicate. It never opens a 2018+ file (enforced by the holdout firewall).

Scientific invariants:
* Registered multiple-testing denominator = 336, immutable. Every one of the 336 frozen
  candidates is a column of the return matrix (zero-trade / failed trials are all-zero
  columns), so a losing/failed candidate never shrinks the denominator.
* No outcome-driven pruning, cherry-picking or deletion. Every trial receives an immutable
  terminal state (EVALUATED / EVALUATED_ZERO_TRADES / EVALUATION_FAILURE) and stays in the
  registry.
* Discovery is exploratory: 2015-2017 was partly inspected during V1, so no V2 candidate is
  "validated alpha" after this run. 2018+ confirmation is a separate, later gate.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import json_hash
from fx_smc_bot.research.v2 import statistics as stats
from fx_smc_bot.research.v2.capabilities import DEVELOPMENT_YEARS, SUPPORTED_INSTRUMENTS
from fx_smc_bot.research.v2.compiler import ADMITTED, compile_all
from fx_smc_bot.research.v2.fastexec import simulate_multi
from fx_smc_bot.research.v2.features import ensure_derived
from fx_smc_bot.research.v2.firewall import HoldoutFirewall
from fx_smc_bot.research.v2.kernel import daily_metrics, spec_to_exec_cfg
from fx_smc_bot.research.v2.materialize import materialization_digest, materialize
from fx_smc_bot.research.v2.search_space import enumerate_admitted_specs
from fx_smc_bot.research.v2.signals import generate_signal
from fx_smc_bot.research.v2.spec import StrategySpec
from fx_smc_bot.research.v2.survivor import DEFAULT_THRESHOLDS, is_scientific_survivor

REGISTERED_V2_DENOMINATOR = 336  # immutable; equals the frozen admitted-executable count
COST_MULTS = (1.0, 1.5, 2.0)
GATE = "A0R5_V2_DISCOVERY_2015_2017_V1"


# --------------------------------------------------------------------------------------
# Data loading (firewall-guarded, 2015-2017 only)
# --------------------------------------------------------------------------------------
def load_instrument_frame(fw: HoldoutFirewall, raw: Path, instrument: str) -> pd.DataFrame:
    monthly: list[pd.DataFrame] = []
    for year in DEVELOPMENT_YEARS:
        for month in range(1, 13):
            rb = fw.read_market_json(
                raw / instrument / "price=bid" / f"year={year}" / f"month={month:02d}" / "data.json"
            )
            ra = fw.read_market_json(
                raw / instrument / "price=ask" / f"year={year}" / f"month={month:02d}" / "data.json"
            )
            b = pd.DataFrame(rb)
            a = pd.DataFrame(ra)
            for df in (b, a):
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            b = b.rename(columns={c: f"bid_{c}" for c in ("open", "high", "low", "close")})
            a = a.rename(columns={c: f"ask_{c}" for c in ("open", "high", "low", "close")})
            monthly.append(pd.merge(
                b[["timestamp", "bid_open", "bid_high", "bid_low", "bid_close"]],
                a[["timestamp", "ask_open", "ask_high", "ask_low", "ask_close"]],
                on="timestamp", how="inner",
            ))
    frame = (
        pd.concat(monthly, ignore_index=True)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return ensure_derived(frame)


# --------------------------------------------------------------------------------------
# Trial universe (rebuilds the frozen 336 with trial IDs; verifies the digest)
# --------------------------------------------------------------------------------------
def load_universe() -> tuple[list[tuple[str, StrategySpec]], str]:
    admitted, _rejected = compile_all(enumerate_admitted_specs())
    admitted = [r for r in admitted if r.terminal_state == ADMITTED]
    trials = materialize(admitted, git_sha="")
    digest = materialization_digest(trials)
    by_hash = {r.spec_hash: r.spec for r in admitted}
    universe = [(t["trial_id"], by_hash[t["configuration_hash"]]) for t in trials]
    return universe, digest


def _config_signature(spec: StrategySpec) -> str:
    payload = spec.canonical_dict()
    payload.pop("instrument", None)
    return json_hash(payload)


def _axis_tuple(spec: StrategySpec) -> tuple[Any, ...]:
    feat = dict(spec.feature.extra)
    model = spec.model
    return (
        spec.feature.kind.value,
        spec.feature.lookback_bars,
        spec.signal.direction.value,
        round(float(spec.signal.entry_threshold), 6),
        spec.signal.session_filter,
        spec.execution.holding_bars,
        feat.get("forecaster"),
        feat.get("cell"),
        model.model_class.value if model else None,
        dict(model.hyperparameters).get("label_horizon_bars") if model else None,
        model.n_components_or_bins if model else None,
    )


# --------------------------------------------------------------------------------------
# Per-trial evaluation
# --------------------------------------------------------------------------------------
def _walk_forward_folds(daily: pd.DataFrame) -> dict[str, Any]:
    """Purged expanding walk-forward: 12m train warm-up, sliding 3m test windows."""

    if daily.empty:
        return {"folds": [], "positive_fold_fraction": 0.0, "n_folds": 0}
    d = daily.copy()
    d["dt"] = pd.to_datetime(d["date"])
    d = d.sort_values("dt")
    start = d["dt"].iloc[0]
    train_end = start + pd.Timedelta(days=365)
    last = d["dt"].iloc[-1]
    folds: list[dict[str, Any]] = []
    k = 0
    while True:
        test_start = train_end + pd.Timedelta(days=91 * k)
        test_end = test_start + pd.Timedelta(days=91)
        if test_start >= last:
            break
        mask = (d["dt"] >= test_start) & (d["dt"] < test_end)
        if mask.any():
            net = float(d.loc[mask, "net_bps"].sum())
            folds.append({"fold": k, "start": test_start.date().isoformat(),
                          "net_bps": round(net, 6), "days": int(mask.sum())})
        k += 1
    positive = sum(1 for f in folds if f["net_bps"] > 0)
    frac = positive / len(folds) if folds else 0.0
    return {"folds": folds, "positive_fold_fraction": round(frac, 6), "n_folds": len(folds)}


def _year_breakdown(daily: pd.DataFrame) -> dict[str, Any]:
    if daily.empty:
        return {"per_year_net_bps": {}, "year_loo_positive": False}
    d = daily.copy()
    d["year"] = d["date"].str.slice(0, 4)
    per_year = {y: round(float(g["net_bps"].sum()), 6) for y, g in d.groupby("year")}
    years = [str(y) for y in DEVELOPMENT_YEARS]
    loo_ok = True
    for left_out in years:
        rest = sum(per_year.get(y, 0.0) for y in years if y != left_out)
        if not rest > 0:
            loo_ok = False
    return {"per_year_net_bps": per_year, "year_loo_positive": bool(loo_ok)}


def evaluate_trial(trial_id: str, spec: StrategySpec, frame: pd.DataFrame) -> dict[str, Any]:
    """Deterministically evaluate one trial; never raises (failures are terminal states)."""

    t0 = time.time()
    try:
        signal = generate_signal(frame, spec)
        cfg = spec_to_exec_cfg(spec)
        results = simulate_multi(frame, signal, cfg, cost_multipliers=COST_MULTS)
        base_daily, base_trades = results[1.0]
        metrics = daily_metrics(base_daily, base_trades)
        m15 = daily_metrics(*results[1.5])
        m20 = daily_metrics(*results[2.0])
        folds = _walk_forward_folds(base_daily)
        years = _year_breakdown(base_daily)
        net = float(metrics["net_bps"])
        skew, kurt = stats.sample_moments(base_daily["net_bps"].to_numpy(dtype=float)
                                          if not base_daily.empty else np.array([0.0]))
        sharpe = float(metrics["daily_sharpe"])
        ndays = int(metrics["days"])
        state = "EVALUATED" if int(metrics["trade_count"]) > 0 else "EVALUATED_ZERO_TRADES"
        row = {
            "trial_id": trial_id,
            "family_id": spec.family_id,
            "instrument": spec.instrument,
            "config_signature": _config_signature(spec),
            "configuration_hash": spec.spec_hash(),
            "terminal_state": state,
            "trade_count": int(metrics["trade_count"]),
            "active_days": ndays,
            "gross_bps": float(metrics["gross_bps"]),
            "cost_bps": float(metrics["cost_bps"]),
            "net_bps": net,
            "net_bps_per_trade": float(metrics["net_bps_per_trade"]),
            "daily_sharpe": sharpe,
            "max_drawdown_bps": float(metrics["max_drawdown_bps"]),
            "hit_rate": float(metrics["hit_rate"]),
            "turnover": float(metrics["turnover"]),
            "net_bps_1_5x": float(m15["net_bps"]),
            "net_bps_2_0x": float(m20["net_bps"]),
            "survives_1_5x": bool(float(m15["net_bps"]) > 0.0),
            "survives_2_0x": bool(float(m20["net_bps"]) > 0.0),
            "psr": round(stats.psr(sharpe, ndays, skew, kurt), 9),
            "dsr": round(stats.dsr(sharpe, ndays, skew, kurt, REGISTERED_V2_DENOMINATOR), 9),
            "fold_positive_fraction": folds["positive_fold_fraction"],
            "n_folds": folds["n_folds"],
            "folds": folds["folds"],
            "per_year_net_bps": years["per_year_net_bps"],
            "year_loo_positive": years["year_loo_positive"],
            "eval_seconds": round(time.time() - t0, 3),
            "daily_dates": list(base_daily["date"]) if not base_daily.empty else [],
            "daily_net_bps": [round(float(x), 9) for x in base_daily["net_bps"]]
            if not base_daily.empty else [],
        }
        return row
    except Exception as exc:  # noqa: BLE001 - failures are terminal states, never fatal
        return {
            "trial_id": trial_id,
            "family_id": spec.family_id,
            "instrument": spec.instrument,
            "config_signature": _config_signature(spec),
            "configuration_hash": spec.spec_hash(),
            "terminal_state": "EVALUATION_FAILURE",
            "error": f"{type(exc).__name__}: {exc}",
            "trade_count": 0, "active_days": 0, "gross_bps": 0.0, "cost_bps": 0.0,
            "net_bps": 0.0, "net_bps_per_trade": 0.0, "daily_sharpe": 0.0,
            "max_drawdown_bps": 0.0, "hit_rate": 0.0, "turnover": 0.0,
            "net_bps_1_5x": 0.0, "net_bps_2_0x": 0.0,
            "survives_1_5x": False, "survives_2_0x": False, "psr": 0.0, "dsr": 0.0,
            "fold_positive_fraction": 0.0, "n_folds": 0, "folds": [],
            "per_year_net_bps": {}, "year_loo_positive": False,
            "eval_seconds": round(time.time() - t0, 3),
            "daily_dates": [], "daily_net_bps": [],
        }


# --------------------------------------------------------------------------------------
# Aggregation: LOO, neighborhood, statistics, survivor predicate
# --------------------------------------------------------------------------------------
def _instrument_loo(rows: list[dict[str, Any]]) -> dict[str, bool]:
    by_sig: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        by_sig[r["config_signature"]][r["instrument"]] = float(r["net_bps"])
    result: dict[str, bool] = {}
    for r in rows:
        nets = by_sig[r["config_signature"]]
        insts = list(nets)
        if len(insts) <= 1:
            result[r["trial_id"]] = float(r["net_bps"]) > 0.0
            continue
        ok = True
        for left_out in insts:
            rest = sum(v for k, v in nets.items() if k != left_out)
            if not rest > 0:
                ok = False
        result[r["trial_id"]] = ok
    return result


def _neighborhood(rows: list[dict[str, Any]], specs: dict[str, StrategySpec]) -> dict[str, float]:
    by_fi: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_fi[(r["family_id"], r["instrument"])].append(r)
    axis_cache = {tid: _axis_tuple(specs[tid]) for tid in specs}
    out: dict[str, float] = {}
    for r in rows:
        focal = r
        focal_axis = axis_cache[focal["trial_id"]]
        neighbors = []
        for other in by_fi[(r["family_id"], r["instrument"])]:
            if other["trial_id"] == focal["trial_id"]:
                continue
            oa = axis_cache[other["trial_id"]]
            diffs = sum(1 for x, y in zip(focal_axis, oa, strict=True) if x != y)
            if diffs == 1:
                neighbors.append(float(other["net_bps"]))
        if not neighbors:
            out[focal["trial_id"]] = 0.0
        else:
            same = sum(1 for v in neighbors if (v > 0) == (focal["net_bps"] > 0))
            out[focal["trial_id"]] = round(same / len(neighbors), 6)
    return out


def build_return_matrix(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """336-column daily net-bps matrix aligned by NY exit date; zero for absent returns."""

    series = {}
    for r in rows:
        if r["daily_dates"]:
            series[r["trial_id"]] = pd.Series(r["daily_net_bps"], index=r["daily_dates"])
        else:
            series[r["trial_id"]] = pd.Series(dtype=float)
    matrix = pd.DataFrame(series).sort_index().fillna(0.0)
    # guarantee every registered trial is a column (denominator immutability)
    for r in rows:
        if r["trial_id"] not in matrix.columns:
            matrix[r["trial_id"]] = 0.0
    return matrix[[r["trial_id"] for r in rows]]


def run_statistics(matrix: pd.DataFrame, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [r["trial_id"] for r in rows]
    values = matrix.to_numpy(dtype=float)
    p_values = [stats.normal_p_value_from_mean(values[:, j]) for j in range(values.shape[1])]
    boot = stats.bootstrap_family_stats(matrix, seed=1729)
    holm = stats.holm_adjust(p_values)
    bh = stats.bh_fdr(p_values)
    rw = boot.get("romano_wolf_stepdown_p", [])
    pbo = stats.pbo_cscv(matrix)
    per_trial = {}
    for j, tid in enumerate(ids):
        per_trial[tid] = {
            "raw_p": round(p_values[j], 9),
            "holm_p": round(holm[j], 9),
            "bh_fdr_p": round(bh[j], 9),
            "romano_wolf_p": rw[j] if j < len(rw) else "NOT_APPLICABLE",
        }
    return {
        "registered_candidate_equivalent_denominator": REGISTERED_V2_DENOMINATOR,
        "evaluated_columns": int(values.shape[1]),
        "white_reality_check_p": boot.get("white_reality_check_p"),
        "hansen_spa_p": boot.get("hansen_spa_p"),
        "bootstrap_iterations": boot.get("bootstrap_iterations"),
        "block_length_days": boot.get("block_length_days"),
        "seed": boot.get("seed"),
        "pbo": pbo,
        "romano_wolf_significant": sum(
            1 for v in rw if isinstance(v, int | float) and v <= 0.05
        ),
        "holm_significant": sum(1 for v in holm if v <= 0.05),
        "bh_fdr_significant": sum(1 for v in bh if v <= 0.05),
        "per_trial": per_trial,
    }


def classify_survivors(
    rows: list[dict[str, Any]], loo: dict[str, bool], neigh: dict[str, float],
    statistics: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    survivors: list[dict[str, Any]] = []
    predicate_rows: list[dict[str, Any]] = []
    pbo = statistics["pbo"].get("pbo", "NOT_APPLICABLE")
    for r in rows:
        candidate = {
            "net_bps": r["net_bps"], "sharpe": r["daily_sharpe"],
            "trade_count": r["trade_count"], "active_days": r["active_days"],
            "fold_positive_fraction": r["fold_positive_fraction"],
            "instrument_loo_positive": loo.get(r["trial_id"], False),
            "neighborhood_same_sign_fraction": neigh.get(r["trial_id"], 0.0),
            "survives_1_5x": r["survives_1_5x"], "survives_2_0x": r["survives_2_0x"],
            "romano_wolf_p": statistics["per_trial"][r["trial_id"]]["romano_wolf_p"]
            if statistics["per_trial"][r["trial_id"]]["romano_wolf_p"] != "NOT_APPLICABLE"
            else 1.0,
            "pbo": pbo,
            "holdout_clean": True, "reproduction_pass": True,
        }
        ok, failed = is_scientific_survivor(candidate, DEFAULT_THRESHOLDS)
        predicate_rows.append({"trial_id": r["trial_id"], "family_id": r["family_id"],
                               "instrument": r["instrument"], "is_survivor": ok,
                               "failed_requirements": failed, "net_bps": r["net_bps"]})
        if ok:
            survivors.append({"trial_id": r["trial_id"], "family_id": r["family_id"],
                              "instrument": r["instrument"], "net_bps": r["net_bps"],
                              "daily_sharpe": r["daily_sharpe"]})
    return survivors, predicate_rows


def review_ranking(rows: list[dict[str, Any]], statistics: dict[str, Any]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        sig = statistics["per_trial"][r["trial_id"]]
        return (float(sig["bh_fdr_p"]), float(r["net_bps"]) <= 0.0,
                not r["survives_2_0x"], -float(r["net_bps"]),
                -float(r["daily_sharpe"]), r["trial_id"])
    ranked = sorted(rows, key=key)
    return [{"rank": i + 1, "trial_id": r["trial_id"], "family_id": r["family_id"],
             "instrument": r["instrument"], "net_bps": round(r["net_bps"], 4),
             "daily_sharpe": r["daily_sharpe"], "trade_count": r["trade_count"],
             "survives_2_0x": r["survives_2_0x"],
             "bh_fdr_p": statistics["per_trial"][r["trial_id"]]["bh_fdr_p"]}
            for i, r in enumerate(ranked)]


def family_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_family[r["family_id"]].append(r)
    out: dict[str, Any] = {}
    for fam, frows in sorted(by_family.items()):
        nets = [r["net_bps"] for r in frows]
        out[fam] = {
            "trials": len(frows),
            "positive_net": sum(1 for r in frows if r["net_bps"] > 0),
            "survives_1_5x": sum(1 for r in frows if r["survives_1_5x"]),
            "survives_2_0x": sum(1 for r in frows if r["survives_2_0x"]),
            "zero_trade": sum(1 for r in frows if r["terminal_state"] == "EVALUATED_ZERO_TRADES"),
            "failures": sum(1 for r in frows if r["terminal_state"] == "EVALUATION_FAILURE"),
            "mean_net_bps": round(float(np.mean(nets)), 4),
            "median_net_bps": round(float(np.median(nets)), 4),
            "best_net_bps": round(float(np.max(nets)), 4),
            "mean_trade_count": round(float(np.mean([r["trade_count"] for r in frows])), 1),
            "by_instrument_mean_net": {
                inst: round(float(np.mean([r["net_bps"] for r in frows
                                           if r["instrument"] == inst])), 4)
                for inst in SUPPORTED_INSTRUMENTS
                if any(r["instrument"] == inst for r in frows)
            },
        }
    return out


def _sharpe_from_daily(daily_net: list[float]) -> float:
    if len(daily_net) < 2:
        return 0.0
    arr = np.array(daily_net, dtype=float)
    std = float(np.std(arr, ddof=1))
    return float(np.mean(arr) / std * math.sqrt(252.0)) if std else 0.0
