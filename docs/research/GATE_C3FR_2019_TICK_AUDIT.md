# Gate C.3F-R — 2019 Tick Audit

## Status: DEFERRED_PENDING_2019_ACQUISITION

The tick audit will be executed after the 2019 M1 dataset is complete.

## Preregistered tolerances

| Metric | Tolerance |
|--------|-----------|
| Timestamps | Exact |
| Expected bars | Exact after common filtering |
| Open/Close | Exact after price quantization |
| High/Low | Exact by default |
| EURUSD/GBPUSD quantization | 5-decimal raw points |
| USDJPY quantization | 3-decimal raw points |

## Protocol

1. Use only frozen 2019 windows from the deterministic audit plan
2. Do not alter windows or tolerances after inspecting results
3. Compare tick-derived M1 bid/ask against downloaded M1 bid/ask
4. A pair-year cannot receive full certification without tick-audit pass
