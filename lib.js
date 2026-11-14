/* ULAK SAR Evidence Atlas - pure, testable logic (no DOM). AI-assisted code, reviewed by the ULAK team.
 * Works in the browser (window.ULAKLib) and in Node (module.exports) for automated tests. */
(function (root, factory) {
  const lib = factory();
  if (typeof module === 'object' && module.exports) module.exports = lib;
  else root.ULAKLib = lib;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MAX_REPORT_BYTES = 5000000;
  const MAX_FEATURES = 1500;

  /** Evidence tiers shown in the UI. Order = strength of evidence. */
  const TIERS = {
    MEASURED: { label: 'Measured', text: 'Real NISAR GCOV pixels processed by the ULAK pipeline' },
    CATALOG: { label: 'Catalog-verified', text: 'Acquisitions confirmed in NASA CMR; pixels not yet measured here' },
    VISUAL: { label: 'Visual only', text: 'NASA GIBS rendered mosaic - colours are not calibrated measurements' },
    SYNTHETIC: { label: 'Software test', text: 'Synthetic fixture for testing - not an observation' },
    UNAVAILABLE: { label: 'Unavailable', text: 'No data for this request' },
    USER_DECLARED: { label: 'User-declared', text: 'Imported legacy report; provenance declared by the user, not verified' }
  };

  function safeText(v, max) {
    const s = v === null || v === undefined ? '' : String(v);
    const m = max || 300;
    return s.length > m ? s.slice(0, m - 1) + '…' : s;
  }

  function isFiniteNumber(x) { return typeof x === 'number' && Number.isFinite(x); }

  function walkFinite(obj, path, errors, depth) {
    if (depth > 40) { errors.push('Structure too deep at ' + path); return; }
    if (typeof obj === 'number') { if (!Number.isFinite(obj)) errors.push('Non-finite number at ' + path); return; }
    if (Array.isArray(obj)) { obj.forEach((v, i) => walkFinite(v, path + '[' + i + ']', errors, depth + 1)); return; }
    if (obj && typeof obj === 'object') { for (const k of Object.keys(obj)) walkFinite(obj[k], path + '.' + k, errors, depth + 1); }
  }

  function checkGeoJSON(gj, errors) {
    if (!gj || gj.type !== 'FeatureCollection' || !Array.isArray(gj.features)) { errors.push('geojson must be a FeatureCollection'); return; }
    if (gj.features.length > MAX_FEATURES) errors.push('Too many features (' + gj.features.length + ')');
    gj.features.forEach((f, i) => {
      const g = f && f.geometry;
      if (!g || g.type !== 'Polygon' || !Array.isArray(g.coordinates) || !Array.isArray(g.coordinates[0])) { errors.push('Feature ' + i + ' must be a Polygon'); return; }
      for (const pt of g.coordinates[0]) {
        if (!Array.isArray(pt) || pt.length < 2 || !isFiniteNumber(pt[0]) || !isFiniteNumber(pt[1]) ||
            pt[0] < -180 || pt[0] > 180 || pt[1] < -90 || pt[1] > 90) { errors.push('Feature ' + i + ' has coordinates outside [lon, lat] ranges'); return; }
      }
    });
  }

  /** Validate an imported/loaded report. Returns {ok, schema, tier, errors, warnings}. */
  function validateReport(obj, byteLength) {
    const errors = [], warnings = [];
    if (isFiniteNumber(byteLength) && byteLength > MAX_REPORT_BYTES) errors.push('File too large (' + byteLength + ' bytes; limit ' + MAX_REPORT_BYTES + ')');
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return { ok: false, errors: ['Report must be a JSON object'], warnings };
    const schema = obj.schema;
    let tier = 'UNAVAILABLE';
    if (schema === 'ulak-change-v2') {
      for (const k of ['data_status', 'provenance', 'compatibility_checks', 'statistics', 'geojson', 'hypotheses', 'warnings', 'limitations']) {
        if (!(k in obj)) errors.push('Missing field ' + k);
      }
      if (obj.data_status === 'MEASURED') tier = 'MEASURED';
      else if (obj.data_status === 'SOFTWARE_TEST_SYNTHETIC') tier = 'SYNTHETIC';
      else errors.push('Unknown data_status ' + safeText(obj.data_status, 40));
      const p = obj.provenance || {};
      for (const side of ['before', 'after']) {
        if (!p[side] || typeof p[side].granule_ur !== 'string') errors.push('provenance.' + side + '.granule_ur required');
        else if (tier === 'MEASURED' && !['https_range_read', 'local_file'].includes(p[side].pixel_source)) errors.push('MEASURED report lacks pixel_source for ' + side);
      }
      if (Array.isArray(obj.compatibility_checks)) {
        const fails = obj.compatibility_checks.filter(c => c && c.blocking && c.status === 'FAIL');
        if (fails.length) errors.push('Blocking compatibility failures: ' + fails.map(c => safeText(c.id, 40)).join(', '));
      } else errors.push('compatibility_checks must be a list');
    } else if (schema === 'ulak-change-v1') {
      tier = 'USER_DECLARED';
      if (!obj.statistics || !isFiniteNumber(obj.statistics.valid_pixels)) errors.push('statistics.valid_pixels required');
      warnings.push('Legacy v1 report: polarization, dates and maturity are user-declared, not verified.');
    } else {
      errors.push('Not a ULAK change report (schema ' + safeText(schema, 40) + ')');
    }
    walkFinite(obj, 'report', errors, 0);
    if (obj.geojson) checkGeoJSON(obj.geojson, errors);
    return { ok: errors.length === 0, schema, tier, errors, warnings };
  }

  /** NISAR granule name -> tokens (see ASF naming convention). Returns null if not parseable. */
  function parseGranuleName(ur) {
    const m = /^NISAR_L2_PR_GCOV_(\d{3})_(\d{3})_([AD])_(\d{3})_(\d{4})_([A-Z]{4})_A_(\d{8}T\d{6})_(\d{8}T\d{6})_([A-Z]\d{5})_([PMNF])_([FP])_([A-Z])_(\d{3})$/.exec(String(ur || ''));
    if (!m) return null;
    return { cycle: m[1], track: m[2], direction: m[3], frame: m[4], mode: m[5], pol: m[6], start: m[7], end: m[8],
      crid: m[9], fidelity: m[10], coverage: m[11], location: m[12], counter: m[13],
      stack: m[2] + '_' + m[3] + '_' + m[4] };
  }

  const FIDELITY = { P: 'Precise', M: 'Medium', N: 'Near real-time', F: 'Forecast' };

  /** Catalog-level compatibility for a requested pair (mirrors analysis/provenance.py). */
  function catalogChecks(a, b) {
    const out = [];
    const A = parseGranuleName(a && a.granule_ur), B = parseGranuleName(b && b.granule_ur);
    const add = (id, desc, status, detail) => out.push({ id, description: desc, status, detail, evidence: 'catalog' });
    if (!A || !B) { add('parse', 'Granule names parse', 'FAIL', 'Unrecognised granule name'); return out; }
    add('chronological_order', 'Before precedes after', a.begin_utc < b.begin_utc ? 'PASS' : 'FAIL', a.acquisition_date + ' → ' + b.acquisition_date);
    add('same_stack', 'Same track / direction / frame / mode', (A.stack === B.stack && A.mode === B.mode) ? 'PASS' : 'FAIL', A.stack + ' / ' + B.stack);
    add('same_crid', 'Same processing release (CRID)', A.crid === B.crid ? 'PASS' : 'FAIL', A.crid + ' / ' + B.crid);
    const pa = a.frequency_a_polarizations || [], pb = b.frequency_a_polarizations || [];
    const dual = pa.includes('HV') && pb.includes('HV');
    add('same_polarization_channel', 'HH and HV available on both dates', dual ? 'PASS' : 'FAIL', pa.join('+') + ' / ' + pb.join('+'));
    add('orbit_fidelity', 'Orbit ephemeris not Forecast', (A.fidelity !== 'F' && B.fidelity !== 'F') ? 'PASS' : 'WARN', FIDELITY[A.fidelity] + ' / ' + FIDELITY[B.fidelity]);
    return out;
  }

  function days(aIso, bIso) { return Math.round((Date.parse(bIso) - Date.parse(aIso)) / 86400000); }

  function sumBetween(dates, values, a, b) {
    let s = 0;
    for (let i = 0; i < dates.length; i++) if (dates[i] >= a && dates[i] <= b && isFiniteNumber(values[i]) && values[i] >= 0) s += values[i];
    return Math.round(s * 10) / 10;
  }

  function fmt(x, d, unit) {
    if (!isFiniteNumber(x)) return '—';
    const s = (d === undefined ? x : x.toFixed(d));
    return unit ? s + ' ' + unit : String(s);
  }
  function signed(x, d) { return isFiniteNumber(x) ? (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(d === undefined ? 2 : d) : '—'; }

  /** English Markdown study report from the current state. All values are coerced to text. */
  function buildStudyReport(st) {
    const L = [];
    const t = st.tier || 'CATALOG';
    L.push('# ULAK SAR Evidence Atlas - Study Report');
    L.push('');
    L.push('Generated: ' + safeText(st.generatedUtc) + '  ');
    L.push('Evidence tier: **' + TIERS[t].label + '** - ' + TIERS[t].text);
    L.push('');
    L.push('## Study area');
    L.push('- ' + safeText(st.areaName));
    if (st.aoi) L.push('- AOI (W,S,E,N): ' + st.aoi.map(v => fmt(v, 2)).join(', '));
    L.push('');
    L.push('## Observations (NASA-ISRO NISAR L2 GCOV, ASF DAAC)');
    for (const [k, g] of [['Before', st.before], ['After', st.after]]) {
      if (!g) continue;
      L.push('- ' + k + ': `' + safeText(g.granule_ur, 140) + '`');
      L.push('  - Acquired (UTC): ' + safeText(g.begin_utc) + '; CMR: ' + safeText(g.cmr_concept_id));
      L.push('  - Source: ' + safeText(g.h5 ? g.h5.https : g.h5_https, 300));
    }
    L.push('');
    L.push('## Compatibility checks');
    for (const c of (st.checks || [])) L.push('- [' + safeText(c.status, 14) + '] ' + safeText(c.description, 120) + ' - ' + safeText(c.detail, 200) + ' (' + safeText(c.evidence, 30) + ')');
    L.push('');
    L.push('## Measured backscatter change');
    if (st.report && st.report.statistics && st.report.statistics.delta_hh_db) {
      const s = st.report.statistics;
      L.push('- Valid samples: ' + fmt(s.valid_pixels));
      L.push('- Median ΔHH: ' + signed(s.delta_hh_db.median) + ' dB; median ΔHV: ' + signed(s.delta_hv_db.median) + ' dB');
      L.push('- Gates: T_HH ' + fmt(s.thresholds_db.T_HH, 2) + ' dB, T_HV ' + fmt(s.thresholds_db.T_HV, 2) + ' dB, R ' + fmt(s.thresholds_db.R_ratio, 1) + ' dB');
      for (const [k, v] of Object.entries(s.class_counts || {})) L.push('- ' + safeText(k, 40) + ': ' + fmt(v) + ' samples');
    } else {
      L.push('- No measurement loaded. No quantitative change is claimed.');
    }
    if (st.cell) {
      L.push('');
      L.push('## Selected candidate cell ' + safeText(st.cell.cell_id, 20));
      L.push('- Dominant hypothesis: ' + safeText(st.cell.dominant_hypothesis, 40));
      L.push('- Median ΔHH ' + signed(st.cell.median_delta_hh_db) + ' dB; median ΔHV ' + signed(st.cell.median_delta_hv_db) + ' dB');
      L.push('- Status: CANDIDATE radar backscatter change, not confirmed flooding.');
    }
    L.push('');
    L.push('## Context (not validation)');
    if (isFiniteNumber(st.rainMm)) L.push('- NASA POWER corrected precipitation at 30.75E, 7.25N between the two dates: ' + fmt(st.rainMm, 1) + ' mm (reanalysis/satellite-derived, coarse).');
    L.push('- No independent inundation reference (gauge, field survey or validated water map) has been compared.');
    L.push('');
    L.push('## What this cannot tell you');
    for (const s of (st.limitations || [])) L.push('- ' + safeText(s, 300));
    L.push('');
    L.push('---');
    L.push('Data: NASA-ISRO NISAR GCOV via NASA ASF DAAC; NASA CMR; NASA POWER; NASA GIBS. Basemap © OpenStreetMap contributors. ' +
           'No NASA or ISRO endorsement is implied. Software and text prepared with AI assistance and reviewed by the ULAK team.');
    return L.join('\n');
  }

  return { TIERS, MAX_REPORT_BYTES, safeText, validateReport, parseGranuleName, catalogChecks, FIDELITY,
           days, sumBetween, fmt, signed, buildStudyReport };
});
