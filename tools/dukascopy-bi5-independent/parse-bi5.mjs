import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const lzma = require("lzma-purejs-requirejs");
const RECORD_SIZE = 24;
const PARSER_ID = "DUKASCOPY_BI5_JAVASCRIPT_INDEPENDENT_PARSER_V1";
const SCALES = Object.freeze({
  EURUSD: 100000, GBPUSD: 100000, AUDUSD: 100000, USDJPY: 1000,
  USDCAD: 100000, USDCHF: 100000, EURJPY: 1000, GBPJPY: 1000, AUDJPY: 1000,
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
  for (let offset = 0; offset < decompressed.length; offset += RECORD_SIZE) {
    const volume = decompressed.readFloatBE(offset + 20);
    if (volume === 0) {
      zeroVolumeExcluded += 1;
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
  return { records, zeroVolumeExcluded, decompressedLength: decompressed.length };
}

export function aggregateBi5Payload(payload, pair, isoDate) {
  const parsed = parseBi5Payload(payload, pair, isoDate);
  const timestamps = parsed.records.map((record) => record.timestamp);
  const ohlc = parsed.records.map((record) => [
    record.timestamp, record.open, record.high, record.low, record.close,
  ]);
  const anchor = utcAnchor(isoDate);
  const inRange = timestamps.filter((timestamp) => timestamp < anchor || timestamp >= anchor + 86400000).length;
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

if (import.meta.url === `file://${process.argv[1].replaceAll("\\", "/")}`) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
