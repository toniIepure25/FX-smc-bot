# Dukascopy Node Acquisition Tool

Pinned wrapper around [dukascopy-node](https://github.com/Leo4815162342/dukascopy-node)
for research-grade FX data acquisition.

## License

dukascopy-node is MIT-licensed. See the package repository for details.

## Setup

```bash
cd tools/dukascopy-node
npm install
```

## Usage

```bash
node acquire.mjs --instrument eurusd --from 2023-01-02 --to 2023-01-03 \
  --timeframe m1 --priceType bid --format csv --outDir ./output
```

## Version

- dukascopy-node: 1.46.4 (pinned)
- Node.js: >= 18 required
