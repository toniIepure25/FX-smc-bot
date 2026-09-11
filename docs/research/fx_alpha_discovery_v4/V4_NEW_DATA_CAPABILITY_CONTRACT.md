# V4 New-Data Capability Contract

**Artifact:** `results/gate_v4/v4_new_data_capability_contract.json`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V4`
**Gate:** `V4_NEW_DATA_CAPABILITY_CONTRACT`
**Starting SHA:** `bf4eea2b21a31af620f6aa4b19a89a9863c5b84a`
**Contract Hash:** `b9899bc7ab48613313176bf2d3e01b71f56e4681157a4919d8a1acc0bc2bd3f3`

---

## 0. Pre-Data Factual Corrections

| ID | Correction |
|---|---|
| C1 | GLBX.MDP3 supports historical MBP-10 / L2 top-10 depth. MBO/L3 full order-by-order granularity begins **2017-05-21**. Before then MBP-10 is the highest granularity. |
| C2 | Micro JPY code is **MJY**, not M6J. (Does not affect primary pilot which uses standard 6J.) |
| C3 | V3 NO_SIGNAL=476 means **no positive intrinsic/gross edge before costs**, NOT "no trades". Zero-trade belonged to LOW_ACTIVITY. Factual correction to label interpretation; does NOT change immutable V3 outcomes. |

---

## 1. Provider / Dataset

| Field | Value |
|---|---|
| Provider | Databento |
| Dataset | GLBX.MDP3 (CME Globex, MDP 3.0) |
| Primary pilot schema | **MBP-10** |
| Auxiliary schemas | Definition, Status |
| MBO (L3) | AVAILABLE_FUTURE_CAPABILITY_NOT_IN_PRIMARY_PILOT |
| API credentials | **NOT available** in this session |

All metadata values (record count, billable size, cost) are emitted as **exact
commands** to execute when `DATABENTO_API_KEY` is provided. No values invented.

**MDP2 limitations:**
- Pre-2017-05-21: level-aggregated (MBP only, no MBO)
- `ts_recv` on old data may equal `ts_event` or be flagged `F_BAD_TS_RECV` — must NOT be treated as genuine capture latency
- Timestamp resolution changes historically must be recorded

---

## 2. Primary Contracts

| Contract | Pair | Multiplier | Tick Size | Tick Value | Quotation | Expiration |
|---|---|---|---|---|---|---|
| **6E** | EUR/USD | 125,000 EUR | 0.000005 | $0.625 | USD per EUR | Quarterly (Mar/Jun/Sep/Dec) |
| **6J** | JPY/USD | 12,500,000 JPY | 0.000001 | $12.50 | JPY per USD | Quarterly (Mar/Jun/Sep/Dec) |
| **6B** | GBP/USD | 100,000 GBP | 0.000005 | $0.50 | USD per GBP | Quarterly (Mar/Jun/Sep/Dec) |

**6J is JPY/USD, NOT spot USDJPY orientation.** A rise in 6J means JPY weakens vs USD.

Trading hours: Sun 17:00 - Fri 16:00 CT (1h break 16:00-17:00 CT).
Expiration: last business day before the 3rd Wednesday of the contract month.

**Excluded:** options, calendar spreads, inter-commodity spreads, synthetic
adjusted continuous prices, micro contracts.

---

## 3. Contract Eligibility / Roll Semantics

**Rule:** A contract is eligible iff:
1. raw_symbol matches parent product pattern (6E/6J/6B + YY + MMM)
2. start_date (Definition schema) ≤ pilot start
3. end_date ≥ pilot end
4. Outright futures (not option/spread/synthetic)

**NO selection based on historical volume, OI, or realized profitability.**

**Roll rule (frozen):** Calendar-based. Roll when current contract is within
5 trading days of expiration. Next eligible quarterly contract becomes front.
Databento roll rule: `calendar`.

**No back-adjusted synthetic price** as raw scientific data.

---

## 4. MBP-10 Capability Contract

**Record format:** DBN (Databento Binary Encoding), ZSTD-compressed (.dbn.zst).
**Immutable source truth:** Raw DBN/DBN.ZST files.

### MBP-10 Fields

| Field | Type | Semantics |
|---|---|---|
| ts_event | u64 | Exchange event time, ns since epoch (UTC) |
| ts_recv | u64 | Databento receive time, ns since epoch (UTC) |
| seq_msg | u32 | Per-channel message sequence number |
| msg_type | u8 | Message type code |
| channel | u8 | MDP channel ID |
| action | u8 | ADD=0, MODIFY=1, DELETE=2, EXECUTE=3, CLEAR=4 |
| side | u8 | BID=0, ASK=1 |
| instrument_id | u32 | Databento internal instrument ID |
| price | u64 | Price in raw tick units |
| size | u32 | Size in raw units |
| depth | u8 | Price level 1-10 (1 = best/top) |
| flags | u8 | Bitwise OR of RecordFlags |
| order_count | u32 | Orders at this level (if present) |
| ts_in_delta | u64 | ns delta from previous event (input) |
| ts_out_delta | u64 | ns delta from previous event (output) |

### Record Flags

| Flag | Value | Meaning |
|---|---|---|
| F_LAST | 128 | Last record in a single event |
| F_TOB | 64 | Top-of-book message |
| F_SNAPSHOT | 32 | Sourced from replay/snapshot server |
| F_MBP | 16 | Aggregated price level (not individual order) |
| F_BAD_TS_RECV | 8 | ts_recv inaccurate (clock issues) |
| F_MAYBE_BAD_BOOK | 4 | Unrecoverable gap detected |
| F_PUBLISHER_SPECIFIC | 2 | Publisher-specific event |

### Canonical Representation

- Format: Parquet (columnar, partitioned)
- Partition keys: instrument / contract / utc_date
- Preserves: seq_msg, channel, all fields above
- Provenance: source DBN file hash + seq_msg + channel

---

## 5. Information Classes

### ADMITTED for uniform pilot

- trades (price, size, ts_event, side)
- trade size
- top-of-book (best bid/ask + sizes)
- top-10 depth (price + size at each level)
- spread (ask - bid)
- microprice (size-weighted mid)
- top-level imbalance
- multi-level depth imbalance (levels 1-10)
- MBP order-flow imbalance (OFI from level changes)
- trade-flow imbalance (signed trade volume)
- liquidity depletion/replenishment
- event intensity
- short-horizon impact/response
- book slope / shape

### NOT ADMITTED

- individual order IDs
- true queue position
- maker queue priority
- order-level lifecycle
- full L3 cancellation/Hawkes features

**Never reconstruct fake L3 from MBP-10.**

---

## 6. Timestamp Semantics

- Event timezone: **UTC**
- Session timezone: **America/Chicago**
- Authoritative ordering: **ts_event + seq_msg** (per channel)
- `ts_event`: exchange event time (ns since epoch)
- `ts_recv`: Databento receive time (ns since epoch)
- MDP2 pre-2017: `ts_recv` may equal `ts_event` or be flagged `F_BAD_TS_RECV`
- **Do NOT derive latency alpha from unsupported timestamps**

---

## 7. Trade-Side Semantics

- Provider field: `side` (u8) on TradeMsg
- CME semantics: **aggressor side** — BUY=0 (lifted ask), SELL=1 (hit bid)
- Verification required against Databento docs when data acquired
- If inference needed: ONE deterministic classifier
  - `trade_price > mid_prev` → BUY
  - `trade_price < mid_prev` → SELL
  - `trade_price == mid_prev` → **UNKNOWN** (valid state)
- **Do NOT force every trade to BUY or SELL**

---

## 8. Book Reconstruction

Deterministic handling of: ADD, MODIFY, DELETE, EXECUTE, CLEAR,
snapshot/recovery, sequence gaps, duplicates, out-of-order events,
locked/crossed states, invalid sizes, missing depth, session reset,
definition changes.

**Data states:**

| State | Meaning |
|---|---|
| CERTIFIED | All 10 levels populated on both sides |
| EXPECTED_SESSION_ABSENCE | Session break (16:00-17:00 CT) |
| PROVIDER_GAP | Provider-documented data gap |
| SEQUENCE_GAP | seq_msg jump detected |
| BOOK_INTEGRITY_FAILURE | Locked/crossed, invalid size |
| DEFINITION_FAILURE | Instrument definition change mid-stream |
| UNRESOLVED_DATA_GAP | Out-of-order or unresolvable state |

**Never silently repair.** All anomalies explicitly marked.

---

## 9. Execution Contract

- **TAKER / MARKETABLE ONLY**
- BUY → executable at best ask (depth=1, side=ASK)
- SELL → executable at best bid (depth=1, side=BID)
- Insufficient top-level size → **REJECT** (no depth walking in pilot)
- NO passive fills, NO maker queue simulation, NO inferred queue priority
- Prefer 1 contract for initial falsification pilot

---

## 10. Cost Contract

| Category | Component | Value |
|---|---|---|
| Observed | spread | ask - bid at event ts |
| Observed | depth consumption | size consumed at executable level |
| Explicit | CME exchange fee | Per CME fee schedule |
| Explicit | NFA regulatory fee | ~$0.03-0.15/contract/side |
| Explicit | Broker/clearing | $1.00/contract/side (conservative) |
| Stress | Adverse slippage | 1 additional tick |
| **Frozen assumption** | **Constant cost** | **1.0 bps per side (ASSUMPTION)** |

Do NOT optimize fees after outcomes.

---

## 11. V4 Exposure Registry

| Axis | Pre-2018 CME FX | 2018+ CME FX |
|---|---|---|
| PRICE_PATH | PREVIOUSLY_EXPOSED (V1-V3 M1) | SEALED (legacy holdout) |
| MICROSTRUCTURE | **UNEXPOSED** (new) | SEALED (legacy holdout) |

Legacy 2018+ FX holdout: **completely sealed, NOT accessible in V4.**

---

## 12. V4 Chronology (Revised)

Because 2018+ overlaps the sealed legacy holdout, V4 uses **ONLY pre-2018 data**
for all four roles:

| Role | Start | End | Exposure |
|---|---|---|---|
| Development | 2015-01-01 | 2016-06-30 | PRICE_EXPOSED / MICRO_UNEXPOSED |
| Internal Validation | 2016-07-01 | 2017-06-30 | PRICE_EXPOSED / MICRO_UNEXPOSED |
| External Validation | 2017-07-01 | 2018-03-31 | PRICE_EXPOSED / MICRO_UNEXPOSED |
| Final Sealed Holdout | 2018-04-01 | 2018-12-31 | PRICE_EXPOSED / MICRO_UNEXPOSED |

- No backward validation
- Roles fixed before download
- V4 final holdout (2018-04 to 2018-12) is DISTINCT from legacy 2018+ holdout

---

## 13. Target Semantics

- Primary comparison: **PRICE-HISTORY BASELINE vs MBP-10 MICROSTRUCTURE**
- Clock-time horizons: 1s, 5s, 30s, 1m, 5m
- Event-time horizons: 10, 50, 100, 500 events
- Target: signed price change from t to t+H at executable prices
- Features strictly before t (no lookahead)
- Corrupt/unavailable book intervals excluded
- **Horizons frozen. Do NOT optimize later.**

---

## 14. Minimal Pilot Objective

**Question:** DOES MBP-10 ADD INCREMENTAL INFORMATION BEYOND PRICE HISTORY?

- Primary metric: predictive-information improvement over baseline
- Secondary: economically large enough vs spread + fees?
- **NOT a profitability search**
- 5 hypotheses (H1-H5), no candidate grid
- Fail-fast: if no incremental info on dev+val, STOP

---

## 15. Provider Metadata / Cost

**No API credentials available.** Exact commands emitted in JSON.

Speculative storage estimates (pending provider metadata):
- ~0.5-2 GB/day/instrument (MBP-10, tick-level)
- ~150-700 GB/year/instrument
- Pilot total: 3 instruments × 4 years ~ 1.8-8.4 TB (raw DBN.ZST)
- Disk: ~10 TB (raw + canonical)

---

## 16. Storage / Compute

- Raw: immutable DBN.ZST, SHA-256 hash at download
- Canonical: Parquet, partitioned by instrument/contract/utc_date
- Streaming decode, bounded daily partitions, predicate pushdown
- **Mac M5 16GB: sufficient** (one daily partition fits)
- **A100: NOT required** for acquisition/canonicalization

---

## 17. Holdout Firewall

| Counter | Value |
|---|---|
| old_V1_V3_2018_plus_requests | 0 |
| old_V1_V3_2018_plus_reads | 0 |
| V4_sealed_holdout_requests | 0 |
| V4_sealed_holdout_reads | 0 |

Metadata-only requests allowed (no market outcomes returned).

---

## 18. Component Hashes

18 independent component hashes + 1 aggregate capability-contract hash:
`b9899bc7ab48613313176bf2d3e01b71f56e4681157a4919d8a1acc0bc2bd3f3`

Components: provider, dataset, contracts, eligibility, schema,
information_classes, timestamps, trade_side, book_reconstruction, execution,
costs, exposure_registry, chronology, targets, pilot, metadata_commands,
storage_compute, firewall.

---

## 19. Terminal Decision

**Verdict:** `V4_NEW_DATA_CAPABILITY_CONTRACT_FROZEN`

**Next gate:** `V4_MINIMAL_MICROSTRUCTURE_PILOT_DESIGN`

Do NOT download historical MBP-10. Do NOT define candidate grids. Do NOT run
models. Do NOT backtest.
