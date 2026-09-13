"""V5R execution engine. Correct: no spread double-count."""
from __future__ import annotations
import numpy as np

COST_BPS = 0.40


def execute(bo: np.ndarray, ao: np.ndarray, mid: np.ndarray,
            mask: np.ndarray, sig: np.ndarray, h: int,
            dates: np.ndarray, cost_mult: float = 1.0) -> tuple:
    """Side-correct execution. 1-bar latency. Max 3/day.
    
    net = bid_ask_gross - explicit_commission (NO spread subtraction).
    Returns (gross, spread_info, comm, n_trades, daily_pnl_array).
    """
    cost = COST_BPS * cost_mult
    valid = mask & ~np.isnan(sig) & (sig != 0)
    idx = np.where(valid)[0]
    idx = idx[idx + 1 + h < len(mid)]
    
    day_cnt = {}
    sel = []
    for i in idx:
        d = dates[i]
        if day_cnt.get(d, 0) >= 3:
            continue
        sel.append(i)
        day_cnt[d] = day_cnt.get(d, 0) + 1
    
    if not sel:
        all_dates = sorted(set(dates[mask]))
        return 0, 0, 0, 0, np.zeros(len(all_dates))
    
    sel = np.array(sel)
    ei, xi = sel + 1, sel + 1 + h
    s = sig[sel]
    
    # Long: entry=ask, exit=bid. Short: entry=bid, exit=ask
    ep_l, xp_l = ao[ei], bo[xi]
    ep_s, xp_s = bo[ei], ao[xi]
    vf = (ep_l > 0) & (xp_l > 0) & (ep_s > 0) & (xp_s > 0)
    sel, ei, xi, s = sel[vf], ei[vf], xi[vf], s[vf]
    
    if len(sel) == 0:
        all_dates = sorted(set(dates[mask]))
        return 0, 0, 0, 0, np.zeros(len(all_dates))
    
    pnl_l = (xp_l - ep_l) / ep_l * 1e4
    pnl_s = (ep_s - xp_s) / ep_s * 1e4
    pnl = np.where(s > 0, pnl_l, pnl_s)
    
    # Spread info (for reporting only, NOT subtracted from net)
    sp = (ao[ei] - bo[ei]) / mid[ei] * 1e4
    sp[~np.isfinite(sp)] = 0
    
    gross = float(pnl.sum())
    comm = float(cost * len(sel))
    # CORRECT: net = gross - comm (spread already in bid/ask P&L)
    
    # Daily P&L
    daily = {}
    for k in range(len(sel)):
        d = dates[sel[k]]
        daily[d] = daily.get(d, 0.0) + (pnl[k] - cost)
    
    all_dates = sorted(set(dates[mask]))
    dp = np.array([daily.get(d, 0.0) for d in all_dates])
    
    return gross, float(sp.sum()), comm, len(sel), dp


def sharpe(dp: np.ndarray) -> float:
    if len(dp) < 10 or dp.std() < 1e-12:
        return 0.0
    return float(dp.mean() / dp.std() * np.sqrt(252))
