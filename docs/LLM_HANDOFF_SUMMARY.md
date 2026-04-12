# LLM Handoff Summary

> Quick-reference version of the project context. For full details,
> see `docs/PROJECT_CONTEXT_FOR_LLMS.md`.

---

## What Is This?

An FX algorithmic trading platform using Smart Money Concepts (SMC/ICT).
After 8 experimental waves, the promoted candidate is **BOS-only USDJPY** —
a single-pair, single-family strategy that trades break-of-structure continuation
patterns on USDJPY H1 with H4 directional confirmation.

## Current State

- **Champion**: `bos_only_usdjpy`
- **Decision**: CONTINUE_PAPER_TRADING (confidence: low-medium)
- **Holdout Sharpe**: 0.850 | PF: 1.96 | Win rate: 29% | MaxDD: 12.6%
- **OOS mean Sharpe**: 1.599 across 27 folds (63% positive)
- **Promotion scorecard**: 8/8 criteria passed (revised 25% WR gate)
- **Status**: Ready for 4-6 week paper trading validation

## What Was Demoted and Why

- **sweep_reversal**: Reversed from profitable to loss-making OOS
- **EURUSD**: Holdout Sharpe -0.818, net destructive
- **GBPUSD**: Holdout Sharpe -1.380, net destructive
- **FVG retrace**: Removed in earlier waves, never showed alpha

## Known Risks

1. Single-pair USDJPY concentration (no diversification)
2. Yahoo data quality (~30% missing bars)
3. High OOS variance (std=2.060)
4. Synthetic data showed Sharpe 0.000 (edge may be data-dependent)
5. Low win rate (29%) — justified by PF=1.96 but psychologically challenging

## What Should Happen Next

Run the paper validation program in `paper_validation_program/`:
1. `python scripts/run_paper_validation.py`
2. Follow weekly review schedule (checkpoints at weeks 1, 2, 4, 6)
3. Apply hard-stop invalidation rules if triggered
4. Make PROMOTE/EXTEND/REJECT decision at week 6

## Do Not

- Re-enable sweep_reversal or add EURUSD/GBPUSD without strong new evidence
- Change the frozen config during paper trading
- Skip hard-stop invalidation rules
- Add new alpha families without full validation
- Expand architecture — focus on validating what exists

## Key Files

- Frozen config: `results/final_promotion_gate/bos_only_usdjpy_champion_bundle/champion_config.json`
- Paper program: `paper_validation_program/paper_validation_program.md`
- Full context: `docs/PROJECT_CONTEXT_FOR_LLMS.md`
