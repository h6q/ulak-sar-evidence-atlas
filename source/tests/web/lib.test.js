// Node built-in test runner:  node --test tests/web
// Tests for web/lib.js (pure logic). Synthetic objects only.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
// lib.js lives in web/ in the working tree and at the repository root in the published layout.
const libPath = [path.join(__dirname, '..', '..', 'web', 'lib.js'), path.join(__dirname, '..', '..', '..', 'lib.js')].find(p => fs.existsSync(p));
const L = require(libPath);
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'data', 'catalog', 'sudd_086_A_005_cmr_snapshot.json'), 'utf8'));
const byDate = d => catalog.granules.find(g => g.acquisition_date === d);

function v2(extra) {
  return Object.assign({
    schema: 'ulak-change-v2', data_status: 'MEASURED',
    provenance: { before: { granule_ur: 'a', pixel_source: 'https_range_read' }, after: { granule_ur: 'b', pixel_source: 'local_file' } },
    compatibility_checks: [], statistics: {}, hypotheses: [], warnings: [], limitations: [],
    geojson: { type: 'FeatureCollection', features: [] }
  }, extra || {});
}

test('valid v2 measured report is accepted', () => {
  const r = L.validateReport(v2());
  assert.equal(r.ok, true); assert.equal(r.tier, 'MEASURED');
});

test('synthetic report is tiered SYNTHETIC, never MEASURED', () => {
  assert.equal(L.validateReport(v2({ data_status: 'SOFTWARE_TEST_SYNTHETIC' })).tier, 'SYNTHETIC');
});

test('MEASURED without pixel_source is rejected', () => {
  const r = v2(); delete r.provenance.after.pixel_source;
  assert.equal(L.validateReport(r).ok, false);
});

test('blocking failed checks are rejected', () => {
  const r = L.validateReport(v2({ compatibility_checks: [{ id: 'same_crid', blocking: true, status: 'FAIL' }] }));
  assert.equal(r.ok, false); assert.match(r.errors.join(' '), /same_crid/);
});

test('swapped lat/lon coordinates are rejected', () => {
  const gj = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[7.1, 130.7], [7.2, 130.7], [7.2, 130.8], [7.1, 130.7]]] } }] };
  assert.equal(L.validateReport(v2({ geojson: gj })).ok, false);
});

test('oversized, non-object, unknown schema and legacy v1', () => {
  assert.equal(L.validateReport(v2(), 6e6).ok, false);
  assert.equal(L.validateReport([1, 2]).ok, false);
  assert.equal(L.validateReport({ schema: 'x' }).ok, false);
  const v1 = L.validateReport({ schema: 'ulak-change-v1', statistics: { valid_pixels: 5 }, geojson: { type: 'FeatureCollection', features: [] } });
  assert.equal(v1.ok, true); assert.equal(v1.tier, 'USER_DECLARED'); assert.ok(v1.warnings.length);
});

test('non-finite numbers are rejected (e.g. injected Infinity)', () => {
  assert.equal(L.validateReport(v2({ statistics: { x: Infinity } })).ok, false);
});

test('granule parser decodes real catalog names', () => {
  const p = L.parseGranuleName(byDate('2026-07-14').granule_ur);
  assert.equal(p.stack, '086_A_005'); assert.equal(p.crid, 'P05023'); assert.equal(p.fidelity, 'F');
  assert.equal(L.parseGranuleName('<img src=x onerror=alert(1)>'), null);
});

test('catalog checks: primary pair passes, SHSH fails, forecast warns, reversed fails', () => {
  const ok = L.catalogChecks(byDate('2026-06-20'), byDate('2026-10-18'));
  assert.ok(ok.every(c => c.status === 'PASS'));
  const shsh = L.catalogChecks(byDate('2026-06-20'), byDate('2026-09-24'));
  assert.equal(shsh.find(c => c.id === 'same_polarization_channel').status, 'FAIL');
  const fc = L.catalogChecks(byDate('2026-07-14'), byDate('2026-10-18'));
  assert.equal(fc.find(c => c.id === 'orbit_fidelity').status, 'WARN');
  const rev = L.catalogChecks(byDate('2026-10-18'), byDate('2026-06-20'));
  assert.equal(rev.find(c => c.id === 'chronological_order').status, 'FAIL');
});

test('rain sum ignores fill values', () => {
  assert.equal(L.sumBetween(['2026-01-01', '2026-01-02', '2026-01-03'], [1.5, -999, 2], '2026-01-01', '2026-01-03'), 3.5);
});

test('study report is English, states no-measurement honestly, and truncates long strings', () => {
  const md = L.buildStudyReport({ tier: 'CATALOG', generatedUtc: 'now', areaName: 'x'.repeat(1000), before: byDate('2026-06-20'), after: byDate('2026-10-18'), checks: [], limitations: ['a'] });
  assert.match(md, /No measurement loaded\. No quantitative change is claimed\./);
  assert.match(md, /Catalog-verified/);
  assert.ok(!md.includes('x'.repeat(400)));
  assert.match(md, /AI assistance/);
});
