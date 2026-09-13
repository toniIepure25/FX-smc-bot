"""R1: True local-linear state-space Kalman filter."""
from __future__ import annotations
import numpy as np


def kalman_local_linear(log_mid: np.ndarray, q: float = 1e-8, r: float = 1e-6) -> tuple:
    """True recursive Kalman filter. State = [level, slope].
    
    Returns (slope, uncertainty) arrays.
    """
    n = len(log_mid)
    slope = np.full(n, np.nan)
    unc = np.full(n, np.nan)
    
    x = np.zeros(2)
    P = np.eye(2) * 1e-6
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    Q = np.array([[q, q/2], [q/2, q]])
    H = np.array([[1.0, 0.0]])
    
    for i in range(n):
        if np.isnan(log_mid[i]):
            continue
        # Predict
        x = F @ x
        P = F @ P @ F.T + Q
        # Update
        y = log_mid[i] - float(H @ x)
        S = float(H @ P @ H.T) + r
        if S < 1e-30:
            continue
        K = (P @ H.T) / S
        x = x + (K.flatten() * y)
        I_KH = np.eye(2) - K @ H
        P = I_KH @ P
        slope[i] = x[1]
        unc[i] = np.sqrt(max(P[1, 1], 0))
    
    return slope, unc


def kalman_signal(log_mid: np.ndarray, scale_bars: int) -> np.ndarray:
    """Generate Kalman trend signal at given scale.
    signal = tanh(slope / (|slope| + uncertainty))
    """
    # Subsample to scale for the Kalman (each bar represents `scale` 5-min bars)
    n = len(log_mid)
    # Use all bars but with scale-dependent process noise
    q = 1e-8 * scale_bars
    r = 1e-6
    slope, unc = kalman_local_linear(log_mid, q=q, r=r)
    sig = np.zeros(n)
    valid = ~np.isnan(slope) & ~np.isnan(unc) & (unc > 1e-15)
    sig[valid] = np.tanh(slope[valid] / (np.abs(slope[valid]) + unc[valid] + 1e-15))
    return sig, slope, unc
