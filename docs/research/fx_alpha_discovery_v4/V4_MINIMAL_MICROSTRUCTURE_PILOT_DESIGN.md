# V4 Minimal Microstructure Pilot Design

**Artifact:** `results/gate_v4/v4_minimal_microstructure_pilot_design.json`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V4`
**Gate:** `V4_MINIMAL_MICROSTRUCTURE_PILOT_DESIGN`
**Starting SHA:** `c1b13ee24669785a16c8a9b077e774b864e3aea0`
**Capability Contract Hash:** `9de92fc724cb936854a496892db85ca04bd6769082b4944b19ce918931f36091`
**Pilot Design Hash:** `28b1b4cf9f6db38828029c37c3daf09f9dd9f3feb769d8f949303e662a48b9b5`

---

## Philosophy

Falsification experiment, NOT alpha search. 5 hypotheses, 1 model class
(ridge linear), 1 baseline (P0), 4 fixed feature groups, frozen targets,
frozen inference, frozen pass/fail. No strategy grid.

## Staged Data Access

| Stage | Period | Status in P1 |
|---|---|---|
| Development | 2016-01-01 to 2016-09-30 | ACCESSIBLE |
| Internal Validation | 2016-10-01 to 2017-03-31 | ACCESSIBLE |
| External Validation | 2017-04-01 to 2017-08-31 | **UNOPENED** |
| Final Holdout | 2017-09-01 to 2017-12-31 | **SEALED** |
| 2018+ | 2018-01-01+ | **ABSOLUTELY SEALED** |

Positive P1 does NOT authorize opening external validation in same run.

## Day Sampling

SHA256(`V4_P1_SAMPLE_V1|{instrument}|{YYYY-MM-DD}`), sort, first 4 per
instrument-month. ~180 instrument-days total. No outcome-based selection.

## Instruments

6E, 6J, 6B. Per-date eligibility + 5-trading-day roll. No reduction later.
6J: price up = JPY strengthens.

## Feature Groups

| Group | Content |
|---|---|
| P0 | Price-only: lagged mid returns, realized vol, trend, calendar |
| P1 | Trade flow: signed count/volume (B/A/N), total count/volume, BSI |
| P2 | L1 book: spread ticks, bid/ask sz, I1, microprice-mid |
| P3 | L2 top-10: aggregated depth, I10, depth-weighted imbalance, OFI, slope |

## Key Formulas

- **I1** = (B0-A0)/(B0+A0), 0 if denom=0
- **MP** = (ask*B0 + bid*A0)/(B0+A0), in ticks vs mid
- **I10** = sum(1/l*(bid_l-ask_l)) / sum(1/l*(bid_l+ask_l)), l=1..10
- **OFI** = sum(1/l*(d_bid_l - d_ask_l)) from successive states
- **STC** = count(B) - count(A), N=0

## Windows / Anchors

- Event-time: 50, 500 events
- Clock-time: 1s, 5s
- Anchors: every 30s (clock) / every 500 events (event-time)

## Confirmatory Targets

| ID | Horizon | Unit |
|---|---|---|
| T1 | 5 seconds | ticks |
| T2 | 30 seconds | ticks |
| T3 | 100 events | ticks |

Direction-neutral mid change. No horizon optimization.

## Five Hypotheses

| H | Statement | Target | Comparison |
|---|---|---|---|
| H1 | Trade flow adds info | T1 | P0+P1 vs P0 |
| H2 | Top-of-book adds info | T1 | P0+P2 vs P0 |
| H3 | Depth adds info beyond BBO | T2 | P0+P2+P3 vs P0+P2 |
| H4 | Event-time > clock-time | T3 | Event vs clock model |
| H5 | Cost-aware calibration | T2 | Decile monotonicity |

## Model

Ridge linear. Alpha grid: [0.01, 0.1, 1, 10, 100]. Blocked CV in dev.
Standardize on dev only. No trees/NN/boosting.

## Inference

2000 paired day-block bootstrap. One-sided. Holm for H1-H4.
Unit: instrument-session-day.

## Pass/Fail (ALL must hold)

1. Holm p <= 0.05
2. Pooled validation loss improves
3. >50% instrument-days improve
4. Positive in >= 2 of 3 instruments

## GO/NO-GO

- >=1 of H1-H4 passes → `V4_MINIMAL_PILOT_INCREMENTAL_INFORMATION_FOUND`
- None pass → `V4_MINIMAL_PILOT_NO_INCREMENTAL_MICROSTRUCTURE_INFORMATION`

## Firewall

P1: dev + int-val sample dates only. Reject ext-val, holdout, 2018+.
All counters = 0.

## Next Gate

`V4_PILOT_METADATA_COST_PREFLIGHT` — obtain real metadata, verify symbols,
report cost/size. Download ZERO MBP-10 outcomes.
