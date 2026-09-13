"""V5R data loading with correct masks."""
from __future__ import annotations
from pathlib import Path
import numpy as np

CACHE_DIR = Path(r"D:\ComputaCenter\v3_processing\discovery_cache")
INSTRUMENTS = ["AUDJPY","AUDUSD","EURCHF","EURGBP","EURJPY","EURUSD",
               "GBPCHF","GBPJPY","GBPUSD","NZDUSD","USDCAD","USDCHF","USDJPY"]
AGG = 5
TRAIN_START, TRAIN_END = "2010-01-01", "2013-12-31"
EVAL_START, EVAL_END = "2014-01-01", "2017-12-31"
SEAL_START = "2018-01-01"


def load_5min(pair: str) -> dict:
    d = np.load(CACHE_DIR / f"merged_{pair}_2010_2017.npz", allow_pickle=False)
    n = len(d["bo"])
    n = (n // AGG) * AGG
    n_agg = n // AGG
    bo = d["bo"].astype(np.float64)[:n]
    ao = d["ao"].astype(np.float64)[:n]
    exec_ = d["exec"][:n]
    obs = d["obs"][:n]
    ny_date = d["ny_date"][:n]
    o_idx, o_mid = d["o_idx"], d["o_mid"].astype(np.float64)
    o_ret = d["o_ret"].astype(np.float64)
    feat_rv = d["feat_realized_vol"].astype(np.float64)[:n]
    feat_range = d["feat_range_compression"].astype(np.float64)[:n]
    feat_spread = d["feat_spread"].astype(np.float64)[:n]

    full_mid = np.full(n, np.nan)
    full_mid[o_idx] = o_mid
    full_ret = np.full(n, np.nan)
    if len(o_ret) > 0:
        full_ret[o_idx[1:]] = o_ret

    bo_r, ao_r = bo.reshape(n_agg, AGG), ao.reshape(n_agg, AGG)
    mid_r, ret_r = full_mid.reshape(n_agg, AGG), full_ret.reshape(n_agg, AGG)
    rv_r, range_r = feat_rv.reshape(n_agg, AGG), feat_range.reshape(n_agg, AGG)
    sp_r, exec_r, obs_r = feat_spread.reshape(n_agg, AGG), exec_.reshape(n_agg, AGG), obs.reshape(n_agg, AGG)
    date_r = ny_date.reshape(n_agg, AGG)

    mid_a = np.full(n_agg, np.nan)
    bo_a = np.full(n_agg, np.nan)
    ao_a = np.full(n_agg, np.nan)
    ret_a = np.full(n_agg, np.nan)
    rv_a = np.full(n_agg, np.nan)
    range_a = np.full(n_agg, np.nan)
    sp_a = np.full(n_agg, np.nan)
    exec_a = np.zeros(n_agg, dtype=bool)
    obs_a = np.zeros(n_agg, dtype=bool)
    date_a = np.array([""] * n_agg, dtype="U10")

    for j in range(n_agg):
        m = ~np.isnan(mid_r[j])
        if m.any(): mid_a[j] = mid_r[j][m][-1]
        m = ~np.isnan(bo_r[j])
        if m.any(): bo_a[j] = bo_r[j][m][-1]
        m = ~np.isnan(ao_r[j])
        if m.any(): ao_a[j] = ao_r[j][m][-1]
        m = ~np.isnan(ret_r[j])
        if m.any(): ret_a[j] = ret_r[j][m].sum()
        m = ~np.isnan(rv_r[j])
        if m.any(): rv_a[j] = rv_r[j][m].mean()
        m = ~np.isnan(range_r[j])
        if m.any(): range_a[j] = range_r[j][m].mean()
        m = ~np.isnan(sp_r[j])
        if m.any(): sp_a[j] = sp_r[j][m].mean()
        exec_a[j] = exec_r[j].any()
        obs_a[j] = obs_r[j].any()
        date_a[j] = date_r[j][-1]

    spread_a = (ao_a - bo_a) / mid_a * 1e4
    spread_a[~np.isfinite(spread_a)] = np.nan

    base_mask = exec_a & obs_a & ~np.isnan(mid_a)
    train_mask = base_mask & (date_a >= TRAIN_START) & (date_a <= TRAIN_END)
    eval_mask = base_mask & (date_a >= EVAL_START) & (date_a <= EVAL_END)

    return {"mid": mid_a, "bo": bo_a, "ao": ao_a, "ret": ret_a,
            "rv": rv_a, "range": range_a, "sp": sp_a, "spread": spread_a,
            "exec": exec_a, "obs": obs_a, "date": date_a,
            "train_mask": train_mask, "eval_mask": eval_mask, "n": n_agg}


def load_panel() -> dict:
    panel = {}
    for pair in INSTRUMENTS:
        panel[pair] = load_5min(pair)
    return panel
