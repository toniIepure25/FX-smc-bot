# Paper Campaign Guide

## Purpose

A paper campaign runs a frozen champion strategy through the paper trading runner on holdout data, then reconciles the results against a matching backtest to detect implementation discrepancies.

## Campaign Flow

1. **Config validation**: Verify the `FrozenCandidate` hash hasn't changed
2. **Data selection**: Extract the holdout (or validation) slice per the candidate's `DataSplitPolicy`
3. **Paper replay**: Run `PaperTradingRunner` bar-by-bar with full journaling
4. **Matching backtest**: Run `BacktestEngine` on the same data slice
5. **Reconciliation**: Compare trade counts, PnL, fill prices using `reconcile_paper_vs_backtest`
6. **Go/No-Go**: If PnL discrepancy exceeds `max_discrepancy_pct` (default 5%), the result is NO-GO

## Configuration

```python
PaperCampaignConfig(
    candidate=frozen_candidate,
    data_slice="holdout",          # or "validation" or "full"
    max_discrepancy_pct=5.0,       # max allowed PnL difference
    daily_summary=True,            # emit daily summary events
)
```

## Output Artifacts

- `journal.jsonl`: Full event journal (signals, orders, fills, state transitions)
- `paper_report.md`: Markdown report with daily reviews and reconciliation
- `campaign.json`: Structured result data

## Discrepancy Sources

Common reasons for paper-vs-backtest differences:

- **Fill timing**: Paper broker processes orders at next bar, backtest may fill intra-bar
- **Slippage model**: Different random seeds or ATR snapshots
- **State persistence**: Paper runner checkpoints and resumes; backtest is stateless
- **Order routing**: Paper broker uses `FillEngine` directly, backtest uses internal logic

## Interpreting Results

| Discrepancy | Action |
|------------|--------|
| < 2% | GO: differences are within noise |
| 2-5% | REVIEW: check fill price distribution and slippage |
| > 5% | NO-GO: investigate implementation divergence |
