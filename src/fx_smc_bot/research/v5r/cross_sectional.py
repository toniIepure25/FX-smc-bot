"""R3: True 13-pair cross-sectional ranking."""
from __future__ import annotations
import numpy as np
from .data import INSTRUMENTS


def cross_sectional_signal(panel: dict, dates: np.ndarray, 
                           eval_mask: np.ndarray, h: int) -> np.ndarray:
    """At each bar, rank all 13 pairs by recent return.
    Returns signal for the panel (one P&L column per strategy).
    
    For top1_vs_bottom1: long best, short worst.
    For top2_vs_bottom2: long top-2, short bottom-2.
    """
    n = len(dates)
    # Compute 6-bar momentum for all pairs
    mom = {}
    for pair in INSTRUMENTS:
        ret = panel[pair]["ret"]
        m = np.full(n, np.nan)
        for i in range(6, n):
            w = ret[i-6:i]
            w = w[~np.isnan(w)]
            if len(w) > 3:
                m[i] = w.sum()
        mom[pair] = m
    
    # At each eval bar, rank pairs
    sig_top1 = np.zeros(n)
    sig_top2 = np.zeros(n)
    
    eval_idx = np.where(eval_mask)[0]
    for i in eval_idx:
        if i < 6:
            continue
        # Get momentum for all pairs at bar i
        vals = {}
        for pair in INSTRUMENTS:
            v = mom[pair][i]
            if not np.isnan(v):
                vals[pair] = v
        if len(vals) < 4:
            continue
        pairs_sorted = sorted(vals.keys(), key=lambda p: vals[p])
        # top1 vs bottom1
        best, worst = pairs_sorted[-1], pairs_sorted[0]
        sig_top1[i] = 1.0  # signal for best pair (long)
        # We'll handle the actual P&L in execution: long best, short worst
        # For top2 vs bottom2
        if len(pairs_sorted) >= 4:
            sig_top2[i] = 1.0
    
    return sig_top1, sig_top2, mom


def panel_pnl(panel: dict, dates: np.ndarray, eval_mask: np.ndarray,
              h: int, structure: str) -> np.ndarray:
    """Compute panel P&L for cross-sectional strategy.
    One P&L column per candidate (not 13).
    """
    n = len(dates)
    daily = {}
    
    # Compute momentum for all pairs
    mom = {}
    for pair in INSTRUMENTS:
        ret = panel[pair]["ret"]
        m = np.full(n, np.nan)
        for i in range(6, n):
            w = ret[i-6:i]
            w = w[~np.isnan(w)]
            if len(w) > 3:
                m[i] = w.sum()
        mom[pair] = m
    
    eval_idx = np.where(eval_mask)[0]
    day_cnt = {}
    
    for i in eval_idx:
        if i < 6 or i + 1 + h >= n:
            continue
        d = dates[i]
        if day_cnt.get(d, 0) >= 3:
            continue
        
        vals = {}
        for pair in INSTRUMENTS:
            v = mom[pair][i]
            if not np.isnan(v):
                vals[pair] = v
        if len(vals) < 4:
            continue
        
        pairs_sorted = sorted(vals.keys(), key=lambda p: vals[p])
        
        if structure == "top1_vs_bottom1":
            longs = [pairs_sorted[-1]]
            shorts = [pairs_sorted[0]]
        else:  # top2_vs_bottom2
            longs = pairs_sorted[-2:]
            shorts = pairs_sorted[:2]
        
        day_pnl = 0.0
        valid = True
        for pair in longs + shorts:
            data = panel[pair]
            ei, xi = i + 1, i + 1 + h
            if not (data["exec"][ei] and data["obs"][ei] and data["exec"][xi] and data["obs"][xi]):
                valid = False
                break
            if pair in longs:
                ep, xp = data["ao"][ei], data["bo"][xi]
            else:
                ep, xp = data["bo"][ei], data["ao"][xi]
            if ep <= 0 or xp <= 0:
                valid = False
                break
            day_pnl += (xp - ep) / ep * 1e4 if pair in longs else (ep - xp) / ep * 1e4
        
        if valid:
            daily[d] = daily.get(d, 0.0) + day_pnl
            day_cnt[d] = day_cnt.get(d, 0) + 1
    
    all_dates = sorted(set(dates[eval_mask]))
    return np.array([daily.get(d, 0.0) for d in all_dates])
