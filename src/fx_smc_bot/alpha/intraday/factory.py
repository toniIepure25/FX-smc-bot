"""V2 strategy runtime factory: maps canonical family names to runtime classes.

Loads typed configuration from YAML files and creates independent
runtime instances per strategy x pair x session.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fx_smc_bot.alpha.intraday.runtime import (
    CausalBarContext,
    OrderAcceptedEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderIntent,
    PositionClosedEvent,
    StatefulStrategyRuntime,
    pip_size,
)
from fx_smc_bot.config import TradingPair

CANONICAL_FAMILIES = {
    "liquidity_sweep_mss_fvg_reversal",
    "liquidity_acceptance_fvg_continuation",
    "opening_range_displacement_fvg_retest",
}


@dataclass
class ResolvedRuntimeConfig:
    """Fully resolved configuration for one runtime instance."""
    family: str
    pair: TradingPair
    session: str
    runtime_class: str
    config: dict[str, Any]
    config_hash: str
    yaml_path: str | None = None


class SweepReversalRuntime:
    """Stateful runtime wrapping SweepReversalDetectorV2."""

    def __init__(
        self,
        pair: TradingPair,
        session: str,
        config: dict[str, Any],
    ) -> None:
        self.family = "liquidity_sweep_mss_fvg_reversal"
        self.pair = pair
        self.session = session
        self._config = config
        self._pip = pip_size(pair)
        self._detector: Any = None
        self._intent_map: dict[str, str] = {}
        self._build_detector()

    def _build_detector(self) -> None:
        from fx_smc_bot.alpha.intraday.sweep_reversal import (
            SweepReversalConfig,
            SweepReversalDetectorV2,
        )
        cfg = SweepReversalConfig(**self._config)
        self._detector = SweepReversalDetectorV2(cfg, pair=self.pair)

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
        htf_bias = ctx.htf_bias
        signals = self._detector.process_bar(
            snapshot=ctx.snapshot,
            open_=ctx.open, high=ctx.high, low=ctx.low, close=ctx.close,
            bar_idx=ctx.bar_idx, bar_time=ctx.timestamp,
            atr=ctx.atr, spread=ctx.spread,
            htf_bias=htf_bias,
        )
        intents = []
        for sig in signals:
            intent = OrderIntent(
                family=self.family,
                pair=self.pair,
                direction=sig.direction,
                entry_price=sig.entry,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                signal_bar=sig.bar_index,
                signal_timestamp=sig.timestamp,
                activation_bar=sig.bar_index + 1,
                expiry_bars=self._config.get("max_order_bars", 20),
                strategy_instance_id=sig.instance.instance_id if sig.instance else "",
                level_id=getattr(sig, "level_id", ""),
                fvg_id=str(id(sig.fvg)) if sig.fvg else "",
                session=self.session,
            )
            intents.append(intent)
        return intents

    def on_order_accepted(self, event: OrderAcceptedEvent) -> None:
        self._intent_map[event.intent_id] = event.order_id

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        pass

    def on_order_cancelled(self, event: OrderCancelledEvent) -> None:
        pass

    def on_position_closed(self, event: PositionClosedEvent) -> None:
        pass

    def snapshot_state(self) -> dict:
        return {
            "family": self.family,
            "pair": self.pair.value,
            "session": self.session,
            "active_instances": len(self._detector.tracker._active)
            if self._detector else 0,
        }

    def reset(self) -> None:
        self._build_detector()
        self._intent_map.clear()


class AcceptanceContinuationRuntime:
    """Stateful runtime wrapping AcceptanceContinuationDetector."""

    def __init__(
        self,
        pair: TradingPair,
        session: str,
        config: dict[str, Any],
    ) -> None:
        self.family = "liquidity_acceptance_fvg_continuation"
        self.pair = pair
        self.session = session
        self._config = config
        self._pip = pip_size(pair)
        self._detector: Any = None
        self._build_detector()

    def _build_detector(self) -> None:
        from fx_smc_bot.alpha.intraday.acceptance_continuation import (
            AcceptanceContinuationConfig,
            AcceptanceContinuationDetector,
        )
        cfg = AcceptanceContinuationConfig(**self._config)
        self._detector = AcceptanceContinuationDetector(cfg, pair=self.pair)

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
        signals = self._detector.process_bar(
            snapshot=ctx.snapshot,
            open_=ctx.open, high=ctx.high, low=ctx.low, close=ctx.close,
            bar_idx=ctx.bar_idx, bar_time=ctx.timestamp,
            atr=ctx.atr, spread=ctx.spread,
        )
        intents = []
        for sig in signals:
            intent = OrderIntent(
                family=self.family,
                pair=self.pair,
                direction=sig.direction,
                entry_price=sig.entry,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                signal_bar=sig.bar_index,
                signal_timestamp=sig.timestamp,
                activation_bar=sig.bar_index + 1,
                expiry_bars=self._config.get("max_order_bars", 20),
                strategy_instance_id=sig.instance.instance_id if sig.instance else "",
                session=self.session,
            )
            intents.append(intent)
        return intents

    def on_order_accepted(self, event: OrderAcceptedEvent) -> None:
        pass

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        pass

    def on_order_cancelled(self, event: OrderCancelledEvent) -> None:
        pass

    def on_position_closed(self, event: PositionClosedEvent) -> None:
        pass

    def snapshot_state(self) -> dict:
        return {
            "family": self.family,
            "pair": self.pair.value,
            "session": self.session,
            "active_instances": len(self._detector.tracker._active)
            if self._detector else 0,
        }

    def reset(self) -> None:
        self._build_detector()


class OpeningRangeRuntime:
    """Stateful runtime wrapping OpeningRangeDetector."""

    def __init__(
        self,
        pair: TradingPair,
        session: str,
        config: dict[str, Any],
    ) -> None:
        self.family = "opening_range_displacement_fvg_retest"
        self.pair = pair
        self.session = session
        self._config = config
        self._pip = pip_size(pair)
        self._detector: Any = None
        self._build_detector()

    def _build_detector(self) -> None:
        from fx_smc_bot.alpha.intraday.opening_range import (
            OpeningRangeConfig,
            OpeningRangeDetector,
        )
        cfg = OpeningRangeConfig(**self._config)
        self._detector = OpeningRangeDetector(cfg, pair=self.pair)

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
        signals = self._detector.process_bar(
            snapshot=ctx.snapshot,
            open_=ctx.open, high=ctx.high, low=ctx.low, close=ctx.close,
            bar_idx=ctx.bar_idx, bar_time=ctx.timestamp,
            atr=ctx.atr, spread=ctx.spread,
        )
        intents = []
        for sig in signals:
            intent = OrderIntent(
                family=self.family,
                pair=self.pair,
                direction=sig.direction,
                entry_price=sig.entry,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                signal_bar=sig.bar_index,
                signal_timestamp=sig.timestamp,
                activation_bar=sig.bar_index + 1,
                expiry_bars=self._config.get("max_order_bars", 20),
                strategy_instance_id=sig.instance.instance_id if sig.instance else "",
                session=self.session,
            )
            intents.append(intent)
        return intents

    def on_order_accepted(self, event: OrderAcceptedEvent) -> None:
        pass

    def on_order_filled(self, event: OrderFilledEvent) -> None:
        pass

    def on_order_cancelled(self, event: OrderCancelledEvent) -> None:
        pass

    def on_position_closed(self, event: PositionClosedEvent) -> None:
        pass

    def snapshot_state(self) -> dict:
        return {
            "family": self.family,
            "pair": self.pair.value,
            "session": self.session,
        }

    def reset(self) -> None:
        self._build_detector()


_RUNTIME_REGISTRY: dict[str, type] = {
    "liquidity_sweep_mss_fvg_reversal": SweepReversalRuntime,
    "liquidity_acceptance_fvg_continuation": AcceptanceContinuationRuntime,
    "opening_range_displacement_fvg_retest": OpeningRangeRuntime,
}


def create_runtime(
    family: str,
    pair: TradingPair,
    session: str,
    config: dict[str, Any],
) -> StatefulStrategyRuntime:
    """Create a V2 strategy runtime instance.

    Raises ValueError for unknown families (no silent fallback).
    """
    cls = _RUNTIME_REGISTRY.get(family)
    if cls is None:
        raise ValueError(
            f"Unknown strategy family '{family}'. "
            f"Available: {sorted(_RUNTIME_REGISTRY.keys())}"
        )
    return cls(pair=pair, session=session, config=config)


def load_strategy_config(yaml_path: Path) -> dict[str, Any]:
    """Load and return strategy configuration from YAML."""
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def resolve_runtime_config(
    family: str,
    pair: TradingPair,
    session: str,
    yaml_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> ResolvedRuntimeConfig:
    """Resolve a full runtime configuration from YAML + overrides."""
    if family not in _RUNTIME_REGISTRY:
        raise ValueError(f"Unknown family: {family}")

    config: dict[str, Any] = {}
    if yaml_path and yaml_path.exists():
        raw = load_strategy_config(yaml_path)
        family_key = _family_config_key(family, session)
        if family_key and family_key in raw:
            config = raw[family_key]
        elif session in raw:
            config = raw[session]

    if overrides:
        config.update(overrides)

    cfg_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    return ResolvedRuntimeConfig(
        family=family,
        pair=pair,
        session=session,
        runtime_class=_RUNTIME_REGISTRY[family].__name__,
        config=config,
        config_hash=cfg_hash,
        yaml_path=str(yaml_path) if yaml_path else None,
    )


def _family_config_key(family: str, session: str = "") -> str | None:
    mapping = {
        "liquidity_sweep_mss_fvg_reversal": "sweep_reversal",
        "liquidity_acceptance_fvg_continuation": "acceptance_continuation",
        "opening_range_displacement_fvg_retest": f"opening_range_{session}",
    }
    return mapping.get(family)
