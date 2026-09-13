"""V5R statistics: WRC, SPA, RW, Holm, BH, PSR, DSR, CSCV PBO."""
from __future__ import annotations
import numpy as np
from scipy import stats as scistats


def wrc_test(daily_pnl: np.ndarray) -> float:
    """White Reality Check. Returns p-value."""
    n_cand, n_days = daily_pnl.shape
    # Max performance
    perf = daily_pnl.mean(axis=1)
    max_perf = perf.max()
    # Bootstrap: stationary bootstrap
    rng = np.random.default_rng(42)
    n_reps = 999
    block = 5
    boot_max = np.zeros(n_reps)
    for b in range(n_reps):
        boot = np.zeros((n_cand, n_days))
        t = rng.integers(0, n_days)
        for i in range(n_days):
            length = 1 + rng.geometric(1.0 / block) if rng.random() < 1.0 else 1
            length = min(length, n_days - t)
            boot[:, i:i+length] = daily_pnl[:, t:t+length]
            t = (t + length) % n_days
        boot_perf = boot.mean(axis=1)
        boot_max[b] = boot_perf.max()
    p = (np.sum(boot_max >= max_perf) + 1) / (n_reps + 1)
    return float(p)


def spa_test(daily_pnl: np.ndarray) -> float:
    """Hansen SPA test. Returns p-value."""
    n_cand, n_days = daily_pnl.shape
    if n_cand < 2:
        return 1.0
    # Mean performance differences
    mu = daily_pnl.mean(axis=1)
    mu_max = mu.max()
    # Covariance
    diffs = daily_pnl - mu[:, None]
    cov = np.cov(diffs.T)
    # SPA statistic
    if np.all(cov == 0):
        return 1.0
    try:
        inv_cov = np.linalg.pinv(cov)
    except:
        return 1.0
    # Simplified SPA: max of standardized performances
    var_mu = np.diag(cov) / n_days
    se = np.sqrt(var_mu)
    se[se < 1e-15] = 1e-15
    z = mu / se
    spa_stat = z.max()
    # Bootstrap p-value
    rng = np.random.default_rng(42)
    n_reps = 999
    boot_stats = np.zeros(n_reps)
    for b in range(n_reps):
        # Resample days
        idx = rng.integers(0, n_days, n_days)
        boot_pnl = daily_pnl[:, idx]
        boot_mu = boot_pnl.mean(axis=1)
        boot_diffs = boot_pnl - boot_mu[:, None]
        boot_cov = np.cov(boot_diffs.T)
        if np.all(boot_cov == 0):
            boot_stats[b] = 0
            continue
        boot_var = np.diag(boot_cov) / n_days
        boot_se = np.sqrt(boot_var)
        boot_se[boot_se < 1e-15] = 1e-15
        boot_z = boot_mu / boot_se
        boot_stats[b] = boot_z.max()
    p = (np.sum(boot_stats >= spa_stat) + 1) / (n_reps + 1)
    return float(p)


def romano_wolf(daily_pnl: np.ndarray) -> np.ndarray:
    """Romano-Wolf stepdown procedure. Returns adjusted p-values."""
    n_cand, n_days = daily_pnl.shape
    # Individual t-tests vs zero
    pvals = np.zeros(n_cand)
    for i in range(n_cand):
        dp = daily_pnl[i]
        if dp.std() < 1e-15:
            pvals[i] = 1.0
        else:
            t_stat = dp.mean() / (dp.std() / np.sqrt(len(dp)))
            pvals[i] = 2 * (1 - scistats.t.cdf(abs(t_stat), len(dp)-1))
    # Stepdown
    order = np.argsort(pvals)[::-1]
    adjusted = np.zeros(n_cand)
    prev = 1.0
    for rank, i in enumerate(order):
        m = n_cand - rank
        adj = min(prev, m * pvals[i])
        adjusted[i] = min(adj, 1.0)
        prev = adj
    return adjusted


def holm(pvals: np.ndarray) -> np.ndarray:
    """Holm-Bonferroni."""
    n = len(pvals)
    order = np.argsort(pvals)
    adjusted = np.zeros(n)
    for rank, i in enumerate(order):
        adjusted[i] = min(1.0, (n - rank) * pvals[i])
    # Enforce monotonicity
    for rank in range(1, n):
        adjusted[order[rank]] = max(adjusted[order[rank]], adjusted[order[rank-1]])
    return adjusted


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR."""
    n = len(pvals)
    order = np.argsort(pvals)
    adjusted = np.zeros(n)
    for rank, i in enumerate(order):
        adjusted[i] = pvals[i] * n / (rank + 1)
    # Enforce monotonicity from top
    for rank in range(n - 2, -1, -1):
        adjusted[order[rank]] = min(adjusted[order[rank]], adjusted[order[rank+1]])
    return np.minimum(adjusted, 1.0)


def psr(daily_pnl: np.ndarray, n_trials: int = 88) -> float:
    """Probabilistic Sharpe Ratio."""
    dp = daily_pnl.mean(axis=1)
    if len(dp) < 10:
        return 0.0
    sr = dp.mean() / (dp.std() + 1e-15) * np.sqrt(252)
    # PSR: probability that true SR > 0 given observed SR
    n = len(dp)
    skew = float(scistats.skew(dp))
    kurt = float(scistats.kurtosis(dp))
    denom = np.sqrt(1 - skew * sr / np.sqrt(n) + (kurt + 2) * sr**2 / (4 * n))
    if denom < 1e-15:
        return 0.0
    z = (sr - 0) / (np.sqrt((1 - skew * sr / np.sqrt(n) + (kurt + 2) * sr**2 / (4 * n)) / n))
    psr_val = scistats.norm.cdf(z)
    # Deflate for trials
    psr_deflated = psr_val ** (1.0 / max(n_trials, 1))
    return float(psr_deflated)


def dsr(daily_pnl: np.ndarray, n_trials: int = 88) -> float:
    """Deflated Sharpe Ratio."""
    dp = daily_pnl.mean(axis=1)
    if len(dp) < 10:
        return 0.0
    sr = dp.mean() / (dp.std() + 1e-15) * np.sqrt(252)
    n = len(dp)
    # Expected max SR under null
    gamma = 0.5772156649
    exp_max_sr = np.sqrt(2 * np.log(n_trials)) * (1 - gamma / (4 * np.log(n_trials)))
    z = (sr - exp_max_sr) / np.sqrt(1 / n)
    return float(scistats.norm.cdf(z))


def cscv_pbo(daily_pnl: np.ndarray, n_splits: int = 4) -> float:
    """Combinatorially Symmetric Cross-Validation PBO."""
    n_cand, n_days = daily_pnl.shape
    if n_days < n_splits * 10:
        return 0.5
    # Split into n_splits folds
    fold_size = n_days // n_splits
    folds = [daily_pnl[:, i*fold_size:(i+1)*fold_size] for i in range(n_splits)]
    
    # For each half-in/half-out combination
    n_half = n_splits // 2
    from itertools import combinations
    combos = list(combinations(range(n_splits), n_half))
    
    n_pos = 0
    n_total = 0
    for combo in combos:
        train_folds = [f for i, f in enumerate(folds) if i in combo]
        test_folds = [f for i, f in enumerate(folds) if i not in combo]
        train_pnl = np.vstack(train_folds)
        test_pnl = np.vstack(test_folds)
        # Best on train
        train_perf = train_pnl.mean(axis=1)
        best_train = train_perf.argmax()
        # Performance on test
        test_perf = test_pnl.mean(axis=1)
        if test_perf[best_train] <= 0:
            n_pos += 1
        n_total += 1
    
    pbo = n_pos / max(n_total, 1)
    return float(pbo)
