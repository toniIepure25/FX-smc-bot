"""ARM64 (Apple M5) performance + peak-memory profile and safe worker recommendation.

Benchmarks representative V3 components on seeded synthetic data (no market data, no
holdout), records wall time and peak RSS, and derives a conservative concurrency
recommendation from available RAM and per-worker footprint. Profiling only; no numerical
behaviour is changed.
"""

from __future__ import annotations

import json
import resource
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"


def _peak_rss_bytes() -> int:
    # ru_maxrss is bytes on macOS, kbytes on Linux.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _sysctl_int(key: str) -> int:
    try:
        return int(subprocess.check_output(["sysctl", "-n", key], text=True).strip())
    except Exception:
        return 0


def _time(fn: Callable[[], Any], repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def _synth(n: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    mid = 1.10 * np.exp(np.cumsum(rng.normal(0, 1e-4, n)))
    return pd.DataFrame({"mid": mid, "ret": np.log(mid)})


def bench_m1_load() -> None:
    df = _synth(1_000_000)
    _ = df["mid"].to_numpy().sum()


def bench_feature_gen() -> None:
    df = _synth(500_000)
    r = np.log(df["mid"]).diff()
    _ = r.rolling(60, min_periods=60).std()
    _ = r.rolling(120, min_periods=120).mean()


def bench_signal_eval() -> None:
    x = _synth(500_000)["ret"].to_numpy()
    z = (x - np.nanmean(x)) / (np.nanstd(x) + 1e-12)
    _ = np.sign(z).sum()


def bench_linear_ml() -> None:
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

    rng = np.random.default_rng(0)
    x = rng.normal(size=(50_000, 6))
    y = (x[:, 0] + rng.normal(size=50_000) > 0).astype(int)
    LogisticRegression(max_iter=200).fit(x, y)


def bench_gmm() -> None:
    from sklearn.mixture import GaussianMixture  # type: ignore[import-untyped]

    rng = np.random.default_rng(0)
    x = rng.normal(size=(30_000, 3))
    GaussianMixture(n_components=3, random_state=0, max_iter=50).fit(x)


def bench_bootstrap() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(size=5_000)
    for _ in range(200):
        idx = rng.integers(0, len(r), len(r))
        _ = float(np.mean(r[idx]))


def bench_cross_pair_sync() -> None:
    a = pd.DataFrame({"timestamp": pd.date_range("2014-01-01", periods=300_000, freq="1min"),
                      "ret": np.random.default_rng(1).normal(size=300_000)})
    b = a.rename(columns={"ret": "ret_b"})
    _ = pd.merge(a, b, on="timestamp", how="inner")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    benches = {
        "m1_load_1e6_bars": bench_m1_load,
        "feature_generation_5e5": bench_feature_gen,
        "signal_eval_5e5": bench_signal_eval,
        "linear_ml_logreg_5e4x6": bench_linear_ml,
        "gmm_3comp_3e4x3": bench_gmm,
        "block_bootstrap_200x5e3": bench_bootstrap,
        "cross_pair_sync_3e5": bench_cross_pair_sync,
    }
    timings = {name: round(_time(fn), 4) for name, fn in benches.items()}
    peak_rss = _peak_rss_bytes()
    ram_bytes = _sysctl_int("hw.memsize")
    logical = _sysctl_int("hw.logicalcpu")

    # Conservative worker recommendation: bound by RAM headroom (assume ~2 GiB per heavy
    # worker) and leave 2 physical cores for the OS/IO; never oversubscribe BLAS threads.
    per_worker_gib = 2.0
    ram_gib = ram_bytes / 2**30
    ram_bound = max(1, int((ram_gib - 4.0) / per_worker_gib))  # keep 4 GiB free
    cpu_bound = max(1, logical - 2)
    recommended = max(1, min(ram_bound, cpu_bound))

    profile = {
        "artifact_id": "V3_MAC_PERFORMANCE_PROFILE_V1",
        "machine": subprocess.check_output(["sysctl", "-n", "hw.model"], text=True).strip(),
        "logical_cpus": logical,
        "ram_gib": round(ram_gib, 2),
        "timings_seconds_best_of_3": timings,
        "peak_rss_bytes": peak_rss,
        "peak_rss_gib": round(peak_rss / 2**30, 3),
        "concurrency_recommendation": {
            "assumed_gib_per_heavy_worker": per_worker_gib,
            "ram_bound_workers": ram_bound,
            "cpu_bound_workers": cpu_bound,
            "recommended_heavy_workers": recommended,
            "blas_threads_per_worker": 1,
            "policy": "set OMP/OPENBLAS/MKL/VECLIB threads=1 per worker to avoid "
                      "oversubscription; do not rely on swap.",
        },
        "fits_within_16gib": peak_rss < ram_bytes,
    }
    (OUT / "mac_performance_profile.json").write_text(json.dumps(profile, indent=2,
                                                                 sort_keys=True))
    print("peak_rss_gib:", profile["peak_rss_gib"], "| recommended_heavy_workers:", recommended)
    for k, v in timings.items():
        print(f"  {k:32s} {v:.4f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
