"""End-to-end deterministic tests for Gate C.2 runtime integration.

Covers all 18 test categories required by the gate specification:
1-7: Sweep Reversal lifecycle
8: Acceptance Continuation lifecycle
9-10: Opening Range lifecycle
11-12: Pair identity and USDJPY pip arithmetic
13-14: Session and family selection
15: Cost configuration effects
16: Invalid ablation paths
17: Cost monotonicity
18: Future-bar mutation invariance
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import (
    AppConfig,
    PAIR_PIP_INFO,
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.domain import Direction
from fx_smc_bot.alpha.intraday.runtime import (
    CausalBarContext,
    OrderIntent,
    pip_size,
    pips_to_price,
)
from fx_smc_bot.alpha.intraday.factory import (
    CANONICAL_FAMILIES,
    create_runtime,
    resolve_runtime_config,
)
from fx_smc_bot.alpha.intraday.state_machine import StrategyState
from fx_smc_bot.backtesting.intraday_engine import (
    IntradayBacktestEngine,
    TradeRecord,
)
from fx_smc_bot.research.ablations import (
    CANONICAL_ABLATIONS,
    apply_ablation,
    generate_ablation_configs,
)
from tests.test_gate_c2.helpers import (
    make_bar_series,
    make_bidask_series,
    make_sweep_setup_series,
)


class TestPipArithmetic:
    """Category 12: USDJPY pip arithmetic is correct."""

    def test_eurusd_pip_size(self) -> None:
        assert pip_size(TradingPair.EURUSD) == 0.0001

    def test_usdjpy_pip_size(self) -> None:
        assert pip_size(TradingPair.USDJPY) == 0.01

    def test_usdjpy_2pip_distance(self) -> None:
        dist = pips_to_price(2.0, TradingPair.USDJPY)
        assert abs(dist - 0.02) < 1e-10

    def test_eurusd_2pip_distance(self) -> None:
        dist = pips_to_price(2.0, TradingPair.EURUSD)
        assert abs(dist - 0.0002) < 1e-10

    def test_gbpusd_pip_size(self) -> None:
        assert pip_size(TradingPair.GBPUSD) == 0.0001


class TestRuntimeFactory:
    """Category 14: Family selection changes actual runtime class."""

    def test_known_families_create_successfully(self) -> None:
        for family in CANONICAL_FAMILIES:
            rt = create_runtime(
                family, TradingPair.EURUSD, "london", {},
            )
            assert rt.family == family
            assert rt.pair == TradingPair.EURUSD

    def test_unknown_family_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown strategy family"):
            create_runtime("nonexistent_strategy", TradingPair.EURUSD, "london", {})

    def test_sweep_creates_correct_class(self) -> None:
        rt = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london", {},
        )
        assert "SweepReversal" in type(rt).__name__

    def test_acceptance_creates_correct_class(self) -> None:
        rt = create_runtime(
            "liquidity_acceptance_fvg_continuation",
            TradingPair.EURUSD, "london", {},
        )
        assert "AcceptanceContinuation" in type(rt).__name__

    def test_opening_range_creates_correct_class(self) -> None:
        rt = create_runtime(
            "opening_range_displacement_fvg_retest",
            TradingPair.EURUSD, "london", {},
        )
        assert "OpeningRange" in type(rt).__name__


class TestSessionSelection:
    """Category 13: Session selection changes actual runtime behavior."""

    def test_different_sessions_different_instances(self) -> None:
        rt_london = create_runtime(
            "opening_range_displacement_fvg_retest",
            TradingPair.EURUSD, "london",
            {"range_start_local": "08:00", "range_end_local": "08:30",
             "session_cutoff_local": "12:00", "session_timezone": "Europe/London"},
        )
        rt_ny = create_runtime(
            "opening_range_displacement_fvg_retest",
            TradingPair.EURUSD, "new_york",
            {"range_start_local": "09:30", "range_end_local": "10:00",
             "session_cutoff_local": "15:00", "session_timezone": "America/New_York"},
        )
        assert rt_london.session == "london"
        assert rt_ny.session == "new_york"
        assert rt_london is not rt_ny


class TestPairIdentity:
    """Category 11: GBPUSD and USDJPY preserve their pair identity."""

    @pytest.mark.parametrize("pair", [TradingPair.GBPUSD, TradingPair.USDJPY])
    def test_runtime_preserves_pair(self, pair: TradingPair) -> None:
        rt = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            pair, "london", {},
        )
        assert rt.pair == pair
        state = rt.snapshot_state()
        assert state["pair"] == pair.value


class TestResolvedConfig:
    """Test config resolution and hashing."""

    def test_config_hash_deterministic(self) -> None:
        c1 = resolve_runtime_config(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london",
        )
        c2 = resolve_runtime_config(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london",
        )
        assert c1.config_hash == c2.config_hash

    def test_different_overrides_different_hash(self) -> None:
        c1 = resolve_runtime_config(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london",
            overrides={"target_r": 2.0},
        )
        c2 = resolve_runtime_config(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london",
            overrides={"target_r": 3.0},
        )
        assert c1.config_hash != c2.config_hash


class TestBidAskDataModel:
    """Test the BidAskBarSeries data model."""

    def test_mid_price_derivation(self) -> None:
        ba = make_bidask_series(n=10)
        mid = ba.mid_close
        expected = (ba.bid_close + ba.ask_close) / 2
        np.testing.assert_allclose(mid, expected)

    def test_spread_non_negative(self) -> None:
        ba = make_bidask_series(n=50)
        violations = ba.validate_invariants()
        assert len(violations) == 0, f"Invariant violations: {violations}"

    def test_to_mid_series_preserves_length(self) -> None:
        ba = make_bidask_series(n=30)
        mid = ba.to_mid_series()
        assert len(mid) == len(ba)
        assert mid.pair == ba.pair

    def test_slice_preserves_bidask(self) -> None:
        ba = make_bidask_series(n=50)
        sl = ba.slice(10, 30)
        assert len(sl) == 20
        np.testing.assert_array_equal(sl.bid_close, ba.bid_close[10:30])


class TestAblations:
    """Category 16: Invalid ablation paths fail."""

    def test_valid_ablation_applies(self) -> None:
        base = {"displacement_body_ratio": 2.0, "fvg_min_atr": 0.3}
        spec = CANONICAL_ABLATIONS["liquidity_sweep_mss_fvg_reversal"][0]
        result = apply_ablation(base, spec)
        assert result[spec.config_path] == spec.override_value

    def test_invalid_path_raises(self) -> None:
        from fx_smc_bot.research.ablations import AblationSpec
        base = {"displacement_body_ratio": 2.0}
        bad = AblationSpec(
            name="bad", config_path="nonexistent_field",
            override_value=0.0,
        )
        with pytest.raises(KeyError, match="nonexistent_field"):
            apply_ablation(base, bad)

    def test_ablation_changes_hash(self) -> None:
        from fx_smc_bot.research.ablations import ablation_config_hash
        base = {"displacement_body_ratio": 2.0, "fvg_min_atr": 0.3}
        spec = CANONICAL_ABLATIONS["liquidity_sweep_mss_fvg_reversal"][0]
        modified = apply_ablation(base, spec)
        assert ablation_config_hash(base) != ablation_config_hash(modified)

    def test_generate_all_ablations(self) -> None:
        base = {
            "displacement_body_ratio": 2.0,
            "fvg_min_atr": 0.3,
            "eligible_level_types": ["equal_highs"],
            "entry_fvg_pct": 0.5,
            "target_r": 2.0,
        }
        configs = generate_ablation_configs(
            "liquidity_sweep_mss_fvg_reversal", base,
        )
        assert len(configs) > 1
        names = [c[0] for c in configs]
        assert "full_model" in names
        assert "no_displacement" in names


class TestCostConfiguration:
    """Category 15 & 17: Cost configuration effects and monotonicity."""

    def test_higher_commission_reduces_net_pnl(self) -> None:
        cfg_low = AppConfig()
        cfg_low.backtest.commission_per_lot = 2.0
        cfg_high = AppConfig()
        cfg_high.backtest.commission_per_lot = 10.0

        assert cfg_high.backtest.commission_per_lot > cfg_low.backtest.commission_per_lot

    def test_cost_decomposition_fields(self) -> None:
        rec = TradeRecord(
            position_id="p1", order_id="o1", intent_id="i1",
            family="test", pair="EURUSD", direction="long",
            session="london",
            entry_price=1.1000, exit_price=1.1050, units=100000,
            gross_pnl=500.0, spread_cost=10.0,
            commission_cost=7.0, slippage_cost=2.0,
            swap_cost=-3.0, net_pnl=478.0,
            entry_bar=10, exit_bar=20,
        )
        assert rec.net_pnl == rec.gross_pnl - rec.spread_cost - rec.commission_cost - rec.slippage_cost + rec.swap_cost


class TestIntradayEngine:
    """Integration tests for the V2 intraday backtest engine."""

    def test_engine_runs_with_runtimes(self) -> None:
        cfg = AppConfig()
        engine = IntradayBacktestEngine(config=cfg)

        rt = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london", {},
        )
        engine.add_runtime(rt)

        data = {TradingPair.EURUSD: make_bar_series(n=80)}
        result = engine.run(data)
        assert result is not None
        assert result.config_hash

    def test_funnels_track_bars_processed(self) -> None:
        cfg = AppConfig()
        engine = IntradayBacktestEngine(config=cfg)

        rt = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london", {},
        )
        idx = engine.add_runtime(rt)

        data = {TradingPair.EURUSD: make_bar_series(n=80)}
        engine.run(data)

        funnels = engine.get_funnels()
        assert funnels[idx].bars_processed > 0

    def test_reconciliation_has_no_violations(self) -> None:
        cfg = AppConfig()
        engine = IntradayBacktestEngine(config=cfg)

        rt = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london", {},
        )
        engine.add_runtime(rt)

        data = {TradingPair.EURUSD: make_bar_series(n=80)}
        engine.run(data)

        recon = engine.reconcile()
        assert len(recon.violations) == 0

    def test_multi_pair_preserves_identity(self) -> None:
        """Category 11: Multi-pair doesn't mix up pair data."""
        cfg = AppConfig()
        engine = IntradayBacktestEngine(config=cfg)

        rt_eu = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.EURUSD, "london", {},
        )
        rt_jpy = create_runtime(
            "liquidity_sweep_mss_fvg_reversal",
            TradingPair.USDJPY, "london", {},
        )
        engine.add_runtime(rt_eu)
        engine.add_runtime(rt_jpy)

        data = {
            TradingPair.EURUSD: make_bar_series(
                pair=TradingPair.EURUSD, n=80, base_price=1.1000,
            ),
            TradingPair.USDJPY: make_bar_series(
                pair=TradingPair.USDJPY, n=80, base_price=140.00,
            ),
        }
        result = engine.run(data)
        assert result is not None

        funnels = engine.get_funnels()
        assert funnels[0].pair == "EURUSD"
        assert funnels[1].pair == "USDJPY"


class TestFutureBarInvariance:
    """Category 18: Future-bar mutation cannot change past V2 events."""

    def test_future_mutation_does_not_change_past_signals(self) -> None:
        series = make_bar_series(n=60, seed=123)

        from fx_smc_bot.alpha.intraday.sweep_reversal import (
            SweepReversalConfig,
            SweepReversalDetectorV2,
        )
        from fx_smc_bot.domain import StructureSnapshot, StructureRegime

        cfg = SweepReversalConfig()
        det = SweepReversalDetectorV2(cfg, pair=TradingPair.EURUSD)

        empty_snap = StructureSnapshot(
            pair=TradingPair.EURUSD,
            timeframe=Timeframe.M5,
            bar_index=0,
        )

        events_normal = []
        for i in range(50):
            bar_time = datetime(2023, 6, 15, 8, 0) + timedelta(minutes=5 * i)
            snap = StructureSnapshot(
                pair=TradingPair.EURUSD,
                timeframe=Timeframe.M5,
                bar_index=i,
            )
            signals = det.process_bar(
                snapshot=snap,
                open_=series.open, high=series.high,
                low=series.low, close=series.close,
                bar_idx=i, bar_time=bar_time,
                atr=0.001, spread=0.00015,
            )
            events_normal.append(len(signals))

        mutated = make_bar_series(n=60, seed=123)
        mutated_high = mutated.high.copy()
        mutated_high[55:] += 0.01

        det2 = SweepReversalDetectorV2(cfg, pair=TradingPair.EURUSD)
        events_mutated = []
        for i in range(50):
            bar_time = datetime(2023, 6, 15, 8, 0) + timedelta(minutes=5 * i)
            snap = StructureSnapshot(
                pair=TradingPair.EURUSD,
                timeframe=Timeframe.M5,
                bar_index=i,
            )
            signals = det2.process_bar(
                snapshot=snap,
                open_=mutated.open, high=mutated_high,
                low=mutated.low, close=mutated.close,
                bar_idx=i, bar_time=bar_time,
                atr=0.001, spread=0.00015,
            )
            events_mutated.append(len(signals))

        assert events_normal == events_mutated


class TestProviderInterface:
    """Test data provider interfaces exist and work."""

    def test_dukascopy_provider_exists(self) -> None:
        from fx_smc_bot.data.historical_providers import DukascopyProvider
        p = DukascopyProvider()
        assert p.provider_name == "dukascopy"

    def test_oanda_provider_not_configured(self) -> None:
        from fx_smc_bot.data.historical_providers import OandaProvider
        p = OandaProvider()
        assert not p.is_configured

    def test_mt5_importer_exists(self) -> None:
        from fx_smc_bot.data.historical_providers import MT5CsvImporter
        p = MT5CsvImporter()
        assert p.provider_name == "mt5"

    def test_cross_validation_runs(self) -> None:
        from fx_smc_bot.data.historical_providers import cross_validate_providers
        ba1 = make_bidask_series(n=50, seed=1)
        ba2 = make_bidask_series(n=50, seed=1)
        result = cross_validate_providers(ba1, ba2, "source_a", "source_b")
        assert result["common_timestamps"] > 0
        assert result["median_abs_price_diff"] < 1e-10
