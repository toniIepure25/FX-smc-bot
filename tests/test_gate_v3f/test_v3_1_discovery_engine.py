"""V3.1 discovery engine tests: materialization, execution semantics, denominator,
checkpointing, statistics and survivor classification.

All tests use synthetic in-memory data; no canonical market data is read and no 2018+
access is possible (the firewall is tested directly).
"""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from fx_smc_bot.research.v3 import discovery_engine as de
from fx_smc_bot.research.v3.discovery_data import DiscoveryFirewall, InstrumentData


# --------------------------------------------------------------------------------------
# Synthetic instrument builder
# --------------------------------------------------------------------------------------
def make_data(n_days: int = 3, exec_off: tuple[int, ...] = ()) -> InstrumentData:
    n = n_days * 1440
    # 2015-01-05 05:00 UTC = 00:00 America/New_York -> bar i is NY minute i
    ts = 1_420_434_000_000 + np.arange(n, dtype=np.int64) * 60_000
    ny = pd.to_datetime(ts, unit="ms", utc=True).tz_convert("America/New_York")
    base = np.full(n, 1.1)
    bo = base.copy()
    ao = base + 0.0001
    bh = base + 0.0002
    bl = base - 0.0002
    bc = base.copy()
    ac = ao.copy()
    execm = np.ones(n, dtype=bool)
    for i in exec_off:
        execm[i] = False
    return InstrumentData(
        inst="TEST", ts=ts, bo=bo, bh=bh, bl=bl, bc=bc, ao=ao,
        ah=ao + 0.0001, al=bl - 0.0001, ac=ac,
        exec=execm, obs=np.ones(n, dtype=bool),
        ny_min=(ny.hour * 60 + ny.minute).to_numpy(dtype=np.int32),
        ny_date=ny.strftime("%Y-%m-%d").to_numpy(),
        ny_year=ny.year.to_numpy(dtype=np.int32),
        o_idx=np.arange(n), o_mid=base.copy(), o_ret=np.zeros(n - 1),
        o_mh=bh.copy(), o_ml=bl.copy(), o_mc=base.copy(), o_spread=np.full(n, 0.0001),
        feat={}, missing_days=[],
    )


# --------------------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------------------
def test_discovery_firewall_blocks_2018_plus() -> None:
    fw = DiscoveryFirewall()
    with pytest.raises(AssertionError):
        fw.guard_years((2010, 2017, 2018))
    assert fw.blocked_2018_plus == 1
    fw.guard_years((2010, 2011, 2017))  # allowed
    assert fw.blocked_2018_plus == 1


# --------------------------------------------------------------------------------------
# Materialization
# --------------------------------------------------------------------------------------
def test_universe_counts_are_frozen() -> None:
    cands = de.materialize_universe()
    a = [c for c in cands if c.universe == "A"]
    b = [c for c in cands if c.universe == "B"]
    assert len(cands) == 1044
    assert len(a) == 992
    assert len(b) == 52
    ids = [c.candidate_id for c in cands]
    assert len(set(ids)) == 1044


def test_registry_hash_is_deterministic() -> None:
    h1 = de.registry_hash(de.materialize_universe())
    h2 = de.registry_hash(de.materialize_universe())
    assert h1 == h2
    assert len(h1) == 64


# --------------------------------------------------------------------------------------
# Execution semantics
# --------------------------------------------------------------------------------------
def test_one_bar_latency() -> None:
    d = make_data()
    sig = np.zeros(d.n, dtype=np.int8)
    sig[100] = 1
    res = de.simulate_v3(d, sig, holding=10)
    daily, trades, _ = res[1.0]
    assert len(trades) == 1
    assert trades[0]["entry_timestamp"] == int(d.ts[101])  # NOT bar 100
    assert trades[0]["exit_timestamp"] == int(d.ts[111])


def test_no_fill_on_non_executable_bar() -> None:
    d = make_data(exec_off=(101,))
    sig = np.zeros(d.n, dtype=np.int8)
    sig[100] = 1
    res = de.simulate_v3(d, sig, holding=10)
    daily, trades, diag = res[1.0]
    assert len(trades) == 1
    assert trades[0]["entry_timestamp"] == int(d.ts[102])  # advanced to next executable
    assert diag["entry_advances"] == 1


def test_mandatory_flat_close() -> None:
    d = make_data()
    sig = np.zeros(d.n, dtype=np.int8)
    sig[600] = 1  # NY 10:00
    res = de.simulate_v3(d, sig, holding=100_000)
    daily, trades, _ = res[1.0]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "mandatory_flat"
    assert trades[0]["exit_timestamp"] == int(d.ts[1005])  # NY 16:45


def test_no_entry_window_blocks_entry() -> None:
    d = make_data()
    sig = np.zeros(d.n, dtype=np.int8)
    sig[1010] = 1  # NY 16:50 (inside 16:30-17:30 no-entry window)
    res = de.simulate_v3(d, sig, holding=10)
    daily, trades, _ = res[1.0]
    assert len(trades) == 0


def test_side_correct_fills_and_cost_model() -> None:
    d = make_data()
    sig = np.zeros(d.n, dtype=np.int8)
    sig[100] = 1
    res = de.simulate_v3(d, sig, holding=10, cost_mults=(1.0, 2.0))
    daily1, tr1, _ = res[1.0]
    daily2, tr2, _ = res[2.0]
    # long enters at ask_open (1.1001), exits at bid_open (1.1) -> gross = -0.909 bps
    assert tr1[0]["side"] == "long"
    assert abs(tr1[0]["gross_bps"] - (-0.0001 / 1.1001 * 10_000.0)) < 1e-6
    # 1.0x: cost = 2 * 0.1 bps (no spread overlay)
    assert abs(tr1[0]["cost_bps"] - 0.2) < 1e-9
    # 2.0x: cost = 1.0 * (es + xs)/2 + 2 * 0.2
    mid = (1.1001 + 1.1) / 2.0
    spread_bps = 0.0001 / mid * 10_000.0
    assert abs(tr2[0]["cost_bps"] - (spread_bps + 0.4)) < 1e-6


def test_exit_on_non_executable_bar_is_impossible() -> None:
    # make every bar in the horizon window non-executable except far later
    d2 = make_data()
    d2.exec[110:120] = False
    sig2 = np.zeros(d2.n, dtype=np.int8)
    sig2[100] = 1
    res = de.simulate_v3(d2, sig2, holding=10)
    daily, trades, _ = res[1.0]
    # entry at 101; horizon exit at 111 is non-executable -> advances to 120
    assert trades[0]["exit_timestamp"] == int(d2.ts[120])


# --------------------------------------------------------------------------------------
# Denominator immutability
# --------------------------------------------------------------------------------------
def _env_with(d: InstrumentData) -> de.EvalEnv:
    return de.EvalEnv(data={"EURUSD": d, "GBPUSD": d, "USDJPY": d}, panel=None,
                      primary_dates=set(d.ny_date[:1440 * 2]),
                      unresolved_gap={}, freeze_hash="t", data_digest="t",
                      registry_hash="t")


def test_failure_row_keeps_denominator() -> None:
    cands = de.materialize_universe()
    c = next(x for x in cands if x.family_id == "V3_A_DONCHIAN_BREAKOUT_POST_COMPRESSION"
             and x.scope == "EURUSD")
    env = _env_with(make_data())
    env.data["EURUSD"].feat = {}  # no features -> signal generation fails
    row = de.evaluate_candidate(c, env)
    assert row["terminal_state"] == de.EVALUATION_FAILURE
    assert row["candidate_id"] == c.candidate_id
    for key in ("net_bps", "trade_count", "daily_sharpe", "survives_2_0x", "loo_contrib"):
        assert key in row


def test_every_candidate_yields_exactly_one_row() -> None:
    d = make_data(n_days=10)
    env = _env_with(d)
    cands = [c for c in de.materialize_universe()
             if c.scope == "EURUSD" and c.archetype_id is None][:5]
    rows = [de.evaluate_candidate(c, env) for c in cands]
    assert len(rows) == len(cands)
    assert [r["candidate_id"] for r in rows] == [c.candidate_id for c in cands]


# --------------------------------------------------------------------------------------
# Checkpoint store
# --------------------------------------------------------------------------------------
def test_checkpoint_roundtrip_and_identity_guard(tmp_path: pytest.TempPath) -> None:
    store = de.CheckpointStore(tmp_path, "f1", "d1", "r1")
    row = {"candidate_id": "V3-0001", "net_bps": 1.5}
    store.save(row)
    loaded = de.CheckpointStore(tmp_path, "f1", "d1", "r1").load_completed()
    assert loaded["V3-0001"]["net_bps"] == 1.5
    with pytest.raises(AssertionError):
        de.CheckpointStore(tmp_path, "f2", "d1", "r1").load_completed()


# --------------------------------------------------------------------------------------
# LOO / neighbourhood aggregation
# --------------------------------------------------------------------------------------
def test_loo_fractions() -> None:
    rows = [
        {"candidate_id": "X", "family_id": "F", "scope": "S", "archetype_id": None,
         "param_hash": "p", "loo_contrib": {"A": 10.0, "B": -4.0, "C": 3.0},
         "net_bps": 9.0},
    ]
    frac = de.loo_fractions(rows)
    # removing A -> -1 < 0; removing B -> 13 > 0; removing C -> 6 > 0 -> 2/3
    assert frac["X"] == pytest.approx(2.0 / 3.0)
    rows[0]["loo_contrib"] = {"A": 10.0, "B": -14.0, "C": 3.0}
    frac = de.loo_fractions(rows)
    # removing A -> -11 < 0; removing B -> 13 > 0; removing C -> -4 < 0 -> 1/3
    assert frac["X"] == pytest.approx(1.0 / 3.0)


def test_neighborhood_fractions() -> None:
    cands = {
        "P": de.Candidate("P", "A", "F", "D", "H", "S", None,
                          {"a": 1.0, "b": 1.0}, "h", True),
        "Q": de.Candidate("Q", "A", "F", "D", "H", "S", None,
                          {"a": 1.0, "b": 2.0}, "h", True),
        "R": de.Candidate("R", "A", "F", "D", "H", "S", None,
                          {"a": 2.0, "b": 1.0}, "h", True),
    }
    rows = [
        {"candidate_id": "P", "family_id": "F", "scope": "S", "archetype_id": None,
         "net_bps": 10.0},
        {"candidate_id": "Q", "family_id": "F", "scope": "S", "archetype_id": None,
         "net_bps": 5.0},
        {"candidate_id": "R", "family_id": "F", "scope": "S", "archetype_id": None,
         "net_bps": -3.0},
    ]
    frac = de.neighborhood_fractions(rows, cands)
    assert frac["P"] == 0.5  # Q positive (same sign), R negative (different sign)
    assert frac["R"] == 0.0  # both one-step neighbours positive, focal negative


# --------------------------------------------------------------------------------------
# Statistics + survivors (synthetic)
# --------------------------------------------------------------------------------------
def _synthetic_rows(n_cand: int = 6, n_days: int = 40) -> list[dict[str, object]]:
    rng = np.random.default_rng(7)
    dates = [f"2012-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n_days)]
    rows = []
    for j in range(n_cand):
        nets = list(rng.normal(0.01 if j == 0 else 0.0, 0.1, size=n_days))
        rows.append({
            "candidate_id": f"V3-{j:04d}", "universe": "A",
            "family_id": "V3_A_DONCHIAN_BREAKOUT_POST_COMPRESSION",
            "domain": "A", "horizon": "H0_micro_intraday", "scope": "EURUSD",
            "archetype_id": None, "param_hash": f"p{j}",
            "terminal_state": "EVALUATED", "trade_count": 100,
            "net_bps": round(float(sum(nets)), 6), "net_bps_per_trade": 0.1,
            "daily_sharpe": 0.5, "dsr": 0.6 if j == 0 else 0.1,
            "fold_positive_fraction": 0.8, "survives_1_5x": True, "survives_2_0x": True,
            "daily_dates_primary": dates, "daily_net_bps_primary": nets,
            "loo_contrib": {"EURUSD": float(sum(nets))},
        })
    return rows


def test_run_statistics_smoke() -> None:
    rows = _synthetic_rows()
    stats = de.run_statistics(rows)
    assert stats["denominator"] == 6
    assert stats["universe"] == "A"
    assert stats["alpha_v3"] == pytest.approx(0.05 / 3)
    assert len(stats["per_candidate"]) == 6
    assert "white_reality_check_p" in stats
    assert "hansen_spa_p" in stats
    assert "pbo" in stats
    assert stats["bootstrap_iterations"] == de.BOOTSTRAP_ITERATIONS


def test_classify_survivors_structure() -> None:
    rows = _synthetic_rows()
    stats = de.run_statistics(rows)
    loo = {r["candidate_id"]: 1.0 for r in rows}
    neigh = {r["candidate_id"]: 1.0 for r in rows}
    survivors, predicate_rows = de.classify_survivors(rows, stats, loo, neigh, True)
    assert len(predicate_rows) == 6
    assert all(s["candidate_id"] in {r["candidate_id"] for r in rows} for s in survivors)
    for pr in predicate_rows:
        assert isinstance(pr["failed_requirements"], list)


def test_review_ranking_orders() -> None:
    rows = _synthetic_rows()
    stats = de.run_statistics(rows)
    ranking = de.review_ranking(rows, stats)
    assert len(ranking) == 6
    assert ranking[0]["rank"] == 1
    assert all(r["rank"] == i + 1 for i, r in enumerate(ranking))
