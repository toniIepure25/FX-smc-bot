"""Gate C.3 tests: bid/ask execution, provider fixes, cost reconciliation."""
from __future__ import annotations

from datetime import datetime

import numpy as np

from fx_smc_bot.backtesting.intraday_engine import (
    EXECUTION_MODE_BID_ASK,
    EXECUTION_MODE_MID,
    IntradayBacktestEngine,
)
from fx_smc_bot.config import (
    AppConfig,
    ExecutionConfig,
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.domain import Direction, Order, OrderType, Position
from fx_smc_bot.execution.fills import BidAskFillEngine
from fx_smc_bot.execution.slippage import (
    NativeBidAskSlippage,
)


def _make_bidask_series(n: int = 100) -> BidAskBarSeries:
    base = 1.1000
    spread = 0.0001
    ts = np.array(
        [np.datetime64("2023-06-15T08:00") + np.timedelta64(5 * i, "m")
         for i in range(n)],
        dtype="datetime64[ns]",
    )
    bid_c = np.full(n, base, dtype=np.float64)
    ask_c = bid_c + spread
    return BidAskBarSeries(
        pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
        timestamps=ts,
        bid_open=bid_c.copy(), bid_high=bid_c + 0.0005,
        bid_low=bid_c - 0.0005, bid_close=bid_c.copy(),
        ask_open=ask_c.copy(), ask_high=ask_c + 0.0005,
        ask_low=ask_c - 0.0005, ask_close=ask_c.copy(),
    )


class TestNativeBidAskSlippage:
    def test_no_synthetic_spread_added(self):
        slip = NativeBidAskSlippage(ExecutionConfig(slippage_pips=0.0))
        price, spread_cost, slip_cost = slip.apply(
            1.1000, Direction.LONG, TradingPair.EURUSD,
        )
        assert price == 1.1000
        assert spread_cost == 0.0
        assert slip_cost == 0.0

    def test_slippage_only(self):
        slip = NativeBidAskSlippage(ExecutionConfig(slippage_pips=0.5))
        price, spread_cost, slip_cost = slip.apply(
            1.1000, Direction.LONG, TradingPair.EURUSD,
        )
        assert price > 1.1000
        assert spread_cost == 0.0
        assert slip_cost > 0.0


class TestBidAskFillEngine:
    def test_long_limit_no_fill_when_ask_low_above(self):
        """LONG limit at 1.1000 does NOT fill if ask_low stays above."""
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.LIMIT, requested_price=1.1000,
            stop_loss=1.0990, take_profit=1.1020, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1002, bid_high=1.1010, bid_low=1.0998,
            bid_close=1.1005,
            ask_open=1.1003, ask_high=1.1011, ask_low=1.1001,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 0, "ask_low=1.1001 > limit=1.1000"

    def test_long_limit_fills_when_ask_low_reaches(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.LIMIT, requested_price=1.1000,
            stop_loss=1.0990, take_profit=1.1020, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.0998, bid_high=1.1010, bid_low=1.0988,
            bid_close=1.1005,
            ask_open=1.0999, ask_high=1.1011, ask_low=1.0998,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        assert fills[0][1].fill_price == 1.1000

    def test_short_limit_uses_bid_high(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.SHORT,
            order_type=OrderType.LIMIT, requested_price=1.1050,
            stop_loss=1.1060, take_profit=1.1030, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1040, bid_high=1.1049, bid_low=1.1030,
            bid_close=1.1035,
            ask_open=1.1041, ask_high=1.1060, ask_low=1.1031,
            ask_close=1.1036,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 0, "bid_high=1.1049 < limit=1.1050: no fill"

    def test_short_limit_fills_when_bid_high_reaches(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.SHORT,
            order_type=OrderType.LIMIT, requested_price=1.1050,
            stop_loss=1.1060, take_profit=1.1030, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1040, bid_high=1.1055, bid_low=1.1030,
            bid_close=1.1035,
            ask_open=1.1041, ask_high=1.1060, ask_low=1.1031,
            ask_close=1.1036,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        assert fills[0][1].fill_price == 1.1050

    def test_long_exit_uses_bid_for_sl(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        pos = Position(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            entry_price=1.1000, stop_loss=1.0990, take_profit=1.1020,
            units=100000, opened_at=datetime(2023, 6, 15, 8, 0),
        )
        fill = engine.check_exit_conditions_bidask(
            pos,
            bid_high=1.1010, bid_low=1.0989,
            ask_high=1.1011, ask_low=1.0991,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert fill is not None
        assert fill.reason.value == "stop_loss_hit"

    def test_long_sl_not_triggered_by_ask_low(self):
        """Even if ask_low < SL, long SL uses bid_low."""
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        pos = Position(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            entry_price=1.1000, stop_loss=1.0990, take_profit=1.1020,
            units=100000, opened_at=datetime(2023, 6, 15, 8, 0),
        )
        fill = engine.check_exit_conditions_bidask(
            pos,
            bid_high=1.1010, bid_low=1.0991,
            ask_high=1.1011, ask_low=1.0988,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert fill is None, "bid_low=1.0991 > SL=1.0990"

    def test_short_exit_uses_ask_for_sl(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        pos = Position(
            pair=TradingPair.EURUSD, direction=Direction.SHORT,
            entry_price=1.1000, stop_loss=1.1010, take_profit=1.0980,
            units=100000, opened_at=datetime(2023, 6, 15, 8, 0),
        )
        fill = engine.check_exit_conditions_bidask(
            pos,
            bid_high=1.1008, bid_low=1.0995,
            ask_high=1.1011, ask_low=1.0996,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert fill is not None
        assert fill.reason.value == "stop_loss_hit"

    def test_short_sl_not_triggered_by_bid_high(self):
        """Short SL uses ask_high, not bid_high."""
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        pos = Position(
            pair=TradingPair.EURUSD, direction=Direction.SHORT,
            entry_price=1.1000, stop_loss=1.1010, take_profit=1.0980,
            units=100000, opened_at=datetime(2023, 6, 15, 8, 0),
        )
        fill = engine.check_exit_conditions_bidask(
            pos,
            bid_high=1.1012, bid_low=1.0995,
            ask_high=1.1009, ask_low=1.0996,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert fill is None, "ask_high=1.1009 < SL=1.1010"

    def test_market_long_uses_ask_open(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, requested_price=0.0,
            stop_loss=1.0990, take_profit=1.1020, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1000, bid_high=1.1010, bid_low=1.0990,
            bid_close=1.1005,
            ask_open=1.1001, ask_high=1.1011, ask_low=1.0991,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        assert fills[0][1].fill_price == 1.1001

    def test_market_short_uses_bid_open(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.SHORT,
            order_type=OrderType.MARKET, requested_price=0.0,
            stop_loss=1.1010, take_profit=1.0980, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1000, bid_high=1.1010, bid_low=1.0990,
            bid_close=1.1005,
            ask_open=1.1001, ask_high=1.1011, ask_low=1.0991,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        assert fills[0][1].fill_price == 1.1000


class TestNoSyntheticSpreadOnBidAsk:
    def test_bidask_fill_zero_spread_cost(self):
        """In bid/ask mode, spread_cost must be 0."""
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, requested_price=0.0,
            stop_loss=1.0990, take_profit=1.1020, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.1000, bid_high=1.1010, bid_low=1.0990,
            bid_close=1.1005,
            ask_open=1.1001, ask_high=1.1011, ask_low=1.0991,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        assert fills[0][1].spread_cost == 0.0


class TestEngineExecutionMode:
    def test_mid_mode_label(self):
        engine = IntradayBacktestEngine(AppConfig())
        ba = _make_bidask_series(50)
        mid = ba.to_mid_series()
        result = engine.run({TradingPair.EURUSD: mid})
        assert result.metadata["execution_mode"] == EXECUTION_MODE_MID

    def test_bidask_mode_label(self):
        engine = IntradayBacktestEngine(AppConfig())
        ba = _make_bidask_series(50)
        result = engine.run({TradingPair.EURUSD: ba})
        assert result.metadata["execution_mode"] == EXECUTION_MODE_BID_ASK


class TestDukascopyScaling:
    def test_eurusd_scale(self):
        from fx_smc_bot.data.historical_providers import INSTRUMENT_META
        meta = INSTRUMENT_META[TradingPair.EURUSD]
        raw_price = 110000
        scaled = raw_price / meta.raw_price_scale
        assert 1.0 <= scaled <= 1.2

    def test_usdjpy_scale(self):
        from fx_smc_bot.data.historical_providers import INSTRUMENT_META
        meta = INSTRUMENT_META[TradingPair.USDJPY]
        raw_price = 140500
        scaled = raw_price / meta.raw_price_scale
        assert 130.0 <= scaled <= 160.0

    def test_usdjpy_not_divided_by_100000(self):
        from fx_smc_bot.data.historical_providers import INSTRUMENT_META
        meta = INSTRUMENT_META[TradingPair.USDJPY]
        raw_price = 140500
        wrong_scale = raw_price / 100_000.0
        assert wrong_scale < 2.0, "Universal 100000 divisor is wrong for JPY"
        correct_scale = raw_price / meta.raw_price_scale
        assert correct_scale > 100.0

    def test_plausible_range_rejects_bad_eurusd(self):
        from fx_smc_bot.data.historical_providers import INSTRUMENT_META
        meta = INSTRUMENT_META[TradingPair.EURUSD]
        assert not (meta.plausible_min <= 140.5 <= meta.plausible_max)

    def test_plausible_range_accepts_good_usdjpy(self):
        from fx_smc_bot.data.historical_providers import INSTRUMENT_META
        meta = INSTRUMENT_META[TradingPair.USDJPY]
        assert meta.plausible_min <= 140.5 <= meta.plausible_max


class TestOandaRequestConstruction:
    def test_no_count_in_request(self):
        """OANDA API prohibits from+to+count together."""
        from fx_smc_bot.data.historical_providers import OandaProvider
        provider = OandaProvider(practice=True)
        import unittest.mock as mock
        with mock.patch(
            "fx_smc_bot.data.historical_providers.urlopen"
        ) as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b'{"candles":[]}'
            mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = mock.MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            provider._token = "test-token"
            provider._fetch_candles(
                "EUR_USD", "M1",
                datetime(2023, 6, 15, 8, 0),
                datetime(2023, 6, 15, 9, 0),
            )
            call_args = mock_urlopen.call_args
            url = call_args[0][0].full_url
            assert "count=" not in url
            assert "price=BA" in url
            assert "smooth=false" in url


class TestMT5TimezoneConversion:
    def test_utc_timezone_no_change(self):
        from fx_smc_bot.data.historical_providers import MT5CsvImporter
        importer = MT5CsvImporter(broker_timezone="UTC")
        assert importer._tz is not None

    def test_timezone_applied(self):
        import csv
        import tempfile

        from fx_smc_bot.data.historical_providers import MT5CsvImporter
        rows = [
            {"Date": "2023.06.15", "Time": "10:00", "Open": "1.1000",
             "High": "1.1005", "Low": "1.0995", "Close": "1.1002",
             "Volume": "100"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="",
        ) as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            tmp_path = f.name

        from pathlib import Path
        importer_utc = MT5CsvImporter(broker_timezone="UTC")
        series_utc, meta_utc = importer_utc.import_csv(
            Path(tmp_path), TradingPair.EURUSD,
        )
        importer_est = MT5CsvImporter(broker_timezone="US/Eastern")
        series_est, meta_est = importer_est.import_csv(
            Path(tmp_path), TradingPair.EURUSD,
        )
        assert series_utc is not None
        assert series_est is not None
        ts_utc = series_utc.timestamps[0]
        ts_est = series_est.timestamps[0]
        assert ts_utc != ts_est
        assert meta_est.source_timezone == "US/Eastern"

        Path(tmp_path).unlink()

    def test_import_returns_metadata(self):
        import csv
        import tempfile

        from fx_smc_bot.data.historical_providers import MT5CsvImporter
        rows = [
            {"Date": "2023.06.15", "Time": "10:00", "Open": "1.1",
             "High": "1.1005", "Low": "1.0995", "Close": "1.1002",
             "Volume": "100"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="",
        ) as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            tmp_path = f.name

        from pathlib import Path
        importer = MT5CsvImporter(broker_timezone="UTC")
        series, meta = importer.import_csv(
            Path(tmp_path), TradingPair.EURUSD,
        )
        assert meta.price_type == "BID_ONLY_OR_MID"
        assert meta.rows == 1
        Path(tmp_path).unlink()


class TestBidAskResampling:
    def test_m1_to_m5(self):
        from fx_smc_bot.data.bidask_resampling import resample_bidask
        n = 10
        ts = np.array(
            [np.datetime64("2023-06-15T08:00") + np.timedelta64(i, "m")
             for i in range(n)],
            dtype="datetime64[ns]",
        )
        bid_o = np.arange(1.10, 1.10 + n * 0.0001, 0.0001)[:n]
        ask_o = bid_o + 0.0001
        series = BidAskBarSeries(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M1,
            timestamps=ts,
            bid_open=bid_o, bid_high=bid_o + 0.0002,
            bid_low=bid_o - 0.0002, bid_close=bid_o + 0.0001,
            ask_open=ask_o, ask_high=ask_o + 0.0002,
            ask_low=ask_o - 0.0002, ask_close=ask_o + 0.0001,
        )
        resampled = resample_bidask(series, Timeframe.M5)
        assert len(resampled) == 2
        assert resampled.timeframe == Timeframe.M5
        assert resampled.bid_open[0] == series.bid_open[0]
        assert resampled.bid_close[0] == series.bid_close[4]
        assert resampled.ask_open[0] == series.ask_open[0]
        assert resampled.ask_close[0] == series.ask_close[4]

    def test_independent_bid_ask_highs(self):
        from fx_smc_bot.data.bidask_resampling import resample_bidask
        n = 5
        ts = np.array(
            [np.datetime64("2023-06-15T08:00") + np.timedelta64(i, "m")
             for i in range(n)],
            dtype="datetime64[ns]",
        )
        bid_h = np.array([1.1010, 1.1020, 1.1015, 1.1005, 1.1012])
        ask_h = np.array([1.1011, 1.1018, 1.1025, 1.1006, 1.1013])
        series = BidAskBarSeries(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M1,
            timestamps=ts,
            bid_open=np.full(n, 1.1000), bid_high=bid_h,
            bid_low=np.full(n, 1.0990), bid_close=np.full(n, 1.1005),
            ask_open=np.full(n, 1.1001), ask_high=ask_h,
            ask_low=np.full(n, 1.0991), ask_close=np.full(n, 1.1006),
        )
        resampled = resample_bidask(series, Timeframe.M5)
        assert len(resampled) == 1
        assert resampled.bid_high[0] == 1.1020
        assert resampled.ask_high[0] == 1.1025


class TestCostReconciliation:
    def test_no_double_spread_in_bidask_mode(self):
        engine = BidAskFillEngine(NativeBidAskSlippage(
            ExecutionConfig(slippage_pips=0.0),
        ))
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.LIMIT, requested_price=1.1000,
            stop_loss=1.0990, take_profit=1.1020, units=100000,
            created_at=datetime(2023, 6, 15, 8, 0),
        )
        fills = engine.process_pending_orders(
            [order],
            bid_open=1.0998, bid_high=1.1010, bid_low=1.0988,
            bid_close=1.1005,
            ask_open=1.0999, ask_high=1.1011, ask_low=1.0998,
            ask_close=1.1006,
            bar_time=datetime(2023, 6, 15, 8, 5),
        )
        assert len(fills) == 1
        _, fill = fills[0]
        assert fill.spread_cost == 0.0
        assert fill.fill_price == 1.1000


class TestTradeRecordCostEquation:
    def test_gross_bid_ask_commission_swap_equation(self):
        from fx_smc_bot.backtesting.intraday_engine import TradeRecord
        rec = TradeRecord(
            position_id="p1", order_id="o1", intent_id="i1",
            family="test", pair="EURUSD", direction="long",
            session="london",
            entry_price=1.1000, exit_price=1.1010, units=100000,
            gross_pnl=100.0,
            bid_ask_execution_effect=2.0,
            spread_cost=0.0,
            commission_cost=7.0,
            slippage_cost=0.5,
            swap_cost=-1.5,
            net_pnl=100.0 - 7.0 + (-1.5),
            entry_bar=10, exit_bar=15,
            price_mode=EXECUTION_MODE_BID_ASK,
        )
        expected_net = (
            rec.gross_pnl - rec.commission_cost + rec.swap_cost
        )
        assert abs(rec.net_pnl - expected_net) < 1e-10
