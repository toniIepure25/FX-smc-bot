"""R2: Real GaussianMixture regime model (causal)."""
from __future__ import annotations
import numpy as np
from sklearn.mixture import GaussianMixture


def fit_gmm_causal(features: np.ndarray, dates: np.ndarray, 
                   eval_start: str, n_components: int,
                   min_train: int = 500) -> tuple:
    """Fit GMM causally: at each eval bar, model is fit on all prior data.
    For efficiency, refit every 252 bars (1 day of 5-min bars).
    
    Returns (signal, regime_probs) arrays for eval period.
    """
    n = len(features)
    signal = np.zeros(n)
    regime_probs = np.zeros((n, n_components))
    
    # Find eval indices
    eval_idx = np.where((dates >= eval_start) & ~np.isnan(features[:, 0]))[0]
    if len(eval_idx) == 0:
        return signal, regime_probs
    
    # Refit schedule: every 252 bars
    refit_interval = 252
    last_fit = -refit_interval
    gmm = None
    cond_means = None
    
    for i in eval_idx:
        # Refit if needed
        if i - last_fit >= refit_interval and i >= min_train:
            train_data = features[:i]
            train_data = train_data[~np.isnan(train_data).any(axis=1)]
            if len(train_data) >= min_train:
                gmm = GaussianMixture(n_components=n_components, random_state=42, n_init=1)
                gmm.fit(train_data)
                # Conditional future-return per regime (from training data)
                labels = gmm.predict(train_data)
                rets = train_data[:, 0]
                cond_means = np.zeros(n_components)
                for c in range(n_components):
                    mask_c = labels == c
                    if mask_c.sum() > 0:
                        cond_means[c] = rets[mask_c].mean()
                last_fit = i
        
        if gmm is None:
            continue
        
        x = features[i].reshape(1, -1)
        if np.isnan(x).any():
            continue
        probs = gmm.predict_proba(x)[0]
        regime_probs[i] = probs
        # Signal: regime-weighted conditional return
        if cond_means is not None:
            signal[i] = float(probs @ cond_means)
    
    return signal, regime_probs
