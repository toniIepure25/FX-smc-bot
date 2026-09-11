"""V3.1 frozen discovery engine: materialization, signals, execution, statistics, survivors.

Executes the already-frozen V3.1 candidate materialization (992 executable scientific-alpha
candidates in universe A, 52 price-alpha-only candidates in universe B) on the frozen
pre-2018 canonical M1 data. This module implements ONLY what is necessary to run the
frozen materialization; it invents no strategies, no parameters and no thresholds. Every
candidate maps back to the frozen family registry / composition grammar / parameter scales.

Frozen rules honoured (all pre-outcome):

* universe A denominator is IMMUTABLE: every one of the 992 candidates receives exactly one
  immutable accounting row (EVALUATED / EVALUATED_ZERO_TRADES / EVALUATION_FAILURE);
  runtime failures, zero-trade candidates and unavailable-feature candidates never shrink
  the denominator;
* execution: side-correct BID/ASK fills, one-completed-M1 latency, adverse-first same-bar
  handling, mandatory NY flat 16:45, no-entry 16:30-17:30, 0.10 bps commission/slippage per
  fill at 1.0x/1.5x/2.0x stress, actual spread inside fills, and a fill may occur ONLY on
  an executable_quote=true bar (asserted); imputed/non-observed rows never fill and pending
  execution advances to the next session-valid executable quote;
* features: causal, right-aligned, computed on the observed sub-series only (imputed rows
  are not zero returns and do not update stateful features); cross-pair constructions
  require every leg contemporaneously observed; volume is provenance-only;
* the USDJPY:2010-01-01 UNRESOLVED_DATA_GAP day is absent from the data: no fills, no
  feature updates, no ML examples; cross constructions requiring that leg are unavailable
  on that day; unrelated instruments remain usable;
* discovery region: 2010-2014 (PRIMARY_DEVELOPMENT) is the return-matrix/statistics region;
  2015-2017 (SECONDARY_ROBUSTNESS, V2-exposed) is used only for robustness diagnostics;
* statistics: the frozen hierarchical battery (WRC, Hansen SPA, Romano-Wolf step-down,
  Holm, BH-FDR, PSR, DSR, CSCV PBO) with the stationary block bootstrap (999 iterations,
  block length 5, frozen seed) over universe A only; V1/V2 lineage is controlled by the
  program-level sequential procedure (alpha 0.05/3 allocated to V3), NOT by injecting
  imaginary columns into the V3 matrix;
* survivorship: the frozen per-horizon predicates only; REVIEW_RANKING != SCIENTIFIC_SURVIVOR.

Deterministic materialization rule (frozen with this engine, pre-outcome): candidate
parameter combinations are the lexicographic Cartesian product of the family's declared
parameter scales (scales in declared order, values ascending); where the full grid exceeds
the frozen PARAM_COMBO_CEILING (25) or an archetype's candidate budget, the FIRST
``ceiling``/``budget`` lexicographic points are the registered candidates and the remainder
are parameter-neighbourhood robustness, not separately-registered candidates. Composition
archetypes enumerate the SIGNAL component's parameter grid (other components pinned at
their canonical first scale values); a composition candidate is evaluated on every unit of
its scope and its P&L is the equal-weighted average across scope units.
"""

from __future__ import annotations

import itertools
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.a0r3d_certified_subset import (
    BASE_COMMISSION_SLIPPAGE_BPS_PER_FILL as _BASE_CS,
)
from fx_smc_bot.research.a0r3d_certified_subset import (
    _sample_moments,
    bh_fdr,
    bootstrap_family_stats,
    dsr,
    holm_adjust,
    normal_p_value_from_mean,
    psr,
)
from fx_smc_bot.research.v2.statistics import pbo_cscv
from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.compiler import (
    ADMITTED_EXECUTABLE,
    PARAM_COMBO_CEILING,
    REGISTERED_SELF_INSTRUMENTS,
    REGISTERED_TRIANGLES,
    compile_all,
)
from fx_smc_bot.research.v3.composition import ARCHETYPE_INDEX, ARCHETYPES
from fx_smc_bot.research.v3.discovery_data import (
    DEVELOPMENT_YEARS,
    PRIMARY_YEARS,
    DiscoveryFirewall,
    InstrumentData,
)
from fx_smc_bot.research.v3.execution_contract import FULLY_EXECUTABLE, executability_class
from fx_smc_bot.research.v3.families import FAMILIES, FAMILY_INDEX
from fx_smc_bot.research.v3.horizons import HORIZON_INDEX, HorizonClass
from fx_smc_bot.research.v3.parameters import PARAMETER_SCALE_INDEX
from fx_smc_bot.research.v3.survivor import PREDICATES

FROZEN_SEED = 1729
ALPHA_PROGRAM = 0.05
N_PROGRAM_VERSIONS = 3
ALPHA_V3 = ALPHA_PROGRAM / N_PROGRAM_VERSIONS
BOOTSTRAP_ITERATIONS = 999
BLOCK_LENGTH_DAYS = 5
COST_MULTS: tuple[float, ...] = (1.0, 1.5, 2.0)

_NO_ENTRY_LO, _NO_ENTRY_HI = 16 * 60 + 30, 17 * 60 + 30
_FLAT_LO, _FLAT_HI = 16 * 60 + 45, 17 * 60 + 30

EVALUATED = "EVALUATED"
EVALUATED_ZERO_TRADES = "EVALUATED_ZERO_TRADES"
EVALUATION_FAILURE = "EVALUATION_FAILURE"


# ======================================================================================
# Candidate materialization (frozen, deterministic)
# ======================================================================================
@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    universe: str
    family_id: str
    domain: str
    horizon: str
    scope: str
    archetype_id: str | None
    params: dict[str, float]
    param_hash: str
    executable: bool

    def axis_tuple(self) -> tuple[Any, ...]:
        return tuple(self.params[k] for k in sorted(self.params))


def _param_combos(scales: tuple[str, ...], cap: int) -> list[dict[str, float]]:
    names = list(scales)
    grids = [PARAMETER_SCALE_INDEX[s].values for s in names]
    combos = [dict(zip(names, vals, strict=True)) for vals in itertools.product(*grids)]
    return combos[:cap]


def materialize_universe() -> list[Candidate]:
    """The frozen 992 (A) + 52 (B) candidate registry, deterministically enumerated."""

    results = {r.family_id: r for r in compile_all()}
    cands: list[Candidate] = []
    seq = 0
    for fam in FAMILIES:
        res = results[fam.family_id]
        if res.terminal_state != ADMITTED_EXECUTABLE or not fam.standalone:
            continue
        combos = _param_combos(fam.parameter_scales, PARAM_COMBO_CEILING)
        if fam.instrument_scope == "self":
            scopes = list(REGISTERED_SELF_INSTRUMENTS)
        elif fam.instrument_scope == "panel":
            scopes = ["PANEL"]
        elif fam.instrument_scope == "triangle":
            scopes = ["|".join(t) for t in REGISTERED_TRIANGLES]
        else:  # pragma: no cover - registry is closed
            scopes = ["PANEL"]
        for scope in scopes:
            for p in combos:
                seq += 1
                ph = canonical_hash(p)
                cands.append(Candidate(
                    candidate_id=f"V3-{seq:04d}",
                    universe="A" if res.survivor_eligible else "B",
                    family_id=fam.family_id, domain=fam.domain,
                    horizon=fam.horizon.value, scope=scope, archetype_id=None,
                    params=p, param_hash=ph,
                    executable=(executability_class(fam.horizon) == FULLY_EXECUTABLE),
                ))
    for arch in ARCHETYPES:
        sig_fam = FAMILY_INDEX[arch.components[0].family_id]
        combos = _param_combos(sig_fam.parameter_scales, arch.candidate_budget)
        for p in combos:
            seq += 1
            ph = canonical_hash({"archetype": arch.archetype_id, **p})
            cands.append(Candidate(
                candidate_id=f"V3-{seq:04d}",
                universe="A" if executability_class(arch.horizon) == FULLY_EXECUTABLE else "B",
                family_id=sig_fam.family_id, domain="M",
                horizon=arch.horizon.value, scope=_arch_scope(arch),
                archetype_id=arch.archetype_id, params=p, param_hash=ph,
                executable=(executability_class(arch.horizon) == FULLY_EXECUTABLE),
            ))
    return cands


def _arch_scope(arch) -> str:
    sig_fam = FAMILY_INDEX[arch.components[0].family_id]
    if sig_fam.instrument_scope == "self":
        return "SELF3"
    if sig_fam.instrument_scope == "triangle":
        return "TRIANGLES"
    return "PANEL"


def registry_hash(cands: list[Candidate]) -> str:
    return canonical_hash([
        {"id": c.candidate_id, "u": c.universe, "f": c.family_id, "s": c.scope,
         "a": c.archetype_id, "p": c.param_hash, "h": c.horizon}
        for c in cands
    ])


# ======================================================================================
# Execution kernels (frozen semantics + executable_quote gating)
# ======================================================================================
def _spread_bps(ac: float, bc: float) -> float:
    mid = (ac + bc) / 2.0
    return (ac - bc) / mid * 10_000.0 if mid > 0 else 0.0


def simulate_v3(
    d: InstrumentData,
    signal: np.ndarray,
    holding: int,
    cost_mults: tuple[float, ...] = COST_MULTS,
    lo: int = 0,
    hi: int | None = None,
) -> dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, int]]]:
    """V3 execution: the certified side-correct state machine with executable_quote gating.

    A fill (entry, exit, stop, target, mandatory flat, delayed close) may occur ONLY on a
    bar with executable_quote == True (asserted). On non-executable bars the clock advances
    but no execution happens; a pending entry advances to the next executable bar.
    """

    hi = len(d.ts) if hi is None else min(hi, len(d.ts))
    bo, bc = d.bo[lo:hi], d.bc[lo:hi]
    ao, ac = d.ao[lo:hi], d.ac[lo:hi]
    ny_min, ny_date, execm = d.ny_min[lo:hi], d.ny_date[lo:hi], d.exec[lo:hi]
    n = hi - lo
    sig = signal[lo:hi]
    if n == 0:
        empty = pd.DataFrame(columns=["date", "gross_bps", "cost_bps", "net_bps", "turnover"])
        diag0 = {"flat_deferred": 0, "entry_advances": 0}
        return {m: (empty.copy(), [], dict(diag0)) for m in cost_mults}

    g_arr = np.zeros(n)
    overlay = np.zeros(n)
    is_exit = np.zeros(n)
    t_arr = np.zeros(n)
    trades: list[TradeRec] = []
    diag = {"flat_deferred": 0, "entry_advances": 0}

    pending = 0
    has_pos = False
    p_side = 0
    p_entry = 0.0
    p_idx = 0
    p_spread = 0.0
    p_ts = 0

    for i in range(n):
        m = int(ny_min[i])
        turn = 0.0
        if has_pos and bool(execm[i]):
            flat = _FLAT_LO <= m < _FLAT_HI
            if flat:
                event, exit_reason = "flat", "mandatory_flat"
            elif i - p_idx >= holding:
                event, exit_reason = "horizon", "horizon"
            else:
                event = None
            if event is not None:
                assert bool(execm[i]), "V3_EXEC: fill on non-executable bar (exit)"
                exit_price = bo[i] if p_side > 0 else ao[i]
                gross = _ret_bps(p_side, p_entry, exit_price)
                exit_spread = _spread_bps(ac[i], bc[i])
                g_arr[i] += gross
                overlay[i] += (p_spread + exit_spread) / 2.0
                is_exit[i] += 1.0
                t_arr[i] += 2.0
                trades.append(_trade_rec(d.ts[lo + p_ts], d.ts[lo + i], ny_date[i], p_side,
                                         exit_reason, gross, p_spread, exit_spread))
                has_pos = False
        pending_persists = False
        if (not has_pos) and pending:
            if bool(execm[i]):
                if not (_NO_ENTRY_LO <= m < _NO_ENTRY_HI):
                    assert bool(execm[i]), "V3_EXEC: fill on non-executable bar (entry)"
                    side = int(pending)
                    p_entry = ao[i] if side > 0 else bo[i]
                    p_side, p_idx, p_ts = side, i, i
                    p_spread = _spread_bps(ac[i], bc[i])
                    has_pos = True
                    turn += 1.0
            else:
                # frozen semantics: pending execution advances to the next
                # session-valid executable quote (the clock advances, no fill)
                diag["entry_advances"] += 1
                pending_persists = True
        t_arr[i] += turn
        if not pending_persists:
            pending = int(sig[i])

    tail: TradeRec | None = None
    if has_pos:
        j = n - 1
        while j >= 0 and not bool(execm[j]):
            j -= 1
        if j >= 0:
            exit_price = bo[j] if p_side > 0 else ao[j]
            gross = _ret_bps(p_side, p_entry, exit_price)
            exit_spread = _spread_bps(ac[j], bc[j])
            tail = (d.ts[lo + p_ts], d.ts[lo + j], ny_date[j], p_side,
                    "delayed_valid_exit_at_dataset_end", gross, p_spread, exit_spread)
            g_arr[j] += gross
            overlay[j] += (p_spread + exit_spread) / 2.0
            is_exit[j] += 1.0
            t_arr[j] += 2.0

    out: dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, int]]] = {}
    for mult in cost_mults:
        c_arr = np.maximum(mult - 1.0, 0.0) * overlay + is_exit * (mult * _BASE_CS * 2.0)
        comp = pd.DataFrame({
            "date": ny_date, "gross_bps": g_arr, "cost_bps": c_arr,
            "net_bps": g_arr - c_arr, "turnover": t_arr,
        })
        trs = [_trade_cost(t, mult) for t in trades]
        if tail is not None:
            trs = [*trs, _trade_cost(tail, mult)]
        daily = comp[comp["net_bps"] != 0.0].groupby("date", as_index=False).agg(
            gross_bps=("gross_bps", "sum"), cost_bps=("cost_bps", "sum"),
            net_bps=("net_bps", "sum"), turnover=("turnover", "sum"),
        )
        out[mult] = (daily, trs, dict(diag))
    return out


TradeRec = tuple[int, int, str, int, str, float, float, float]


def _ret_bps(side: int, entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0
    if side > 0:
        return (exit_price - entry) / entry * 10_000.0
    return (entry - exit_price) / entry * 10_000.0


def _trade_rec(ets: int, xts: int, xdate: str, side: int,
               reason: str, gross: float, es: float, xs: float) -> TradeRec:
    return (int(ets), int(xts), str(xdate), int(side), reason, gross, es, xs)


def _trade_cost(rec: TradeRec, mult: float) -> dict[str, Any]:
    ets, xts, xdate, side, reason, gross, es, xs = rec
    cost = max(mult - 1.0, 0.0) * (es + xs) / 2.0 + mult * _BASE_CS * 2.0
    return {"entry_timestamp": int(ets), "exit_timestamp": int(xts),
            "exit_date": str(xdate), "side": "long" if side > 0 else "short",
            "exit_reason": reason, "gross_bps": round(gross, 9),
            "cost_bps": round(cost, 9), "net_bps": round(gross - cost, 9)}


def compact_window(signal: np.ndarray, holding: int) -> tuple[int, int]:
    """Deterministic compaction: bars needed around non-zero signals."""

    nz = np.nonzero(signal)[0]
    if nz.size == 0:
        return 0, 0
    lo = max(0, int(nz[0]) - 2)
    hi = int(nz[-1]) + holding + 200
    return lo, hi


# ======================================================================================
# Signal generation (frozen family mechanisms, causal, observed-only)
# ======================================================================================
def _nan_free(*arrays: np.ndarray) -> np.ndarray:
    out = np.ones(len(arrays[0]), dtype=bool)
    for a in arrays:
        out &= np.isfinite(a)
    return out


def _clamp_holding(horizon: HorizonClass, value: float) -> int:
    spec = HORIZON_INDEX[horizon]
    return int(min(max(value, spec.min_holding_bars), spec.max_holding_bars))


def _session_open_window(ny_min: np.ndarray) -> np.ndarray:
    """NY 07:00-09:00 or 09:30-11:00 (frozen session-open conditioning window)."""

    return ((ny_min >= 7 * 60) & (ny_min < 9 * 60)) | (
        (ny_min >= 9 * 60 + 30) & (ny_min < 11 * 60))


def _channel(d: InstrumentData, L: int) -> tuple[np.ndarray, np.ndarray]:
    """Prior-L observed-bar high/low of mid (right-aligned, excludes current bar)."""

    o_mid = d.o_mid
    m = len(o_mid)
    hi = np.full(m, np.nan)
    lo = np.full(m, np.nan)
    if m > L:
        s_h = pd.Series(o_mid).rolling(L).max().shift(1).to_numpy()
        s_l = pd.Series(o_mid).rolling(L).min().shift(1).to_numpy()
        hi[:] = s_h
        lo[:] = s_l
    return _roll_obs_to_grid(hi, d), _roll_obs_to_grid(lo, d)


def _roll_obs_to_grid(values_obs: np.ndarray, d: InstrumentData) -> np.ndarray:
    from fx_smc_bot.research.v3.discovery_data import _roll_to_grid
    return _roll_to_grid(values_obs, d.o_idx, d.n)


def _vol_median(d: InstrumentData, W: int = 480) -> np.ndarray:
    rv = d.feat["realized_vol"]
    med = pd.Series(rv).rolling(W, min_periods=60).median().to_numpy()
    return med


def sig_A(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    L = int(p["lookback_bars_intraday"])
    sig_thr = float(p["entry_threshold_sigma"])
    rc = d.feat["range_compression"]
    atr = d.feat["atr"]
    mid = d.feat["mid"]
    ch_hi, ch_lo = _channel(d, L)
    med = _vol_median(d)
    compressed = rc < (0.5 * med)
    ok = _nan_free(mid, ch_hi, ch_lo, atr, rc, med) & (atr > 0)
    long_ = ok & compressed & (mid > ch_hi + sig_thr * atr)
    short = ok & compressed & (mid < ch_lo - sig_thr * atr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, L)


def sig_B_tsmom(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    L = int(p["lookback_bars_intraday"])
    sig_thr = float(p["entry_threshold_sigma"])
    t1 = d.feat[f"trend_slope_{L}"]
    L2 = min(2 * L, 480)
    t2 = d.feat[f"trend_slope_{L2}"]
    ok = _nan_free(t1, t2)
    long_ = ok & (t1 > sig_thr) & (t2 > sig_thr)
    short = ok & (t1 < -sig_thr) & (t2 < -sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H1_SESSION_DAILY, L)


def sig_B_pullback(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    L = int(p["lookback_bars_intraday"])
    sig_thr = float(p["entry_threshold_sigma"])
    L2 = min(2 * L, 480)
    trend = d.feat[f"trend_slope_{L2}"]
    pull = d.feat[f"mom_z_{L}"]
    ok = _nan_free(trend, pull)
    long_ = ok & (trend > sig_thr) & (pull < -sig_thr)
    short = ok & (trend < -sig_thr) & (pull > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H1_SESSION_DAILY, L)


def sig_C_zscore(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    H = int(p["halflife_bars"])
    sig_thr = float(p["entry_threshold_sigma"])
    dz = d.feat[f"dist_z_{H}"]
    rv = d.feat["realized_vol"]
    med = _vol_median(d)
    ok = _nan_free(dz, rv, med)
    high_vol = rv > (2.0 * med)
    long_ = ok & ~high_vol & (dz < -sig_thr)
    short = ok & ~high_vol & (dz > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, H)


def sig_C_ou(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    H = int(p["halflife_bars"])
    sig_thr = float(p["entry_threshold_sigma"])
    dz = d.feat[f"dist_z_{H}"]
    half = _ou_halflife(d)
    ok = _nan_free(dz, half) & (half >= 30.0) & (half <= 1000.0)
    long_ = ok & (dz < -sig_thr)
    short = ok & (dz > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H1_SESSION_DAILY, H)


def _rolling_lag1_autocorr(x: np.ndarray, W: int) -> np.ndarray:
    s = pd.Series(x)
    s1 = s.shift(1)
    S1 = s.rolling(W).sum()
    S1m = s1.rolling(W).sum()
    S2 = (s * s).rolling(W).sum()
    S2m = (s1 * s1).rolling(W).sum()
    S12 = (s * s1).rolling(W).sum()
    num = S12 - S1 * S1m / W
    den1 = S2 - S1 * S1 / W
    den2 = S2m - S1m * S1m / W
    with np.errstate(invalid="ignore", divide="ignore"):
        r = num / np.sqrt(np.maximum(den1 * den2, 1e-30))
    return r.to_numpy()


def _ou_halflife(d: InstrumentData) -> np.ndarray:
    """Rolling (300 observed bars) OU half-life from lag-1 autocorrelation of returns."""

    r = d.o_ret
    m = len(r)
    out = np.full(m + 1, np.nan)
    if m < 310:
        return _roll_obs_to_grid(out, d)
    corr = _rolling_lag1_autocorr(r, 300)
    with np.errstate(invalid="ignore", divide="ignore"):
        hl = np.where((corr > 0) & (corr < 1),
                      -math.log(2.0) / np.log(np.clip(corr, 1e-9, 1 - 1e-9)), np.nan)
    out[1:] = hl
    return _roll_obs_to_grid(out, d)


def sig_D(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    L = int(p["lookback_bars_intraday"])
    sig_thr = float(p["entry_threshold_sigma"])
    pk = d.feat["parkinson_vol"]
    med = pd.Series(pk).rolling(480, min_periods=60).median().to_numpy()
    rc = d.feat["range_compression"]
    atr = d.feat["atr"]
    mid = d.feat["mid"]
    ch_hi, ch_lo = _channel(d, L)
    hl = (d.bh + d.ah) / 2.0 - (d.bl + d.al) / 2.0
    ok = _nan_free(mid, ch_hi, ch_lo, atr, pk, med, rc) & (atr > 0)
    compressed = (rc < 0.5 * med) | (pk < 0.5 * med)
    expansion = hl > sig_thr * atr
    long_ = ok & compressed & expansion & (mid > ch_hi)
    short = ok & compressed & expansion & (mid < ch_lo)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, L)


def sig_E(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    sig_thr = float(p["entry_threshold_sigma"])
    H = int(p["halflife_bars"])
    dz = d.feat[f"dist_z_{H}"]
    sz = d.feat["spread_z"]
    ok = _nan_free(dz, sz)
    low_spread = sz < 0.0
    veto = sz > 1.5
    long_ = ok & low_spread & ~veto & (dz < -sig_thr)
    short = ok & low_spread & ~veto & (dz > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, H)


def sig_F(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    L = int(p["lookback_bars_intraday"])
    sig_thr = float(p["entry_threshold_sigma"])
    k = float(p["cost_edge_multiple"])
    mz = d.feat[f"mom_z_{L}"]
    rv = d.feat["realized_vol"]
    spread = d.feat["spread"]
    mid = d.feat["mid"]
    holding = _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, L)
    ny_min = d.ny_min
    open_win = _session_open_window(ny_min)
    ok = _nan_free(mz, rv, spread, mid) & (mid > 0)
    edge = np.abs(mz) * rv * holding * 10_000.0  # expected bps over holding (rv = log-return/bar)
    cost = (spread / mid * 10_000.0) + 2.0 * _BASE_CS
    gated = edge >= k * cost
    long_ = ok & open_win & gated & (mz > sig_thr)
    short = ok & open_win & gated & (mz < -sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, holding


def sig_I_kalman(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    H = int(p["halflife_bars"])
    sig_thr = float(p["entry_threshold_sigma"])
    drift_z = _kalman_drift_z(d, H)
    ok = np.isfinite(drift_z)
    long_ = ok & (drift_z > sig_thr)
    short = ok & (drift_z < -sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H1_SESSION_DAILY, H)


_KALMAN_DRIFT_CACHE: dict[tuple[str, int], np.ndarray] = {}


def _kalman_drift_z(d: InstrumentData, H: int) -> np.ndarray:
    """Filtered (not smoothed) local-trend Kalman drift in vol units (causal, sequential)."""

    key = (d.inst, int(H))
    if key in _KALMAN_DRIFT_CACHE:
        return _KALMAN_DRIFT_CACHE[key]
    y = d.o_mid
    m = len(y)
    out = np.full(m + 1, np.nan)
    if m < 200:
        _KALMAN_DRIFT_CACHE[key] = _roll_obs_to_grid(out, d)
        return _KALMAN_DRIFT_CACHE[key]
    rv = d.feat["realized_vol"]
    rv_obs = np.interp(d.o_idx, np.arange(d.n), rv)
    tau = float(H)
    # state [level, velocity]; proper 2-state KF with tracked covariance
    x = float(y[0])
    v = 0.0
    rvol0 = max(float(rv_obs[0]), 1e-9)
    p11 = (0.01 * rvol0 * y[0]) ** 2
    p12 = 0.0
    p22 = (0.001 * rvol0 * y[0]) ** 2
    for j in range(1, m):
        rvol = max(float(rv_obs[j]), 1e-9)
        R = (2.0 * rvol * y[j - 1]) ** 2
        Qh = (0.1 * rvol * y[j - 1]) ** 2
        Qv = (0.01 * rvol * y[j - 1] / tau) ** 2
        fx = x + v
        fv = v
        pf11 = p11 + 2.0 * p12 + p22 + Qh
        pf12 = p12 + p22 + Qh
        pf22 = p22 + Qv
        innov = y[j] - fx
        S = pf11 + R
        K1 = pf11 / S
        K2 = pf12 / S
        x = fx + K1 * innov
        v = fv + K2 * innov
        p11 = (1.0 - K1) * pf11 - K2 * pf12
        p12 = (1.0 - K1) * pf12 - K2 * pf22
        p22 = pf22
        out[j + 1] = v / (y[j] * rvol) if y[j] > 0 else np.nan
    grid = _roll_obs_to_grid(out, d)
    _KALMAN_DRIFT_CACHE[key] = grid
    return grid


def sig_I_changepoint(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    H = int(p["halflife_bars"])
    sig_thr = float(p["entry_threshold_sigma"])
    r = d.o_ret
    m = len(r)
    out = np.zeros(m + 1, dtype=np.int8)
    if m > H + 10:
        s = pd.Series(r)
        mu = s.rolling(H).mean().to_numpy()
        sd = s.rolling(H).std().to_numpy()
        half = max(H // 2, 5)
        recent = s.rolling(half).mean().to_numpy()
        prior = s.rolling(half).mean().shift(half).to_numpy()
        with np.errstate(invalid="ignore"):
            dev = (recent - prior) / sd
        valid = (np.isfinite(mu) & np.isfinite(sd) & (sd > 1e-12)
                 & np.isfinite(recent) & np.isfinite(prior))
        out[1:][valid & (dev > sig_thr)] = 1
        out[1:][valid & (dev < -sig_thr)] = -1
    return _roll_obs_to_grid(out, d), _clamp_holding(HorizonClass.H1_SESSION_DAILY, H)


def sig_K(d: InstrumentData, p: dict[str, float]) -> tuple[np.ndarray, int]:
    sig_thr = float(p["entry_threshold_sigma"])
    k = float(p["cost_edge_multiple"])
    mz = d.feat["mom_z_60"]
    rv = d.feat["realized_vol"]
    spread = d.feat["spread"]
    mid = d.feat["mid"]
    holding = 60
    ok = _nan_free(mz, rv, spread, mid) & (mid > 0)
    edge = np.abs(mz) * rv * holding * 10_000.0
    cost = (spread / mid * 10_000.0) + 2.0 * _BASE_CS
    gated = edge >= k * cost
    long_ = ok & gated & (mz > sig_thr)
    short = ok & gated & (mz < -sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    sig[~d.obs] = 0
    return sig, _clamp_holding(HorizonClass.H0_MICRO_INTRADAY, holding)


def sig_L(d: InstrumentData, p: dict[str, float], base_sig: np.ndarray,
          base_daily: pd.DataFrame) -> tuple[np.ndarray, int]:
    """Meta-label filter: expanding purged logistic over base-signal trades."""

    sig_thr = float(p["entry_threshold_sigma"])
    ts_ = d.feat["trend_slope_120"]
    holding = _clamp_holding(HorizonClass.H1_SESSION_DAILY, 120)
    base = np.where((ts_ > sig_thr) | (ts_ < -sig_thr), np.sign(ts_), 0).astype(np.int8)
    base[~d.obs] = 0
    if base.sum() == 0:
        return base, holding
    # labels from the base execution (gross edge vs round-trip cost per trade)
    res = simulate_v3(d, base, holding, cost_mults=(1.0,))
    daily, trades, _ = res[1.0]
    if not trades:
        return base, holding
    feats = {
        "mom": d.feat["mom_z_60"], "sz": d.feat["spread_z"],
        "rv": d.feat["realized_vol"], "ts": d.feat["trend_slope_120"],
    }
    X: list[list[float]] = []
    ylab: list[int] = []
    entry_rows: list[int] = []
    ts_to_row = {int(t): i for i, t in enumerate(d.ts)}
    for tr in trades:
        i = ts_to_row.get(int(tr["entry_timestamp"]))
        if i is None or i < 1:
            continue
        s = i - 1  # decision bar (causal: entry fills at the open of bar i)
        vals = [feats[k][s] for k in ("mom", "sz", "rv", "ts")]
        if any(not np.isfinite(v) for v in vals):
            continue
        X.append([float(v) for v in vals])
        ylab.append(1 if float(tr["gross_bps"]) > float(tr["cost_bps"]) else 0)
        entry_rows.append(i)
    if len(X) < 50:
        return base, holding
    Xa = np.array(X)
    ya = np.array(ylab)
    mu = Xa.mean(axis=0)
    sd = Xa.std(axis=0) + 1e-9
    Xs = (Xa - mu) / sd
    # expanding logistic: predict each base trade from earlier trades only (purged/embargoed
    # by construction: a trade's own label is never in its own training set)
    pred = np.zeros(len(Xs))
    w = np.zeros(4)
    b = 0.0
    lr = 0.05
    for j in range(len(Xs)):
        if j >= 50:
            z = Xs[j] @ w + b
            pred[j] = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            g = pred[j] - ya[j]
            w -= lr * (g * Xs[j] + 1e-4 * w)
            b -= lr * g
        else:
            pred[j] = 0.5
    final = np.zeros(d.n, dtype=np.int8)
    for j, i in enumerate(entry_rows):
        if pred[j] >= 0.5:
            s = i - 1
            while s >= 0 and base[s] == 0:
                s -= 1
            if s >= 0:
                final[s] = base[s]
    final[~d.obs] = 0
    return final, holding


# ======================================================================================
# Panel / triangle contexts
# ======================================================================================
@dataclass
class PanelContext:
    datas: dict[str, InstrumentData]
    grid_ts: np.ndarray
    grid_ny_date: np.ndarray
    leg_idx: dict[str, np.ndarray]
    all_obs: np.ndarray
    usd_factor: np.ndarray
    resid_z: dict[str, np.ndarray]
    daily_dates: np.ndarray
    daily_mid: dict[str, np.ndarray]
    daily_spread: dict[str, np.ndarray]
    tri_resid_z: dict[str, np.ndarray]
    tri_leg_idx: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]


def build_panel_context(datas: dict[str, InstrumentData]) -> PanelContext:
    base = datas["EURUSD"]
    grid_ts = base.ts
    leg_idx: dict[str, np.ndarray] = {}
    all_obs = np.ones(len(grid_ts), dtype=bool)
    for inst, d in datas.items():
        if d.n == base.n and np.array_equal(d.ts, grid_ts):
            idx = np.arange(d.n)
            all_obs &= d.obs
        else:
            idx = np.searchsorted(d.ts, grid_ts)
            idx = np.where(idx < d.n, idx, -1)
            obs_at = np.zeros(len(grid_ts), dtype=bool)
            good = (idx >= 0) & (idx < d.n) & (d.ts[idx] == grid_ts)
            obs_at[good] = d.obs[idx[good]]
            all_obs &= obs_at
        leg_idx[inst] = idx

    # USD factor on the grid (M1 returns of the six USD majors, sign-corrected)
    uf = np.full(len(grid_ts), np.nan)
    acc = np.zeros(len(grid_ts))
    cnt = np.zeros(len(grid_ts))
    for inst, sgn in (("EURUSD", -1.0), ("GBPUSD", -1.0), ("USDJPY", 1.0),
                      ("AUDUSD", -1.0), ("NZDUSD", -1.0), ("USDCAD", -1.0)):
        d = datas[inst]
        r = np.full(d.n, np.nan)
        if len(d.o_ret):
            r[d.o_idx[1:]] = d.o_ret
        r_grid = _map_to_grid(r, d, grid_ts, leg_idx[inst])
        ok = np.isfinite(r_grid)
        acc += sgn * np.where(ok, r_grid, 0.0)
        cnt += ok
    with np.errstate(invalid="ignore", divide="ignore"):
        uf = np.where(cnt >= 6, acc / np.maximum(cnt, 1), np.nan)

    # daily closes + daily USD factor + per-pair rolling-60d beta + M1 residual z
    daily_dates, daily_mid = _panel_daily(datas, grid_ts, leg_idx, all_obs)
    grid_ny_date = _ts_to_date_str(grid_ts)
    day_of_bar = np.searchsorted(daily_dates, grid_ny_date, side="right") - 1
    uf_daily = _daily_usd_factor(daily_mid, len(daily_dates))
    resid_z: dict[str, np.ndarray] = {}
    for inst in datas:
        r_daily = np.full(len(daily_dates), np.nan)
        mid = daily_mid[inst]
        ok = np.isfinite(mid)
        r_daily[1:] = np.where(ok[1:] & ok[:-1], np.log(mid[1:] / mid[:-1]), np.nan)
        beta = _rolling_ols_beta(r_daily, uf_daily, 60)
        beta_lag = np.roll(beta, 1)
        beta_lag[0] = np.nan
        # M1 residual: r_i_t - beta(day(t)-1) * usd_factor_t
        d = datas[inst]
        r = np.full(d.n, np.nan)
        if len(d.o_ret):
            r[d.o_idx[1:]] = d.o_ret
        r_grid = _map_to_grid(r, d, grid_ts, leg_idx[inst])
        beta_idx = np.clip(day_of_bar, 0, len(beta_lag) - 1)
        beta_at = np.where(day_of_bar >= 0, beta_lag[beta_idx], np.nan)
        resid = r_grid - beta_at * uf
        resid_z[inst] = _rolling_zscore_grid(resid, 480)

    # triangle residuals
    tri_resid_z: dict[str, np.ndarray] = {}
    tri_leg_idx: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for (a, b, c) in (("EURUSD", "USDJPY", "EURJPY"), ("GBPUSD", "USDJPY", "GBPJPY"),
                      ("AUDUSD", "USDJPY", "AUDJPY"), ("EURUSD", "GBPUSD", "EURGBP"),
                      ("EURUSD", "USDCHF", "EURCHF")):
        key = f"{a}|{b}|{c}"
        s1, s2 = (-1.0, -1.0) if c.endswith("JPY") else (1.0, -1.0)
        la, lb, lc = leg_idx[a], leg_idx[b], leg_idx[c]
        ok = all_obs & _leg_obs(datas[a], la) & _leg_obs(datas[b], lb) & _leg_obs(datas[c], lc)
        ln_a = _leg_log_mid_grid(datas[a], grid_ts, la)
        ln_b = _leg_log_mid_grid(datas[b], grid_ts, lb)
        ln_c = _leg_log_mid_grid(datas[c], grid_ts, lc)
        with np.errstate(invalid="ignore"):
            res = np.where(ok, ln_c + s1 * ln_a + s2 * ln_b, np.nan)
        tri_resid_z[key] = _rolling_zscore_grid(res, 300)
        tri_leg_idx[key] = (la, lb, lc)

    daily_spread: dict[str, np.ndarray] = {}
    uniq, inv = np.unique(base.ny_date, return_inverse=True)
    for inst, d in datas.items():
        sp = (d.ac - d.bc) / ((d.ac + d.bc) / 2.0) * 10_000.0
        if d.n == len(grid_ts) and np.array_equal(d.ts, grid_ts):
            ok, sp_at = d.obs, sp
        else:
            idx = leg_idx[inst]
            ok = np.zeros(len(grid_ts), dtype=bool)
            good = (idx >= 0) & (idx < d.n)
            ok[good] = d.obs[idx[good]]
            sp_at = np.full(len(grid_ts), np.nan)
            sp_at[good] = sp[idx[good]]
        vals = np.where(ok & np.isfinite(sp_at), sp_at, np.nan)
        daily_spread[inst] = (pd.Series(vals, index=inv).groupby(level=0).last()
                              .reindex(range(len(uniq))).to_numpy())

    return PanelContext(datas=datas, grid_ts=grid_ts, grid_ny_date=grid_ny_date,
                        leg_idx=leg_idx, all_obs=all_obs, usd_factor=uf,
                        resid_z=resid_z, daily_dates=daily_dates, daily_mid=daily_mid,
                        daily_spread=daily_spread, tri_resid_z=tri_resid_z,
                        tri_leg_idx=tri_leg_idx)


def _leg_obs(d: InstrumentData, idx: np.ndarray) -> np.ndarray:
    out = np.zeros(len(idx), dtype=bool)
    good = (idx >= 0) & (idx < d.n)
    out[good] = d.obs[idx[good]]
    return out


def _signal_to_instrument_grid(sig_grid: np.ndarray, ctx: PanelContext,
                               inst: str) -> np.ndarray:
    """Map a signal defined on the panel (EURUSD) clock grid onto one instrument's own
    clock grid (instruments have slightly different session coverage)."""

    d = ctx.datas[inst]
    if d.n == len(ctx.grid_ts) and np.array_equal(d.ts, ctx.grid_ts):
        return sig_grid
    out = np.zeros(d.n, dtype=np.int8)
    idx = ctx.leg_idx[inst]
    good = (idx >= 0) & (idx < d.n) & (d.ts[idx] == ctx.grid_ts)
    out[idx[good]] = sig_grid[good]
    return out


def _map_to_grid(values: np.ndarray, d: InstrumentData, grid_ts: np.ndarray,
                 idx: np.ndarray) -> np.ndarray:
    out = np.full(len(grid_ts), np.nan)
    good = (idx >= 0) & (idx < d.n) & (d.ts[idx] == grid_ts)
    out[good] = values[idx[good]]
    return out


def _leg_log_mid_grid(d: InstrumentData, grid_ts: np.ndarray, idx: np.ndarray) -> np.ndarray:
    lm = np.log(np.where(d.obs, (d.bc + d.ac) / 2.0, np.nan))
    return _map_to_grid(lm, d, grid_ts, idx)


def _ts_to_date_str(ts: np.ndarray) -> np.ndarray:
    dt = pd.to_datetime(ts, unit="ms", utc=True).tz_convert("America/New_York")
    return dt.strftime("%Y-%m-%d").to_numpy()


def _panel_daily(datas: dict[str, InstrumentData], grid_ts: np.ndarray,
                 leg_idx: dict[str, np.ndarray],
                 all_obs: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    base = datas["EURUSD"]
    dates = base.ny_date
    n = len(grid_ts)
    uniq, inv = np.unique(dates, return_inverse=True)
    daily_mid: dict[str, np.ndarray] = {}
    for inst, d in datas.items():
        mids = (d.bc + d.ac) / 2.0
        if d.n == n and np.array_equal(d.ts, grid_ts):
            ok = d.obs
            mid_at = mids
        else:
            idx = leg_idx[inst]
            ok = np.zeros(n, dtype=bool)
            good = (idx >= 0) & (idx < d.n)
            ok[good] = d.obs[idx[good]]
            mid_at = np.full(n, np.nan)
            mid_at[good] = mids[idx[good]]
        vals = np.where(ok & np.isfinite(mid_at), mid_at, np.nan)
        # last observed mid per NY day (groupby.last skips NaN)
        daily_mid[inst] = (pd.Series(vals, index=inv).groupby(level=0).last()
                           .reindex(range(len(uniq))).to_numpy())
    return uniq, daily_mid


def _daily_usd_factor(daily_mid: dict[str, np.ndarray], n_days: int) -> np.ndarray:
    """Daily USD-appreciation factor: mean of the six sign-corrected USD-major daily
    log-returns; NaN unless all six are available that day."""

    pairs = (("EURUSD", -1.0), ("GBPUSD", -1.0), ("USDJPY", 1.0),
             ("AUDUSD", -1.0), ("NZDUSD", -1.0), ("USDCAD", -1.0))
    r6 = np.full((n_days, len(pairs)), np.nan)
    for k, (p2, sgn) in enumerate(pairs):
        mid = daily_mid[p2]
        r6[1:, k] = np.where(np.isfinite(mid[1:]) & np.isfinite(mid[:-1]),
                             sgn * np.log(mid[1:] / mid[:-1]), np.nan)
    out = np.full(n_days, np.nan)
    allfin = np.isfinite(r6).all(axis=1)
    out[allfin] = r6[allfin].mean(axis=1)
    return out


def _rolling_ols_beta(y: np.ndarray, x: np.ndarray, W: int) -> np.ndarray:
    m = len(y)
    out = np.full(m, np.nan)
    if m < W + 1:
        return out
    sy = pd.Series(y).rolling(W).sum().to_numpy()
    sx = pd.Series(x).rolling(W).sum().to_numpy()
    sxx = pd.Series(x * x).rolling(W).sum().to_numpy()
    sxy = pd.Series(y * x).rolling(W).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        vx = sxx - sx * sx / W
        beta = np.where(vx > 1e-18, (sxy - sy * sx / W) / np.maximum(vx, 1e-18), np.nan)
    out[:] = beta
    return out


def _rolling_zscore_grid(x: np.ndarray, W: int) -> np.ndarray:
    s = pd.Series(x)
    mu = s.rolling(W, min_periods=W // 2).mean().to_numpy()
    sd = s.rolling(W, min_periods=W // 2).std().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where((sd > 1e-12) & np.isfinite(mu), (x - mu) / np.maximum(sd, 1e-12), np.nan)
    return z


# ======================================================================================
# Panel / triangle / portfolio signal + execution
# ======================================================================================
def sig_G_factor(
    ctx: PanelContext, p: dict[str, float]
) -> tuple[np.ndarray, dict[str, np.ndarray], int]:
    """Returns (signal on grid, {pair: position series}, holding). One position at a time:
    the pair with the most extreme residual z beyond the threshold."""

    sig_thr = float(p["entry_threshold_sigma"])
    L = int(p["lookback_bars_intraday"])
    holding = _clamp_holding(HorizonClass.H1_SESSION_DAILY, L)
    n = len(ctx.grid_ts)
    pos: dict[str, np.ndarray] = {inst: np.zeros(n, dtype=np.int8) for inst in ctx.datas}
    best_abs = np.full(n, -np.inf)
    best_z = np.full(n, np.nan)
    best_pair: dict[int, str] = {}
    for inst, z in ctx.resid_z.items():
        ok = np.isfinite(z) & np.isfinite(ctx.usd_factor)
        az = np.abs(z)
        better = ok & (az > sig_thr) & (az > best_abs)
        best_abs = np.where(better, az, best_abs)
        best_z = np.where(better, z, best_z)
        for i in np.where(better)[0]:
            best_pair[int(i)] = inst
    insts = list(ctx.datas)
    inst_col = {inst: k for k, inst in enumerate(insts)}
    pos2d = np.zeros((n, len(insts)), dtype=np.int8)
    if best_pair:
        bars = np.array(sorted(best_pair), dtype=np.int64)
        cols = np.array([inst_col[best_pair[int(b)]] for b in bars], dtype=np.int64)
        signs = np.where(best_z[bars] < 0, 1, -1).astype(np.int8)
        pos2d[bars, cols] = signs
    for k, inst in enumerate(insts):
        pos[inst] = pos2d[:, k]
    sig = pos2d.sum(axis=1).astype(np.int8)
    return sig, pos, holding


def sig_H_triangle(ctx: PanelContext, tri: str, p: dict[str, float]) -> tuple[np.ndarray, int]:
    sig_thr = float(p["entry_threshold_sigma"])
    H = int(p["halflife_bars"])
    z = ctx.tri_resid_z[tri]
    ok = np.isfinite(z) & ctx.all_obs
    long_ = ok & (z < -sig_thr)
    short = ok & (z > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    return sig, _clamp_holding(HorizonClass.H1_SESSION_DAILY, H)


def sig_G_xsmom(ctx: PanelContext, p: dict[str, float]) -> tuple[np.ndarray, np.ndarray, int]:
    """Daily cross-sectional momentum: long top-3 / short bottom-3 risk-adjusted pairs."""

    D = int(p["lookback_days_multiday"])
    sig_thr = float(p["entry_threshold_sigma"])
    dates = ctx.daily_dates
    n = len(dates)
    pos = np.zeros((n, len(ctx.datas)), dtype=np.int8)
    insts = list(ctx.datas)
    for t in range(D, n):
        scores = {}
        for inst in insts:
            mid = ctx.daily_mid[inst]
            if not (np.isfinite(mid[t]) and np.isfinite(mid[t - D])):
                continue
            r = math.log(mid[t] / mid[t - D])
            window = mid[max(0, t - 60):t]
            window = window[np.isfinite(window)]
            if len(window) < 10:
                continue
            vol = float(np.std(np.log(window[1:] / window[:-1]), ddof=1))
            if vol <= 0:
                continue
            scores[inst] = r / (vol * math.sqrt(D))
        if len(scores) < 6:
            continue
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        for inst, sc in ranked[:3]:
            if sc > sig_thr * 0.1:
                pos[t, insts.index(inst)] = 1
        for inst, sc in ranked[-3:]:
            if sc < -sig_thr * 0.1:
                pos[t, insts.index(inst)] = -1
    return pos, dates, 1


def simulate_triangle(
    ctx: PanelContext, tri: str, signal: np.ndarray, holding: int,
    cost_mults: tuple[float, ...] = COST_MULTS,
) -> dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]]:
    """3-leg triangular trade: short synthetic / long legs (or inverse), side-correct fills,
    synchronized executable bars only, NY flat, frozen costs per leg."""

    (a, b, c) = tri.split("|")
    da, db, dc = ctx.datas[a], ctx.datas[b], ctx.datas[c]
    la, lb, lc = ctx.tri_leg_idx[tri]
    n = len(ctx.grid_ts)
    g_arr = np.zeros(n)
    overlay = np.zeros(n)
    is_exit = np.zeros(n)
    t_arr = np.zeros(n)
    leg_pnl = {a: 0.0, b: 0.0, c: 0.0}
    trades: list[dict[str, Any]] = []
    diag = {"flat_deferred": 0, "entry_advances": 0, "unresolved_gap_fills": 0}

    def leg_exec(d: InstrumentData, idx: np.ndarray, i: int) -> bool:
        k = idx[i]
        return bool(0 <= k < d.n and d.exec[k])

    def leg_price(d: InstrumentData, idx: np.ndarray, i: int, side: int) -> float:
        k = idx[i]
        return float(d.ao[k] if side > 0 else d.bo[k])

    def leg_spread(d: InstrumentData, idx: np.ndarray, i: int) -> float:
        k = idx[i]
        return _spread_bps(d.ac[k], d.bc[k])

    pending = 0
    has_pos = False
    p_side = 0
    p_idx = 0
    p_entries: dict[str, float] = {}
    p_spreads: dict[str, float] = {}
    # leg directions for a +1 signal: short synthetic (c), long legs (a, b)
    dir_map = {a: 1, b: 1, c: -1}

    for i in range(n):
        m = int(da.ny_min[la[i]])
        all_exec = leg_exec(da, la, i) and leg_exec(db, lb, i) and leg_exec(dc, lc, i)
        turn = 0.0
        if has_pos and all_exec:
            flat = _FLAT_LO <= m < _FLAT_HI
            bars_held = i - p_idx
            if flat or bars_held >= holding:
                reason = "mandatory_flat" if flat else "horizon"
                gross = 0.0
                ov = 0.0
                for leg, d, idx in ((a, da, la), (b, db, lb), (c, dc, lc)):
                    side = dir_map[leg] * p_side
                    k = idx[i]
                    exit_price = float(d.bo[k] if side > 0 else d.ao[k])
                    entry_price = p_entries[leg]
                    r = _ret_bps(side, entry_price, exit_price)
                    gross += r
                    ov += leg_spread(d, idx, i)
                    leg_pnl[leg] += r
                g_arr[i] += gross
                overlay[i] += ov / 3.0
                is_exit[i] += 3.0
                t_arr[i] += 6.0
                trades.append({"exit_date": str(ctx.grid_ny_date[i]), "exit_reason": reason,
                               "_gross": gross, "_ov": ov, "n_legs": 3, "p_side": p_side})
                has_pos = False
        pending_persists = False
        if (not has_pos) and pending:
            if all_exec:
                if not (_NO_ENTRY_LO <= m < _NO_ENTRY_HI):
                    p_side = int(pending)
                    p_idx = i
                    p_entries = {}
                    p_spreads = {}
                    for leg, d, idx in ((a, da, la), (b, db, lb), (c, dc, lc)):
                        side = dir_map[leg] * p_side
                        p_entries[leg] = leg_price(d, idx, i, side)
                        p_spreads[leg] = leg_spread(d, idx, i)
                    has_pos = True
                    turn += 3.0
            else:
                diag["entry_advances"] += 1
                pending_persists = True
        t_arr[i] += turn
        if not pending_persists:
            pending = int(signal[i])

    out: dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]] = {}
    for mult in cost_mults:
        c_arr = np.maximum(mult - 1.0, 0.0) * overlay + is_exit * (mult * _BASE_CS * 2.0)
        comp = pd.DataFrame({
            "date": ctx.grid_ny_date[:n],
            "gross_bps": g_arr, "cost_bps": c_arr, "net_bps": g_arr - c_arr, "turnover": t_arr,
        })
        trs = []
        for t in trades:
            cost = max(mult - 1.0, 0.0) * t["_ov"] / 3.0 + mult * _BASE_CS * 2.0 * 3
            trs.append({"exit_date": t["exit_date"], "exit_reason": t["exit_reason"],
                        "gross_bps": round(t["_gross"], 9),
                        "cost_bps": round(cost, 9), "net_bps": round(t["_gross"] - cost, 9)})
        daily = comp[comp["net_bps"] != 0.0].groupby("date", as_index=False).agg(
            gross_bps=("gross_bps", "sum"), cost_bps=("cost_bps", "sum"),
            net_bps=("net_bps", "sum"), turnover=("turnover", "sum"),
        )
        out[mult] = (daily, trs, {"leg_pnl_bps": dict(leg_pnl), **diag})
    return out


def simulate_daily_portfolio(
    ctx: PanelContext, pos: np.ndarray, dates: np.ndarray,
    cost_mults: tuple[float, ...] = COST_MULTS,
) -> dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]]:
    """Daily-rebalanced cross-sectional portfolio (price-alpha; financing unsupported)."""

    insts = list(ctx.datas)
    n = len(dates)
    g_arr = np.zeros(n)
    c_base = np.zeros(n)
    leg_pnl = {inst: 0.0 for inst in insts}
    prev = np.zeros(len(insts), dtype=np.int8)
    trs_base: list[dict[str, Any]] = []
    for t in range(1, n):
        gross = 0.0
        cost = 0.0
        rebal = 0
        for j, inst in enumerate(insts):
            mid = ctx.daily_mid[inst]
            if not (np.isfinite(mid[t]) and np.isfinite(mid[t - 1])):
                continue
            r = math.log(mid[t] / mid[t - 1]) * 10_000.0
            if prev[j] != 0:
                gross += prev[j] * r
                leg_pnl[inst] += prev[j] * r
            dpos = int(pos[t, j]) - int(prev[j])
            if dpos != 0:
                rebal += 1
                spread_bps = float(ctx.daily_spread[inst][t])
                if not np.isfinite(spread_bps):
                    spread_bps = 0.0
                cost += abs(dpos) * (spread_bps / 2.0 + _BASE_CS)
        g_arr[t] = gross
        c_base[t] = cost
        if rebal:
            trs_base.append({"exit_date": str(dates[t]), "exit_reason": "daily_rebalance",
                             "gross_bps": round(gross, 9), "cost_bps": round(cost, 9),
                             "net_bps": round(gross - cost, 9)})
        prev = pos[t].copy()
    out: dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]] = {}
    turnover = np.abs(np.diff(pos, axis=0, prepend=0)).sum(axis=1)
    for mult in cost_mults:
        c_arr = mult * c_base
        comp = pd.DataFrame({"date": dates, "gross_bps": g_arr, "cost_bps": c_arr,
                             "net_bps": g_arr - c_arr, "turnover": turnover})
        daily = comp[comp["net_bps"] != 0.0].groupby("date", as_index=False).agg(
            gross_bps=("gross_bps", "sum"), cost_bps=("cost_bps", "sum"),
            net_bps=("net_bps", "sum"), turnover=("turnover", "sum"),
        )
        trs = [{"exit_date": t["exit_date"], "exit_reason": "daily_rebalance",
                "gross_bps": t["gross_bps"], "cost_bps": round(t["cost_bps"] * mult, 9),
                "net_bps": round(t["gross_bps"] - t["cost_bps"] * mult, 9)} for t in trs_base]
        out[mult] = (daily, trs, {"leg_pnl_bps": dict(leg_pnl)})
    return out

# ======================================================================================
# Cointegration (Kalman hedge) + composition-archetype signals
# ======================================================================================
def _kalman_hedge(d_syn: InstrumentData, d_leg: InstrumentData,
                  idx_syn: np.ndarray, idx_leg: np.ndarray, n: int) -> np.ndarray:
    """Causal Kalman filter of the log-price hedge ratio beta (state: beta_t)."""

    n = len(idx_syn)
    good_s = (idx_syn >= 0) & (idx_syn < d_syn.n)
    good_l = (idx_leg >= 0) & (idx_leg < d_leg.n)
    obs_s = np.zeros(n, dtype=bool)
    obs_l = np.zeros(n, dtype=bool)
    obs_s[good_s] = d_syn.obs[idx_syn[good_s]]
    obs_l[good_l] = d_leg.obs[idx_leg[good_l]]
    ok = good_s & good_l & obs_s & obs_l
    ln_s = np.full(n, np.nan)
    ln_l = np.full(n, np.nan)
    mid_s = (d_syn.bc[idx_syn[good_s]] + d_syn.ac[idx_syn[good_s]]) / 2.0
    mid_l = (d_leg.bc[idx_leg[good_l]] + d_leg.ac[idx_leg[good_l]]) / 2.0
    ln_s[good_s] = np.log(mid_s)
    ln_l[good_l] = np.log(mid_l)
    y = np.full(n, np.nan)
    y[ok] = ln_s[ok] - ln_l[ok]
    beta = np.full(n, 1.0)
    Q = 1e-10
    R = (3e-4) ** 2
    b = 1.0
    started = False
    for i in range(n):
        if not np.isfinite(y[i]):
            beta[i] = b
            continue
        if not started:
            b, started = y[i], True
            beta[i] = b
            continue
        bp = b + Q
        innov = y[i] - b
        S = bp + R
        K = bp / S
        b = b + K * innov
        beta[i] = b
    return beta


_KALMAN_HEDGE_CACHE: dict[tuple[str, str, int], np.ndarray] = {}


def _kalman_hedge_cached(ctx: PanelContext, syn: str, leg: str) -> np.ndarray:
    key = (syn, leg, len(ctx.grid_ts))
    if key not in _KALMAN_HEDGE_CACHE:
        _KALMAN_HEDGE_CACHE[key] = _kalman_hedge(
            ctx.datas[syn], ctx.datas[leg], ctx.leg_idx[syn], ctx.leg_idx[leg],
            len(ctx.grid_ts))
    return _KALMAN_HEDGE_CACHE[key]


def _log_spread_grid(ctx: PanelContext, syn: str, leg: str) -> np.ndarray:
    """ln(mid_syn) - ln(mid_leg) on the panel grid, NaN where either leg is unavailable."""

    n = len(ctx.grid_ts)
    good_s = (ctx.leg_idx[syn] >= 0) & (ctx.leg_idx[syn] < ctx.datas[syn].n)
    good_l = (ctx.leg_idx[leg] >= 0) & (ctx.leg_idx[leg] < ctx.datas[leg].n)
    ln_s = np.full(n, np.nan)
    ln_l = np.full(n, np.nan)
    mid_s = (ctx.datas[syn].bc[ctx.leg_idx[syn][good_s]]
             + ctx.datas[syn].ac[ctx.leg_idx[syn][good_s]]) / 2.0
    mid_l = (ctx.datas[leg].bc[ctx.leg_idx[leg][good_l]]
             + ctx.datas[leg].ac[ctx.leg_idx[leg][good_l]]) / 2.0
    ln_s[good_s] = np.log(mid_s)
    ln_l[good_l] = np.log(mid_l)
    y = np.full(n, np.nan)
    y[good_s & good_l] = ln_s[good_s & good_l] - ln_l[good_s & good_l]
    return y


def sig_H_coint(
    ctx: PanelContext, pair: tuple[str, str], p: dict[str, float]
) -> tuple[np.ndarray, int]:
    """pair = (synthetic, leg); trade the Kalman-hedged log-spread z-score reversion."""

    sig_thr = float(p["entry_threshold_sigma"])
    H = int(p["halflife_bars"])
    syn, leg = pair
    beta = _kalman_hedge_cached(ctx, syn, leg)
    y = _log_spread_grid(ctx, syn, leg)
    spread = y - beta
    z = _rolling_zscore_grid(spread, 480)
    okz = np.isfinite(z)
    long_ = okz & (z < -sig_thr)
    short = okz & (z > sig_thr)
    sig = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    return sig, _clamp_holding(HorizonClass.H2_INTRAWEEK, H * 1440)


def _coint_state_ok(ctx: PanelContext, tri: str) -> np.ndarray:
    """Cointegration-state eligibility (frozen FILTER role of M_TRIANGLE): the
    Kalman-hedged log-spread of (synthetic, leg) is in a tight state, i.e.
    |spread| < 0.5 x its rolling 480-bar std (the hedge is currently working)."""

    a, _b, c = tri.split("|")
    y = _log_spread_grid(ctx, c, a)
    beta = _kalman_hedge_cached(ctx, c, a)
    spread = y - beta
    sd = pd.Series(spread).rolling(480, min_periods=120).std().to_numpy()
    with np.errstate(invalid="ignore"):
        return np.isfinite(spread) & np.isfinite(sd) & (sd > 1e-12) & (np.abs(spread) < 0.5 * sd)


def _regime_moderate(d: InstrumentData) -> np.ndarray:
    rv = d.feat["realized_vol"]
    s = pd.Series(rv)
    q25 = s.rolling(480, min_periods=60).quantile(0.25).to_numpy()
    q75 = s.rolling(480, min_periods=60).quantile(0.75).to_numpy()
    return np.isfinite(rv) & np.isfinite(q25) & np.isfinite(q75) & (rv >= q25) & (rv <= q75)


def _cost_gate(d: InstrumentData, direction: np.ndarray, holding: int) -> np.ndarray:
    mz = d.feat["mom_z_60"]
    rv = d.feat["realized_vol"]
    spread = d.feat["spread"]
    mid = d.feat["mid"]
    ok = _nan_free(mz, rv, spread, mid) & (mid > 0)
    edge = np.abs(mz) * rv * holding * 10_000.0
    cost = (spread / mid * 10_000.0) + 2.0 * _BASE_CS
    return ok & (edge >= 1.0 * cost)


def _daily_low_spread_gate(ctx: PanelContext, dates: np.ndarray) -> np.ndarray:
    """(n_days, n_inst) boolean: the pair's daily spread is below its rolling 60-day
    median (frozen GATE role: cost-gated sparse entry, daily analogue)."""

    n = len(dates)
    out = np.zeros((n, len(ctx.datas)), dtype=bool)
    for j, inst in enumerate(ctx.datas):
        sp = ctx.daily_spread[inst]
        med = pd.Series(sp).rolling(60, min_periods=20).median().to_numpy()
        out[:, j] = np.isfinite(sp) & np.isfinite(med) & (sp < med)
    return out


def _factor_state_filter(ctx: PanelContext) -> np.ndarray:
    """Boolean mask: Kalman-filtered drift confirms the residual dislocation (opposite
    sign) AND the panel is in a moderate-volatility regime (frozen FILTER/REGIME roles)."""

    drift_ok = np.zeros(len(ctx.grid_ts), dtype=bool)
    for inst, z in ctx.resid_z.items():
        dz = _kalman_drift_z(ctx.datas[inst], 100)
        dz_grid = _map_to_grid(dz, ctx.datas[inst], ctx.grid_ts, ctx.leg_idx[inst])
        drift_ok |= np.isfinite(dz_grid) & ((z < 0) & (dz_grid > 0) | (z > 0) & (dz_grid < 0))
    regime = _regime_moderate(ctx.datas["EURUSD"])
    return drift_ok & regime


def _arch_signal(
    cand: Candidate, d: InstrumentData, ctx: PanelContext | None
) -> tuple[np.ndarray, int]:
    """Composition-archetype signal for one scope unit (self instrument or panel)."""

    assert cand.archetype_id is not None
    arch = ARCHETYPE_INDEX[cand.archetype_id]
    p = cand.params
    if arch.archetype_id == "M_TREND_PULLBACK_VOLREGIME_SPREADGATE":
        sig, holding = sig_B_pullback(d, p)
        regime = _regime_moderate(d)
        gate = d.feat["spread_z"] < 0.0
        sig = np.where(regime & gate & np.isfinite(d.feat["spread_z"]), sig, 0).astype(np.int8)
    elif arch.archetype_id == "M_COMPRESSION_BREAKOUT_REGIME":
        sig, holding = sig_A(d, p)
        regime = _regime_moderate(d)
        rc = d.feat["range_compression"]
        med = _vol_median(d)
        filt = (rc < 0.5 * med) & np.isfinite(rc) & np.isfinite(med)
        sig = np.where(regime & filt, sig, 0).astype(np.int8)
    elif arch.archetype_id == "M_LIQSHOCK_SESSION_REVERSION_COSTGATE":
        sig, holding = sig_C_zscore(d, p)
        open_win = _session_open_window(d.ny_min)
        gate = _cost_gate(d, sig, holding)
        sig = np.where(open_win & gate, sig, 0).astype(np.int8)
    elif arch.archetype_id == "M_FACTOR_RESIDUAL_STATEFILTER_VOLNORM":
        assert ctx is not None
        sig, _pos, holding = sig_G_factor(ctx, p)
        sig = np.where(_factor_state_filter(ctx), sig, 0).astype(np.int8)
    elif arch.archetype_id == "M_TRIANGLE_COINTEGRATION_VOLNORM":
        assert ctx is not None
        tri = "|".join(REGISTERED_TRIANGLES[0])
        sig, holding = sig_H_triangle(ctx, tri, p)
        coint_ok = _coint_state_ok(ctx, tri)
        regime = _regime_moderate(ctx.datas["EURUSD"])
        sig = np.where(coint_ok & regime, sig, 0).astype(np.int8)
    else:  # pragma: no cover - closed grammar
        raise ValueError(f"unknown archetype {arch.archetype_id}")
    return sig, holding


def _xsmom_signal(cand: Candidate, ctx: PanelContext) -> tuple[np.ndarray, np.ndarray, int]:
    """M_XSMOM daily-portfolio signal: (pos[n_days, n_inst], dates, holding)."""

    p = cand.params
    pos, dates, _ = sig_G_xsmom(ctx, p)
    # FILTER: a fresh causal change-point within the last 5 days (any panel leg);
    # a shift on day k marks days k..k+5 (causal: no future information)
    day_shift = np.zeros(len(dates), dtype=bool)
    for inst in ctx.datas:
        d = ctx.datas[inst]
        r_grid = np.full(d.n, np.nan)
        if len(d.o_ret):
            r_grid[d.o_idx[1:]] = d.o_ret
        s = pd.Series(r_grid)
        mu = s.rolling(60).mean().to_numpy()
        sd = s.rolling(60).std().to_numpy()
        with np.errstate(invalid="ignore"):
            shift = (np.isfinite(mu) & np.isfinite(sd) & (sd > 1e-12)
                     & np.isfinite(r_grid) & (np.abs(r_grid) > 2.0 * sd))
        day_of = np.searchsorted(dates, d.ny_date, side="right") - 1
        valid = shift & (day_of >= 0) & (day_of < len(dates))
        day_shift[day_of[valid]] = True
    recent = (pd.Series(day_shift.astype(np.int8)).rolling(6, min_periods=1).max()
              .to_numpy() > 0)
    gate = _daily_low_spread_gate(ctx, dates)
    pos = np.where(np.tile(recent[:, None], (1, len(ctx.datas))) & gate, pos, 0).astype(np.int8)
    return pos, dates, 1


# ======================================================================================
# Per-candidate evaluation (one immutable accounting row per candidate)
# ======================================================================================
@dataclass
class EvalEnv:
    data: dict[str, InstrumentData]
    panel: PanelContext | None
    primary_dates: set
    unresolved_gap: dict[str, list[str]]
    freeze_hash: str
    data_digest: str
    registry_hash: str


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "gross_bps", "cost_bps", "net_bps", "turnover"])


def _daily_to_series(daily: pd.DataFrame) -> tuple[list[str], list[float]]:
    if daily is None or daily.empty:
        return [], []
    return (list(daily["date"]), [round(float(x), 9) for x in daily["net_bps"]])


def _metrics(dates: list[str], nets: list[float], trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not nets:
        return {"trade_count": len(trades), "active_days": 0, "gross_bps": 0.0, "cost_bps": 0.0,
                "net_bps": 0.0, "net_bps_per_trade": 0.0, "daily_sharpe": 0.0,
                "max_drawdown_bps": 0.0, "hit_rate": 0.0, "turnover": 0.0}
    arr = np.array(nets, dtype=float)
    n = len(arr)
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(arr.mean() / std * math.sqrt(252.0)) if std > 0 else 0.0
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = float(np.max(peak - cum)) if n else 0.0
    hit = float(np.mean([t["net_bps"] > 0 for t in trades])) if trades else 0.0
    net = float(arr.sum())
    return {"trade_count": len(trades), "active_days": n, "net_bps": net,
            "net_bps_per_trade": net / len(trades) if trades else 0.0,
            "daily_sharpe": sharpe, "max_drawdown_bps": dd, "hit_rate": hit,
            "turnover": 0.0}


def _walk_forward_folds(dates: list[str], nets: list[float]) -> dict[str, Any]:
    if not dates:
        return {"folds": [], "positive_fold_fraction": 0.0, "n_folds": 0}
    d = pd.DataFrame({"date": pd.to_datetime(dates), "net_bps": nets}).sort_values("date")
    start = d["date"].iloc[0]
    last = d["date"].iloc[-1]
    train_end = start + pd.Timedelta(days=365)
    folds: list[dict[str, Any]] = []
    k = 0
    while True:
        test_start = train_end + pd.Timedelta(days=91 * k)
        test_end = test_start + pd.Timedelta(days=91)
        if test_start >= last:
            break
        mask = (d["date"] >= test_start) & (d["date"] < test_end)
        if mask.any():
            net = float(d.loc[mask, "net_bps"].sum())
            folds.append({"fold": k, "start": str(test_start.date()), "net_bps": round(net, 6),
                          "days": int(mask.sum())})
        k += 1
    positive = sum(1 for f in folds if f["net_bps"] > 0)
    frac = round(positive / len(folds), 6) if folds else 0.0
    return {"folds": folds, "positive_fold_fraction": frac, "n_folds": len(folds)}


def _year_breakdown(dates: list[str], nets: list[float]) -> dict[str, Any]:
    if not dates:
        return {"per_year_net_bps": {}, "year_loo_positive": False}
    d = pd.DataFrame({"date": dates, "net_bps": nets})
    d["year"] = d["date"].str.slice(0, 4)
    per_year = {y: round(float(g["net_bps"].sum()), 6) for y, g in d.groupby("year")}
    years = [str(y) for y in (2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017)]
    loo_ok = True
    for left_out in years:
        rest = sum(per_year.get(y, 0.0) for y in years if y != left_out)
        if not rest > 0:
            loo_ok = False
    return {"per_year_net_bps": per_year, "year_loo_positive": bool(loo_ok)}


def _psr_dsr(dates: list[str], nets: list[float], denom: int) -> tuple[float, float]:
    if len(nets) < 30:
        return 0.0, 0.0
    arr = np.array(nets, dtype=float)
    std = float(arr.std(ddof=1))
    if std <= 0:
        return 0.0, 0.0
    sharpe = float(arr.mean() / std * math.sqrt(252.0))
    skew, kurt = _sample_moments(arr)
    return (round(psr(sharpe, len(arr), skew, kurt), 9),
            round(dsr(sharpe, len(arr), skew, kurt, denom), 9))


def _failure_row(cand: Candidate, exc: BaseException, t0: float) -> dict[str, Any]:
    return {
        "candidate_id": cand.candidate_id, "universe": cand.universe,
        "family_id": cand.family_id, "domain": cand.domain, "horizon": cand.horizon,
        "scope": cand.scope, "archetype_id": cand.archetype_id, "param_hash": cand.param_hash,
        "params": {k: float(v) for k, v in cand.params.items()}, "executable": cand.executable,
        "terminal_state": EVALUATION_FAILURE, "error": f"{type(exc).__name__}: {exc}",
        "trade_count": 0, "active_days": 0, "gross_bps": 0.0, "cost_bps": 0.0,
        "net_bps": 0.0, "net_bps_per_trade": 0.0, "daily_sharpe": 0.0,
        "max_drawdown_bps": 0.0, "hit_rate": 0.0, "turnover": 0.0,
        "net_bps_1_5x": 0.0, "net_bps_2_0x": 0.0, "survives_1_5x": False, "survives_2_0x": False,
        "psr": 0.0, "dsr": 0.0, "fold_positive_fraction": 0.0, "n_folds": 0, "folds": [],
        "per_year_net_bps": {}, "year_loo_positive": False, "loo_contrib": {},
        "data_availability": {}, "eval_seconds": round(time.time() - t0, 3),
        "daily_dates_primary": [], "daily_net_bps_primary": [],
    }


def _primary(daily: pd.DataFrame, primary_dates: set) -> tuple[list[str], list[float]]:
    dates, nets = _daily_to_series(daily)
    return ([dt for dt, nt in zip(dates, nets, strict=True) if dt in primary_dates],
            [nt for dt, nt in zip(dates, nets, strict=True) if dt in primary_dates])


def _eval_standalone(cand: Candidate, env: EvalEnv):
    fam = FAMILY_INDEX[cand.family_id]
    if fam.instrument_scope == "self":
        return _eval_standalone_self(cand, env)
    if fam.instrument_scope == "panel":
        return _eval_standalone_panel(cand, env)
    if fam.instrument_scope == "triangle":
        return _eval_standalone_triangle(cand, env)
    raise ValueError(f"unknown scope {fam.instrument_scope}")


def _eval_standalone_self(cand: Candidate, env: EvalEnv):
    d = env.data[cand.scope]
    sig, holding = _family_signal(cand, d, None)
    lo, hi = compact_window(sig, holding)
    res = simulate_v3(d, sig, holding, COST_MULTS, lo, hi)
    d1, tr, diag = res[1.0]
    d15, _, _ = res[1.5]
    d20, _, _ = res[2.0]
    loo = {cand.scope: float(sum(_daily_to_series(d1)[1]))}
    return d1, d15, d20, tr, diag, loo, holding


def _eval_standalone_panel(cand: Candidate, env: EvalEnv):
    if cand.family_id == "V3_G_USD_FACTOR_RESIDUAL_REVERSION":
        return _eval_panel_gfactor(cand, env)
    if cand.family_id == "V3_G_CROSS_SECTIONAL_MOMENTUM":
        return _eval_panel_gxsmom(cand, env)
    if cand.family_id == "V3_H_COINTEGRATION_KALMAN_HEDGE":
        return _eval_panel_hcoint(cand, env)
    raise ValueError(f"unknown panel family {cand.family_id}")


def _eval_panel_gfactor(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    sig, pos, holding = sig_G_factor(ctx, cand.params)
    d1 = d15 = d20 = None
    tr: list[dict[str, Any]] = []
    diag: dict[str, Any] = {}
    loo: dict[str, float] = {}
    for inst in ctx.datas:
        si = _signal_to_instrument_grid(pos[inst], ctx, inst)
        if not si.any():
            loo[inst] = 0.0
            continue
        dd = env.data[inst]
        lo, hi = compact_window(si, holding)
        r = simulate_v3(dd, si, holding, COST_MULTS, lo, hi)
        a1, t1, g1 = r[1.0]
        a15, _, _ = r[1.5]
        a20, _, _ = r[2.0]
        d1 = a1 if d1 is None else _add_daily(d1, a1)
        d15 = a15 if d15 is None else _add_daily(d15, a15)
        d20 = a20 if d20 is None else _add_daily(d20, a20)
        tr = tr + t1
        loo[inst] = float(sum(_daily_to_series(a1)[1]))
        if not diag:
            diag = dict(g1)
    if d1 is None:
        d1 = d15 = d20 = _empty_daily()
    return d1, d15, d20, tr, diag, loo, holding


def _eval_panel_gxsmom(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    pos, dates, _ = sig_G_xsmom(ctx, cand.params)
    res = simulate_daily_portfolio(ctx, pos, dates, COST_MULTS)
    d1, tr, diag = res[1.0]
    d15, _, _ = res[1.5]
    d20, _, _ = res[2.0]
    loo = {inst: float(v) for inst, v in diag.get("leg_pnl_bps", {}).items()}
    return d1, d15, d20, tr, diag, loo, 1


def _eval_panel_hcoint(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    p = cand.params
    d1 = d15 = d20 = None
    tr: list[dict[str, Any]] = []
    diag: dict[str, Any] = {}
    loo: dict[str, float] = {}
    pairs = [(t[2], t[0]) for t in REGISTERED_TRIANGLES]
    for syn, leg in pairs:
        sig, holding = sig_H_coint(ctx, (syn, leg), p)
        if not sig.any():
            loo[syn] = 0.0
            loo[leg] = 0.0
            continue
        r = simulate_triangle_pair(ctx, (syn, leg), sig, holding, COST_MULTS)
        a1, t1, g1 = r[1.0]
        a15, _, _ = r[1.5]
        a20, _, _ = r[2.0]
        d1 = a1 if d1 is None else _add_daily(d1, a1)
        d15 = a15 if d15 is None else _add_daily(d15, a15)
        d20 = a20 if d20 is None else _add_daily(d20, a20)
        tr = tr + t1
        lp: dict[str, Any] = g1.get("leg_pnl_bps", {})
        loo[syn] = loo.get(syn, 0.0) + float(lp.get(syn, 0.0))
        loo[leg] = loo.get(leg, 0.0) + float(lp.get(leg, 0.0))
        if not diag:
            diag = {k: v for k, v in g1.items() if k != "leg_pnl_bps"}
    if d1 is None:
        d1 = d15 = d20 = _empty_daily()
    return d1, d15, d20, tr, diag, loo, 1


def _eval_standalone_triangle(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    p = cand.params
    tri = cand.scope
    sig, holding = sig_H_triangle(ctx, tri, p)
    res = simulate_triangle(ctx, tri, sig, holding, COST_MULTS)
    d1, tr, diag = res[1.0]
    d15, _, _ = res[1.5]
    d20, _, _ = res[2.0]
    loo = {leg: float(v) for leg, v in diag.get("leg_pnl_bps", {}).items()}
    return d1, d15, d20, tr, diag, loo, holding


def _add_daily(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    m = pd.merge(a, b, on="date", how="outer", suffixes=("_a", "_b")).fillna(0.0)
    out = pd.DataFrame({"date": m["date"]})
    for col in ("gross_bps", "cost_bps", "net_bps", "turnover"):
        out[col] = m[f"{col}_a"] + m[f"{col}_b"]
    return out[out["net_bps"] != 0.0]


def _family_signal(
    cand: Candidate, d: InstrumentData, ctx: PanelContext | None
) -> tuple[np.ndarray, int]:
    fid = cand.family_id
    p = cand.params
    if fid == "V3_A_DONCHIAN_BREAKOUT_POST_COMPRESSION":
        return sig_A(d, p)
    if fid == "V3_B_MULTISCALE_TSMOM_VOLSCALED":
        return sig_B_tsmom(d, p)
    if fid == "V3_B_TREND_PULLBACK_ENTRY":
        return sig_B_pullback(d, p)
    if fid == "V3_C_ZSCORE_OVERSHOOT_REVERSION":
        return sig_C_zscore(d, p)
    if fid == "V3_C_OU_HALFLIFE_REVERSION":
        return sig_C_ou(d, p)
    if fid == "V3_D_COMPRESSION_EXPANSION_BREAK":
        return sig_D(d, p)
    if fid == "V3_E_SPREAD_STATE_GATED_REVERSAL":
        return sig_E(d, p)
    if fid == "V3_F_SESSION_OPEN_CONDITIONED_MOMENTUM":
        return sig_F(d, p)
    if fid == "V3_I_KALMAN_STATE_TREND":
        return sig_I_kalman(d, p)
    if fid == "V3_I_CHANGEPOINT_REGIME_SHIFT":
        return sig_I_changepoint(d, p)
    if fid == "V3_K_COST_GATED_SPARSE_ENTRY":
        return sig_K(d, p)
    if fid == "V3_L_META_LABEL_TRADE_FILTER":
        ts_ = d.feat["trend_slope_120"]
        sig_thr = float(p["entry_threshold_sigma"])
        base = np.where((ts_ > sig_thr) | (ts_ < -sig_thr), np.sign(ts_), 0).astype(np.int8)
        base[~d.obs] = 0
        holding = _clamp_holding(HorizonClass.H1_SESSION_DAILY, 120)
        res = simulate_v3(d, base, holding, cost_mults=(1.0,))
        _, trades, _ = res[1.0]
        return sig_L(d, p, base, res[1.0][0])
    raise ValueError(f"unknown self family {fid}")


def _eval_archetype(cand: Candidate, env: EvalEnv):
    scope = cand.scope
    if scope == "SELF3":
        return _eval_archetype_self(cand, env)
    if scope == "PANEL":
        return _eval_archetype_panel(cand, env)
    if scope == "TRIANGLES":
        return _eval_archetype_triangles(cand, env)
    raise ValueError(f"unknown archetype scope {scope}")


def _eval_archetype_self(cand: Candidate, env: EvalEnv):
    d1 = d15 = d20 = None
    tr: list[dict[str, Any]] = []
    diag: dict[str, Any] = {}
    loo: dict[str, float] = {}
    n_units = 0
    for inst in REGISTERED_SELF_INSTRUMENTS:
        d = env.data[inst]
        sig, holding = _arch_signal(cand, d, env.panel)
        lo, hi = compact_window(sig, holding)
        res = simulate_v3(d, sig, holding, COST_MULTS, lo, hi)
        a1, t1, g1 = res[1.0]
        a15, _, _ = res[1.5]
        a20, _, _ = res[2.0]
        d1 = a1 if d1 is None else _add_daily(d1, a1)
        d15 = a15 if d15 is None else _add_daily(d15, a15)
        d20 = a20 if d20 is None else _add_daily(d20, a20)
        tr = tr + t1
        loo[inst] = float(sum(_daily_to_series(a1)[1]))
        if not diag:
            diag = dict(g1)
        n_units += 1
    if d1 is None:
        d1 = d15 = d20 = _empty_daily()
    else:
        d1 = _scale_daily(d1, 1.0 / n_units)
        d15 = _scale_daily(d15, 1.0 / n_units)
        d20 = _scale_daily(d20, 1.0 / n_units)
    return d1, d15, d20, tr, diag, loo, 1


def _eval_archetype_panel(cand: Candidate, env: EvalEnv):
    if cand.archetype_id == "M_FACTOR_RESIDUAL_STATEFILTER_VOLNORM":
        return _eval_arch_panel_mfactor(cand, env)
    if cand.archetype_id == "M_XSMOM_CHANGEPOINT_COSTGATE":
        return _eval_arch_panel_mxsmom(cand, env)
    raise ValueError(f"archetype {cand.archetype_id} not panel-evaluable")


def _eval_arch_panel_mfactor(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    _sig, pos, holding = sig_G_factor(ctx, cand.params)
    filt = _factor_state_filter(ctx)
    for inst in ctx.datas:
        pos[inst] = np.where(filt, pos[inst], 0).astype(np.int8)
    d1 = d15 = d20 = None
    tr: list[dict[str, Any]] = []
    diag: dict[str, Any] = {}
    loo: dict[str, float] = {}
    for inst in ctx.datas:
        si = _signal_to_instrument_grid(pos[inst], ctx, inst)
        if not si.any():
            loo[inst] = 0.0
            continue
        dd = env.data[inst]
        lo, hi = compact_window(si, holding)
        r = simulate_v3(dd, si, holding, COST_MULTS, lo, hi)
        a1, t1, g1 = r[1.0]
        a15, _, _ = r[1.5]
        a20, _, _ = r[2.0]
        d1 = a1 if d1 is None else _add_daily(d1, a1)
        d15 = a15 if d15 is None else _add_daily(d15, a15)
        d20 = a20 if d20 is None else _add_daily(d20, a20)
        tr = tr + t1
        loo[inst] = float(sum(_daily_to_series(a1)[1]))
        if not diag:
            diag = dict(g1)
    if d1 is None:
        d1 = d15 = d20 = _empty_daily()
    return d1, d15, d20, tr, diag, loo, holding


def _eval_arch_panel_mxsmom(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    pos, dates, _ = _xsmom_signal(cand, ctx)
    res = simulate_daily_portfolio(ctx, pos, dates, COST_MULTS)
    d1, tr, diag = res[1.0]
    d15, _, _ = res[1.5]
    d20, _, _ = res[2.0]
    loo = {inst: float(v) for inst, v in diag.get("leg_pnl_bps", {}).items()}
    return d1, d15, d20, tr, diag, loo, 1


def _eval_archetype_triangles(cand: Candidate, env: EvalEnv):
    assert env.panel is not None
    ctx = env.panel
    d1 = d15 = d20 = None
    tr: list[dict[str, Any]] = []
    diag: dict[str, Any] = {}
    loo: dict[str, float] = {}
    n_units = 0
    regime = _regime_moderate(ctx.datas["EURUSD"])
    for tri in ("|".join(t) for t in REGISTERED_TRIANGLES):
        sig, holding = sig_H_triangle(ctx, tri, cand.params)
        coint_ok = _coint_state_ok(ctx, tri)
        sig_t = np.where(coint_ok & regime & np.isfinite(ctx.tri_resid_z[tri]),
                         sig, 0).astype(np.int8)
        r = simulate_triangle(ctx, tri, sig_t, holding, COST_MULTS)
        a1, t1, g1 = r[1.0]
        a15, _, _ = r[1.5]
        a20, _, _ = r[2.0]
        d1 = a1 if d1 is None else _add_daily(d1, a1)
        d15 = a15 if d15 is None else _add_daily(d15, a15)
        d20 = a20 if d20 is None else _add_daily(d20, a20)
        tr = tr + t1
        lp: dict[str, Any] = g1.get("leg_pnl_bps", {})
        for leg, v in lp.items():
            loo[leg] = loo.get(leg, 0.0) + float(v)
        if not diag:
            diag = {k: v for k, v in g1.items() if k != "leg_pnl_bps"}
        n_units += 1
    if d1 is None:
        d1 = d15 = d20 = _empty_daily()
    else:
        d1 = _scale_daily(d1, 1.0 / n_units)
        d15 = _scale_daily(d15, 1.0 / n_units)
        d20 = _scale_daily(d20, 1.0 / n_units)
    return d1, d15, d20, tr, diag, loo, 1


def _scale_daily(daily: pd.DataFrame, k: float) -> pd.DataFrame:
    out = daily.copy()
    for col in ("gross_bps", "cost_bps", "net_bps", "turnover"):
        out[col] = out[col] * k
    return out


def evaluate_candidate(cand: Candidate, env: EvalEnv) -> dict[str, Any]:
    t0 = time.time()
    try:
        if cand.archetype_id is not None:
            d1, d15, d20, tr, diag, loo, holding = _eval_archetype(cand, env)
        else:
            d1, d15, d20, tr, diag, loo, holding = _eval_standalone(cand, env)
        dates_p, nets_p = _primary(d1, env.primary_dates)
        nets_15 = _primary(d15, env.primary_dates)[1]
        nets_20 = _primary(d20, env.primary_dates)[1]
        tr_p = [t for t in tr if str(t.get("exit_date", "")) in env.primary_dates]
        m = _metrics(dates_p, nets_p, tr_p)
        folds = _walk_forward_folds(dates_p, nets_p)
        years = _year_breakdown(*_daily_to_series(d1))
        psr_v, dsr_v = _psr_dsr(dates_p, nets_p, 992)
        state = EVALUATED if m["trade_count"] > 0 else EVALUATED_ZERO_TRADES
        row = {
            "candidate_id": cand.candidate_id, "universe": cand.universe,
            "family_id": cand.family_id, "domain": cand.domain, "horizon": cand.horizon,
            "scope": cand.scope, "archetype_id": cand.archetype_id,
            "param_hash": cand.param_hash,
            "params": {k: float(v) for k, v in cand.params.items()},
            "executable": cand.executable, "holding_bars": int(holding),
            "terminal_state": state,
            "trade_count": m["trade_count"], "active_days": m["active_days"],
            "net_bps": round(m["net_bps"], 6),
            "net_bps_per_trade": round(m["net_bps_per_trade"], 6),
            "daily_sharpe": round(m["daily_sharpe"], 6),
            "max_drawdown_bps": round(m["max_drawdown_bps"], 6),
            "hit_rate": round(m["hit_rate"], 6),
            "net_bps_1_5x": round(float(sum(nets_15)), 6),
            "net_bps_2_0x": round(float(sum(nets_20)), 6),
            "survives_1_5x": bool(sum(nets_15) > 0.0),
            "survives_2_0x": bool(sum(nets_20) > 0.0),
            "psr": psr_v, "dsr": dsr_v,
            "fold_positive_fraction": folds["positive_fold_fraction"],
            "n_folds": folds["n_folds"], "folds": folds["folds"],
            "per_year_net_bps": years["per_year_net_bps"],
            "year_loo_positive": years["year_loo_positive"],
            "loo_contrib": {k: round(float(v), 6) for k, v in loo.items()},
            "data_availability": {
                "entry_advances": int(diag.get("entry_advances", 0)),
                "flat_deferred": int(diag.get("flat_deferred", 0)),
                "unresolved_gap_days": _gap_exposure(cand, env),
            },
            "eval_seconds": round(time.time() - t0, 3),
            "daily_dates_primary": dates_p, "daily_net_bps_primary": nets_p,
        }
        return row
    except Exception as exc:  # noqa: BLE001 - failures are terminal states
        return _failure_row(cand, exc, t0)


def _gap_exposure(cand: Candidate, env: EvalEnv) -> list[str]:
    """UNRESOLVED_DATA_GAP days this candidate's scope is exposed to (no fills/features there)."""

    out: set[str] = set()
    scopes: set[str] = set()
    if cand.scope in env.data:
        scopes.add(cand.scope)
    if cand.scope in ("PANEL", "SELF3") or cand.archetype_id in (
            "M_FACTOR_RESIDUAL_STATEFILTER_VOLNORM", "M_XSMOM_CHANGEPOINT_COSTGATE"):
        scopes.update(env.panel.datas.keys() if env.panel else [])
    if "|" in cand.scope:
        scopes.update(cand.scope.split("|"))
    for inst in scopes:
        out.update(env.unresolved_gap.get(inst, []))
    return sorted(out)
# ======================================================================================
# Two-leg cointegration executor (long synthetic / short beta*leg)
# ======================================================================================
def simulate_triangle_pair(
    ctx: PanelContext, pair: tuple[str, str], signal: np.ndarray, holding: int,
    cost_mults: tuple[float, ...] = COST_MULTS,
) -> dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]]:
    """2-leg hedged trade: +1 signal = long synthetic, short 1.0*leg (hedge ratio ~1)."""

    syn, leg = pair
    ds, dl = ctx.datas[syn], ctx.datas[leg]
    ls, ll = ctx.leg_idx[syn], ctx.leg_idx[leg]
    n = len(ctx.grid_ts)
    g_arr = np.zeros(n)
    overlay = np.zeros(n)
    is_exit = np.zeros(n)
    t_arr = np.zeros(n)
    leg_pnl = {syn: 0.0, leg: 0.0}
    trades: list[dict[str, Any]] = []
    diag = {"flat_deferred": 0, "entry_advances": 0}

    def lexec(d: InstrumentData, idx: np.ndarray, i: int) -> bool:
        k = idx[i]
        return bool(0 <= k < d.n and d.exec[k])

    pending = 0
    has_pos = False
    p_side = 0
    p_idx = 0
    p_entries: dict[str, float] = {}
    dir_map = {syn: 1, leg: -1}

    for i in range(n):
        k_s = ls[i]
        m = int(ds.ny_min[k_s]) if 0 <= k_s < ds.n else -1
        all_exec = lexec(ds, ls, i) and lexec(dl, ll, i)
        turn = 0.0
        if has_pos and all_exec:
            flat = _FLAT_LO <= m < _FLAT_HI
            if flat or (i - p_idx) >= holding:
                reason = "mandatory_flat" if flat else "horizon"
                gross = 0.0
                ov = 0.0
                for lg, d, idx in ((syn, ds, ls), (leg, dl, ll)):
                    side = dir_map[lg] * p_side
                    k = idx[i]
                    exit_price = float(d.bo[k] if side > 0 else d.ao[k])
                    r = _ret_bps(side, p_entries[lg], exit_price)
                    gross += r
                    ov += _spread_bps(float(d.ac[k]), float(d.bc[k]))
                    leg_pnl[lg] += r
                g_arr[i] += gross
                overlay[i] += ov / 2.0
                is_exit[i] += 2.0
                t_arr[i] += 4.0
                trades.append({"exit_date": str(ctx.grid_ny_date[i]), "exit_reason": reason,
                               "_gross": gross, "_ov": ov})
                has_pos = False
        pending_persists = False
        if (not has_pos) and pending:
            if all_exec:
                if not (_NO_ENTRY_LO <= m < _NO_ENTRY_HI):
                    p_side = int(pending)
                    p_idx = i
                    p_entries = {}
                    for lg, d, idx in ((syn, ds, ls), (leg, dl, ll)):
                        side = dir_map[lg] * p_side
                        k = idx[i]
                        p_entries[lg] = float(d.ao[k] if side > 0 else d.bo[k])
                    has_pos = True
                    turn += 2.0
            else:
                diag["entry_advances"] += 1
                pending_persists = True
        t_arr[i] += turn
        if not pending_persists:
            pending = int(signal[i])

    out: dict[float, tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]] = {}
    for mult in cost_mults:
        c_arr = np.maximum(mult - 1.0, 0.0) * overlay + is_exit * (mult * _BASE_CS * 2.0)
        comp = pd.DataFrame({"date": ctx.grid_ny_date[:n], "gross_bps": g_arr,
                             "cost_bps": c_arr, "net_bps": g_arr - c_arr, "turnover": t_arr})
        trs = []
        for t in trades:
            cost = max(mult - 1.0, 0.0) * t["_ov"] / 2.0 + mult * _BASE_CS * 2.0 * 2
            trs.append({"exit_date": t["exit_date"], "exit_reason": t["exit_reason"],
                        "gross_bps": round(t["_gross"], 9),
                        "cost_bps": round(cost, 9), "net_bps": round(t["_gross"] - cost, 9)})
        daily = comp[comp["net_bps"] != 0.0].groupby("date", as_index=False).agg(
            gross_bps=("gross_bps", "sum"), cost_bps=("cost_bps", "sum"),
            net_bps=("net_bps", "sum"), turnover=("turnover", "sum"),
        )
        out[mult] = (daily, trs, {"leg_pnl_bps": dict(leg_pnl), **diag})
    return out


# ======================================================================================
# Aggregation: instrument/leg LOO + parameter neighbourhood
# ======================================================================================
def loo_fractions(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Fraction of scope units whose removal leaves the rest positive (frozen >= 0.60)."""

    groups: dict[tuple, dict[str, float]] = {}
    for r in rows:
        key = (r["family_id"], r["scope"], r["archetype_id"], r["param_hash"])
        groups.setdefault(key, {}).update(r["loo_contrib"])
    out: dict[str, float] = {}
    for r in rows:
        key = (r["family_id"], r["scope"], r["archetype_id"], r["param_hash"])
        contrib = groups[key]
        units = list(contrib)
        if not units:
            out[r["candidate_id"]] = 0.0
            continue
        ok = 0
        for u in units:
            rest = sum(v for k, v in contrib.items() if k != u)
            if rest > 0.0:
                ok += 1
        out[r["candidate_id"]] = round(ok / len(units), 6)
    return out


def neighborhood_fractions(
    rows: list[dict[str, Any]], cands: dict[str, Candidate]
) -> dict[str, float]:
    """Fraction of one-step parameter neighbours with the same sign of net P&L."""

    by_group: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        key = (r["family_id"], r["scope"], r["archetype_id"])
        by_group.setdefault(key, []).append(r)
    out: dict[str, float] = {}
    for grp in by_group.values():
        axes = {r["candidate_id"]: cands[r["candidate_id"]].axis_tuple() for r in grp}
        for r in grp:
            focal = axes[r["candidate_id"]]
            focal_net = float(r["net_bps"])
            neigh: list[float] = []
            for o in grp:
                if o["candidate_id"] == r["candidate_id"]:
                    continue
                oa = axes[o["candidate_id"]]
                if len(oa) != len(focal):
                    continue
                diffs = sum(1 for x, y in zip(focal, oa, strict=True) if x != y)
                if diffs == 1:
                    neigh.append(float(o["net_bps"]))
            if not neigh:
                out[r["candidate_id"]] = 0.0
            else:
                same = sum(1 for v in neigh if (v > 0) == (focal_net > 0))
                out[r["candidate_id"]] = round(same / len(neigh), 6)
    return out


# ======================================================================================
# Frozen statistics (universe A only; hierarchical error control at alpha_V3)
# ======================================================================================
def build_return_matrix(rows: list[dict[str, Any]]) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for r in rows:
        if r["daily_dates_primary"]:
            series[r["candidate_id"]] = pd.Series(
                r["daily_net_bps_primary"], index=r["daily_dates_primary"])
        else:
            series[r["candidate_id"]] = pd.Series(dtype=float)
    matrix = pd.DataFrame(series).sort_index().fillna(0.0)
    for r in rows:
        if r["candidate_id"] not in matrix.columns:
            matrix[r["candidate_id"]] = 0.0
    return matrix[[r["candidate_id"] for r in rows]]


def run_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = build_return_matrix(rows)
    values = matrix.to_numpy(dtype=float)
    n_cand = values.shape[1]
    boot = bootstrap_family_stats(matrix, seed=FROZEN_SEED,
                                  iterations=BOOTSTRAP_ITERATIONS, block_length=BLOCK_LENGTH_DAYS)
    rw_global = boot["romano_wolf_stepdown_p"]
    p_raw = [normal_p_value_from_mean(values[:, j]) for j in range(n_cand)]
    holm = holm_adjust(p_raw)
    bh = bh_fdr(p_raw)
    pbo = pbo_cscv(matrix)

    # family-level gatekeeper (RW within family) + domain-level BH across family p-values
    fam_of = {r["candidate_id"]: r["family_id"] for r in rows}
    dom_of = {r["candidate_id"]: r["domain"] for r in rows}
    fams = sorted(set(fam_of.values()))
    fam_gate_p: dict[str, float] = {}
    rw_family: dict[str, float] = {}
    for fi, fam in enumerate(fams):
        cols = [c for c in matrix.columns if fam_of[c] == fam]
        sub = matrix[cols]
        b = bootstrap_family_stats(sub, seed=FROZEN_SEED + fi + 1,
                                   iterations=BOOTSTRAP_ITERATIONS, block_length=BLOCK_LENGTH_DAYS)
        rwf = b["romano_wolf_stepdown_p"]
        for c, pv in zip(cols, rwf, strict=True):
            rw_family[c] = float(pv)
        fam_gate_p[fam] = min(rwf) if rwf else 1.0
    domains = sorted(set(dom_of.values()))
    domain_pass: dict[str, bool] = {}
    for dom in domains:
        fams_dom = [f for f in fams if FAMILY_INDEX[f].domain == dom]
        ps = [fam_gate_p[f] for f in fams_dom]
        adj = bh_fdr(ps)
        domain_pass[dom] = any(p <= ALPHA_V3 for p in adj)

    per_cand: dict[str, Any] = {}
    significant: dict[str, bool] = {}
    for j, r in enumerate(rows):
        cid = r["candidate_id"]
        fam = fam_of[cid]
        dom = dom_of[cid]
        sig = (
            float(rw_global[j]) <= ALPHA_V3
            and float(rw_family[cid]) <= ALPHA_V3
            and fam_gate_p[fam] <= ALPHA_V3
            and domain_pass[dom]
            and float(holm[j]) <= ALPHA_V3
        )
        significant[cid] = bool(sig)
        per_cand[cid] = {
            "raw_p": round(p_raw[j], 9), "holm_p": round(holm[j], 9),
            "bh_fdr_p": round(bh[j], 9), "rw_global_p": round(float(rw_global[j]), 9),
            "rw_family_p": round(float(rw_family[cid]), 9),
            "family_gate_p": round(fam_gate_p[fam], 9), "domain_pass": domain_pass[dom],
            "significant": bool(sig),
        }
    return {
        "universe": "A", "denominator": n_cand,
        "alpha_program": ALPHA_PROGRAM, "n_program_versions": N_PROGRAM_VERSIONS,
        "alpha_v3": round(ALPHA_V3, 9),
        "white_reality_check_p": boot["white_reality_check_p"],
        "hansen_spa_p": boot["hansen_spa_p"],
        "bootstrap_iterations": boot["bootstrap_iterations"],
        "block_length_days": boot["block_length_days"], "seed": boot["seed"],
        "pbo": pbo,
        "romano_wolf_significant": sum(1 for v in rw_global if float(v) <= ALPHA_V3),
        "holm_significant": sum(1 for v in holm if float(v) <= ALPHA_V3),
        "bh_fdr_significant": sum(1 for v in bh if float(v) <= ALPHA_V3),
        "family_gatekeeper": {f: round(p, 9) for f, p in fam_gate_p.items()},
        "domain_pass": domain_pass,
        "hierarchical_significant_count": sum(significant.values()),
        "per_candidate": per_cand,
    }


# ======================================================================================
# Frozen survivor classification (per-horizon predicates; REVIEW_RANKING != SURVIVOR)
# ======================================================================================
def classify_survivors(rows: list[dict[str, Any]], stats: dict[str, Any],
                       loo_frac: dict[str, float], neigh_frac: dict[str, float],
                       firewall_clean: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    survivors: list[dict[str, Any]] = []
    predicate_rows: list[dict[str, Any]] = []
    pbo = stats["pbo"].get("pbo", "NOT_APPLICABLE")
    for r in rows:
        if r["universe"] != "A":
            continue
        pred = PREDICATES[HorizonClass(r["horizon"])]
        pc = stats["per_candidate"][r["candidate_id"]]
        failed: list[str] = []
        if not (float(r["net_bps"]) > 0.0
                and float(r["net_bps_per_trade"]) >= pred.min_net_bps_per_trade):
            failed.append("net_profitability")
        if not (float(r["dsr"]) >= pred.min_annualized_dsr
                and float(r["dsr"]) > pred.min_deflated_sharpe):
            failed.append("risk_adjusted")
        if int(r["trade_count"]) < pred.min_trades:
            failed.append("sample_sufficiency")
        if not float(r["fold_positive_fraction"]) >= pred.fold_robustness_min_fraction:
            failed.append("fold_robustness")
        loo_v = float(loo_frac.get(r["candidate_id"], 0.0))
        if not loo_v >= pred.instrument_robustness_min_fraction:
            failed.append("instrument_robustness")
        if not float(neigh_frac.get(r["candidate_id"], 0.0)) >= 0.60:
            failed.append("neighborhood_stability")
        if not (bool(r["survives_1_5x"]) and bool(r["survives_2_0x"])):
            failed.append("cost_stress")
        if not pc["significant"]:
            failed.append("multiple_testing")
        if pbo != "NOT_APPLICABLE" and not float(pbo) <= 0.50:
            failed.append("overfitting")
        if not firewall_clean:
            failed.append("data_integrity")
        ok = not failed
        predicate_rows.append({
            "candidate_id": r["candidate_id"], "family_id": r["family_id"],
            "domain": r["domain"], "horizon": r["horizon"], "scope": r["scope"],
            "is_survivor": ok, "failed_requirements": failed,
            "net_bps": r["net_bps"], "daily_sharpe": r["daily_sharpe"],
            "dsr": r["dsr"], "trade_count": r["trade_count"],
        })
        if ok:
            survivors.append({
                "candidate_id": r["candidate_id"], "family_id": r["family_id"],
                "domain": r["domain"], "horizon": r["horizon"], "scope": r["scope"],
                "net_bps": r["net_bps"], "daily_sharpe": r["daily_sharpe"],
                "dsr": r["dsr"], "trade_count": r["trade_count"],
                "rw_global_p": pc["rw_global_p"], "holm_p": pc["holm_p"],
            })
    return survivors, predicate_rows


def review_ranking(rows: list[dict[str, Any]], stats: dict[str, Any]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple[Any, ...]:
        pc = stats["per_candidate"][r["candidate_id"]]
        return (float(pc["bh_fdr_p"]), float(r["net_bps"]) <= 0.0,
                not bool(r["survives_2_0x"]), -float(r["net_bps"]),
                -float(r["daily_sharpe"]), r["candidate_id"])
    ranked = sorted((r for r in rows if r["universe"] == "A"), key=key)
    return [{"rank": i + 1, "candidate_id": r["candidate_id"],
             "family_id": r["family_id"], "domain": r["domain"], "scope": r["scope"],
             "net_bps": round(r["net_bps"], 4), "daily_sharpe": r["daily_sharpe"],
             "trade_count": r["trade_count"], "survives_2_0x": r["survives_2_0x"],
             "bh_fdr_p": stats["per_candidate"][r["candidate_id"]]["bh_fdr_p"]}
            for i, r in enumerate(ranked[:50])]


# ======================================================================================
# Diagnostics (diagnostics only; never selection criteria)
# ======================================================================================
def group_diagnostics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(str(r[key]), []).append(r)
    out: dict[str, Any] = {}
    for g, grp in sorted(by.items()):
        nets = [float(r["net_bps"]) for r in grp]
        valid_states = (EVALUATED, EVALUATED_ZERO_TRADES)
        trade_counts = [r["trade_count"] for r in grp]
        out[g] = {
            "evaluated": len(grp),
            "runtime_valid": sum(1 for r in grp if r["terminal_state"] in valid_states),
            "runtime_failed": sum(1 for r in grp if r["terminal_state"] == EVALUATION_FAILURE),
            "zero_trade": sum(1 for r in grp if r["terminal_state"] == EVALUATED_ZERO_TRADES),
            "positive_raw": sum(1 for r in grp if float(r["net_bps"]) > 0),
            "positive_1_5x": sum(1 for r in grp if bool(r["survives_1_5x"])),
            "positive_2_0x": sum(1 for r in grp if bool(r["survives_2_0x"])),
            "mean_net_bps": round(float(np.mean(nets)), 4) if nets else 0.0,
            "median_net_bps": round(float(np.median(nets)), 4) if nets else 0.0,
            "best_net_bps": round(float(np.max(nets)), 4) if nets else 0.0,
            "mean_trade_count": round(float(np.mean(trade_counts)), 1) if trade_counts else 0.0,
        }
    return out


def diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "by_domain": group_diagnostics(rows, "domain"),
        "by_family": group_diagnostics(rows, "family_id"),
        "by_horizon": group_diagnostics(rows, "horizon"),
        "by_scope": group_diagnostics(rows, "scope"),
        "by_archetype": group_diagnostics(
            [r for r in rows if r["archetype_id"]], "archetype_id"),
    }


# ======================================================================================
# Checkpoint / resume (keyed by freeze hash + data digest + registry hash + candidate_id)
# ======================================================================================
class CheckpointStore:
    def __init__(self, root: Path, freeze_hash: str, data_digest: str, registry_hash: str):
        self.root = root
        self.identity = {"freeze_hash": freeze_hash, "data_digest": data_digest,
                         "registry_hash": registry_hash}
        self.dir = root / "checkpoints"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "candidates.jsonl"
        self.meta = self.dir / "identity.json"

    def load_completed(self) -> dict[str, dict[str, Any]]:
        if not self.meta.exists():
            return {}
        meta = json.loads(self.meta.read_text())
        if meta != self.identity:
            raise AssertionError(
                "V3_1_CHECKPOINT: identity mismatch; refusing to mix artifacts from a "
                f"different freeze/data/registry. expected={self.identity} found={meta}")
        out: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                out[row["candidate_id"]] = row
        return out

    def save(self, row: dict[str, Any]) -> None:
        if not self.meta.exists():
            self.meta.write_text(json.dumps(self.identity, indent=1))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _count_state(rows: list[dict[str, Any]], states: tuple[str, ...]) -> int:
    return sum(1 for r in rows if r["terminal_state"] in states)


# ======================================================================================
# Orchestrator
# ======================================================================================
def run_discovery(
    canonical: Path,
    cache_dir: Path,
    ckpt_root: Path,
    freeze_hash: str,
    data_digest: str,
    fw: DiscoveryFirewall,
    workers: int = 4,
) -> dict[str, Any]:
    t_start = time.time()
    cands = materialize_universe()
    a_cands = [c for c in cands if c.universe == "A"]
    b_cands = [c for c in cands if c.universe == "B"]
    if len(a_cands) != 992 or len(b_cands) != 52:
        raise AssertionError(
            f"V3_1_UNIVERSE: materialized A={len(a_cands)} B={len(b_cands)}; expected 992/52")
    reg_hash = registry_hash(cands)
    cand_index = {c.candidate_id: c for c in cands}

    from fx_smc_bot.research.v3.discovery_data import (
        INSTRUMENTS_13,
        SELF_INSTRUMENTS,
        load_instrument,
    )
    data: dict[str, InstrumentData] = {}
    for inst in SELF_INSTRUMENTS:
        data[inst] = load_instrument(canonical, inst, DEVELOPMENT_YEARS, fw,
                                     cache_dir=cache_dir, freeze_hash=freeze_hash,
                                     data_digest=data_digest)
    panel_data: dict[str, InstrumentData] = {}
    for inst in INSTRUMENTS_13:
        if inst not in data:
            data[inst] = load_instrument(canonical, inst, DEVELOPMENT_YEARS, fw,
                                         cache_dir=cache_dir, freeze_hash=freeze_hash,
                                         data_digest=data_digest)
        panel_data[inst] = data[inst]
    panel = build_panel_context(panel_data)

    base = data["EURUSD"]
    primary_dates = {str(x) for x in base.ny_date[base.ny_year <= PRIMARY_YEARS[-1]]}
    unresolved_gap: dict[str, list[str]] = {}
    for inst, d in data.items():
        if "2010-01-01" in d.missing_days:
            unresolved_gap[inst] = ["2010-01-01"]
    env = EvalEnv(data=data, panel=panel, primary_dates=primary_dates,
                  unresolved_gap=unresolved_gap, freeze_hash=freeze_hash,
                  data_digest=data_digest, registry_hash=reg_hash)

    store = CheckpointStore(ckpt_root, freeze_hash, data_digest, reg_hash)
    completed = store.load_completed()
    rows: list[dict[str, Any]] = []
    n_new = 0
    for c in cands:
        if c.candidate_id in completed:
            rows.append(completed[c.candidate_id])
            continue
        row = evaluate_candidate(c, env)
        store.save(row)
        rows.append(row)
        n_new += 1
        if n_new % 25 == 0:
            done = len(rows) - len(completed)
            print(f"  checkpoint: {done} new / {len(cands)} total", flush=True)

    rows.sort(key=lambda r: r["candidate_id"])
    if len(rows) != len(cands):
        raise AssertionError("V3_1_DENOMINATOR: accounting rows != frozen universe size")

    loo_frac = loo_fractions(rows)
    neigh_frac = neighborhood_fractions(rows, cand_index)
    a_rows = [r for r in rows if r["universe"] == "A"]
    b_rows = [r for r in rows if r["universe"] == "B"]
    stats = run_statistics(a_rows)
    firewall_clean = fw.blocked_2018_plus == 0
    survivors, predicate_rows = classify_survivors(rows, stats, loo_frac, neigh_frac,
                                                    firewall_clean)
    ranking = review_ranking(rows, stats)
    diag = diagnostics(rows)
    b_diag = diagnostics(b_rows)

    if survivors:
        verdict = "V3_PRE2018_SCIENTIFIC_SURVIVOR_FOUND_HOLDOUT_READY"
        next_gate = "V3_HOLDOUT_CONFIRMATION (separate explicit authorization; NOT this session)"
    else:
        verdict = "V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR"
        next_gate = "V3_PROGRAM_REVIEW (no 2018+ access; no redesign in this session)"

    result = {
        "artifact_id": "V3_1_DISCOVERY_RUN_V1",
        "program_id": "FX_INTRADAY_ALPHA_DISCOVERY_V3",
        "amendment": "V3_DATA_AVAILABILITY_AMENDMENT_V1",
        "freeze_hash": freeze_hash,
        "global_data_digest": data_digest,
        "candidate_registry_hash": reg_hash,
        "universe_A": {
            "planned": 992, "evaluated": len(a_rows),
            "runtime_valid": _count_state(a_rows, (EVALUATED, EVALUATED_ZERO_TRADES)),
            "runtime_failed": _count_state(a_rows, (EVALUATION_FAILURE,)),
            "zero_trade": _count_state(a_rows, (EVALUATED_ZERO_TRADES,)),
            "positive_raw": sum(1 for r in a_rows if float(r["net_bps"]) > 0),
            "positive_1_5x": sum(1 for r in a_rows if bool(r["survives_1_5x"])),
            "positive_2_0x": sum(1 for r in a_rows if bool(r["survives_2_0x"])),
        },
        "universe_B": {
            "planned": 52, "evaluated": len(b_rows),
            "runtime_valid": _count_state(b_rows, (EVALUATED, EVALUATED_ZERO_TRADES)),
            "runtime_failed": _count_state(b_rows, (EVALUATION_FAILURE,)),
            "zero_trade": _count_state(b_rows, (EVALUATED_ZERO_TRADES,)),
            "positive_raw": sum(1 for r in b_rows if float(r["net_bps"]) > 0),
            "positive_1_5x": sum(1 for r in b_rows if bool(r["survives_1_5x"])),
            "positive_2_0x": sum(1 for r in b_rows if bool(r["survives_2_0x"])),
            "claim_class": "PRICE_ALPHA_ONLY (never an executable scientific survivor)",
        },
        "statistics": stats,
        "survivors": survivors,
        "survivor_predicate_rows": predicate_rows,
        "review_ranking_top50": ranking,
        "diagnostics": diag,
        "diagnostics_B": b_diag,
        "unresolved_data_gap": {
            "units": {k: v for k, v in unresolved_gap.items()},
            "handling": "no fills, no feature updates, no ML examples; cross constructions "
                        "requiring the leg unavailable that day; unrelated instruments usable",
            "exposed_candidates": sum(
                1 for r in rows if r["data_availability"].get("unresolved_gap_days")),
        },
        "lineage": {
            "rule": "V1/V2 candidates are NOT columns in the V3 matrix; cross-version "
                    "multiplicity controlled by the program-level sequential procedure",
            "V1_evaluated": 8, "V2_evaluated": 336,
            "alpha_program": ALPHA_PROGRAM, "alpha_v3": round(ALPHA_V3, 9),
        },
        "firewall": fw.as_dict(),
        "wall_seconds": round(time.time() - t_start, 1),
        "terminal_verdict": verdict,
        "next_gate": next_gate,
        "candidate_rows": rows,
    }
    return result