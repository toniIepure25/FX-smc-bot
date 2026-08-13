"""Typed, causal Feature DAG for V3.

Every feature is a node with a declared, hashable identity: source fields, instrument
dependencies, granularity, lookback, warm-up, timestamp availability, units, NaN policy,
normalization, causality classification and parent nodes. A single DAG replaces the V2
situation where the same formula could be re-implemented inconsistently across strategies.

Causality is enforced structurally: only ``CAUSAL_ENDPOINT`` nodes (using information up to
and including bar close ``t``, with right-aligned windows) are admissible. Centered or
full-sample transforms are representable only so the validator can *reject* them -- they can
never enter an admitted strategy. The DAG detects cycles, resolves capability dependencies,
computes a deterministic topological order and hashes each node by immutable identity so
pre-outcome feature computations can be cached and shared safely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import check_required


class Causality(str, Enum):
    CAUSAL_ENDPOINT = "causal_endpoint"  # right-aligned; uses info up to bar close t only
    FORBIDDEN_CENTERED = "forbidden_centered"  # symmetric window peeks at future
    FORBIDDEN_FULL_SAMPLE = "forbidden_full_sample"  # fit on the whole sample


class NanPolicy(str, Enum):
    DROP_WARMUP = "drop_warmup"  # undefined during warm-up; no forward fill of the future
    PROPAGATE = "propagate"


@dataclass(frozen=True, slots=True)
class FeatureNode:
    node_id: str
    kind: str
    source_fields: tuple[str, ...]
    instrument_dependencies: tuple[str, ...]  # "self" or explicit symbols
    granularity: str
    lookback_bars: int
    warmup_bars: int
    timestamp_availability: str  # e.g. "bar_close_t"
    units: str
    nan_policy: NanPolicy
    normalization: str
    causality: Causality
    required_capabilities: tuple[str, ...]
    parents: tuple[str, ...] = ()

    def identity(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "source_fields": list(self.source_fields),
            "instrument_dependencies": list(self.instrument_dependencies),
            "granularity": self.granularity,
            "lookback_bars": self.lookback_bars,
            "warmup_bars": self.warmup_bars,
            "timestamp_availability": self.timestamp_availability,
            "units": self.units,
            "nan_policy": self.nan_policy.value,
            "normalization": self.normalization,
            "causality": self.causality.value,
            "required_capabilities": sorted(self.required_capabilities),
            "parents": sorted(self.parents),
        }

    def node_hash(self) -> str:
        return canonical_hash(self.identity())


@dataclass(slots=True)
class FeatureDAG:
    nodes: dict[str, FeatureNode] = field(default_factory=dict)

    def add(self, node: FeatureNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate feature node id: {node.node_id}")
        self.nodes[node.node_id] = node

    def validate(self) -> None:
        """Structural + causal + capability validation. Raises on any violation."""

        # 1. every parent exists
        for node in self.nodes.values():
            for parent in node.parents:
                if parent not in self.nodes:
                    raise ValueError(f"node {node.node_id} references missing parent {parent}")
        # 2. no cycles (DFS three-colour)
        self._assert_acyclic()
        # 3. causality: no forbidden node admitted, and no causal node may depend on a
        #    forbidden one (leakage cannot enter through a parent)
        for node in self.nodes.values():
            if node.causality is not Causality.CAUSAL_ENDPOINT:
                raise ValueError(
                    f"node {node.node_id} is {node.causality.value}; only causal_endpoint "
                    f"nodes are admissible (no centered/full-sample transforms)"
                )
            for parent in node.parents:
                if self.nodes[parent].causality is not Causality.CAUSAL_ENDPOINT:
                    raise ValueError(
                        f"node {node.node_id} depends on non-causal parent {parent}"
                    )
        # 4. capabilities resolve
        for node in self.nodes.values():
            ok, missing = check_required(node.required_capabilities)
            if not ok:
                raise ValueError(
                    f"node {node.node_id} requires unsupported capabilities {missing}"
                )

    def _assert_acyclic(self) -> None:
        white, grey, black = 0, 1, 2
        color = {nid: white for nid in self.nodes}

        def visit(nid: str, stack: tuple[str, ...]) -> None:
            color[nid] = grey
            for parent in self.nodes[nid].parents:
                if color[parent] == grey:
                    cyc = " -> ".join((*stack, nid, parent))
                    raise ValueError(f"cycle detected in feature DAG: {cyc}")
                if color[parent] == white:
                    visit(parent, (*stack, nid))
            color[nid] = black

        for nid in self.nodes:
            if color[nid] == white:
                visit(nid, ())

    def topological_order(self) -> list[str]:
        """Deterministic topo order: parents before children, ties broken by node_id."""

        order: list[str] = []
        visited: set[str] = set()

        def visit(nid: str) -> None:
            if nid in visited:
                return
            for parent in sorted(self.nodes[nid].parents):
                visit(parent)
            visited.add(nid)
            order.append(nid)

        for nid in sorted(self.nodes):
            visit(nid)
        return order

    def max_warmup_bars(self) -> int:
        """Warm-up needed before any node is defined = sum along the deepest path."""

        memo: dict[str, int] = {}

        def depth_warmup(nid: str) -> int:
            if nid in memo:
                return memo[nid]
            node = self.nodes[nid]
            parent_max = max((depth_warmup(p) for p in node.parents), default=0)
            memo[nid] = node.warmup_bars + parent_max
            return memo[nid]

        return max((depth_warmup(nid) for nid in self.nodes), default=0)

    def dag_hash(self) -> str:
        ordered = self.topological_order()
        return canonical_hash(
            {
                "topological_order": ordered,
                "node_hashes": {nid: self.nodes[nid].node_hash() for nid in ordered},
            }
        )

    def payload(self) -> dict[str, Any]:
        ordered = self.topological_order()
        return {
            "artifact_id": "V3_FEATURE_DAG_V1",
            "node_count": len(self.nodes),
            "edge_count": sum(len(n.parents) for n in self.nodes.values()),
            "max_warmup_bars": self.max_warmup_bars(),
            "topological_order": ordered,
            "nodes": [self.nodes[nid].identity() | {"node_hash": self.nodes[nid].node_hash()}
                      for nid in ordered],
            "dag_hash": self.dag_hash(),
        }


def _causal(
    node_id: str,
    kind: str,
    *,
    source_fields: tuple[str, ...],
    lookback: int,
    caps: tuple[str, ...],
    units: str,
    parents: tuple[str, ...] = (),
    instrument_dependencies: tuple[str, ...] = ("self",),
    granularity: str = "M1",
    normalization: str = "none",
    warmup: int | None = None,
) -> FeatureNode:
    return FeatureNode(
        node_id=node_id,
        kind=kind,
        source_fields=source_fields,
        instrument_dependencies=instrument_dependencies,
        granularity=granularity,
        lookback_bars=lookback,
        warmup_bars=lookback if warmup is None else warmup,
        timestamp_availability="bar_close_t",
        units=units,
        nan_policy=NanPolicy.DROP_WARMUP,
        normalization=normalization,
        causality=Causality.CAUSAL_ENDPOINT,
        required_capabilities=caps,
        parents=parents,
    )


def build_canonical_dag() -> FeatureDAG:
    """The frozen set of causal primitive + derived feature nodes shared across families."""

    dag = FeatureDAG()
    # --- base price/return primitives ---
    dag.add(_causal("mid_close", "mid_price", source_fields=("bid_close", "ask_close"),
                    lookback=1, caps=("MID_OHLC",), units="price", warmup=0))
    dag.add(_causal("m1_return", "log_return", source_fields=("mid_close",), lookback=2,
                    caps=("M1_RETURNS",), units="log_return", parents=("mid_close",)))
    dag.add(_causal("spread", "quoted_spread", source_fields=("bid_close", "ask_close"),
                    lookback=1, caps=("M1_SPREAD",), units="price", warmup=0))
    # --- volatility / range estimators (right-aligned) ---
    dag.add(_causal("realized_vol", "rolling_std_return", source_fields=("mid_close",),
                    lookback=60, caps=("M1_REALIZED_VOL",), units="vol",
                    parents=("m1_return",)))
    dag.add(_causal("parkinson_vol", "parkinson_range_vol",
                    source_fields=("mid_high", "mid_low"), lookback=60,
                    caps=("RANGE_ESTIMATORS_M1",), units="vol"))
    dag.add(_causal("atr", "wilder_atr", source_fields=("mid_high", "mid_low", "mid_close"),
                    lookback=14, caps=("RANGE_ESTIMATORS_M1",), units="price"))
    dag.add(_causal("range_compression", "hl_range_ratio",
                    source_fields=("mid_high", "mid_low"), lookback=60,
                    caps=("RANGE_ESTIMATORS_M1",), units="ratio"))
    # --- momentum / trend (right-aligned regression slope over a window) ---
    dag.add(_causal("trend_slope", "ols_slope_tstat", source_fields=("mid_close",),
                    lookback=120, caps=("M1_RETURNS",), units="tstat",
                    parents=("mid_close",)))
    dag.add(_causal("mom_zscore", "return_zscore", source_fields=("mid_close",), lookback=60,
                    caps=("M1_RETURNS",), units="z", normalization="rolling_zscore",
                    parents=("m1_return",)))
    # --- mean reversion ---
    dag.add(_causal("dist_from_ewma", "price_minus_ewma", source_fields=("mid_close",),
                    lookback=120, caps=("M1_RETURNS",), units="z",
                    normalization="rolling_zscore", parents=("mid_close",)))
    # --- microstructure (spread state) ---
    dag.add(_causal("spread_zscore", "spread_zscore", source_fields=("bid_close", "ask_close"),
                    lookback=120, caps=("M1_SPREAD",), units="z",
                    normalization="rolling_zscore", parents=("spread",)))
    # --- seasonality / calendar (conditioning variables) ---
    dag.add(_causal("session_cell", "ny_session_bucket", source_fields=("timestamp",),
                    lookback=1, caps=("SESSION_TIME_OF_DAY",), units="categorical", warmup=0))
    dag.add(_causal("calendar_cell", "calendar_bucket", source_fields=("timestamp",),
                    lookback=1, caps=("CALENDAR_CELLS",), units="categorical", warmup=0))
    # --- cross-pair / factor structure (multi-instrument, synchronized) ---
    dag.add(_causal("cross_return_panel", "synced_return_panel", source_fields=("mid_close",),
                    lookback=2, caps=("CROSS_PAIR_SYNC", "CURRENCY_FACTOR_PANEL"),
                    units="log_return", instrument_dependencies=("panel",),
                    parents=("m1_return",)))
    dag.add(_causal("usd_factor", "cross_sectional_usd_factor", source_fields=("mid_close",),
                    lookback=60, caps=("CURRENCY_FACTOR_PANEL",), units="factor_return",
                    instrument_dependencies=("panel",), parents=("cross_return_panel",)))
    dag.add(_causal("factor_residual", "residual_vs_usd_factor", source_fields=("mid_close",),
                    lookback=60, caps=("CURRENCY_FACTOR_PANEL",), units="residual_return",
                    instrument_dependencies=("panel",),
                    parents=("cross_return_panel", "usd_factor")))
    # --- statistical-arbitrage residual (triangular / cointegration, rolling hedge) ---
    dag.add(_causal("triangle_residual", "triangular_residual_zscore",
                    source_fields=("mid_close",), lookback=300,
                    caps=("TRIANGULAR_RESIDUAL",), units="z",
                    normalization="rolling_zscore",
                    instrument_dependencies=("triangle",), parents=("cross_return_panel",)))
    return dag
