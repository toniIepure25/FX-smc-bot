# V4 Pilot Metadata Cost Preflight

**Artifact:** `results/gate_v4/v4_pilot_metadata_cost_preflight.json`
**Program:** `FX_INTRADAY_ALPHA_DISCOVERY_V4`
**Gate:** `V4_PILOT_METADATA_COST_PREFLIGHT`
**Starting SHA:** `95777577d3f56a397c8fe3fab74a7c3747ce2dee`
**Capability Contract Hash:** `9de92fc724cb936854a496892db85ca04bd6769082b4944b19ce918931f36091`
**Pilot Design Hash:** `28b1b4cf9f6db38828029c37c3daf09f9dd9f3feb769d8f949303e662a48b9b5`
**Manifest Hash:** `a405f35aeab4c273a255af1b19a337ba09d15c8fd3d3978cd757efbf82cbc2aa`

---

## Status: BLOCKED BY API CREDENTIAL

No `DATABENTO_API_KEY` in environment. All local/sample work is complete.
Exact metadata commands emitted. **No estimates fabricated.**

## P1 Sample Manifest

| Metric | Value |
|---|---|
| Total instrument-days | 180 |
| Development | 108 |
| Internal Validation | 72 |
| 6E | 60 |
| 6J | 60 |
| 6B | 60 |

## Symbol Resolution

Resolved via CME quarterly calendar + 5-trading-day roll rule.
Contracts used: 6E/6J/6B quarterly (H/M/U/Z) for 2016-2017.

## MBP-10 Coverage

PENDING_METADATA_VERIFICATION. GLBX.MDP3 coverage from 2010-06.
All selected dates (2016-2017) within coverage per provider docs.

## Record Count / Billable Size / Cost

**PENDING_METADATA.** Requires API key. Commands in preflight script.

## Budget Scenarios

| Scenario | Instrument-Days | Note |
|---|---|---|
| FULL_P1 | 180 | Frozen scientific sample |
| SCENARIO_50 | 90 | Budget only, NOT scientific |
| SCENARIO_25 | 45 | Budget only, NOT scientific |

## Storage Plan

Pending metadata. Mac M5 16GB viable for day-partitioned streaming.

## License

Store locally: Yes. Cache: Yes. Transform: Yes. Private research: Yes.
Commit publicly: **NO**. Do NOT commit vendor market data to Git.

## Firewall

All 11 counters: **0**

## Preflight Script

`scripts/v4/pilot_metadata_preflight.py`

```
set DATABENTO_API_KEY=...
python scripts/v4/pilot_metadata_preflight.py \
  --manifest results/gate_v4/v4_p1_sample_manifest.json \
  --metadata-only --output results/gate_v4/preflight_results.json
```

## Terminal Verdict

`V4_PILOT_METADATA_PREFLIGHT_BLOCKED_BY_API_CREDENTIAL`

**Next gate (when ready):** `V4_PILOT_ACQUISITION_AUTHORIZATION`
