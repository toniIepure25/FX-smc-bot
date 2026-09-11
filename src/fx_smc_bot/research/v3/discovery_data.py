"""V3.1 discovery data layer: firewall-guarded canonical M1 loading + causal features.

This module is the ONLY code path that reads canonical market data during the V3.1
discovery run. Every read is guarded by :class:`DiscoveryFirewall`, which structurally
blocks any 2018+ partition and counts every file/byte touched, so the sealed-holdout
invariant (2018+ requests = 0, 2018+ reads = 0) is enforced before I/O, not audited
afterwards.

Frozen semantics honoured here (see observation_contract.py / canonical_m1.py):

* imputed (carry-forward) rows are clock rows, NOT market observations: stateful market
  features are computed on the observed sub-series only and carried forward on the clock
  grid (a feature is never *updated* by an imputed row, and an imputed row is never a
  zero return);
* the return after a gap is measured across the gap between real observations;
* ``executable_quote`` (session-valid AND bid+ask observed) is the only mask on which a
  fill may ever occur (enforced in the execution kernel, asserted there);
* cross-pair synchronization requires EVERY leg observed at the timestamp
  (contemporaneous); a stale/imputed leg breaks synchronization;
* volume is provenance-only and is never an alpha feature.

The USDJPY:2010-01-01 UNRESOLVED_DATA_GAP day is absent from the canonical tree; the
frame simply has no rows for that instrument-day, which by construction yields no fills,
no feature updates and no ML examples on it (mission section 4).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pyarrow.dataset as ds  # type: ignore[import-untyped]

HOLDOUT_YEAR_FLOOR = 2018
DEVELOPMENT_YEARS: tuple[int, ...] = (2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017)
PRIMARY_YEARS: tuple[int, ...] = (2010, 2011, 2012, 2013, 2014)
SECONDARY_YEARS: tuple[int, ...] = (2015, 2016, 2017)

INSTRUMENTS_13: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF",
    "EURJPY", "GBPJPY", "AUDJPY", "EURGBP", "EURCHF", "GBPCHF",
)
SELF_INSTRUMENTS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY")
TRIANGLES: tuple[tuple[str, str, str], ...] = (
    ("EURUSD", "USDJPY", "EURJPY"),
    ("GBPUSD", "USDJPY", "GBPJPY"),
    ("AUDUSD", "USDJPY", "AUDJPY"),
    ("EURUSD", "GBPUSD", "EURGBP"),
    ("EURUSD", "USDCHF", "EURCHF"),
)
# USD factor = average USD-appreciation signal over the six USD majors (sign-corrected:
# X/USD pairs fall when USD rises; USD/JPY rises when USD rises).
USD_FACTOR_PAIRS: tuple[tuple[str, float], ...] = (
    ("EURUSD", -1.0), ("GBPUSD", -1.0), ("USDJPY", +1.0),
    ("AUDUSD", -1.0), ("NZDUSD", -1.0), ("USDCAD", -1.0),
)

FEATURE_VERSION = "v3_1_discovery_features_1"

# Structural standardization window for rolling_zscore nodes: 4x the node lookback,
# floored at 240 observed bars, capped at 480 (frozen engine constant, pre-outcome).
def _z_window(lookback: int) -> int:
    return int(min(max(4 * int(lookback), 240), 480))


@dataclass
class DiscoveryFirewall:
    """Pre-I/O guard for the sealed 2018+ holdout, with archived counters."""

    reads: int = 0
    partitions_read: int = 0
    bytes_read: int = 0
    blocked_2018_plus: int = 0

    def guard_years(self, years: tuple[int, ...] | list[int]) -> None:
        bad = [y for y in years if y >= HOLDOUT_YEAR_FLOOR]
        if bad:
            self.blocked_2018_plus += len(bad)
            raise AssertionError(
                f"V3_1_DISCOVERY_FIREWALL: 2018+ year(s) {bad} blocked; sealed holdout "
                f"is independent evidence and may not be opened in a discovery session."
            )

    def record(self, n_files: int, n_bytes: int) -> None:
        self.reads += n_files
        self.partitions_read += n_files
        self.bytes_read += n_bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "2018_plus_provider_requests_issued": 0,
            "2018_plus_market_files_read": self.reads if self.blocked_2018_plus == 0 else -1,
            "2018_plus_reads_blocked": self.blocked_2018_plus,
            "canonical_partitions_read": self.partitions_read,
            "canonical_bytes_read": self.bytes_read,
            "holdout_year_floor": HOLDOUT_YEAR_FLOOR,
            "all_reads_pre_2018": self.blocked_2018_plus == 0,
        }


@dataclass
class InstrumentData:
    """One instrument's canonical M1 clock grid (pre-2018) + causal features."""

    inst: str
    ts: np.ndarray
    bo: np.ndarray
    bh: np.ndarray
    bl: np.ndarray
    bc: np.ndarray
    ao: np.ndarray
    ah: np.ndarray
    al: np.ndarray
    ac: np.ndarray
    exec: np.ndarray
    obs: np.ndarray
    ny_min: np.ndarray
    ny_date: np.ndarray
    ny_year: np.ndarray
    o_idx: np.ndarray
    o_mid: np.ndarray
    o_ret: np.ndarray
    o_mh: np.ndarray
    o_ml: np.ndarray
    o_mc: np.ndarray
    o_spread: np.ndarray
    feat: dict[str, np.ndarray] = field(default_factory=dict)
    missing_days: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return int(self.ts.shape[0])

    def primary_mask(self) -> np.ndarray:
        return self.ny_year <= PRIMARY_YEARS[-1]


def _missing_days(ny_date: np.ndarray) -> list[str]:
    """Calendar trading days (weekday != Saturday) inside the span with no rows at all."""

    days_present = set(ny_date.tolist())
    span = pd.date_range(str(ny_date[0]), str(ny_date[-1]), tz="UTC")
    return sorted(
        str(x.date()) for x in span
        if x.weekday() != 5 and x.strftime("%Y-%m-%d") not in days_present
    )


def _side_scan(canonical: Path, inst: str, side: str, years: tuple[int, ...],
               fw: DiscoveryFirewall) -> pd.DataFrame:
    fw.guard_years(years)
    root = canonical / inst
    dataset = ds.dataset(root, format="parquet", partitioning="hive")
    lo, hi = int(min(years)), int(max(years))
    filt = (ds.field("price") == side) & (ds.field("year") >= lo) & (ds.field("year") <= hi)
    tbl = dataset.to_table(
        filter=filt,
        columns=["timestamp", "open", "high", "low", "close",
                 "observed", "executable_quote", "is_imputed", "session_valid"],
    )
    n_files = sum(
        1 for p in (root / f"price={side}").glob("year=*/month=*/day=*")
        if p.is_dir() and lo <= int(p.parts[-3].split("=")[1]) <= hi
    )
    fw.record(n_files, int(tbl.nbytes))
    df = tbl.to_pandas()
    df = df.drop(columns=["price", "year", "month", "day"], errors="ignore")
    return df


def load_instrument(canonical: Path, inst: str, years: tuple[int, ...],
                    fw: DiscoveryFirewall, cache_dir: Path | None = None,
                    freeze_hash: str = "", data_digest: str = "") -> InstrumentData:
    """Load + merge one instrument's canonical M1 grid for ``years`` (all < 2018)."""

    cache_key = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = cache_dir / f"merged_{inst}_{years[0]}_{years[-1]}.npz"
        if cache_key.exists():
            meta_path = cache_key.with_suffix(".meta.json")
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                fh_ok = meta.get("freeze_hash") == freeze_hash
                dd_ok = meta.get("data_digest") == data_digest
                if fh_ok and dd_ok:
                    z = np.load(cache_key)
                    data = _from_npz(inst, z)
                    if "missing_days" in z:
                        data.missing_days = [str(x) for x in z["missing_days"]]
                    else:  # legacy cache written before missing_days was persisted
                        data.missing_days = _missing_days(data.ny_date)
                    return data

    bid = _side_scan(canonical, inst, "bid", years, fw)
    ask = _side_scan(canonical, inst, "ask", years, fw)
    _cols = ("open", "high", "low", "close", "observed", "executable_quote", "is_imputed")
    m = pd.merge(
        bid.rename(columns={c: f"bid_{c}" for c in _cols}),
        ask.rename(columns={c: f"ask_{c}" for c in _cols}),
        on="timestamp", how="inner",
    ).sort_values("timestamp").reset_index(drop=True)
    if m.empty:
        raise RuntimeError(f"no canonical rows for {inst} {years}")

    ts = m["timestamp"].to_numpy(dtype=np.int64)
    ny = pd.to_datetime(ts, unit="ms", utc=True).tz_convert("America/New_York")
    ny_min = (ny.hour * 60 + ny.minute).to_numpy(dtype=np.int32)
    ny_date = ny.strftime("%Y-%m-%d").to_numpy()
    ny_year = ny.year.to_numpy(dtype=np.int32)

    bo = m["bid_open"].to_numpy(dtype=np.float64)
    bh = m["bid_high"].to_numpy(dtype=np.float64)
    bl = m["bid_low"].to_numpy(dtype=np.float64)
    bc = m["bid_close"].to_numpy(dtype=np.float64)
    ao = m["ask_open"].to_numpy(dtype=np.float64)
    ah = m["ask_high"].to_numpy(dtype=np.float64)
    al = m["ask_low"].to_numpy(dtype=np.float64)
    ac = m["ask_close"].to_numpy(dtype=np.float64)
    exec_mask = (m["bid_executable_quote"].to_numpy(dtype=bool)
                 & m["ask_executable_quote"].to_numpy(dtype=bool))
    obs_mask = (~m["bid_is_imputed"].to_numpy(dtype=bool)
                & ~m["ask_is_imputed"].to_numpy(dtype=bool)
                & m["bid_observed"].to_numpy(dtype=bool)
                & m["ask_observed"].to_numpy(dtype=bool))

    missing = _missing_days(ny_date)

    data = InstrumentData(
        inst=inst, ts=ts, bo=bo, bh=bh, bl=bl, bc=bc, ao=ao, ah=ah, al=al, ac=ac,
        exec=exec_mask, obs=obs_mask, ny_min=ny_min, ny_date=ny_date, ny_year=ny_year,
        o_idx=np.arange(0), o_mid=np.array([0.0]), o_ret=np.array([0.0]),
        o_mh=np.array([0.0]), o_ml=np.array([0.0]), o_mc=np.array([0.0]),
        o_spread=np.array([0.0]),
    )
    data.missing_days = missing
    _build_observed_subseries(data)
    compute_features(data)

    if cache_key is not None:
        _to_npz(data, cache_key)
        cache_key.with_suffix(".meta.json").write_text(json.dumps(
            {"freeze_hash": freeze_hash, "data_digest": data_digest,
             "feature_version": FEATURE_VERSION, "inst": inst,
             "years": [int(y) for y in years]}, indent=1))
    return data


def _build_observed_subseries(d: InstrumentData) -> None:
    idx = np.where(d.obs)[0]
    d.o_idx = idx
    d.o_mid = ((d.bc[idx] + d.ac[idx]) / 2.0).astype(np.float64)
    d.o_mh = ((d.bh[idx] + d.ah[idx]) / 2.0).astype(np.float64)
    d.o_ml = ((d.bl[idx] + d.al[idx]) / 2.0).astype(np.float64)
    d.o_mc = d.o_mid
    d.o_spread = (d.ac[idx] - d.bc[idx]).astype(np.float64)
    m = len(idx)
    if m >= 2:
        # o_ret[j] = log(mid[j+1]/mid[j]); aligned to o_mid[1:] (return measured across
        # gaps between real observations; an imputed minute never contributes a return)
        d.o_ret = np.log(d.o_mid[1:] / d.o_mid[:-1])
    else:
        d.o_ret = np.array([], dtype=np.float64)


def _roll_to_grid(values_obs: np.ndarray, idx_o: np.ndarray, n: int) -> np.ndarray:
    """Map an observed-sub-series value onto the clock grid (last observed <= t)."""

    j = np.searchsorted(idx_o, np.arange(n), side="right") - 1
    out = np.full(n, np.nan, dtype=np.float64)
    valid = j >= 0
    out[valid] = values_obs[j[valid]]
    return out


def _rolling_ols_tstat(y: np.ndarray, L: int) -> np.ndarray:
    """Right-aligned rolling OLS slope t-stat of ``y`` (observed sub-series) over L bars."""

    m = len(y)
    out = np.full(m, np.nan, dtype=np.float64)
    if m < L or L < 3:
        return out
    x = np.arange(L, dtype=np.float64)
    xbar = x.mean()
    sxx = float(((x - xbar) ** 2).sum())
    sy = pd.Series(y).rolling(L).sum().to_numpy()
    sy2 = pd.Series(y * y).rolling(L).sum().to_numpy()
    sxy = np.convolve(y, x[::-1], mode="valid")
    sxy_full = np.full(m, np.nan, dtype=np.float64)
    sxy_full[L - 1:] = sxy
    with np.errstate(invalid="ignore", divide="ignore"):
        syy = sy2 - sy * sy / L
        beta = (sxy_full - xbar * sy) / sxx
        sse = syy - beta * beta * sxx
        ok = np.isfinite(syy) & np.isfinite(beta) & (sse > 1e-30)
        denom = np.sqrt(np.maximum(sse, 1e-30))
        t = np.where(ok, beta * math.sqrt(sxx) * math.sqrt(L - 2) / denom, np.nan)
    out[:] = t
    return out


def _rolling_zscore(x: np.ndarray, W: int) -> np.ndarray:
    s = pd.Series(x)
    mu = s.rolling(W).mean().to_numpy()
    sd = s.rolling(W).std().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where((sd > 1e-12) & np.isfinite(mu), (x - mu) / np.maximum(sd, 1e-12), np.nan)
    return z


def compute_features(d: InstrumentData) -> None:
    """Compute the frozen causal feature set (observed sub-series, mapped to clock grid)."""

    o_mid, o_ret = d.o_mid, d.o_ret
    o_mh, o_ml, o_spread = d.o_mh, d.o_ml, d.o_spread
    idx_o, n = d.o_idx, d.n
    m = len(o_mid)
    f: dict[str, np.ndarray] = {}
    if m < 10:
        d.feat = f
        return

    # --- base (clock grid) ---
    f["mid"] = _roll_to_grid(o_mid, idx_o, n)
    f["spread"] = _roll_to_grid(o_spread, idx_o, n)

    # --- volatility / range (observed sub-series, right-aligned) ---
    # o_ret[j] arrives at observed row j+1: align to o_mid rows by prepending one NaN
    rv = np.full(len(o_mid), np.nan, dtype=np.float64)
    if len(o_ret):
        rv[1:] = pd.Series(o_ret).rolling(60).std().to_numpy()
    f["realized_vol"] = _roll_to_grid(np.nan_to_num(rv, nan=0.0), idx_o, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        hi = np.maximum(o_mh, 1e-12)
        lo = np.maximum(o_ml, 1e-12)
        p2 = np.where((o_mh > 0) & (o_ml > 0), np.log(hi / lo) ** 2, np.nan)
    pk = np.sqrt(pd.Series(p2).rolling(60).mean().to_numpy() / (4.0 * math.log(2.0)))
    f["parkinson_vol"] = _roll_to_grid(np.nan_to_num(pk, nan=0.0), idx_o, n)
    tr = np.empty(m, dtype=np.float64)
    tr[0] = o_mh[0] - o_ml[0]
    tr[1:] = np.maximum(o_mh[1:] - o_ml[1:],
                        np.maximum(np.abs(o_mh[1:] - o_mid[:-1]), np.abs(o_ml[1:] - o_mid[:-1])))
    atr = pd.Series(tr).ewm(alpha=1.0 / 14.0, adjust=False).mean().to_numpy()
    f["atr"] = _roll_to_grid(atr, idx_o, n)
    hl = o_mh - o_ml
    with np.errstate(invalid="ignore", divide="ignore"):
        rc = np.where(pd.Series(hl).rolling(60).mean().to_numpy() > 1e-12,
                      hl / np.maximum(pd.Series(hl).rolling(60).mean().to_numpy(), 1e-12), np.nan)
    f["range_compression"] = _roll_to_grid(np.nan_to_num(rc, nan=1.0), idx_o, n)

    # --- momentum / trend at the frozen intraday lookback scale ---
    for L in (15, 30, 60, 120, 240):
        f[f"trend_slope_{L}"] = _roll_to_grid(_rolling_ols_tstat(o_mid, L), idx_o, n)
        if m > L:
            r_l = np.full(m, np.nan, dtype=np.float64)
            r_l[L:] = np.log(o_mid[L:] / o_mid[:-L])
            f[f"mom_z_{L}"] = _roll_to_grid(_rolling_zscore(r_l, _z_window(L)), idx_o, n)
        else:
            f[f"mom_z_{L}"] = np.full(n, np.nan)
    for L2 in (480,):
        f[f"trend_slope_{L2}"] = _roll_to_grid(_rolling_ols_tstat(o_mid, L2), idx_o, n)

    # --- mean reversion at the frozen halflife scale ---
    for S in (30, 100, 300, 1000):
        ewma = pd.Series(o_mid).ewm(span=S, adjust=False).mean().to_numpy()
        dist = o_mid - ewma
        f[f"dist_z_{S}"] = _roll_to_grid(_rolling_zscore(dist, _z_window(S)), idx_o, n)

    # --- spread state ---
    f["spread_z"] = _roll_to_grid(_rolling_zscore(o_spread, 480), idx_o, n)

    # --- clock features (may advance with time; not stateful market features) ---
    ny_min = d.ny_min
    sess = np.where(ny_min < 8 * 60, 0, np.where(ny_min < 13 * 60, 1,
                                                 np.where(ny_min < 17 * 60, 2, 3)))
    f["session_cell"] = sess.astype(np.float64)
    tdt = pd.to_datetime(d.ts, unit="ms", utc=True).tz_convert("America/New_York")
    f["calendar_cell"] = tdt.dayofweek.to_numpy(dtype=np.float64)

    d.feat = f


def _to_npz(d: InstrumentData, path: Path) -> None:
    arrays: dict[str, Any] = {
        "ts": d.ts, "bo": d.bo, "bh": d.bh, "bl": d.bl, "bc": d.bc,
        "ao": d.ao, "ah": d.ah, "al": d.al, "ac": d.ac,
        "exec": d.exec, "obs": d.obs, "ny_min": d.ny_min,
        "ny_date": d.ny_date.astype("U10"), "ny_year": d.ny_year,
        "o_idx": d.o_idx, "o_mid": d.o_mid, "o_ret": d.o_ret,
        "o_mh": d.o_mh, "o_ml": d.o_ml, "o_spread": d.o_spread,
        "missing_days": np.array(d.missing_days, dtype="U10"),
    }
    for k, v in d.feat.items():
        arrays[f"feat_{k}"] = v.astype(np.float32)
    np.savez_compressed(path, **arrays)


def _from_npz(inst: str, z: Any) -> InstrumentData:
    d = InstrumentData(
        inst=inst,
        ts=z["ts"], bo=z["bo"], bh=z["bh"], bl=z["bl"], bc=z["bc"],
        ao=z["ao"], ah=z["ah"], al=z["al"], ac=z["ac"],
        exec=z["exec"], obs=z["obs"], ny_min=z["ny_min"],
        ny_date=z["ny_date"], ny_year=z["ny_year"],
        o_idx=z["o_idx"], o_mid=z["o_mid"], o_ret=z["o_ret"],
        o_mh=z["o_mh"], o_ml=z["o_ml"], o_mc=z["o_mid"].copy(), o_spread=z["o_spread"],
    )
    d.feat = {k[len("feat_"):]: v.astype(np.float64) for k, v in z.items()
              if k.startswith("feat_")}
    return d


def sync_observed_mask(datas: dict[str, InstrumentData]) -> np.ndarray:
    """Clock grid (of the first instrument) + mask of timestamps where EVERY leg is observed."""

    base = next(iter(datas.values()))
    n = base.n
    grid_ok = np.ones(n, dtype=bool)
    for d in datas.values():
        if d.n != n or not np.array_equal(d.ts, base.ts):
            # grids must be identical (shared M1 UTC clock); fall back to intersection
            grid_ok &= np.isin(base.ts, d.ts)
        else:
            grid_ok &= d.obs
    return grid_ok


def daily_close_grid(d: InstrumentData) -> tuple[np.ndarray, np.ndarray]:
    """(ny_date, day-close mid) per NY trading day; close = last executable bar of the day
    (falls back to the last observed bar when the day has no executable bar)."""

    dates = d.ny_date
    mids = (d.bc + d.ac) / 2.0
    out_dates: list[str] = []
    out_mids: list[float] = []
    i = 0
    n = d.n
    while i < n:
        day = dates[i]
        j = i
        while j + 1 < n and dates[j + 1] == day:
            j += 1
        seg = slice(i, j + 1)
        exec_idx = np.where(d.exec[seg])[0]
        if exec_idx.size:
            k = int(exec_idx[-1])
        else:
            obs_idx = np.where(d.obs[seg])[0]
            if not obs_idx.size:
                i = j + 1
                continue
            k = int(obs_idx[-1])
        out_dates.append(day)
        out_mids.append(float(mids[seg.start + k]))
        i = j + 1
    return np.array(out_dates), np.array(out_mids, dtype=np.float64)
