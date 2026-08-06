import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { aggregateBi5Payload } from "./parse-bi5.mjs";

const require = createRequire(import.meta.url);
const lzma = require("lzma-purejs-requirejs");

function fixture(records) {
  const body = Buffer.alloc(records.length * 24);
  records.forEach((record, index) => {
    const offset = index * 24;
    body.writeInt32BE(record.second, offset);
    body.writeInt32BE(record.open, offset + 4);
    body.writeInt32BE(record.close, offset + 8);
    body.writeInt32BE(record.low, offset + 12);
    body.writeInt32BE(record.high, offset + 16);
    body.writeFloatBE(record.volume, offset + 20);
  });
  return Buffer.from(lzma.compressFile(body));
}

const payload = fixture([
  { second: 0, open: 123450, close: 123460, low: 123440, high: 123470, volume: 1.5 },
  { second: 86399, open: 123460, close: 123450, low: 123440, high: 123470, volume: 2.5 },
  { second: 60, open: 1, close: 1, low: 1, high: 1, volume: 0 },
]);
for (const pair of [
  "EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD",
  "USDCHF", "EURJPY", "GBPJPY", "AUDJPY",
]) {
  const result = aggregateBi5Payload(payload, pair, "2011-03-14");
  assert.equal(result.row_count, 2);
  assert.equal(result.zero_volume_excluded_count, 1);
  assert.equal(result.negative_zero_excluded_count, 0);
  assert.equal(result.out_of_range_count, 0);
  assert.equal(result.timestamps_monotonic, true);
  assert.equal(result.ohlc_invariants_pass, true);
  assert.equal(result.decompression_status, "PASS");
}
assert.throws(() => aggregateBi5Payload(payload, "NZDUSD", "2011-03-14"));
assert.throws(() => aggregateBi5Payload(Buffer.from([1, 2, 3]), "EURUSD", "2011-03-14"));
assert.throws(
  () => aggregateBi5Payload(Buffer.from(lzma.compressFile(Buffer.from([1]))), "EURUSD", "2011-03-14")
);
const outOfDay = aggregateBi5Payload(
  fixture([{ second: 86400, open: 1, close: 1, low: 1, high: 1, volume: 1 }]),
  "EURUSD",
  "2011-03-14"
);
assert.equal(outOfDay.out_of_range_count, 1);
process.stdout.write("independent BI5 parser tests passed\n");
