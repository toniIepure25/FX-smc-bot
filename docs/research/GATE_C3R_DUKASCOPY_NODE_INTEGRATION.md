# Gate C.3R — Dukascopy-Node Integration

## Overview

`dukascopy-node` is integrated as a pinned acquisition backend for
downloading public Dukascopy historical FX data. The Node.js tool is
isolated from the Python research runtime and serves only as a data
acquisition mechanism.

## Components

### Node.js Side (`tools/dukascopy-node/`)

| File | Purpose |
|------|---------|
| `package.json` | Pins dukascopy-node 1.46.4 |
| `package-lock.json` | Reproducible dependency tree |
| `acquire.mjs` | Structured acquisition script |
| `test_acquire.mjs` | Node test runner (version pin, import check) |
| `README.md` | Setup and usage documentation |

### Python Side

| File | Purpose |
|------|---------|
| `src/fx_smc_bot/data/dukascopy_node_provider.py` | Python-to-Node bridge |
| `scripts/acquire_dukascopy_node_history.py` | Acquisition CLI |
| `scripts/validate_and_certify.py` | Validation and certification pipeline |

## Security

- No credentials required or used
- No post-install scripts beyond normal npm installation
- npm audit: 0 vulnerabilities
- Package version pinned (not `latest`)

## Structured Output

`acquire.mjs` emits JSON records to stdout:

```json
{"type": "acquisition_start", "instrument": "eurusd", ...}
{"type": "acquisition_complete", "rows": 1440, "outFile": "...", ...}
{"type": "acquisition_error", "error": "...", "stack": "...", ...}
```

The Python bridge parses these records for status monitoring,
error propagation, and manifest building.

## License

dukascopy-node is MIT-licensed. See the package repository for details.
