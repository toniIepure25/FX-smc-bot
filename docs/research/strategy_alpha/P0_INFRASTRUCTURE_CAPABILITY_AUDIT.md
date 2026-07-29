# P0 Infrastructure Capability Audit

Status: `PASS`

| Capability | Status | Evidence |
| --- | --- | --- |
| signal_timestamping | IMPLEMENTED_NOT_CERTIFIED | CausalBarContext carries bar_idx and timestamp. |
| entry_timing | IMPLEMENTED_NOT_CERTIFIED | Pending orders are processed on subsequent bars in the engine loop. |
| market_and_limit_orders | IMPLEMENTED_NOT_CERTIFIED | FillEngine and BidAskFillEngine implement MARKET/LIMIT/STOP. |
| bid_ask_execution | IMPLEMENTED_NOT_CERTIFIED | BidAskFillEngine uses ask for long entry and bid for short entry. |
| same_bar_ambiguity | CERTIFIED | Conservative fill policy resolves SL before TP. |
| spread | PARTIAL | Native bid/ask embeds actual spread; fallback fixed spread exists. |
| slippage | IMPLEMENTED_NOT_CERTIFIED | Fixed and native bid/ask slippage models exist. |
| commission | IMPLEMENTED_NOT_CERTIFIED | TradeLedger has commission_per_lot. |
| swap | IMPLEMENTED_NOT_CERTIFIED | SwapCalculator exists for overnight positions. |
| position_sizing | PARTIAL | Portfolio state exists; 1R normalized P0 layer required. |
| overlapping_positions | PARTIAL | Portfolio state exists; candidate-level overlap guard required. |
| maximum_exposure | PARTIAL | Configs define max_concurrent_positions. |
| session_cutoffs | PARTIAL | Session classification exists; hard cutoff enforcement varies by runtime. |
| dst_handling | IMPLEMENTED_NOT_CERTIFIED | Timezone/session utilities exist. |
| weekend_handling | PARTIAL | Data-quality handling exists; P0 no-trade policy freezes missing periods. |
| missing_bars | PARTIAL | Provenance records missing intervals; P0 freezes no interpolation. |
| partial_fills | MISSING | Order model fills all units. |
| order_expiry | IMPLEMENTED_NOT_CERTIFIED | Orders expire via expires_at. |
| trade_ledger | IMPLEMENTED_NOT_CERTIFIED | TradeLedger exists; P0 commits aggregate-only outputs. |
| equity_curve | IMPLEMENTED_NOT_CERTIFIED | BacktestResult and metrics consume equity curve. |
| drawdown | IMPLEMENTED_NOT_CERTIFIED | Performance metrics compute max drawdown. |
| deterministic_replay | PARTIAL | Seeded components exist; P0 adds deterministic aggregate replay audit. |
| random_seed_control | IMPLEMENTED_NOT_CERTIFIED | Campaign and fill engines accept seeds. |
| benchmark_generation | MISSING | P0 must freeze benchmarks before alpha claims. |
| block_bootstrap_inference | PARTIAL | Research inference utilities exist; strategy-level inference is P0 scoped. |
