/**
 * Minimal test: verify dukascopy-node is importable and version is pinned.
 */
import { describe, it } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync } from 'fs';

describe('dukascopy-node tool', () => {
  it('package.json pins exact version', () => {
    const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'));
    assert.equal(pkg.dependencies['dukascopy-node'], '1.46.4');
  });

  it('getHistoricalRates is importable', async () => {
    const mod = await import('dukascopy-node');
    assert.ok(typeof mod.getHistoricalRates === 'function');
  });
});
