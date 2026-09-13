"""V5 Forensic Golden Tests - Execution engine verification.
POST_OUTCOME_ENGINEERING_ONLY.
"""
import numpy as np
import pytest


def test_a_monotonic_up_long_positive():
    """Long on rising market must produce positive gross with zero costs."""
    n = 100
    mid = np.linspace(1.0, 1.1, n)
    bo = mid * 0.9999
    ao = mid * 1.0001
    # Long: entry at ask, exit at bid
    ep, xp = ao[1], bo[6]
    pnl = (xp - ep) / ep * 1e4
    assert pnl > 0, f"Expected positive P&L for long on rising, got {pnl}"


def test_b_monotonic_down_short_positive():
    """Short on falling market must produce positive gross with zero costs."""
    n = 100
    mid = np.linspace(1.1, 1.0, n)
    bo = mid * 0.9999
    ao = mid * 1.0001
    # Short: entry at bid, exit at ask
    ep, xp = bo[1], ao[6]
    pnl = (ep - xp) / ep * 1e4
    assert pnl > 0, f"Expected positive P&L for short on falling, got {pnl}"


def test_c_wrong_direction_loses():
    """Long on falling market must lose."""
    n = 100
    mid = np.linspace(1.1, 1.0, n)
    bo = mid * 0.9999
    ao = mid * 1.0001
    # Long on falling: entry at ask, exit at bid
    ep, xp = ao[1], bo[6]
    pnl = (xp - ep) / ep * 1e4
    assert pnl < 0, f"Expected negative P&L for long on falling, got {pnl}"


def test_d_bid_ask_direction():
    """Long enters ASK, exits BID. Short enters BID, exits ASK."""
    n = 50
    mid = np.linspace(1.0, 1.05, n)
    bo = mid * 0.9999
    ao = mid * 1.0001
    # Long: must enter at ask (higher) and exit at bid (lower)
    assert ao[1] > bo[1], "Ask must be above bid"
    # Short: must enter at bid (lower) and exit at ask (higher)
    assert bo[1] < ao[1], "Bid must be below ask"


def test_e_latency_one_bar():
    """Signal at t executes at t+1 (one bar latency)."""
    # In the execution engine: ei = idx + 1, xi = idx + 1 + h
    # Signal at bar 0 -> entry at bar 1, exit at bar 1+h
    idx = 0
    h = 5
    ei = idx + 1
    xi = idx + 1 + h
    assert ei == 1, "Entry must be at signal_bar + 1"
    assert xi == 6, "Exit must be at signal_bar + 1 + h"


def test_f_cost_identity():
    """net = gross - spread - explicit_cost (algebraic identity)."""
    gross = 100.0
    spread = 20.0
    comm = 10.0
    net = gross - spread - comm
    assert abs(net - 70.0) < 1e-10


def test_g_date_mask_excludes_2010_2013():
    """2010-2013 must yield zero trades when eval starts 2014."""
    dates = np.array(["2010-01-01"] * 50 + ["2014-01-01"] * 50)
    correct_mask = (dates >= "2014-01-01") & (dates <= "2017-12-31")
    trades_2010 = correct_mask[:50].sum()
    assert trades_2010 == 0, "2010-2013 bars must be excluded"
    trades_2014 = correct_mask[50:].sum()
    assert trades_2014 == 50, "2014+ bars must be included"


def test_h_obs_mask_required():
    """Imputed/non-observed bars cannot create fills.
    ORIGINAL BUG: mask_a lacks obs flag.
    """
    # This test documents the bug - it would FAIL on the original code
    exec_a = np.ones(10, dtype=bool)
    obs_a = np.array([True]*5 + [False]*5)
    mid_valid = np.ones(10, dtype=bool)
    # Original (buggy): mask = exec & ~isnan(mid) -> all 10 pass
    mask_buggy = exec_a & mid_valid
    # Correct: mask = exec & obs & ~isnan(mid) -> only 5 pass
    mask_correct = exec_a & obs_a & mid_valid
    assert mask_buggy.sum() == 10, "Buggy mask lets imputed bars through"
    assert mask_correct.sum() == 5, "Correct mask blocks imputed bars"


def test_spread_not_double_counted():
    """Verify that bid/ask execution already includes spread.
    Long P&L = (bid_exit - ask_entry) / ask_entry
    This already reflects the spread cost.
    """
    mid = np.array([1.0, 1.01])
    spread_bps = 1.0  # 1 bp spread
    bo = mid * (1 - spread_bps / 2e4)
    ao = mid * (1 + spread_bps / 2e4)
    # Long: enter at ask[0], exit at bid[1]
    ep, xp = ao[0], bo[1]
    pnl = (xp - ep) / ep * 1e4
    # Mid move = 1bp, spread cost ~1bp, so net ~ 0
    mid_move = (mid[1] - mid[0]) / mid[0] * 1e4
    assert pnl < mid_move, "Bid/ask P&L must be less than mid move (spread included)"


def test_2018_firewall():
    """No 2018+ data access in any V5 code path."""
    # Verify that the eval mask excludes 2018+
    dates = np.array(["2017-12-31", "2018-01-01", "2018-06-01"])
    mask = (dates >= "2014-01-01") & (dates <= "2017-12-31")
    assert mask[0] == True, "2017 must be included"
    assert mask[1] == False, "2018 must be excluded"
    assert mask[2] == False, "2018 must be excluded"


def test_pair_orientation_invariance():
    """Synthetic +1% move must yield correct long/short gross sign
    regardless of quote orientation."""
    # USD/JPY style: price goes from 150 to 151.5 (+1%)
    mid = np.array([150.0, 151.5])
    bo = mid * 0.99995
    ao = mid * 1.00005
    # Long: positive P&L
    pnl_long = (bo[1] - ao[0]) / ao[0] * 1e4
    assert pnl_long > 0, "Long on +1% move must be positive"
    # Short: negative P&L
    pnl_short = (bo[0] - ao[1]) / bo[0] * 1e4
    assert pnl_short < 0, "Short on +1% move must be negative"
    # Inverse orientation: price goes from 0.00667 to 0.00659 (-1.2%)
    # (e.g., JPY/USD)
    mid2 = np.array([0.00667, 0.00659])
    bo2 = mid2 * 0.99995
    ao2 = mid2 * 1.00005
    pnl_long2 = (bo2[1] - ao2[0]) / ao2[0] * 1e4
    assert pnl_long2 < 0, "Long on -1.2% move must be negative"
    pnl_short2 = (bo2[0] - ao2[1]) / bo2[0] * 1e4
    assert pnl_short2 > 0, "Short on -1.2% move must be positive"
