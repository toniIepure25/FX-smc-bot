"""V5R Discovery Runner - True Structural Models.
POST-PROSPECTIVE-SEAL. All code in git.
"""
from __future__ import annotations
import json, os, sys, time, warnings
from pathlib import Path
import numpy as np

os.environ["OMP_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore")

REPO = Path(r"D:\ComputaCenter\FX-smc-bot")
sys.path.insert(0, str(REPO / "src"))

from fx_smc_bot.research.v5r.data import load_5min, load_panel, INSTRUMENTS, EVAL_START, EVAL_END
from fx_smc_bot.research.v5r.kalman import kalman_signal
from fx_smc_bot.research.v5r.gmm_regime import fit_gmm_causal
from fx_smc_bot.research.v5r.cross_sectional import panel_pnl
from fx_smc_bot.research.v5r.pca_factor import causal_pca_signal
from fx_smc_bot.research.v5r.sequence_models import train_sequence_model
from fx_smc_bot.research.v5r.cost_aware import cost_aware_signal
from fx_smc_bot.research.v5r.execution import execute, sharpe
from fx_smc_bot.research.v5r.statistics import (
    wrc_test, spa_test, romano_wolf, holm, bh_fdr, psr, dsr, cscv_pbo
)

OUT = REPO / "results" / "gate_v5r"
OUT.mkdir(parents=True, exist_ok=True)
DATA_DIGEST = "15a5c1af697c85dfaa454812aa8061b2a4d97fafa956196210bc3b38415d11c0"
PROTOCOL_HASH = ""  # Will be computed from protocol file


def main():
    t0 = time.time()
    print(f"V5R TRUE STRUCTURAL MODELS RUN - {time.strftime('%H:%M:%S')}")
    print(f"Data digest: {DATA_DIGEST}")
    
    # Load protocol hash
    proto = json.loads((OUT / "v5r_prospective_protocol.json").read_text())
    PROTOCOL_HASH = json.dumps(proto, sort_keys=True).encode()
    import hashlib
    PROTOCOL_HASH = hashlib.sha256(PROTOCOL_HASH).hexdigest()
    print(f"Protocol hash: {PROTOCOL_HASH}")
    
    # Load panel
    print("Loading panel...")
    panel = load_panel()
    ref = panel[INSTRUMENTS[0]]
    n = ref["n"]
    print(f"  {n} 5-min bars, {len(INSTRUMENTS)} instruments")
    
    all_cands = []  # (cid, family, horizon, n_trades, gross, spread, comm, net, net15, net20, sharpe, daily_pnl)
    
    # ============================================================
    # R1: TRUE KALMAN (24 candidates)
    # ============================================================
    print("\n=== R1: True Kalman ===")
    for pair in INSTRUMENTS:
        a = panel[pair]
        mid, bo, ao = a["mid"], a["bo"], a["ao"]
        mask = a["eval_mask"]
        dates_p = a["date"]
        log_mid = np.log(np.where(mid > 0, mid, np.nan))
        
        for scale in [6, 24, 96]:  # 30m, 2h, 8h in 5-min bars
            sig, slope, unc = kalman_signal(log_mid, scale)
            sig[~mask] = 0
            for cm in [1.0, 1.5]:
                for h in [3, 6, 12, 24]:  # 15,30,60,120 min
                    cid = f"R1_s{scale}_c{cm}_h{h*5}"
                    g, sp, co, nt, dp = execute(bo, ao, mid, mask, sig, h, dates_p, cm)
                    net = g - co
                    net15 = g - co * 1.5
                    net20 = g - co * 2.0
                    all_cands.append((cid, "R1", h*5, nt, g, sp, co, net, net15, net20, sharpe(dp), dp))
        print(f"  {pair} done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # R2: TRUE GMM (8 candidates)
    # ============================================================
    print("\n=== R2: True GMM ===")
    for pair in INSTRUMENTS:
        a = panel[pair]
        mid, bo, ao = a["mid"], a["bo"], a["ao"]
        mask = a["eval_mask"]
        dates_p = a["date"]
        n_p = a["n"]
        ret, rv, rng, sp = a["ret"], a["rv"], a["range"], a["sp"]
        
        # Build features: [return, vol, range, spread, trend]
        trend = np.zeros(n_p)
        for i in range(6, n_p):
            w = ret[i-6:i]
            w = w[~np.isnan(w)]
            if len(w) > 3:
                trend[i] = w.sum()
        features = np.column_stack([ret, rv, rng, sp, trend])
        
        for nc in [2, 3]:
            sig, probs = fit_gmm_causal(features, dates_p, EVAL_START, nc)
            sig[~mask] = 0
            for h in [6, 12, 24, 48]:  # 30,60,120,240 min
                cid = f"R2_n{nc}_h{h*5}"
                g, sp_c, co, nt, dp = execute(bo, ao, mid, mask, sig, h, dates_p, 1.0)
                net = g - co
                all_cands.append((cid, "R2", h*5, nt, g, sp_c, co, net, g-co*1.5, g-co*2.0, sharpe(dp), dp))
        print(f"  {pair} done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # R3: TRUE CROSS-SECTIONAL (8 candidates)
    # ============================================================
    print("\n=== R3: True Cross-Sectional ===")
    ref_dates = panel[INSTRUMENTS[0]]["date"]
    ref_mask = panel[INSTRUMENTS[0]]["eval_mask"]
    for structure in ["top1_vs_bottom1", "top2_vs_bottom2"]:
        for h in [6, 12, 24, 48]:
            cid = f"R3_{structure[:4]}_h{h*5}"
            # Panel P&L: one column (uses reference dates for alignment)
            dp = panel_pnl(panel, ref_dates, ref_mask, h, structure)
            n_active = int((dp != 0).sum())
            gross = float(dp.sum())
            all_cands.append((cid, "R3", h*5, n_active, gross, 0, 0, gross, gross, gross, sharpe(dp), dp))
    print(f"  Done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # R4: TRUE PCA FACTOR (16 candidates)
    # ============================================================
    print("\n=== R4: True PCA Factor ===")
    ref_train = panel[INSTRUMENTS[0]]["train_mask"]
    for ft in ["usd_common", "pca1_causal"]:
        for dyn in ["residual_momentum", "residual_drift"]:
            for h in [6, 12, 24, 48]:
                cid = f"R4_{ft[:4]}_{dyn[:4]}_h{h*5}"
                dp = causal_pca_signal(panel, ref_dates, ref_train, ref_mask, h, ft, dyn)
                n_active = int((dp != 0).sum())
                gross = float(dp.sum())
                all_cands.append((cid, "R4", h*5, n_active, gross, 0, 0, gross, gross, gross, sharpe(dp), dp))
    print(f"  Done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # R5: TRUE GRU/TCN (16 candidates)
    # ============================================================
    print("\n=== R5: True GRU/TCN ===")
    for pair in INSTRUMENTS:
        a = panel[pair]
        mid, bo, ao = a["mid"], a["ao"], a["bo"]
        mask = a["eval_mask"]
        train_mask = a["train_mask"]
        dates_p = a["date"]
        n_p = a["n"]
        ret, rv, rng, sp = a["ret"], a["rv"], a["range"], a["sp"]
        
        # Build features: [ret, range, spread, time]
        time_feat = np.zeros(n_p)
        for i in range(n_p):
            time_feat[i] = (i % 288) / 288.0  # time of day
        
        for arch in ["gru", "tcn"]:
            for ctx in [12, 48]:  # 60m, 240m in 5-min bars
                # Build training samples (subsample for speed)
                train_idx = np.where(train_mask & ~np.isnan(ret))[0]
                train_idx = train_idx[ctx:]
                # Subsample to max 3000 samples
                if len(train_idx) > 3000:
                    step = len(train_idx) // 3000
                    train_idx = train_idx[::step]
                
                X_train, y_train = [], []
                for i in train_idx:
                    if i + 6 >= n_p:
                        continue
                    X = np.column_stack([ret[i-ctx:i], rng[i-ctx:i], sp[i-ctx:i], time_feat[i-ctx:i]])
                    X = np.nan_to_num(X)
                    y = ret[i+6] if not np.isnan(ret[i+6]) else 0
                    X_train.append(X)
                    y_train.append(y)
                
                if len(X_train) < 100:
                    continue
                
                X_train = np.array(X_train)
                y_train = np.array(y_train)
                # Validation: last 10%
                n_val = max(len(X_train) // 10, 50)
                X_val, y_val = X_train[-n_val:], y_train[-n_val:]
                X_tr, y_tr = X_train[:-n_val], y_train[:-n_val]
                
                model, loss_hist = train_sequence_model(
                    arch, X_tr, y_tr, X_val, y_val,
                    n_features=4, max_epochs=30, patience=5, lr=0.001, seed=42
                )
                
                # Generate signals for eval period
                eval_idx = np.where(mask & ~np.isnan(ret))[0]
                eval_idx = eval_idx[eval_idx >= ctx]
                sig = np.zeros(n_p)
                for i in eval_idx[::5]:  # Subsample for speed
                    if i + 6 >= n_p:
                        continue
                    X = np.column_stack([ret[i-ctx:i], rng[i-ctx:i], sp[i-ctx:i], time_feat[i-ctx:i]])
                    X = np.nan_to_num(X)
                    out, _ = model.forward(X)
                    sig[i] = out[-1]
                
                for h in [6, 12, 24, 48]:
                    cid = f"R5_{arch}_c{ctx}_h{h*5}"
                    g, sp_c, co, nt, dp = execute(bo, ao, mid, mask, sig, h, dates_p, 1.0)
                    net = g - co
                    all_cands.append((cid, "R5", h*5, nt, g, sp_c, co, net, g-co*1.5, g-co*2.0, sharpe(dp), dp))
        print(f"  {pair} done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # R7: TRUE COST-AWARE (16 candidates)
    # ============================================================
    print("\n=== R7: True Cost-Aware ===")
    for pair in INSTRUMENTS:
        a = panel[pair]
        mid, bo, ao = a["mid"], a["bo"], a["ao"]
        mask = a["eval_mask"]
        dates_p = a["date"]
        n_p = a["n"]
        ret, rv, rng, sp = a["ret"], a["rv"], a["range"], a["sp"]
        log_mid = np.log(np.where(mid > 0, mid, np.nan))
        
        # Get R1 Kalman outputs
        k_sig, k_slope, k_unc = kalman_signal(log_mid, 24)
        
        # Get R2 GMM outputs
        trend = np.zeros(n_p)
        for i in range(6, n_p):
            w = ret[i-6:i]
            w = w[~np.isnan(w)]
            if len(w) > 3:
                trend[i] = w.sum()
        features = np.column_stack([ret, rv, rng, sp, trend])
        gmm_sig, gmm_probs = fit_gmm_causal(features, dates_p, EVAL_START, 2)
        
        for source in ["kalman", "gmm"]:
            for cm in [1.0, 1.5]:
                if source == "kalman":
                    sig = cost_aware_signal(k_slope, k_unc, np.zeros(n_p), np.zeros((n_p,2)), a["spread"], cm, mask)
                else:
                    sig = cost_aware_signal(np.zeros(n_p), np.full(n_p, 1e-6), gmm_sig, gmm_probs, a["spread"], cm, mask)
                sig[~mask] = 0
                for h in [6, 12, 24, 48]:
                    cid = f"R7_{source[:4]}_c{cm}_h{h*5}"
                    g, sp_c, co, nt, dp = execute(bo, ao, mid, mask, sig, h, dates_p, cm)
                    net = g - co
                    all_cands.append((cid, "R7", h*5, nt, g, sp_c, co, net, g-co*1.5, g-co*2.0, sharpe(dp), dp))
        print(f"  {pair} done ({time.time()-t0:.0f}s)")
    
    # ============================================================
    # AGGREGATE
    # ============================================================
    print(f"\n=== AGGREGATING ({len(all_cands)} instrument results) ===")
    cmap = {}
    for (cid, fam, h, nt, g, sp, co, net, n15, n20, sh, dp) in all_cands:
        if cid not in cmap:
            cmap[cid] = {"cid": cid, "family": fam, "horizon": h, "n_trades": 0,
                         "gross": 0, "spread": 0, "comm": 0, "net": 0,
                         "net15": 0, "net20": 0, "sharpe_sum": 0, "n_inst": 0,
                         "dp": None}
        c = cmap[cid]
        c["n_trades"] += nt
        c["gross"] += g; c["spread"] += sp; c["comm"] += co
        c["net"] += net; c["net15"] += n15; c["net20"] += n20
        c["sharpe_sum"] += sh; c["n_inst"] += 1
        if c["dp"] is None:
            c["dp"] = dp
        else:
            if len(dp) == len(c["dp"]):
                c["dp"] = c["dp"] + dp
    
    candidates = []
    daily_pnl_matrix = {}
    for c in cmap.values():
        c["sharpe"] = c["sharpe_sum"] / max(c["n_inst"], 1)
        del c["sharpe_sum"]
        candidates.append(c)
        if c["dp"] is not None and len(c["dp"]) > 0:
            daily_pnl_matrix[c["cid"]] = c["dp"]
        del c["dp"]
    
    # ============================================================
    # STATISTICS
    # ============================================================
    print("\n=== STATISTICS ===")
    # Build daily P&L matrix (88 x n_days)
    all_dates = sorted(set(ref_dates[ref_mask]))
    n_days = len(all_dates)
    dp_matrix = np.zeros((len(candidates), n_days))
    for i, c in enumerate(candidates):
        if c["cid"] in daily_pnl_matrix:
            dp = daily_pnl_matrix[c["cid"]]
            # Align to all_dates
            dp_aligned = np.zeros(n_days)
            for j, d in enumerate(all_dates):
                if j < len(dp):
                    dp_aligned[j] = dp[j]
            dp_matrix[i] = dp_aligned
    
    wrc_p = wrc_test(dp_matrix)
    spa_p = spa_test(dp_matrix)
    rw_adj = romano_wolf(dp_matrix)
    holm_adj = holm(rw_adj)
    bh_adj = bh_fdr(rw_adj)
    
    # PSR/DSR for best candidate
    best_idx = np.argmax(dp_matrix.mean(axis=1))
    psr_val = psr(dp_matrix, 88)
    dsr_val = dsr(dp_matrix, 88)
    pbo_val = cscv_pbo(dp_matrix)
    
    print(f"  WRC p={wrc_p:.4f}, SPA p={spa_p:.4f}")
    print(f"  PBO={pbo_val:.4f}, PSR={psr_val:.4f}, DSR={dsr_val:.4f}")
    
    # ============================================================
    # PRE-HOLDOUT CANDIDATE RULE
    # ============================================================
    pre_holdout = []
    for c in candidates:
        if (c["net"] > 0 and c["sharpe"] >= 0.75 and
            c["n_trades"] >= 60 and c["n_inst"] >= 40 and
            c["net15"] > 0 and c["net20"] > 0):
            pre_holdout.append(c["cid"])
    
    # ============================================================
    # SAVE RESULTS
    # ============================================================
    results = {
        "artifact_id": "V5R_CANDIDATE_RESULTS_V1",
        "protocol_hash": PROTOCOL_HASH,
        "data_digest": DATA_DIGEST,
        "total_candidates": len(candidates),
        "total_instrument_results": len(all_cands),
        "n_gross_positive": sum(1 for c in candidates if c["gross"] > 0),
        "n_net_positive": sum(1 for c in candidates if c["net"] > 0),
        "n_net15_positive": sum(1 for c in candidates if c["net15"] > 0),
        "n_net20_positive": sum(1 for c in candidates if c["net20"] > 0),
        "best_gross": max((c["gross"] for c in candidates), default=0),
        "best_net": max((c["net"] for c in candidates), default=0),
        "best_sharpe": max((c["sharpe"] for c in candidates), default=0),
        "candidates": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()} for c in candidates],
    }
    (OUT / "v5r_candidate_results.json").write_text(json.dumps(results, indent=1))
    
    stats = {
        "artifact_id": "V5R_STATISTICS_V1",
        "protocol_hash": PROTOCOL_HASH,
        "wrc_p": round(wrc_p, 6),
        "spa_p": round(spa_p, 6),
        "romano_wolf_max_adj": round(float(rw_adj.max()), 6),
        "holm_max_adj": round(float(holm_adj.max()), 6),
        "bh_max_adj": round(float(bh_adj.max()), 6),
        "psr": round(psr_val, 6),
        "dsr": round(dsr_val, 6),
        "cscv_pbo": round(pbo_val, 6),
        "bootstrap": {"type": "stationary", "reps": 999, "block_length": 5},
    }
    (OUT / "v5r_statistics.json").write_text(json.dumps(stats, indent=1))
    
    verdict = ("V5R_TRUE_STRUCTURAL_PRE_HOLDOUT_CANDIDATE_FOUND" if pre_holdout
               else "V5R_TRUE_STRUCTURAL_MODELS_NO_PRE_HOLDOUT_EDGE")
    decision = {
        "artifact_id": "V5R_DISCOVERY_DECISION_V1",
        "protocol_hash": PROTOCOL_HASH,
        "n_candidates": len(candidates),
        "n_pre_holdout": len(pre_holdout),
        "pre_holdout_ids": pre_holdout,
        "verdict": verdict,
        "next_gate": "V5R_2018_ONE_SHOT_HOLDOUT_PROTOCOL" if pre_holdout else "MARKET_PIVOT",
    }
    (OUT / "v5r_discovery_decision.json").write_text(json.dumps(decision, indent=1))
    
    print(f"\n{'='*60}")
    print(f"CANDIDATES: {len(candidates)} | INSTR: {len(all_cands)}")
    print(f"GROSS POS: {results['n_gross_positive']} | NET POS: {results['n_net_positive']}")
    print(f"BEST GROSS: {results['best_gross']:.1f} | BEST NET: {results['best_net']:.1f}")
    print(f"PRE-HOLDOUT: {len(pre_holdout)}")
    print(f"VERDICT: {verdict}")
    print(f"TIME: {time.time()-t0:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
