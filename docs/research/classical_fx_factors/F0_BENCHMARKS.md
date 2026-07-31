# Gate F.0 Benchmarks

Program `FX_CLASSICAL_RISK_PREMIA_V1` uses exactly five frozen benchmarks. All
use the same certified calendar, execution timing, portfolio risk controls, and
cost/accounting engine as applicable. Prior lineage seals remain closed.

1. **Zero-return cash portfolio.** Daily return is exactly zero; no positions,
   turnover, financing, or execution costs.
2. **Equal-risk long USD basket.** Use the seven USD pairs in the frozen universe
   with direction long USD: short `EURUSD`, `GBPUSD`, `AUDUSD`, `NZDUSD`; long
   `USDJPY`, `USDCAD`, `USDCHF`. Allocate equal ex-ante instrument risk.
3. **Equal-risk passive currency basket.** Hold all ten frozen pairs long base
   and short quote with equal ex-ante instrument risk; rebalance under the frozen
   portfolio rules.
4. **Fixed 12-month TSMOM benchmark.** For each instrument, hold the sign of its
   252-trading-day return available through `t-1`, with equal ex-ante risk.
5. **Matched-turnover random-sign portfolio.** Randomize signs with fixed seed
   `1729` while preserving instrument, rebalance dates, absolute notional,
   holding duration, turnover, and cost exposure.

Benchmark 5 is the primary alpha comparator:

```text
candidate daily net return
- matched-turnover random-sign daily net return
```

No benchmark membership, direction, seed, or construction rule may be changed
after outcomes. These definitions are preregistered and contain no benchmark
result.
