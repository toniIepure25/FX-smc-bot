# V4 Data-Class & Market-Arena Selection

**Artifact:** `results/gate_v4/v4_data_class_selection.json`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V4`
**Lineage:** `FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1`
**Starting SHA:** `28c269ee0d078ed8ebfa5cc31b8fd1179264d666`
**Scope:** Select the highest-information new data class + market arena for the next
prospective program. No data download, no V4 candidates, no backtest, no old 2018+
holdout access.

---

## 1. Immutable V3 Evidence (Context)

| Metric | Value |
|---|---|
| Cumulative trials (V1+V2+V3) | 1388 |
| Scientific survivors | 0 |
| WRC trajectory | ~1.0 across all programs |
| V3 Universe A (n=992) | 169 zero-trade, 20 positive_raw, 13 @1.5x, 12 @2.0x, 0 survivors |
| V3 Universe B (n=52) | 0 positive |
| PBO | 0.186 |

**V3 failure taxonomy (Universe A):**

| Class | Count | Share |
|---|---|---|
| NO_SIGNAL (no trades at all) | 476 | 48.0% |
| COST_DOMINATED (gross-positive, net-negative) | 272 | 27.4% |
| LOW_ACTIVITY (sparse, <250 trades) | 239 | 24.1% |
| STRESS_FRAGILE (fails stress) | 5 | 0.5% |

**Strong conclusions carried forward:**

1. Price-only public FX M1 is exhausted for the tested intraday classes.
2. Several gross-positive families are economically destroyed by execution cost.
3. True microstructure hypotheses remain **UNTESTED** — the old data lacks the
   information (no tick-level trades, no top-of-book, no signed flow).

---

## 2. Old Holdout Firewall

- Old-program 2018+ provider requests: **0**
- Old-program 2018+ market reads: **0**
- The sealed legacy 2018+ FX holdout is **NOT** used to compare markets.
- A new program gets its own prospective dev/val/holdout chronology.

---

## 3. Arena Comparison

| Dimension | A: CME FX Futures | B: CME Equity Futures | C: Spot FX Tick | D: Crypto L2 |
|---|---|---|---|---|
| Examples | 6E/6B/6J/6A, M6E/M6B/M6J | MES, MNQ | EURUSD, GBPUSD, USDJPY | BTC/ETH on Binance, Coinbase, Kraken, Bybit, Deribit, OKX |
| Data class | Tick trades + top-of-book (NBBO); **no full L2** | Tick trades + top-of-book; **no full L2** | Bid/ask quote updates; no central book | **Full L2** book events + signed trades + ToB + funding/OI |
| Market | Centralized CME FX (same as V1-V3) | Centralized CME equity (different) | Fragmented OTC (same FX, no venue) | Centralized crypto (different market) |
| Tick size | Explicit (6E 0.000005 ~ $0.50) | Explicit (MES 0.25 = $12.50) | Broker-dependent | Explicit per exchange |
| Fees | Explicit (CME+NFA+broker) | Explicit | Spread markup, hard to model | Explicit taker/maker + funding |
| Coverage | Decades (CME DataMine) | Decades | Broker-dependent, variable | >7 yr, 24/7, >99.9% (Tardis) |
| Providers | CME DataMine, Databento, FirstRate | CME DataMine, Databento, FirstRate | Dukascopy (M1), broker feeds | Tardis.dev, Kaiko, native APIs |
| FX lineage | **Yes** | No | Yes | No |

---

## 4. Scientific-Information Scores (1-5)

**Weights:** scientific_value 30%, info_content 25%, execution_fidelity 15%,
cost_signal 10%, data_quality 10%, practicality 5%, low_overfit_risk 5%.

| Criterion (weight) | A | B | C | D |
|---|---|---|---|---|
| scientific_value (0.30) | 5 | 3 | 2 | 4 |
| info_content (0.25) | 3 | 3 | 2 | 5 |
| execution_fidelity (0.15) | 5 | 5 | 2 | 4 |
| cost_signal (0.10) | 4 | 4 | 2 | 4 |
| data_quality (0.10) | 4 | 4 | 2 | 4 |
| practicality (0.05) | 4 | 4 | 2 | 5 |
| low_overfit_risk (0.05) | 4 | 4 | 3 | 2 |
| **Weighted total** | **4.20** | **3.60** | **2.05** | **4.20** |

**Tie-break:** A and D tie at 4.20. A is primary because it follows from the
V1/V2/V3 FX evidence (same market, new data class) and is a lower-friction
centralized venue. D is the fallback (highest raw information but a different
market, so V3 FX evidence does not transfer).

**Rationale for key scores:**

- **A scientific_value=5:** directly answers the V3 question — does FX
  microstructure add information M1 missed? Stays in FX lineage.
- **D scientific_value=4:** richest microstructure but different market; V3
  evidence does not transfer.
- **D info_content=5:** full L2 book events + signed trades + top-of-book.
- **A/B info_content=3:** trades + top-of-book, no full L2.
- **D low_overfit_risk=2:** crypto microstructure is less studied, more
  parameter-sensitive, and the 24/7 regime shifts increase overfit risk.
- **C low_overfit_risk=3:** fragmented OTC data is too noisy to overfit to
  meaningfully, but also too noisy to learn from.

---

## 5. Information Classes & Capability Honesty

| Class | A: CME FX | B: CME Equity | C: Spot FX | D: Crypto L2 |
|---|---|---|---|---|
| TRADE_FLOW (ts, price, size, side) | Yes | Yes | Partial | Yes (signed) |
| TOP_OF_BOOK (bid/ask + sizes) | Yes | Yes | Yes (broker) | Yes |
| DEPTH (multi-level) | **No** | **No** | **No** | Yes |
| BOOK_EVENTS (add/cancel/modify/execute) | **No** | **No** | **No** | Yes |
| DERIVED (OFI, microprice, spread state, book slope, resiliency) | Partial (trades+quotes) | Partial | Limited | Full |

**Capability honesty:** Arena A supports TRADE_FLOW + TOP_OF_BOOK + derived
features (microprice, OFI from trades+quotes) but does **NOT** support DEPTH or
BOOK_EVENTS (no full L2). Arena D supports all classes.

---

## 6. Pilot Questions (not strategies)

| ID | Question |
|---|---|
| P1 | Does signed trade/quote/depth flow predict subsequent short-horizon price movement beyond price history alone? |
| P2 | Does microstructure state identify periods where expected move >> executable spread + fee? |
| P3 | Is predictive information clearer in event-time than fixed M1 sampling? |
| P4 | Does liquidity depletion/replenishment contain information not captured by M1 range/return/spread? |
| P5 | Do families analogous to V3 gross-positive/cost-dominated classes become economically plausible in a centralized lower-friction arena? |

These are **questions, not strategies**. No candidate grids.

---

## 7. Banned Classes

- Another large M1 indicator sweep
- Stacking RSI/MACD/moving averages
- Threshold combinatorics
- Post-hoc session optimization
- Parameter rescue around V3 positives
- Fake tick features reconstructed from candles
- Price-only triangular / cointegration repetition
- High-turnover mean-reversion without explicit executable-cost conditioning

---

## 8. Model Capacity Note

Do **NOT** choose deep learning as the objective. First prove the new
information class adds incremental predictive information over a
price-history baseline. Later models may include: linear/logistic baselines,
state-space/latent-factor, Hawkes/event-process, change-point, sequence,
self-supervised event representations, optimal stopping/execution timing.
Representation learning is secondary.

---

## 9. Minimal Falsification Pilot

| Parameter | Value |
|---|---|
| Arena | A: CME FX futures (primary) |
| Instruments | 2-3 liquid FX futures (M6E, M6J, M6B) |
| Period | 12-24 months of tick data |
| Split | Frozen chronological dev/val BEFORE outcomes; separately sealed holdout (new program's own chronology) |
| Comparison | Price-only M1 baseline vs new-information model (trades + top-of-book flow features) |
| Execution | Executable bid/ask + explicit CME fees + tick size; event-time where appropriate |
| Measure | Incremental predictive information (log-loss / rank-IC beyond baseline) AND economic value (net of executable cost) |
| Hypotheses | Small (<= 5, e.g. P1-P3) |
| Answers | DOES THE NEW DATA CLASS ADD INFORMATION? (not: can we find a profitable strategy by searching enough parameters?) |
| Fail-fast | If the new-information model adds no incremental predictive information over the price-only baseline on dev+val, STOP — the data class is not worth a full program |

---

## 10. Data-Split / Chronology Policy

- **New prospective chronology:** development → internal_validation → external_validation → final_sealed_holdout
- **Old 2018 FX holdout:** NOT part of the new program; remains sealed.
- **No backward validation:** never discover on later data and validate backwards on the old 2018 holdout.
- **Roles fixed before:** every role fixed before downloading/inspecting outcomes where operationally feasible.
- **Pre-existing exposure:** none assumed; document any unavoidable exposure at the capability-contract gate.

---

## 11. Resource Plan (Primary Arena A)

| Resource | Estimate |
|---|---|
| GB/day/instrument | ~0.5-2 GB (trades + top-of-book, tick-level) |
| GB/month/instrument | ~15-60 GB |
| GB/year/instrument | ~150-700 GB |
| Pilot footprint | 2-3 instruments x 12-24 months ~ 5-50 GB |
| RAM | 16 GB sufficient for streaming/predicate-pushed Parquet |
| Disk | ~100 GB pilot; ~1-2 TB full multi-year program |
| CPU | CPU-only sufficient for pilot; A100 optional later |
| Storage format | Partitioned Parquet (instrument/date), streaming, predicate pushdown, event-native schema |

---

## 12. Decision

| Rank | Arena | Score | Role |
|---|---|---|---|
| 1 | A: CME FX futures | 4.20 | **PRIMARY** |
| 2 | D: Crypto L2 | 4.20 | **FALLBACK** |
| 3 | B: CME equity futures | 3.60 | not selected |
| 4 | C: Spot FX tick | 2.05 | not selected |

**Primary:** `NEW_DATA_CLASS_CME_FX_FUTURES_MICROSTRUCTURE_SELECTED`
**Fallback:** `NEW_DATA_CLASS_CRYPTO_L2_SELECTED`

**Why A dominates:** A is the only arena that (1) stays in the FX market so the
V1/V2/V3 evidence directly transfers, (2) provides true microstructure (trades +
top-of-book) to test the untested microstructure hypotheses, and (3) is a
centralized lower-friction venue that directly addresses the V3 cost-dominated
lesson. D has richer raw information (full L2) but is a different market, so
the V3 FX evidence does not transfer; it is the fallback if CME FX futures data
is unavailable/too costly.

**Not selected:**

- **B (CME equity futures):** same data class as A but a different market
  (equity indices); the V3 FX evidence does not transfer.
- **C (Spot FX tick):** fragmented OTC, no central order book, variable
  quality, hard to model execution; cannot fully test microstructure.

---

## 13. Next Gate

**`V4_NEW_DATA_CAPABILITY_CONTRACT`** — define and freeze data semantics /
acquisition for the selected arena (contract specs, provider, schema, coverage,
cost, the new dev/val/holdout chronology). DO NOT download the full dataset,
materialize V4 candidates, or run a backtest in this session.

---

## 14. Terminal Verdict

`NEW_DATA_CLASS_CME_FX_FUTURES_MICROSTRUCTURE_SELECTED`
