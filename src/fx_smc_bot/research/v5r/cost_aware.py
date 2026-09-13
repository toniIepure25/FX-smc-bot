"""R7: True cost-aware decision using R1/R2 model outputs."""
from __future__ import annotations
import numpy as np


def cost_aware_signal(kalman_slope: np.ndarray, kalman_unc: np.ndarray,
                      gmm_signal: np.ndarray, gmm_probs: np.ndarray,
                      spread_bps: np.ndarray, cost_mult: float,
                      mask: np.ndarray) -> np.ndarray:
    """ENTER/WAIT/ABSTAIN decision.
    
    Uses R1 Kalman posterior (slope + uncertainty) and R2 GMM regime-weighted signal.
    ENTER if |expected_move| > uncertainty + spread + explicit_cost.
    """
    n = len(kalman_slope)
    cost_bps = 0.40 * cost_mult
    sig = np.zeros(n)
    
    for i in range(n):
        if not mask[i]:
            continue
        # R1: Kalman expected move = slope * horizon_bars (approx 1 bar)
        k_move = kalman_slope[i] if not np.isnan(kalman_slope[i]) else 0
        k_unc = kalman_unc[i] if not np.isnan(kalman_unc[i]) else 1e-6
        # R2: GMM regime-weighted expected return
        g_move = gmm_signal[i] if not np.isnan(gmm_signal[i]) else 0
        g_unc = 0.01  # approximate uncertainty from regime probs
        
        # Combined expected move (average of R1 and R2)
        exp_move = (k_move + g_move) / 2
        combined_unc = (k_unc + g_unc) / 2
        
        # Current executable cost
        sp = spread_bps[i] if not np.isnan(spread_bps[i]) else 0.5
        total_cost = sp + cost_bps
        
        # Decision: ENTER if |exp_move| > unc + cost
        if abs(exp_move) > combined_unc + total_cost:
            sig[i] = np.sign(exp_move)
        # else: ABSTAIN (sig=0)
    
    return sig
