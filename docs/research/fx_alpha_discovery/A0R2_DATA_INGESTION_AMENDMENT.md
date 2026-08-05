# A0R2 Data Ingestion Amendment

Amendment ID: `A0R2_PRE_OUTCOME_DATA_INGESTION_AND_EXECUTABLE_QUOTE_AMENDMENT_V1`

Status: `FROZEN_BEFORE_EMPIRICAL_OUTCOMES`

Pre-additional-data SHA: `2252fb87d1fcc2248b1f51f2b2a2691af794ea7d`

This outcome-blind amendment governs only market-data availability and executable quote validity. It preserves the frozen signals, family definitions, parameters, costs, selection thresholds, temporal partitions, statistical tests, 1200 trial IDs, and the V2 materialization byte-for-byte.

Market-acquisition metadata was observed. Individual market rows were not inspected for strategy behavior; strategy returns and trial performance were not observed; the amendment was not selected from economic outcomes.

## Frozen Principles

- A partial successful provider response is transport success plus an incomplete partition.
- Missing open-market days require targeted repair.
- A crossed bid/ask M1 state is unavailable for execution and feature anchoring.
- Price modification and synthetic spread correction are prohibited.
- An otherwise usable month need not be rejected solely for isolated crossed states.
- Invalid quote states are prohibited from downstream use.
