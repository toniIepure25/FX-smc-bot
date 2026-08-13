"""Discovery-stage invariant tests (denominator immutability, LOO, survivors, matrix)."""

from __future__ import annotations

from fx_smc_bot.research.v2 import discovery as disco
from fx_smc_bot.research.v2.search_space import enumerate_admitted_specs
from fx_smc_bot.research.v2.synthetic import synthetic_frame


def _row(tid: str, inst: str, sig: str, net: float, *, trades: int = 150,
         days: int = 120, dates: list[str] | None = None,
         netseries: list[float] | None = None, state: str = "EVALUATED") -> dict:
    return {
        "trial_id": tid, "family_id": "F01_SESSION_OPENING_MOMENTUM_REVERSAL",
        "instrument": inst, "config_signature": sig, "configuration_hash": tid,
        "terminal_state": state, "trade_count": trades, "active_days": days,
        "gross_bps": net + 5, "cost_bps": 5.0, "net_bps": net, "net_bps_per_trade": 0.0,
        "daily_sharpe": 1.0 if net > 0 else -0.5, "max_drawdown_bps": -1.0,
        "hit_rate": 0.5, "turnover": 1.0, "net_bps_1_5x": net - 1, "net_bps_2_0x": net - 2,
        "survives_1_5x": net - 1 > 0, "survives_2_0x": net - 2 > 0, "psr": 0.5, "dsr": 0.5,
        "fold_positive_fraction": 0.8 if net > 0 else 0.2, "n_folds": 8, "folds": [],
        "per_year_net_bps": {}, "year_loo_positive": net > 0,
        "eval_seconds": 0.1,
        "daily_dates": dates if dates is not None else ["2015-01-02", "2015-01-05"],
        "daily_net_bps": netseries if netseries is not None else [net / 2, net / 2],
    }


def test_registered_denominator_is_336_and_matches_universe() -> None:
    assert disco.REGISTERED_V2_DENOMINATOR == 336
    universe, _digest = disco.load_universe()
    assert len(universe) == 336


def test_return_matrix_keeps_all_columns_including_zero_and_failed() -> None:
    rows = [
        _row("V2-0001", "EURUSD", "s1", 3.0),
        _row("V2-0002", "GBPUSD", "s1", -2.0, state="EVALUATED_ZERO_TRADES", trades=0,
             dates=[], netseries=[]),
        _row("V2-0003", "USDJPY", "s1", 0.0, state="EVALUATION_FAILURE", dates=[], netseries=[]),
    ]
    matrix = disco.build_return_matrix(rows)
    # denominator immutability: every registered trial is a column
    assert list(matrix.columns) == ["V2-0001", "V2-0002", "V2-0003"]
    # zero-trade / failed trials are all-zero columns, not dropped
    assert float(matrix["V2-0002"].abs().sum()) == 0.0
    assert float(matrix["V2-0003"].abs().sum()) == 0.0


def test_statistics_denominator_and_columns() -> None:
    rows = [_row(f"V2-{i:04d}", "EURUSD", f"s{i}", (-1.0) ** i) for i in range(6)]
    matrix = disco.build_return_matrix(rows)
    st = disco.run_statistics(matrix, rows)
    assert st["registered_candidate_equivalent_denominator"] == 336
    assert st["evaluated_columns"] == len(rows)
    assert 0.0 <= float(st["white_reality_check_p"]) <= 1.0


def test_instrument_loo_uses_siblings() -> None:
    # same config across 3 instruments, all positive -> LOO positive for each
    rows = [_row("A", "EURUSD", "cfg", 3.0), _row("B", "GBPUSD", "cfg", 2.0),
            _row("C", "USDJPY", "cfg", 1.0)]
    loo = disco._instrument_loo(rows)
    assert loo["A"] and loo["B"] and loo["C"]
    # one strongly negative sibling can break a leave-one-out subset
    rows2 = [_row("A", "EURUSD", "cfg", 3.0), _row("B", "GBPUSD", "cfg", -10.0),
             _row("C", "USDJPY", "cfg", 1.0)]
    loo2 = disco._instrument_loo(rows2)
    # leaving out EURUSD -> GBPUSD+USDJPY = -9 < 0 -> not robust
    assert not loo2["A"]


def test_classify_survivors_applies_frozen_predicate() -> None:
    strong = _row("WIN", "EURUSD", "s", 8.0)
    weak = _row("LOSE", "EURUSD", "s2", -3.0)
    rows = [strong, weak]
    matrix = disco.build_return_matrix(rows)
    st = disco.run_statistics(matrix, rows)
    # force RW p favourable for the strong one so only the predicate economics decide
    st["per_trial"]["WIN"]["romano_wolf_p"] = 0.01
    loo = {"WIN": True, "LOSE": False}
    neigh = {"WIN": 0.9, "LOSE": 0.1}
    survivors, predicate_rows = disco.classify_survivors(rows, loo, neigh, st)
    win_row = next(p for p in predicate_rows if p["trial_id"] == "WIN")
    lose_row = next(p for p in predicate_rows if p["trial_id"] == "LOSE")
    assert "net_profitability" in lose_row["failed_requirements"]
    assert not lose_row["is_survivor"]
    # WIN passes economics/robustness; survivorship then depends only on frozen predicate
    assert win_row["is_survivor"] == (len(win_row["failed_requirements"]) == 0)


def test_evaluate_trial_is_deterministic_and_never_raises() -> None:
    spec = next(s for s in enumerate_admitted_specs()
                if s.instrument == "EURUSD"
                and s.family_id == "F01_SESSION_OPENING_MOMENTUM_REVERSAL")
    frame = synthetic_frame("EURUSD", n_bars=3000, seed=3)
    r1 = disco.evaluate_trial("V2-test", spec, frame)
    r2 = disco.evaluate_trial("V2-test", spec, frame)
    assert r1["terminal_state"] in ("EVALUATED", "EVALUATED_ZERO_TRADES")
    assert r1["net_bps"] == r2["net_bps"]
    assert r1["trade_count"] == r2["trade_count"]


def test_evaluate_trial_failure_is_terminal_not_fatal(monkeypatch) -> None:
    import fx_smc_bot.research.v2.discovery as d

    def boom(*_a, **_k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(d, "generate_signal", boom)
    spec = next(s for s in enumerate_admitted_specs() if s.instrument == "EURUSD")
    frame = synthetic_frame("EURUSD", n_bars=500, seed=1)
    row = d.evaluate_trial("V2-x", spec, frame)
    assert row["terminal_state"] == "EVALUATION_FAILURE"
    assert "synthetic failure" in row["error"]
    assert row["net_bps"] == 0.0
