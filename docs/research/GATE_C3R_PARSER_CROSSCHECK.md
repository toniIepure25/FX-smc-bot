# Gate C.3R — Parser Cross-Check

## Methodology

Compare `dukascopy-node` M1 output against expectations for:
- EURUSD (non-JPY pair, 5-decimal pricing)
- USDJPY (JPY pair, 3-decimal pricing)

## Results

### EURUSD (2023-06)
- **Source**: dukascopy-node M1 bid download
- **Scaling**: Prices in standard 5-decimal format (e.g., 1.08427)
- **No universal /100000 divisor applied**: Confirmed
- **Price range**: Plausible (approximately 1.06-1.10 for June 2023)
- **Ask ≥ Bid**: Confirmed for all joined bars
- **Timestamp format**: Millisecond Unix epoch, UTC

### USDJPY (2023-06)
- **Source**: dukascopy-node M1 bid download
- **Scaling**: Prices in standard 3-decimal format (e.g., 139.725)
- **JPY scaling correct**: Confirmed (values ~130-145 range, not ~0.001)
- **No universal /100000 divisor applied**: Confirmed
- **Ask ≥ Bid**: Confirmed for all joined bars
- **Timestamp format**: Millisecond Unix epoch, UTC

### Cross-Check Notes
- `dukascopy-node` returns prices pre-scaled to standard format
- No manual price scaling is needed (unlike raw BI5 binary format)
- The native Python BI5 provider applies `raw_price / 100000.0` for
  non-JPY and `raw_price / 1000.0` for JPY; dukascopy-node handles
  this internally
- Both paths should produce identical prices for the same underlying
  Dukascopy data

## Comparison Status

| Check | EURUSD | USDJPY |
|-------|--------|--------|
| Correct scaling | PASS | PASS |
| Plausible prices | PASS | PASS |
| No ask < bid | PASS | PASS |
| UTC timestamps | PASS | PASS |
| No timezone shift | PASS | PASS |

## Full Native BI5 Comparison

Deferred until both the native Python BI5 provider and dukascopy-node
produce overlapping M1 data for a deterministic sample. The BI5 provider
requires direct binary parsing which was `BLOCKED_BY_DATA_ACCESS` in
Gate C.3.
