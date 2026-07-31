# F0-RP-E2E-R Response Firewall

`F0RPE2ER_HISTORICAL_RESPONSE_FIREWALL_V1` validates request scope before I/O and rejects an entire response before persistence when any row violates the frozen identity, schema, or 2010-2022 date boundary. Sanitized violation records never retain numerical values. NZD and NZDUSD are rejected.
