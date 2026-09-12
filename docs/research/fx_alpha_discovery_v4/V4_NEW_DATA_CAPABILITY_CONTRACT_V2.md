# V4 New-Data Capability Contract V2 (Pre-Outcome Factual Correction)

**Artifact:** `results/gate_v4/v4_new_data_capability_contract_v2.json`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V4`
**Gate:** `V4_NEW_DATA_CAPABILITY_CONTRACT`
**Starting SHA:** `0e7d4fe33e9041d3176a6c8896628cb9cb4e72bb`
**Supersedes Hash:** `b9899bc7ab48613313176bf2d3e01b71f56e4681157a4919d8a1acc0bc2bd3f3`
**New Contract Hash:** `9de92fc724cb936854a4...` (19 components)
**Lineage:** V4_CAPABILITY_CONTRACT_V1 → PRE_OUTCOME_FACTUAL_CORRECTION → V4_CAPABILITY_CONTRACT_V2

---

## Corrections Applied (10)

| # | Correction |
|---|---|
| C1 | Corrected 6E/6J/6B contract specs (tick size, tick value, contract size, quotation) |
| C2 | Replaced spanning-contract eligibility with per-date eligibility + 5-trading-day roll |
| C3 | Corrected MBP-10 schema to Databento documented fields |
| C4 | Corrected trade-side semantics to provider-native B/A/N (no inference) |
| C5 | Corrected book-state semantics (authoritative embedded state) |
| C6 | Fixed chronology to completely pre-2018 |
| C7 | Recorded historical protocol regimes |
| C8 | Fixed cost model to USD/contract/side |
| C9 | Corrected target semantics to direction-neutral |
| C10 | Rebuilt contract identity (new hash, lineage V1→V2) |

---

## 1. Corrected CME Contract Specs

| Contract | Pair | Size | Quotation | Tick | Tick Value | Direction |
|---|---|---|---|---|---|---|
| **6E** | EUR/USD | 125,000 EUR | USD per EUR | 0.00005 | $6.25 | ↑ = EUR strengthens |
| **6J** | USD/JPY | 12,500,000 JPY | USD per JPY | 0.0000005 | $6.25 | ↑ = **JPY strengthens** |
| **6B** | GBP/USD | 62,500 GBP | USD per GBP | 0.0001 | $6.25 | ↑ = GBP strengthens |

**6J: A PRICE INCREASE means JPY STRENGTHENS vs USD** (inverse of spot USDJPY convention).

All three: quarterly (Mar/Jun/Sep/Dec), expire last business day before 3rd Wednesday,
CME Globex, Sun 17:00 - Fri 16:00 CT.

---

## 2. Per-Date Contract Eligibility

A contract is eligible on date D iff:
1. Outright standard 6E/6J/6B future
2. Definition metadata shows it active on D
3. D precedes its frozen calendar roll date
4. Valid definition and book data exist on D

**Roll rule:** Exactly 5 CME trading days before expiration. Calendar metadata only.
NO volume, OI, returns, or profitability.

---

## 3. Corrected MBP-10 Schema

**Core fields:** ts_recv, ts_event, rtype, publisher_id, instrument_id, action (char: A/M/D/T/C), side (char: B/A/N), depth (u8), price (int64, 1 unit = 1e-9), size (int64), flags (u8), ts_in_delta (int32), sequence (uint32)

**Top-10 level arrays (embedded in each record):**
- bid_px_00..09, ask_px_00..09 (int64)
- bid_sz_00..09, ask_sz_00..09 (int64)
- bid_ct_00..09, ask_ct_00..09 (int64, if present)

**Removed from V1:** seq_msg, msg_type, channel, ts_out_delta

**Canonical provenance:** ts_event, sequence, publisher_id, instrument_id, raw DBN hash

---

## 4. Trade-Side Semantics

| Provider value | Meaning |
|---|---|
| B | BUY aggressor (lifted ask) |
| A | SELL aggressor (hit bid) |
| N | UNKNOWN |

**No inference.** UNKNOWN is valid. No forced signing.

---

## 5. Book-State Semantics

MBP-10 is **NOT** an MBO delta stream. The embedded top-10 level arrays on each
record are **authoritative**. action/depth describe the triggering event only.

**Validity:** valid BBO, bid < ask, nonnegative sizes, monotone price levels,
valid sequence, explicit missing levels. Do NOT require all 10 levels.

**No manual mutation.** No invented ADD/MODIFY/DELETE/EXECUTE arithmetic.

---

## 6. Completely Pre-2018 Chronology

| Role | Start | End | Protocol Era |
|---|---|---|---|
| Development | 2016-01-01 | 2016-09-30 | MDP2, ms→ns precision |
| Internal Validation | 2016-10-01 | 2017-03-31 | MDP2, ns |
| External Validation | 2017-04-01 | 2017-08-31 | MDP2→MDP3 (2017-05-21) |
| Final Sealed Holdout | 2017-09-01 | 2017-12-31 | MDP3 |

All periods: PRICE_PATH_PREVIOUSLY_EXPOSED / MICROSTRUCTURE_UNEXPOSED
**2018-01-01 onward: SEALED. No V4 period touches it.**

---

## 7. Protocol Regimes

| Era | Period | Source | Precision |
|---|---|---|---|
| MDP2/FIX | 2010-06 to 2017-05-20 | Legacy MDP2/FIX flat-file | ms (pre-2015-11-20), ns (after) |
| MDP3/MBOFD | 2017-05-21+ | MDP3/MBOFD | ns |

`protocol_era` field in provenance. NOT an alpha feature.

---

## 8. Cost Model (USD/contract/side)

| Component | Value |
|---|---|
| CME exchange fee | Per fee schedule |
| NFA regulatory | Per contract/side |
| Broker/clearing | Per contract/side |
| **Frozen assumption** | **$2.50/contract/side (ASSUMPTION)** |
| Stress primary | +1 adverse tick |
| Stress secondary | +2 adverse ticks |

**NOT bps.** Spread is observed market data, charged separately. No double counting.

---

## 9. Target Semantics (Direction-Neutral)

**Primary target:** Future midprice (or microprice) change from feature cutoff to t+H.
`target = (mid_{t+H} - mid_t) / mid_t` or tick-normalized.

**Economic evaluation (separate):** BUY/SELL round-trip at executable prices + USD fees.

Horizons: 1s, 5s, 30s, 1m, 5m (clock); 10, 50, 100, 500 (event). Frozen.

---

## 10. Firewall Counters

| Counter | Value |
|---|---|
| historical_mbp10_outcome_requests | 0 |
| historical_trades_outcome_requests | 0 |
| v4_model_computations | 0 |
| v4_backtests | 0 |
| old_V1_V3_2018_plus_requests | 0 |
| old_V1_V3_2018_plus_reads | 0 |
| V4_2018_plus_requests | 0 |
| V4_2018_plus_reads | 0 |

---

## Terminal Verdict

`V4_NEW_DATA_CAPABILITY_CONTRACT_V2_FROZEN`

**Next gate:** `V4_MINIMAL_MICROSTRUCTURE_PILOT_DESIGN` (do NOT start in this session)
