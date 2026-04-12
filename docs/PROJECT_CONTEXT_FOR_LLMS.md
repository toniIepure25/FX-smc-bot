# Project Context for LLM Conversations

> **Purpose**: This document provides a complete context summary of the FX-smc-bot
> project so that any new LLM conversation can immediately understand the project
> history, current state, and what should happen next. Paste this document at the
> start of new conversations.
>
> **Last updated**: 2026-04-12

---

## 1. Project Overview

**FX-smc-bot** is a professional FX (foreign exchange) algorithmic trading platform
built around Smart Money Concepts (SMC) and Inner Circle Trader (ICT) methodology.
The system detects institutional-grade price action patterns (liquidity sweeps,
breaks of structure, fair value gaps, order blocks) and converts them into
systematic trading signals with full risk management.

**Repository**: `/home/tonystark/Desktop/fx-smc-bot/FX-smc-bot/`

---

## 2. Repository Architecture

### Core Modules (`src/fx_smc_bot/`)

| Module | Purpose |
|--------|---------|
| `structure/` | Market structure detection: swings, BOS, CHoCH, FVG, liquidity sweeps, order blocks |
| `alpha/` | Signal generation: candidate creation, filtering, scoring, approval pipeline |
| `backtesting/` | Backtest engine, metrics computation, attribution analysis |
| `risk/` | Position sizing, drawdown tracking, portfolio constraints, exposure management |
| `execution/` | Order management, fill simulation, slippage modeling, stress testing |
| `portfolio/` | Candidate selection, risk allocation, correlation management |
| `live/` | Paper trading runner, broker adapter, journal, health monitoring, alerts |
| `research/` | Walk-forward, gating, evaluation, campaigns, paper review, reconciliation |
| `ml/` | Regime classification, meta-labeling, microstructure features |
| `data/` | Data loading, normalization, diagnostics, providers (Yahoo, Dukascopy, CSV, Parquet) |
| `config.py` | Central configuration: AppConfig, AlphaConfig, RiskConfig, ExecutionConfig |

### Key Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `run_paper_validation.py` | **Current**: Disciplined paper trading campaign runner |
| `run_final_promotion_gate.py` | Final promotion gate evaluation (6 themes) |
| `run_simplification_decision.py` | USDJPY simplification wave |
| `run_rootcause_investigation.py` | Holdout failure root-cause analysis |
| `run_holdout_stability_investigation.py` | Holdout stability investigation |
| `run_risk_compression_campaign.py` | Risk compression wave |
| `run_real_data_campaign.py` | Real data validation campaign |
| `run_paper.py` | Basic paper trading CLI |

### Results Directory (`results/`)

| Directory | Content |
|-----------|---------|
| `final_promotion_gate/` | **Latest**: Final BOS-only USDJPY promotion evaluation |
| `simplification_wave/` | USDJPY concentration and simplification analysis |
| `rootcause_wave/` | Holdout failure root-cause investigation |
| `holdout_stability_wave/` | Holdout stability analysis |
| `risk_compression_wave/` | Risk compression campaign results |
| `real_data_campaign/` | Real data validation results |
| `validation_wave1/`, `validation_wave2/` | Earlier synthetic validation waves |

### Paper Validation Program (`paper_validation_program/`)

Complete 6-week paper-trading validation program with governance docs,
review templates, invalidation rules, and metrics specifications.

---

## 3. Strategy Evolution Timeline

### Wave 1-2: Synthetic Validation (Early)
- Built full SMC/ICT framework with multiple alpha families
- Tested on Dukascopy-quality synthetic data
- Identified initial promising candidates: sweep_plus_bos, bos_continuation

### Wave 3: Real Data Validation
- Switched from synthetic to Yahoo Finance real data (EURUSD, GBPUSD, USDJPY)
- Discovered a **sweep detection wiring bug** that inflated synthetic results
- After bug fix, real-data validation showed genuine alpha in BOS continuation

### Wave 4: Risk Compression
- Original drawdowns were ~35% — unacceptable for deployment
- Applied hardened risk profile: 0.30% risk/trade, 12.5% circuit breaker
- Reduced drawdown to ~13% while preserving Sharpe and PF

### Wave 5: Holdout Stability Investigation
- Walk-forward and holdout analysis revealed serious concerns:
  - **Win rate collapsed** from training to holdout
  - **sweep_reversal reversed** from profitable to loss-making OOS
  - **USDJPY concentration was extreme** — 100% of training PnL from USDJPY
  - **EURUSD and GBPUSD were net destructive** in holdout
- Recommendation: CONTINUE_WITH_SIMPLIFICATION

### Wave 6: USDJPY Simplification
- Validated the USDJPY concentration hypothesis across 7 pair universes
- **BOS-only USDJPY holdout Sharpe: 0.850** (vs 0.154 all-pairs)
- **WF mean OOS Sharpe: 1.442** across 10 folds (60% positive)
- EURUSD holdout: -0.818, GBPUSD holdout: -1.380 — both harmful
- Multi-pair diversification **hurts** OOS consistency
- sweep_reversal **permanently demoted**

### Wave 7: Final Promotion Gate
- Comprehensive evaluation of BOS-only USDJPY across:
  - 27 OOS folds (anchored-5, anchored-8, rolling, rolling-small)
  - 5 spread multipliers (1.0x to 3.0x)
  - 4 execution stress scenarios
  - 2 data sources (Yahoo, Dukascopy synthetic)
- **Promotion scorecard: 8/8** (under revised 25% win-rate threshold)
- Win rate (29%) justified for trend-following signal with PF=1.96
- Decision: **CONTINUE_PAPER_TRADING** (confidence: low-medium)

### Wave 8: Paper Validation Program (Current)
- Built disciplined 6-week paper trading program
- 5 formal checkpoints with explicit pass/warn/fail criteria
- Hard-stop invalidation rules and escalation protocol
- Weekly review templates and metrics specification
- Full governance documentation

---

## 4. Current Champion

| Property | Value |
|----------|-------|
| **Label** | bos_only_usdjpy |
| **Family** | bos_continuation |
| **Pair** | USDJPY only |
| **Timeframe** | H1 (with H4 higher-timeframe confirmation) |
| **Risk per trade** | 0.30% |
| **Max portfolio risk** | 0.90% |
| **Circuit breaker** | 12.5% |
| **Spread assumption** | 1.0 pip (default) |
| **Slippage assumption** | 0.5 pip |
| **Fill policy** | Conservative |

### Performance Evidence

| Metric | Holdout | OOS (27 folds) |
|--------|---------|----------------|
| Sharpe | 0.850 | Mean 1.599 |
| Profit Factor | 1.96 | — |
| Win Rate | 29.1% | — |
| Max Drawdown | 12.6% | — |
| Total Trades | 220 | — |
| % Positive Folds | — | 63% |
| Stress (all 4 pass) | Yes | — |
| Spread robustness | Positive through 3.0x | — |

### Why This Champion

1. **USDJPY is the only pair with real alpha** — EURUSD and GBPUSD are net destructive
2. **BOS continuation is the only surviving family** — sweep_reversal reversed OOS
3. **Simplification improved performance** — fewer pairs = higher Sharpe, lower variance
4. **Passes all revised promotion gates** — 8/8 criteria met
5. **Robust under execution stress** — positive under all 4 scenarios, through 3x spreads

---

## 5. Current Risks and Caveats

| Risk | Severity | Mitigation |
|------|----------|------------|
| Single-pair concentration (USDJPY only) | High | Paper trading validates; not a blocker for paper stage |
| Yahoo data quality (~30% missing bars) | Medium | Synthetic cross-check done; paper will use live data |
| High OOS variance (std=2.060) | Medium | 63% positive folds; weekly monitoring in paper |
| Low win rate (29%) | Low | Justified by PF=1.96; structural for trend-following |
| Synthetic holdout Sharpe = 0.000 | Medium | Yahoo edge may not fully persist on cleaner data |
| Regime sensitivity | Medium | Hard-stop triggers in paper program |
| No institutional-grade data confirmation | Medium | Paper trading itself tests real data |

---

## 6. What Should Happen Next

### Immediate: Paper Trading (4-6 weeks)
1. Deploy frozen `bos_only_usdjpy` config to paper trading
2. Follow the `paper_validation_program/` governance docs
3. Execute weekly reviews at each checkpoint
4. Apply hard-stop rules if triggers are hit
5. At week 6: make PROMOTE / EXTEND / REJECT decision

### After Paper (if promoted):
1. Prepare live deployment package with real capital sizing
2. Start with minimal allocation
3. Continue weekly monitoring
4. Scale up only after 4+ weeks of live confirmation

### After Paper (if rejected):
1. Document the failure mode
2. Investigate what backtest evidence was misleading
3. Consider if the BOS signal needs fundamental improvement
4. Do NOT casually retry without addressing the root cause

---

## 7. Guardrails for Future Changes

### DO NOT casually:
- Re-enable sweep_reversal (it was permanently demoted with strong evidence)
- Re-add EURUSD or GBPUSD (both net destructive in holdout)
- Add new alpha families without full train/holdout/walk-forward validation
- Change the risk profile without re-running the promotion gate
- Lower the circuit breaker threshold below 10%
- Skip the paper trading stage

### DO:
- Treat the paper stage as a controlled experiment
- Use the frozen config — do not drift
- Document all observations in the weekly review templates
- Apply hard-stop rules without discretion
- Validate any new ideas through the same rigorous process (train/holdout/WF/stress)

### If you want to improve the strategy:
- Start a new research branch, do not modify the promoted candidate
- Run full validation: train, holdout, walk-forward, execution stress
- Compare against the current champion using the same methodology
- Only promote if the new candidate is clearly superior

---

## 8. Key File Locations

| Purpose | Path |
|---------|------|
| Frozen champion config | `results/final_promotion_gate/bos_only_usdjpy_champion_bundle/champion_config.json` |
| Final promotion verdict | `results/final_promotion_gate/final_promotion_verdict.json` |
| Paper validation program | `paper_validation_program/paper_validation_program.md` |
| Program manifest | `paper_validation_program/paper_program_manifest.json` |
| Paper runner script | `scripts/run_paper_validation.py` |
| Invalidation rules | `paper_validation_program/paper_stage_invalidation_rules.md` |
| Weekly review template | `paper_validation_program/weekly_review_template.md` |
| Checkpoint schedule | `paper_validation_program/paper_stage_checkpoints.md` |
| Decision matrix | `paper_validation_program/checkpoint_decision_matrix.md` |
| LLM handoff summary | `docs/LLM_HANDOFF_SUMMARY.md` |

---

## 9. Glossary

| Term | Meaning |
|------|---------|
| BOS | Break of Structure — a swing high/low violation indicating trend continuation |
| SMC | Smart Money Concepts — institutional order flow methodology |
| ICT | Inner Circle Trader — source methodology for SMC patterns |
| FVG | Fair Value Gap — imbalance zone in price action |
| OOS | Out of Sample — data not used in training/optimization |
| WF | Walk-Forward — temporal cross-validation methodology |
| PF | Profit Factor — gross profits / gross losses |
| CB | Circuit Breaker — automatic halt when drawdown exceeds threshold |
| HTF | Higher Timeframe — H4 used for directional bias confirmation |
| Holdout | Final 20% of data reserved for unbiased evaluation |
