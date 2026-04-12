# Paper Stage Checklist

Candidate: bos_only_usdjpy
Frozen at: 2026-04-12T18:47:22.264784

## Pre-Deployment
- [ ] Deploy frozen config to paper environment
- [ ] Verify signal generation matches backtest expectations
- [ ] Confirm risk parameters loaded correctly
- [ ] Set up monitoring dashboard
- [ ] Configure alerts for hard-stop triggers

## Week 1-2: Initial Validation
- [ ] Verify trade frequency (expect 5-12/week)
- [ ] Confirm signal funnel is active
- [ ] Check for system errors
- [ ] Compare paper fills vs expected execution

## Week 3-4: First Assessment
- [ ] Calculate running Sharpe
- [ ] Check if Sharpe > 0 (minimum bar)
- [ ] Review win rate vs 22-38% expected range
- [ ] Drawdown audit (< 15%)
- [ ] Decide: continue / review / suspend

## Week 5-6: Full Review
- [ ] Cumulative Sharpe assessment
- [ ] Discrepancy analysis (paper vs backtest)
- [ ] Final promotion decision: live / extend paper / reject