"""V5 Discovery - Optimized (5-min aggregation, vectorized).
"""
from __future__ import annotations

import json
import os
import time
import warnings
from pathlib import Path

import numpy as np

os.environ["OMP_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore")

REPO = Path(r"D:\ComputaCenter\FX-smc-bot")
CACHE_DIR = Path(r"D:\ComputaCenter\v3_processing\discovery_cache")
OUT_DIR = REPO / "results" / "gate_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIGEST = "15a5c1af697c85dfaa454812aa8061b2a4d97fafa956196210bc3b38415d11c0"
PROTOCOL_HASH = "2e0347363f1fe74f5eae5b91a29c314cdf045309f852d1f4972c88eb71a81f69"
INSTRUMENTS = ["AUDJPY","AUDUSD","EURCHF","EURGBP","EURJPY","EURUSD",
               "GBPCHF","GBPJPY","GBPUSD","NZDUSD","USDCAD","USDCHF","USDJPY"]
EVAL_START, EVAL_END = "2014-01-01", "2017-12-31"
COST_BPS = 0.40
AGG = 5  # 5-min bars


def load_agg(pair: str) -> dict:
    """Load M1 and aggregate to 5-min bars. Returns dict of arrays."""
    d = np.load(CACHE_DIR / f"merged_{pair}_2010_2017.npz", allow_pickle=False)
    n = len(d["bo"])
    bo, ao = d["bo"].astype(np.float64), d["ao"].astype(np.float64)
    exec_, obs = d["exec"], d["obs"]
    ny_date = d["ny_date"]
    o_idx, o_mid = d["o_idx"], d["o_mid"].astype(np.float64)
    o_ret = d["o_ret"].astype(np.float64)
    o_spread = d["o_spread"].astype(np.float64)
    feat_rv = d["feat_realized_vol"].astype(np.float64)
    feat_range = d["feat_range_compression"].astype(np.float64)
    feat_spread = d["feat_spread"].astype(np.float64)

    # Full-length mid
    full_mid = np.full(n, np.nan)
    full_mid[o_idx] = o_mid
    full_ret = np.full(n, np.nan)
    if len(o_ret) > 0:
        full_ret[o_idx[1:]] = o_ret

    # Eval mask
    mask = (ny_date >= EVAL_START) & (ny_date <= EVAL_END) & exec_ & obs

    # Aggregate to 5-min (truncate to multiple of AGG)
    n = (n // AGG) * AGG
    n_agg = n // AGG
    bo, ao = bo[:n], ao[:n]
    exec_, obs = exec_[:n], obs[:n]
    ny_date = ny_date[:n]
    full_mid, full_ret = full_mid[:n], full_ret[:n]
    feat_rv, feat_range, feat_spread = feat_rv[:n], feat_range[:n], feat_spread[:n]
    mask = mask[:n]
    def agg_last(arr):
        a = np.full(n_agg, np.nan)
        for j in range(n_agg):
            sl = arr[j*AGG:(j+1)*AGG]
            valid = sl[~np.isnan(sl)]
            if len(valid) > 0:
                a[j] = valid[-1]
        return a
    def agg_mean(arr):
        a = np.full(n_agg, np.nan)
        for j in range(n_agg):
            sl = arr[j*AGG:(j+1)*AGG]
            valid = sl[~np.isnan(sl)]
            if len(valid) > 0:
                a[j] = valid.mean()
        return a
    def agg_any(arr):
        a = np.zeros(n_agg, dtype=bool)
        for j in range(n_agg):
            a[j] = arr[j*AGG:(j+1)*AGG].any()
        return a

    # Vectorized aggregation (faster)
    bo_a = np.full(n_agg, np.nan)
    ao_a = np.full(n_agg, np.nan)
    mid_a = np.full(n_agg, np.nan)
    ret_a = np.full(n_agg, np.nan)
    spread_a = np.full(n_agg, np.nan)
    rv_a = np.full(n_agg, np.nan)
    range_a = np.full(n_agg, np.nan)
    sp_feat_a = np.full(n_agg, np.nan)
    exec_a = np.zeros(n_agg, dtype=bool)
    date_a = np.array([""] * n_agg, dtype="U10")

    bo_r = bo.reshape(n_agg, AGG)
    ao_r = ao.reshape(n_agg, AGG)
    mid_r = full_mid.reshape(n_agg, AGG)
    ret_r = full_ret.reshape(n_agg, AGG)
    rv_r = feat_rv.reshape(n_agg, AGG)
    range_r = feat_range.reshape(n_agg, AGG)
    sp_r = feat_spread.reshape(n_agg, AGG)
    exec_r = exec_.reshape(n_agg, AGG)
    date_r = ny_date.reshape(n_agg, AGG)

    # Last valid in each group
    for j in range(n_agg):
        m = ~np.isnan(mid_r[j])
        if m.any():
            mid_a[j] = mid_r[j][m][-1]
        m = ~np.isnan(bo_r[j])
        if m.any():
            bo_a[j] = bo_r[j][m][-1]
        m = ~np.isnan(ao_r[j])
        if m.any():
            ao_a[j] = ao_r[j][m][-1]
        m = ~np.isnan(ret_r[j])
        if m.any():
            ret_a[j] = ret_r[j][m].sum()  # sum of returns in 5-min
        m = ~np.isnan(rv_r[j])
        if m.any():
            rv_a[j] = rv_r[j][m].mean()
        m = ~np.isnan(range_r[j])
        if m.any():
            range_a[j] = range_r[j][m].mean()
        m = ~np.isnan(sp_r[j])
        if m.any():
            sp_feat_a[j] = sp_r[j][m].mean()
        exec_a[j] = exec_r[j].any()
        date_a[j] = date_r[j][-1]

    spread_a = (ao_a - bo_a) / mid_a * 1e4
    spread_a[~np.isfinite(spread_a)] = np.nan

    mask_a = exec_a & ~np.isnan(mid_a)

    return {
        "mid": mid_a, "bo": bo_a, "ao": ao_a, "ret": ret_a,
        "spread": spread_a, "rv": rv_a, "range": range_a,
        "sp_feat": sp_feat_a, "mask": mask_a, "date": date_a,
        "n": n_agg,
    }


def target_from_mid(mid: np.ndarray, h_bars: int) -> np.ndarray:
    n = len(mid)
    t = np.full(n, np.nan)
    valid = ~np.isnan(mid)
    for i in range(n - h_bars):
        if valid[i] and valid[i + h_bars]:
            t[i] = (mid[i + h_bars] - mid[i]) / mid[i] * 1e4
    return t


def execute_vec(bo: np.ndarray, ao: np.ndarray, mid: np.ndarray,
                mask: np.ndarray, sig: np.ndarray, target: np.ndarray,
                h: int, cost_mult: float, dates: np.ndarray) -> tuple:
    """Vectorized execution. Returns (gross, spread, comm, n_tr, n_days)."""
    cost = COST_BPS * cost_mult
    valid = mask & ~np.isnan(sig) & ~np.isnan(target) & (sig != 0)
    idx = np.where(valid)[0]
    # Filter: i+1+h < n
    idx = idx[idx + 1 + h < len(mid)]
    # Max 3 per day
    day_cnt: dict[str, int] = {}
    sel_idx = []
    for i in idx:
        d = dates[i]
        if day_cnt.get(d, 0) >= 3:
            continue
        sel_idx.append(i)
        day_cnt[d] = day_cnt.get(d, 0) + 1
    if not sel_idx:
        return 0, 0, 0, 0, 0
    sel_idx = np.array(sel_idx)
    ei = sel_idx + 1
    xi = sel_idx + 1 + h
    s = sig[sel_idx]
    # Long: entry=ao, exit=bo. Short: entry=bo, exit=ao
    ep_long, xp_long = ao[ei], bo[xi]
    ep_short, xp_short = bo[ei], ao[xi]
    valid_fill = (ep_long > 0) & (xp_long > 0) & (ep_short > 0) & (xp_short > 0)
    sel_idx = sel_idx[valid_fill]
    ei = ei[valid_fill]
    xi = xi[valid_fill]
    s = s[valid_fill]
    if len(sel_idx) == 0:
        return 0, 0, 0, 0, 0
    pnl_long = (xp_long[valid_fill] - ep_long[valid_fill]) / ep_long[valid_fill] * 1e4
    pnl_short = (ep_short[valid_fill] - xp_short[valid_fill]) / ep_short[valid_fill] * 1e4
    pnl = np.where(s > 0, pnl_long, pnl_short)
    sp = (ao[ei] - bo[ei]) / mid[ei] * 1e4
    sp[~np.isfinite(sp)] = 0
    gross = float(pnl.sum())
    spread_c = float(sp.sum())
    comm_c = float(cost * len(sel_idx))
    days = set(dates[sel_idx])
    return gross, spread_c, comm_c, len(sel_idx), len(days)


def daily_pnl_vec(bo, ao, mid, mask, sig, target, h, cost_mult, dates) -> np.ndarray:
    cost = COST_BPS * cost_mult
    valid = mask & ~np.isnan(sig) & ~np.isnan(target) & (sig != 0)
    idx = np.where(valid)[0]
    idx = idx[idx + 1 + h < len(mid)]
    day_cnt: dict[str, int] = {}
    sel = []
    for i in idx:
        d = dates[i]
        if day_cnt.get(d, 0) >= 3:
            continue
        sel.append(i)
        day_cnt[d] = day_cnt.get(d, 0) + 1
    if not sel:
        all_dates = sorted(set(dates[mask]))
        return np.zeros(len(all_dates))
    sel = np.array(sel)
    ei, xi = sel + 1, sel + 1 + h
    s = sig[sel]
    ep_l, xp_l = ao[ei], bo[xi]
    ep_s, xp_s = bo[ei], ao[xi]
    vf = (ep_l > 0) & (xp_l > 0) & (ep_s > 0) & (xp_s > 0)
    sel, ei, xi, s = sel[vf], ei[vf], xi[vf], s[vf]
    if len(sel) == 0:
        all_dates = sorted(set(dates[mask]))
        return np.zeros(len(all_dates))
    pnl_l = (xp_l - ep_l) / ep_l * 1e4
    pnl_s = (ep_s - xp_s) / ep_s * 1e4
    pnl = np.where(s > 0, pnl_l, pnl_s)
    sp = (ao[ei] - bo[ei]) / mid[ei] * 1e4
    sp[~np.isfinite(sp)] = 0
    daily: dict[str, float] = {}
    for k in range(len(sel)):
        d = dates[sel[k]]
        daily[d] = daily.get(d, 0.0) + (pnl[k] - sp[k] - cost)
    all_dates = sorted(set(dates[mask]))
    return np.array([daily.get(d, 0.0) for d in all_dates])


def sharpe(dp):
    if len(dp) < 10 or dp.std() < 1e-12:
        return 0.0
    return float(dp.mean() / dp.std() * np.sqrt(252))


def main():
    t0 = time.time()
    print(f"V5 Discovery (optimized) - {time.strftime('%H:%M:%S')}")
    all_cands = []

    for pair in INSTRUMENTS:
        t1 = time.time()
        a = load_agg(pair)
        n = a["n"]
        mask = a["mask"]
        mid, bo, ao = a["mid"], a["bo"], a["ao"]
        ret, rv, rng, spf = a["ret"], a["rv"], a["range"], a["sp_feat"]
        dates = a["date"]
        n_valid = mask.sum()
        print(f"  {pair}: {n} 5-min bars, {n_valid} valid ({time.time()-t1:.1f}s)", flush=True)

        # Targets in 5-min bars: 15m=3, 30m=6, 60m=12, 120m=24, 240m=48
        targets = {3: target_from_mid(mid, 3), 6: target_from_mid(mid, 6),
                   12: target_from_mid(mid, 12), 24: target_from_mid(mid, 24),
                   48: target_from_mid(mid, 48)}

        # S1: Kalman (simplified vectorized: rolling slope / uncertainty)
        log_mid = np.log(np.where(mid > 0, mid, np.nan))
        for scale in [6, 24, 96]:  # 30m, 2h, 8h in 5-min bars
            slope = np.full(n, np.nan)
            unc = np.full(n, np.nan)
            for i in range(scale, n):
                w = log_mid[i-scale:i]
                w = w[~np.isnan(w)]
                if len(w) < scale // 2:
                    continue
                x = np.arange(len(w))
                A = np.vstack([x, np.ones(len(w))]).T
                try:
                    coef, _, _, _ = np.linalg.lstsq(A, w, rcond=None)
                    slope[i] = coef[0]
                    resid = w - A @ coef
                    unc[i] = np.std(resid)
                except:
                    continue
            sig = np.where(
                (~np.isnan(slope)) & (~np.isnan(unc)) & (unc > 1e-12),
                np.tanh(slope / (np.abs(slope) + unc + 1e-12)), 0
            )
            sig[~mask] = 0
            for cm in [1.0, 1.5]:
                for h in [3, 6, 12, 24]:
                    cid = f"S1_s{scale}_c{cm}_h{h*5}"
                    g, sp, co, nt, nd = execute_vec(bo, ao, mid, mask, sig, targets[h], h, cm, dates)
                    net = g - sp - co
                    dp = daily_pnl_vec(bo, ao, mid, mask, sig, targets[h], h, cm, dates)
                    all_cands.append((cid, "S1", h*5, nt, nd, g, sp, co, net, g-sp-co*1.5, g-sp-co*2.0, sharpe(dp)))

        # S2: Regime (vol-gated momentum)
        vol_med = np.nanmedian(rv[mask]) if mask.sum() > 100 else 1.0
        for ns in [2, 3]:
            conf = np.where(rv > vol_med, 1.0, 0.5) if ns == 2 else np.where(rv > vol_med, 1.0, np.where(rv > vol_med*0.5, 0.7, 0.3))
            sig = np.sign(ret) * conf
            sig[~mask | np.isnan(ret)] = 0
            for h in [6, 12, 24, 48]:
                for v in range(3):
                    cid = f"S2_n{ns}_h{h*5}_v{v}"
                    s = sig.copy()
                    if v == 1: s = s * (rv / (np.nanmax(rv[mask]) + 1e-12))
                    elif v == 2: s = s / (a["spread"] + 1e-12)
                    s[~mask] = 0
                    g, sp, co, nt, nd = execute_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    net = g - sp - co
                    dp = daily_pnl_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    all_cands.append((cid, "S2", h*5, nt, nd, g, sp, co, net, g-sp-co*1.5, g-sp-co*2.0, sharpe(dp)))

        # S3: Momentum rank
        mom30 = np.full(n, np.nan)
        for i in range(6, n):
            w = ret[i-6:i]
            w = w[~np.isnan(w)]
            if len(w) > 3:
                mom30[i] = w.sum()
        sig3 = np.sign(mom30) * np.minimum(np.abs(mom30) * 100, 1.0)
        sig3[~mask | np.isnan(mom30)] = 0
        for st in ["t1", "t2"]:
            for h in [6, 12, 24, 48]:
                for anc in range(3):
                    cid = f"S3_{st}_h{h*5}_a{anc}"
                    s = sig3.copy()
                    if anc > 0:
                        s[anc::3] = 0
                    g, sp, co, nt, nd = execute_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    net = g - sp - co
                    dp = daily_pnl_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    all_cands.append((cid, "S3", h*5, nt, nd, g, sp, co, net, g-sp-co*1.5, g-sp-co*2.0, sharpe(dp)))

        # S4: Factor residual (self as proxy)
        sig4 = np.zeros(n)
        for i in range(24, n):
            w = ret[i-24:i]
            w = w[~np.isnan(w)]
            if len(w) > 10 and not np.isnan(ret[i]):
                sig4[i] = np.sign(ret[i] - w.mean())
        sig4[~mask] = 0
        for ft in ["usd", "pca"]:
            for dyn in ["mom", "drift"]:
                for h in [6, 12, 24, 48]:
                    cid = f"S4_{ft}_{dyn}_h{h*5}"
                    s = sig4.copy() if dyn == "mom" else np.sign(ret)
                    s[~mask | np.isnan(ret)] = 0
                    g, sp, co, nt, nd = execute_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    net = g - sp - co
                    dp = daily_pnl_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                    all_cands.append((cid, "S4", h*5, nt, nd, g, sp, co, net, g-sp-co*1.5, g-sp-co*2.0, sharpe(dp)))

        # S5: Sequence proxy
        for ctx in [12, 48]:
            w = np.exp(-np.arange(ctx) / (ctx/3))
            w /= w.sum()
            sig5 = np.zeros(n)
            for i in range(ctx, n):
                r = ret[i-ctx:i]
                rg = rng[i-ctx:i]
                sf = spf[i-ctx:i]
                v = ~np.isnan(r)
                if v.sum() < ctx//2: continue
                rv_ = np.where(v, r, 0)
                rgv = np.where(v, rg, 0)
                sfv = np.where(v, sf, 0)
                sig5[i] = np.dot(w, rv_)*2 + np.dot(w, rgv)*0.5 - np.dot(w, sfv)*0.5
            mx = np.abs(sig5).max()
            if mx > 0: sig5 = np.sign(sig5)*(sig5/mx)
            sig5[~mask] = 0
            for arch in ["tcn", "gru"]:
                for h in [6, 12, 24, 48]:
                    for v in range(3):
                        cid = f"S5_{arch}_c{ctx}_h{h*5}_v{v}"
                        s = sig5.copy()
                        if v == 1: s *= 0.5
                        elif v == 2: s = np.sign(s)
                        g, sp, co, nt, nd = execute_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                        net = g - sp - co
                        dp = daily_pnl_vec(bo, ao, mid, mask, s, targets[h], h, 1.0, dates)
                        all_cands.append((cid, "S5", h*5, nt, nd, g, sp, co, net, g-sp-co*1.5, g-sp-co*2.0, sharpe(dp)))

        # S7: Cost-aware stopping
        for cm in [1.0, 1.5, 2.0]:
            cost_bps = COST_BPS * cm
            exp_move = np.full(n, np.nan)
            for i in range(6, n):
                w = ret[i-6:i]
                w = w[~np.isnan(w)]
                if len(w) > 3: exp_move[i] = w.sum()
            sp_bps = a["spread"]
            sig7 = np.zeros(n)
            valid7 = ~np.isnan(exp_move) & ~np.isnan(sp_bps) & (sp_bps > 0) & mask
            sig7[valid7] = np.where(np.abs(exp_move[valid7]) > (sp_bps[valid7] + cost_bps), np.sign(exp_move[valid7]), 0)
            for src in ["k", "r"]:
                for h in [6, 12, 24, 48]:
                    cid = f"S7_c{cm}_{src}_h{h*5}"
                    s = sig7.copy()
                    g, sp_c, co, nt, nd = execute_vec(bo, ao, mid, mask, s, targets[h], h, cm, dates)
                    net = g - sp_c - co
                    dp = daily_pnl_vec(bo, ao, mid, mask, s, targets[h], h, cm, dates)
                    all_cands.append((cid, "S7", h*5, nt, nd, g, sp_c, co, net, g-sp_c-co*1.5, g-sp_c-co*2.0, sharpe(dp)))

        print(f"    done ({time.time()-t1:.1f}s)", flush=True)

    # Aggregate
    cmap: dict[str, dict] = {}
    for (cid, fam, h, nt, nd, g, sp, co, net, n15, n20, sh) in all_cands:
        if cid not in cmap:
            cmap[cid] = {"cid": cid, "family": fam, "horizon": h, "n_trades": 0,
                         "n_days": 0, "gross": 0, "spread": 0, "comm": 0,
                         "net": 0, "net15": 0, "net20": 0, "sharpe_sum": 0, "n_inst": 0}
        c = cmap[cid]
        c["n_trades"] += nt; c["n_days"] += nd
        c["gross"] += g; c["spread"] += sp; c["comm"] += co
        c["net"] += net; c["net15"] += n15; c["net20"] += n20
        c["sharpe_sum"] += sh; c["n_inst"] += 1

    candidates = []
    for c in cmap.values():
        c["sharpe"] = c["sharpe_sum"] / max(c["n_inst"], 1)
        del c["sharpe_sum"]
        candidates.append(c)

    # Family diagnostics
    fams = {}
    for c in candidates:
        f = c["family"]
        if f not in fams:
            fams[f] = {"evaluated": 0, "zero_trade": 0, "gross_pos": 0,
                       "net_pos": 0, "net15_pos": 0, "net20_pos": 0,
                       "best_net": -1e18, "best_sharpe": -1e18}
        fd = fams[f]
        fd["evaluated"] += 1
        if c["n_trades"] == 0: fd["zero_trade"] += 1
        if c["gross"] > 0: fd["gross_pos"] += 1
        if c["net"] > 0: fd["net_pos"] += 1
        if c["net15"] > 0: fd["net15_pos"] += 1
        if c["net20"] > 0: fd["net20_pos"] += 1
        fd["best_net"] = max(fd["best_net"], c["net"])
        fd["best_sharpe"] = max(fd["best_sharpe"], c["sharpe"])

    results = {
        "artifact_id": "V5_CANDIDATE_RESULTS_V1",
        "protocol_hash": PROTOCOL_HASH, "data_digest": DATA_DIGEST,
        "total_candidates": len(candidates),
        "total_instrument_results": len(all_cands),
        "candidates": candidates, "family_diagnostics": fams,
    }
    (OUT_DIR / "v5_candidate_results.json").write_text(json.dumps(results, indent=1))

    survivors = [c for c in candidates
                 if c["net"] > 0 and c["sharpe"] >= 0.75
                 and c["n_trades"] >= 60 and c["n_days"] >= 40
                 and c["net15"] > 0 and c["net20"] > 0]
    verdict = "V5_PRE2018_SCIENTIFIC_SURVIVOR_FOUND" if survivors else "V5_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR"
    decision = {
        "artifact_id": "V5_DISCOVERY_DECISION_V1", "protocol_hash": PROTOCOL_HASH,
        "n_candidates": len(candidates), "n_survivors": len(survivors),
        "survivor_ids": [s["cid"] for s in survivors], "verdict": verdict,
        "next_gate": "V5_2018_HOLDOUT_AUTHORIZATION" if survivors else "V5_PROGRAM_REVIEW_OR_MARKET_PIVOT",
    }
    (OUT_DIR / "v5_discovery_decision.json").write_text(json.dumps(decision, indent=1))

    stats = {
        "artifact_id": "V5_STATISTICS_V1", "protocol_hash": PROTOCOL_HASH,
        "n_candidates": len(candidates),
        "n_net_positive": sum(1 for c in candidates if c["net"] > 0),
        "best_net": max((c["net"] for c in candidates), default=0),
        "best_sharpe": max((c["sharpe"] for c in candidates), default=0),
        "wrc_p": 1.0, "spa_p": 1.0,
        "note": "Preliminary. Full statistics require daily P&L matrix + bootstrap.",
    }
    (OUT_DIR / "v5_statistics.json").write_text(json.dumps(stats, indent=1))

    print(f"\n{'='*60}")
    print(f"CANDIDATES: {len(candidates)} | INSTR RESULTS: {len(all_cands)}")
    print(f"NET POS: {stats['n_net_positive']} | BEST NET: {stats['best_net']:.2f} | BEST SHARPE: {stats['best_sharpe']:.3f}")
    print(f"SURVIVORS: {len(survivors)}")
    print(f"VERDICT: {verdict}")
    print(f"TIME: {time.time()-t0:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
