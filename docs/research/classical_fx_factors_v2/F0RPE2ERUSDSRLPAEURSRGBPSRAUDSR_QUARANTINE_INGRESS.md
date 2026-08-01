# F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR-AUDSR Quarantine Ingress

Overlay ID: `RBA_F1_QUARANTINE_AWARE_INGRESS_V1`

Status: `FROZEN_BEFORE_CURRENT_F1_ACCESS`

No official dated pre-2023 current-table F1 workbook snapshot was found for the
2011-2022 coverage. The current F1 workbook may therefore be considered only
under this quarantine-aware ingress overlay.

The raw current workbook payload is memory-only and must not be persisted. A
full payload SHA-256 is computed while streaming, with an explicit maximum
payload size of 25,000,000 bytes.

The ingress separates transport-level workbook receipt, structural metadata
decoding, authorized numerical observation decoding, quarantined numerical
observation decoding, persistence, and economic use.

For `.xlsx`, the parser must be low-level and streaming. It may inspect workbook
metadata, sheet identity, header rows, the date column, and authorized Cash Rate
cells for rows dated on or before `2022-12-31`. For rows after `2022-12-31`, the
parser may decode only the date needed to establish row scope and must stop the
row immediately. It must not decode, persist, or use post-2022 numerical cells.
