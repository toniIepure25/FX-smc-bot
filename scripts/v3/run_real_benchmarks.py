"""Real-data resource benchmarks on the M5, seeded from the certified real M1 sample.

Loads the certified real EURUSD/USDJPY M1 partitions and tiles them to representative
development scale (one instrument-year ~= 374k bars; a 13-pair panel), then benchmarks the
components the discovery workload actually exercises and measures peak RSS + memory pressure.
The concurrency recommendation is DERIVED from the measured per-worker footprint, not trusted
from the synthetic guess. No V3 signal/P&L/ranking is computed; features here are footprint
probes only.
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
CANON = REPO / "data" / "canonical"

BARS_PER_INSTRUMENT_YEAR = 374_400   # 260 trading days x 1440 M1 bars
DEV_YEARS = 8                         # 2010-2017
PANEL_INSTRUMENTS = 13


def _peak_rss_gib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30  # bytes on macOS


def _sysctl_int(key: str) -> int:
    try:
        return int(subprocess.check_output(["sysctl", "-n", key], text=True).strip())
    except Exception:
        return 0


def _memory_pressure() -> str:
    try:
        out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True,
                             timeout=10).stdout
        for line in out.splitlines():
            if "System-wide memory free percentage" in line:
                return line.strip()
    except Exception:
        pass
    return "unavailable"


def _time(fn: Callable[[], Any], repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return round(best, 4)


def load_real_mid(instrument: str, side: str = "bid") -> np.ndarray:
    base = CANON / instrument / f"price={side}" / "year=2014" / "month=06" / "day=10"
    df = pd.read_parquet(base / "data.parquet")
    return df["close"].to_numpy(dtype="float64")


def tile_to(arr: np.ndarray, n: int) -> np.ndarray:
    reps = (n // len(arr)) + 1
    return np.tile(arr, reps)[:n]


def bench_single_pair_features(mid: np.ndarray) -> None:
    r = np.diff(np.log(mid))
    s = pd.Series(r)
    _ = s.rolling(60, min_periods=60).std()
    _ = s.rolling(120, min_periods=120).mean()
    _ = s.rolling(240, min_periods=240).apply(lambda x: x[-1], raw=True)


def bench_cross_pair_sync(panel: dict[str, np.ndarray]) -> None:
    n = min(len(v) for v in panel.values())
    ts = pd.date_range("2010-01-04", periods=n, freq="1min", tz="UTC")
    frames = [pd.DataFrame({"timestamp": ts, k: v[:n]}) for k, v in panel.items()]
    out = frames[0]
    for f in frames[1:]:
        out = pd.merge(out, f, on="timestamp", how="inner")


def bench_kalman(mid: np.ndarray) -> None:
    # scalar local-level Kalman filter (causal), pure numpy
    x = np.log(mid)
    q, rr = 1e-6, 1e-4
    xhat = x[0]
    p = 1.0
    for z in x:
        p += q
        k = p / (p + rr)
        xhat += k * (z - xhat)
        p *= (1 - k)


def bench_gmm(feat: np.ndarray) -> None:
    from sklearn.mixture import GaussianMixture  # type: ignore[import-untyped]

    GaussianMixture(n_components=3, random_state=0, max_iter=30).fit(feat)


def bench_ml(feat: np.ndarray, y: np.ndarray) -> None:
    from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

    LogisticRegression(max_iter=200, random_state=0).fit(feat, y)


def bench_event_execution(mid: np.ndarray) -> None:
    # causal event-state pass: signal at t-1, hold H bars, side-correct fills (footprint probe)
    sig = np.sign(np.diff(np.log(mid), prepend=mid[0]))
    h = 30
    i = 61
    n = len(mid)
    pnl = 0.0
    while i + h < n:
        if sig[i - 1] != 0:
            pnl += (mid[i + h] - mid[i]) / mid[i] * sig[i - 1]
            i += h
        else:
            i += 1


def bench_bootstrap(returns: np.ndarray) -> None:
    rng = np.random.default_rng(0)
    for _ in range(499):
        idx = rng.integers(0, len(returns), len(returns))
        _ = float(np.mean(returns[idx]))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    real_eur = load_real_mid("EURUSD")
    real_jpy = load_real_mid("USDJPY")
    real_bars = int(len(real_eur))

    # representative working sets seeded from REAL M1 values
    iy = BARS_PER_INSTRUMENT_YEAR
    mid_1y = tile_to(real_eur, iy)
    panel_1y = {f"pair{i}": tile_to(real_eur if i % 2 else real_jpy, iy)
                for i in range(PANEL_INSTRUMENTS)}
    feat = np.column_stack([
        tile_to(real_eur, 100_000), tile_to(real_jpy, 100_000),
        tile_to(np.diff(real_eur, prepend=real_eur[0]), 100_000),
    ])
    y = (feat[:, 0] > np.median(feat[:, 0])).astype(int)
    ret_1y = np.diff(np.log(mid_1y))

    timings = {
        "single_pair_features_374k": _time(lambda: bench_single_pair_features(mid_1y)),
        "cross_pair_sync_13x374k": _time(lambda: bench_cross_pair_sync(panel_1y), repeats=1),
        "kalman_local_level_374k": _time(lambda: bench_kalman(mid_1y)),
        "gmm_3comp_1e5x3": _time(lambda: bench_gmm(feat), repeats=1),
        "logreg_1e5x3": _time(lambda: bench_ml(feat, y), repeats=1),
        "event_execution_374k": _time(lambda: bench_event_execution(mid_1y)),
        "block_bootstrap_499_374k": _time(lambda: bench_bootstrap(ret_1y), repeats=1),
    }

    peak_rss = _peak_rss_gib()
    ram_gib = _sysctl_int("hw.memsize") / 2**30
    logical = _sysctl_int("hw.logicalcpu")

    # Per-worker footprint: extrapolate the 1-year panel peak to the full 8-year development
    # span (linear in rows). Cross-pair families are the memory driver.
    per_worker_1y_gib = peak_rss
    per_worker_full_dev_gib = round(per_worker_1y_gib * DEV_YEARS, 2)

    reserve_gib = 4.0
    ram_bound = max(1, int((ram_gib - reserve_gib) / max(per_worker_full_dev_gib, 0.5)))
    cpu_bound = max(1, logical - 2)
    recommended = max(1, min(ram_bound, cpu_bound))

    profile = {
        "artifact_id": "V3_MAC_REAL_BENCHMARKS_V1",
        "seeded_from_certified_real_m1": True,
        "real_bars_per_pair": real_bars,
        "representative_scale": {
            "instrument_year_bars": iy,
            "panel_instruments": PANEL_INSTRUMENTS,
            "development_years": DEV_YEARS,
        },
        "machine": subprocess.check_output(["sysctl", "-n", "hw.model"], text=True).strip(),
        "logical_cpus": logical,
        "ram_gib": round(ram_gib, 2),
        "memory_pressure": _memory_pressure(),
        "timings_seconds": timings,
        "peak_rss_gib_1y_panel": round(peak_rss, 3),
        "extrapolated_per_worker_full_dev_gib": per_worker_full_dev_gib,
        "concurrency_recommendation": {
            "policy": "adaptive_bounded: start at recommended, monitor RSS/pressure, scale "
                      "down on pressure; never oversubscribe BLAS (threads=1/worker); no swap.",
            "ram_bound_workers": ram_bound,
            "cpu_bound_workers": cpu_bound,
            "recommended_heavy_workers": recommended,
            "blas_threads_per_worker": 1,
            "note": "cross-pair panel families are the memory driver; single-pair families "
                    "tolerate more workers. Prefer per-family-class concurrency.",
        },
        "fits_within_16gib": per_worker_full_dev_gib < ram_gib,
        "supersedes_synthetic_recommendation_of_6": True,
    }
    (OUT / "mac_real_benchmarks.json").write_text(json.dumps(profile, indent=2, sort_keys=True))
    print("peak_rss_gib (1y panel):", round(peak_rss, 3),
          "| per-worker full-dev est:", per_worker_full_dev_gib, "GiB")
    print("recommended heavy workers:", recommended, "(ram", ram_bound, "cpu", cpu_bound, ")")
    for k, v in timings.items():
        print(f"  {k:28s} {v}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
