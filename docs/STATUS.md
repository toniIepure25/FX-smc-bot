# Project Status

**Status:** `CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED`
**As of:** 2026-11-03
**Scope:** FX M1 structural alpha discovery, 13 pairs, 2010–2017
**Evidence:** [V5R Terminal Postmortem](research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md)

This is the single authoritative status page for the repository. If another
document disagrees with this page, **this page wins**. Research documents and
result artifacts are historical evidence; they are not updated retroactively.

---

## 1. Bottom line

- The 2026 FX M1 alpha-discovery programme is **terminally closed**.
- **Zero** candidates survived the pre-registered gates.
- The **2018+ holdout was never inspected** and remains sealed.
- There is **no validated live edge** and no basis for deploying capital.
- The framework, data plumbing, test suite and research protocol remain usable
  engineering assets.

The isolated R7 result (5 trades, +675 bps gross, Sharpe 0.002) is a
small-sample artifact. It is not alpha and must not be promoted.

## 2. Lineage

| Version | Scope | Candidates | Verdict | Status |
|---|---|---:|---|---|
| V1–V3 | Broad signal search: momentum, mean reversion, volatility, session/calendar, ML | 1,388 | `V3_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` | Scientific null |
| V4 | CME FX futures L2 microstructure (Databento) | 0 | `V4_CLOSED_NO_PAID_DATA_ACQUISITION` | Never executed |
| V5 | First "structural models" attempt | 160 | `V5_DISCOVERY_COMPLETE_NO_SCIENTIFIC_SURVIVOR` | Invalid — fidelity failures |
| V5 forensics | Engineering audit of V5 | — | `V5_FORENSICS_MIXED` | Diagnostic only |
| V5R | True structural models: Kalman, GMM, cross-sectional, PCA, GRU/TCN, cost-aware | 88 | `V5R_TRUE_STRUCTURAL_MODELS_NO_PRE_HOLDOUT_EDGE` | Invalid — protocol deviations |
| V5R corrected | Protocol-conformance rerun of V5R | 88 | `V5R_CORRECTED_NO_PRE_HOLDOUT_EDGE` | Scientific null |

Tested information classes included M1 OHLCV, bid/ask and spread, realised and
Parkinson volatility, ATR, range compression, trend slope, momentum/distance
z-scores, session/calendar features, cross-sectional strength across 13 pairs,
PCA factor residuals, Kalman state, GMM regimes and neural sequence encoders.

Tested cost models ranged from 0.40 bps round-trip base to 0.80 bps stress, plus
bid/ask execution. Horizons were 15, 30, 60, 120 and 240 minutes.

## 3. What is and is not validated

| Claim | Status |
|---|---|
| A repeatable FX M1 edge exists in the tested data | **Not established** — null result |
| Any candidate is ready for live trading | **No** |
| The 2018+ holdout is clean | **Yes** — it was never read |
| The backtest/execution code is useful and tested | **Yes**, with the caveats below |
| The legacy `bos_only_usdjpy` paper programme proves an edge | **No** — it was designed on earlier data and never produced recorded sessions |
| The forward paper Docker service is safe for live money | **No** — legacy, unvalidated, requires credentials |

## 4. Important artifact discrepancy

`results/gate_v5r_corrected/v5r_corrected_discovery_decision.json` contains:

```json
"next_gate": "MARKET_PIVOT_CRYPTO_PERPETUALS"
```

That field is a **generated run artifact**, not a decision. The terminal
postmortem (2026-09-13) explicitly says there is **no next alpha gate**, and the
repository's final commit records the programme as exhausted. Do not treat the
JSON field as approval for a crypto-perpetuals programme.

Likewise, `docs/PROJECT_CONTEXT_FOR_LLMS.md` and `docs/LLM_HANDOFF_SUMMARY.md`
describe the earlier paper-trading state (2026-04). They are retained as
historical handoffs and are **superseded by this page**.

## 5. Holdout and data rules

- The 2018+ holdout is sealed. No inspection, summary statistics or model
  selection may touch it.
- The canonical research window is 2010–2017 M1 FX data, digest
  `15a5c1af...` as recorded in the terminal postmortem.
- Data outside the research window requires a new programme and a new
  pre-registration before any access.
- Raw tick/M1 datasets are not committed; see [data/README.md](../data/README.md).

## 6. Prohibited actions on the current programme

The following are explicitly out of bounds:

- no V6 on the same FX data;
- no new parameter sweeps, threshold tuning or signal inversions;
- no candidate rescues or "one more variant" runs;
- no re-labelling invalid runs as valid;
- no post-hoc changes to frozen protocols, gates or candidate lists;
- no 2018+ inspection;
- no live deployment based on V1–V5R results.

Any new research must start from a new data class or market, with a new
pre-registered protocol, and must not reuse the closed programme's holdout.

## 7. What remains reusable

- **Data layer:** Dukascopy `.bi5` parsing, tick/M1 ingestion, bid/ask
  resampling, manifests, data-boundary guards and holdout firewalls.
- **Execution layer:** bid/ask fills, spread and slippage stress, cost realism.
- **Statistics:** walk-forward, WRC/SPA/Romano-Wolf/Holm/BH corrections,
  PBO/CSCV, bootstrap and multiple-testing controls.
- **Models:** Kalman, GMM, cross-sectional ranking, PCA residuals, GRU/TCN and
  cost-aware stopping reference implementations.
- **Operations:** paper broker, JSONL journal, resumable state, health checks,
  alerts and Docker packaging.
- **Tests:** protocol-conformance and golden-execution cases that encode costly
  engineering lessons (spread double-counting, date-mask loss, bid/ask ordering,
  candidate-ID collisions, dimensionality errors).

## 8. Where to go next

The next step is a **decision**, not a new run:

1. **New data class** (e.g. L2/order flow) — new cost, new hypothesis, new
   pre-registration.
2. **New market** (e.g. crypto perpetuals) — new protocol; FX results do not
   transfer.
3. **Archive** — keep the framework as a reusable research asset and stop alpha
   work.
4. **Legacy paper programme** — only if a separate review concludes the old
   evidence is valid; it is currently unvalidated.

See [ROADMAP.md](ROADMAP.md) for the engineering plan and
[research/README.md](research/README.md) for the archive index.

## 9. Related documents

| Document | Purpose |
|---|---|
| [V5R Terminal Postmortem](research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md) | Binding research closure |
| [V5 Engineering Forensics](research/fx_alpha_discovery_v5/V5_ENGINEERING_FORENSICS.md) | Why V5 was invalid |
| [V5 Integrity Adjudication](research/fx_alpha_discovery_v5/V5_INTEGRITY_ADJUDICATION.md) | Adjudication of V5 |
| [V3 Program Review](research/fx_alpha_discovery_v3/V3_PROGRAM_REVIEW.md) | Broad-search closure |
| [Research archive index](research/README.md) | All programmes and decision memos |
| [Architecture](ARCHITECTURE.md) | Reusable framework design |
| [Roadmap](ROADMAP.md) | P1–P3 engineering plan |
