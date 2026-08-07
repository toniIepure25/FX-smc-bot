import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const lzma = require("lzma-purejs-requirejs");
const RECORD_SIZE = 24;
const PARSER_ID = "DUKASCOPY_BI5_JAVASCRIPT_INDEPENDENT_PARSER_V1";
const SCALES = Object.freeze({
  EURUSD: [100000, 5], GBPUSD: [100000, 5], AUDUSD: [100000, 5], USDJPY: [1000, 3],
  USDCAD: [100000, 5], USDCHF: [100000, 5], EURJPY: [1000, 3], GBPJPY: [1000, 3], AUDJPY: [1000, 3],
});

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const utcAnchor = (isoDate) => Date.parse(`${isoDate}T00:00:00.000Z`);

export function parseBi5Payload(payload, pair, isoDate) {
  if (!Object.hasOwn(SCALES, pair)) throw new Error("A0R2_UNAUTHORIZED_NATIVE_BI5_INSTRUMENT");
  const raw = Buffer.from(payload);
  const decompressed = Buffer.from(lzma.decompressFile(raw));
  if (decompressed.length % RECORD_SIZE !== 0) {
    throw new Error("A0R2_BI5_INVALID_RECORD_LENGTH");
  }
  const anchor = utcAnchor(isoDate);
  const records = [];
  let zeroVolumeExcluded = 0;
  let negativeZeroExcluded = 0;
  let nonFiniteVolume = 0;
  for (let offset = 0; offset < decompressed.length; offset += RECORD_SIZE) {
    const volume = decompressed.readFloatBE(offset + 20);
    if (!Number.isFinite(volume)) {
      nonFiniteVolume += 1;
      throw new Error("A0R2_BI5_NON_FINITE_VOLUME");
    }
    if (volume === 0) {
      zeroVolumeExcluded += 1;
      negativeZeroExcluded += Number(Object.is(volume, -0));
      continue;
    }
    records.push({
      timestamp: anchor + decompressed.readInt32BE(offset) * 1000,
      open: decompressed.readInt32BE(offset + 4),
      close: decompressed.readInt32BE(offset + 8),
      low: decompressed.readInt32BE(offset + 12),
      high: decompressed.readInt32BE(offset + 16),
      volumeBits: Buffer.from(decompressed.subarray(offset + 20, offset + 24)),
    });
  }
  return { records, zeroVolumeExcluded, negativeZeroExcluded, nonFiniteVolume, decompressedLength: decompressed.length };
}

export function aggregateBi5Payload(payload, pair, isoDate) {
  const parsed = parseBi5Payload(payload, pair, isoDate);
  const timestamps = parsed.records.map((record) => record.timestamp);
  const ohlc = parsed.records.map((record) => [
    record.timestamp, record.open, record.high, record.low, record.close,
  ]);
  const anchor = utcAnchor(isoDate);
  const inRange = timestamps.filter((timestamp) => timestamp < anchor || timestamp >= anchor + 86400000).length;
  const ohlcInvariantsPass = parsed.records.every((record) => record.high >= Math.max(record.open, record.close) && record.low <= Math.min(record.open, record.close));
  return {
    parser_id: PARSER_ID,
    raw_sha256: sha256(Buffer.from(payload)),
    row_count: parsed.records.length,
    ordered_timestamp_sha256: sha256(JSON.stringify(timestamps)),
    integer_ohlc_sha256: sha256(JSON.stringify(ohlc)),
    volume_bits_sha256: sha256(Buffer.concat(parsed.records.map((record) => record.volumeBits))),
    first_timestamp: timestamps.at(0) ?? null,
    last_timestamp: timestamps.at(-1) ?? null,
    duplicate_count: timestamps.length - new Set(timestamps).size,
    out_of_range_count: inRange,
    zero_volume_excluded_count: parsed.zeroVolumeExcluded,
    negative_zero_excluded_count: parsed.negativeZeroExcluded,
    non_finite_volume_count: parsed.nonFiniteVolume,
    integer_scale: SCALES[pair][0],
    decimal_precision: SCALES[pair][1],
    timestamps_monotonic: timestamps.every((value, index) => index === 0 || timestamps[index - 1] <= value),
    ohlc_invariants_pass: ohlcInvariantsPass,
    decompression_status: "PASS",
    record_length_status: "PASS",
  };
}

async function main() {
  const [input, pair, isoDate] = process.argv.slice(2);
  if (!input || !pair || !isoDate) throw new Error("usage: parse-bi5.mjs INPUT PAIR YYYY-MM-DD");
  const result = aggregateBi5Payload(await readFile(input), pair, isoDate);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
