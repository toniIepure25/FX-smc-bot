# Gate C.3R — Dukascopy-Node Integration

## Overview

`dukascopy-node` v1.46.4 was integrated as a pinned research acquisition tool
to download public Dukascopy historical FX data without credentials.

## Architecture

```
tools/dukascopy-node/
  package.json          — pins dukascopy-node@1.46.4
  package-lock.json     — committed lock file
  acquire.mjs           — structured JSON output wrapper
  test_acquire.mjs      — Node.js test (importability, version pin)
  README.md             — usage documentation
```

## Key Design Decisions

1. **Pinned version**: Exact `1.46.4` in `package.json`, lock committed
2. **Isolated from Python**: Node tool is acquisition-only, not strategy engine
3. **Structured output**: `acquire.mjs` emits JSON records for machine parsing
4. **Daily download granularity**: Full-month downloads fail due to network
   timeouts; daily downloads with retry are reliable
5. **Cache**: dukascopy-node's built-in cache avoids re-downloading

## Python Bridge

`src/fx_smc_bot/data/dukascopy_node_provider.py` orchestrates:
- Argument validation
- Daily subprocess invocation
- JSON status capture
- Monthly aggregation
- Bid/ask alignment by exact UTC timestamp
- Parquet conversion with atomic writes
- Resumability (completed partitions skipped)

## Node/npm Versions

- Node.js: v20.9.0
- npm: 10.1.0
- dukascopy-node: 1.46.4

## npm Audit

```
found 0 vulnerabilities
```

## License

dukascopy-node is MIT-licensed (Leo4815162342/dukascopy-node).
