"""R4: Real causal PCA factor + USD common factor residual."""
from __future__ import annotations
import numpy as np
from sklearn.decomposition import PCA
from .data import INSTRUMENTS


def build_panel_returns(panel: dict, n: int) -> np.ndarray:
    """Build synchronized 13-pair return matrix (n x 13). Uses min length."""
    n_min = min(len(panel[p]["ret"]) for p in INSTRUMENTS)
    n = min(n, n_min)
    rets = np.full((n, len(INSTRUMENTS)), np.nan)
    for j, pair in enumerate(INSTRUMENTS):
        rets[:, j] = panel[pair]["ret"][:n]
    return rets


def causal_pca_signal(panel: dict, dates: np.ndarray, train_mask: np.ndarray,
                      eval_mask: np.ndarray, h: int, 
                      factor_type: str, dynamic: str) -> np.ndarray:
    """Real PCA/USD factor with causal fitting.
    
    factor_type: 'usd_common' or 'pca1_causal'
    dynamic: 'residual_momentum' or 'residual_drift'
    
    Returns daily P&L array.
    """
    n = min(len(dates), min(len(panel[p]["ret"]) for p in INSTRUMENTS))
    rets = build_panel_returns(panel, n)
    
    # Find USD index
    usd_idx = INSTRUMENTS.index("EURUSD") if "EURUSD" in INSTRUMENTS else 5
    
    # Causal: fit PCA/scaler on training data only
    train_idx = np.where(train_mask)[0]
    train_rets = rets[train_idx]
    train_rets = train_rets[~np.isnan(train_rets).any(axis=1)]
    
    if len(train_rets) < 100:
        return np.zeros(n)
    
    # Fit PCA on training data
    pca = PCA(n_components=1, random_state=42)
    pca.fit(train_rets)
    pca_mean = pca.mean_
    pca_components = pca.components_[0]
    
    # For USD common factor: beta to EURUSD
    usd_rets = train_rets[:, usd_idx]
    usd_rets = usd_rets[~np.isnan(usd_rets)]
    
    daily = {}
    eval_idx = np.where(eval_mask)[0]
    day_cnt = {}
    n_min = min(len(panel[p]["mid"]) for p in INSTRUMENTS)
    
    for i in eval_idx:
        if i < 24 or i + 1 + h >= n_min:
            continue
        d = dates[i]
        if day_cnt.get(d, 0) >= 3:
            continue
        
        # Compute factor and residuals for all pairs
        r_window = rets[i-24:i]
        r_window = r_window[~np.isnan(r_window).any(axis=1)]
        if len(r_window) < 10:
            continue
        
        if factor_type == "pca1_causal":
            # Project onto PCA component
            centered = r_window - pca_mean
            scores = centered @ pca_components
            # Residual: actual - projected
            recon = np.outer(scores, pca_components) + pca_mean
            residuals = r_window - recon
            # Current bar residual
            r_i = rets[i]
            if np.isnan(r_i).any():
                continue
            c_i = r_i - pca_mean
            score_i = c_i @ pca_components
            resid_i = c_i - score_i * pca_components
        else:  # usd_common
            # Beta to USD
            usd_w = r_window[:, usd_idx]
            valid = ~np.isnan(usd_w)
            if valid.sum() < 10:
                continue
            betas = np.zeros(len(INSTRUMENTS))
            for j in range(len(INSTRUMENTS)):
                rj = r_window[:, j]
                v = valid & ~np.isnan(rj)
                if v.sum() < 10:
                    continue
                betas[j] = np.dot(rj[v], usd_w[v]) / (np.dot(usd_w[v], usd_w[v]) + 1e-12)
            # Residual for current bar
            r_i = rets[i]
            usd_i = rets[i, usd_idx]
            if np.isnan(usd_i):
                continue
            resid_i = r_i - betas * usd_i
            resid_i = np.where(np.isnan(r_i), 0, resid_i)
        
        # Dynamic
        if dynamic == "residual_momentum":
            sig_vals = np.zeros(len(INSTRUMENTS))
            if factor_type == "pca1_causal":
                # For each row in window, compute residual for each pair
                for t in range(len(r_window)):
                    centered = r_window[t] - pca_mean
                    if np.isnan(centered).any():
                        continue
                    score = float(centered @ pca_components)
                    recon = score * pca_components
                    res = centered - recon
                    sig_vals += res
            else:
                usd_w = r_window[:, usd_idx]
                valid_usd = ~np.isnan(usd_w)
                for j in range(len(INSTRUMENTS)):
                    rj = r_window[:, j]
                    v = valid_usd & ~np.isnan(rj)
                    if v.sum() < 10:
                        continue
                    beta = np.dot(rj[v], usd_w[v]) / (np.dot(usd_w[v], usd_w[v]) + 1e-12)
                    res = rj[v] - beta * usd_w[v]
                    sig_vals[j] = res.sum()
        else:  # residual_drift
            sig_vals = resid_i
        
        # Trade pairs with strongest residual signal
        valid_pairs = [j for j in range(len(INSTRUMENTS)) if not np.isnan(sig_vals[j])]
        if len(valid_pairs) < 2:
            continue
        sig_vals_v = np.array([sig_vals[j] for j in valid_pairs])
        pairs_v = np.array(valid_pairs)
        
        # Long top, short bottom
        order = np.argsort(sig_vals_v)
        short_pair = INSTRUMENTS[pairs_v[order[0]]]
        long_pair = INSTRUMENTS[pairs_v[order[-1]]]
        
        day_pnl = 0.0
        valid = True
        for pair, direction in [(long_pair, 1), (short_pair, -1)]:
            data = panel[pair]
            ei, xi = i + 1, i + 1 + h
            if ei >= len(data["exec"]) or xi >= len(data["exec"]):
                valid = False
                break
            if not (data["exec"][ei] and data["obs"][ei] and data["exec"][xi] and data["obs"][xi]):
                valid = False
                break
            if direction == 1:
                ep, xp = data["ao"][ei], data["bo"][xi]
                pnl = (xp - ep) / ep * 1e4
            else:
                ep, xp = data["bo"][ei], data["ao"][xi]
                pnl = (ep - xp) / ep * 1e4
            if ep <= 0 or xp <= 0:
                valid = False
                break
            day_pnl += pnl
        
        if valid:
            daily[d] = daily.get(d, 0.0) + day_pnl
            day_cnt[d] = day_cnt.get(d, 0) + 1
    
    all_dates = sorted(set(dates[eval_mask]))
    return np.array([daily.get(d, 0.0) for d in all_dates])
