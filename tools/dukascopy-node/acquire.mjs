/**
 * Structured acquisition script for dukascopy-node.
 *
 * Emits machine-readable JSON status records to stdout.
 * Designed to be called from the Python orchestration layer.
 *
 * Usage (single day):
 *   node acquire.mjs --instrument eurusd --from 2023-01-02 --to 2023-01-03 \
 *     --timeframe m1 --priceType bid --format json --outDir ./output
 *
 * Usage (bulk month — much faster, one process for whole month):
 *   node acquire.mjs --instrument eurusd --from 2019-04-01 --to 2019-05-01 \
 *     --timeframe m1 --priceType bid --format json --outDir ./output \
 *     --batchSize 30 --retries 5 --pauseBetweenBatchesMs 200
 */
import { getHistoricalRates } from 'dukascopy-node';
import { writeFileSync, mkdirSync } from 'fs';
import { basename, join } from 'path';

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const key = argv[i].replace(/^--/, '');
    const val = argv[i + 1];
    if (val && !val.startsWith('--')) {
      args[key] = val;
      i++;
    } else {
      args[key] = 'true';
    }
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);

  const instrument = args.instrument || 'eurusd';
  const dateFrom = args.from || '2023-01-02';
  const dateTo = args.to || '2023-01-03';
  const timeframe = args.timeframe || 'm1';
  const priceType = args.priceType || 'bid';
  const format = args.format || 'json';
  const outDir = args.outDir || './output';
  const cacheDir = args.cacheDir || join(outDir, '.cache');
  const batchSize = parseInt(args.batchSize || '30', 10);
  const retries = parseInt(args.retries || '5', 10);
  const pauseBetweenBatchesMs = parseInt(args.pauseBetweenBatchesMs || '200', 10);
  const useCache = args.cache !== 'false';
  const outFileName = args.outFileName || `${instrument}_${priceType}_${timeframe}_${dateFrom}_${dateTo}.${format === 'csv' ? 'csv' : 'json'}`;
  if (basename(outFileName) !== outFileName || !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(outFileName)) {
    throw new Error('outFileName must be one safe path component');
  }

  const statusRecord = {
    type: 'acquisition_start',
    instrument,
    dateFrom,
    dateTo,
    timeframe,
    priceType,
    format,
    batchSize,
    retries,
    pauseBetweenBatchesMs,
    useCache,
    nodeVersion: process.version,
    packageVersion: '1.46.4',
    timestamp: new Date().toISOString(),
  };
  console.log(JSON.stringify(statusRecord));

  try {
    const data = await getHistoricalRates({
      instrument,
      dates: {
        from: new Date(dateFrom),
        to: new Date(dateTo),
      },
      timeframe,
      priceType,
      format: 'json',
      utcOffset: 0,
      volumes: true,
      flats: false,
      batchSize,
      pauseBetweenBatchesMs,
      retryCount: retries,
      pauseBetweenRetriesMs: 1000,
      useCache,
      cachePath: cacheDir,
    });

    mkdirSync(outDir, { recursive: true });
    const outFile = join(outDir, outFileName);

    if (format === 'csv') {
      if (data.length === 0) {
        writeFileSync(outFile, '');
      } else {
        const headers = Object.keys(data[0]).join(',');
        const rows = data.map(r => Object.values(r).join(','));
        writeFileSync(outFile, [headers, ...rows].join('\n') + '\n');
      }
    } else {
      writeFileSync(outFile, JSON.stringify(data, null, 0));
    }

    const result = {
      type: 'acquisition_complete',
      instrument,
      priceType,
      timeframe,
      dateFrom,
      dateTo,
      rows: data.length,
      outFile,
      firstTimestamp: data.length > 0 ? data[0].timestamp : null,
      lastTimestamp: data.length > 0 ? data[data.length - 1].timestamp : null,
      firstOpen: data.length > 0 ? data[0].open : null,
      firstHigh: data.length > 0 ? data[0].high : null,
      firstLow: data.length > 0 ? data[0].low : null,
      firstClose: data.length > 0 ? data[0].close : null,
      timestamp: new Date().toISOString(),
    };
    console.log(JSON.stringify(result));
    process.exit(0);
  } catch (err) {
    const errRecord = {
      type: 'acquisition_error',
      instrument,
      priceType,
      timeframe,
      dateFrom,
      dateTo,
      error: err.message || String(err),
      stack: err.stack || '',
      code: err.code || '',
      timestamp: new Date().toISOString(),
    };
    console.log(JSON.stringify(errRecord));
    process.exit(1);
  }
}

main();
