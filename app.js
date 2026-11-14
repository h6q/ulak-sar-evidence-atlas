/* ULAK SAR Evidence Atlas v0.3 - "Beneath the Canopy" (Sudd). AI-assisted code, reviewed by the ULAK team.
 * Uses NASA GIBS rendered mosaics ONLY as a visual layer. Quantitative values come exclusively from a
 * validated ULAK report produced from real NISAR GCOV pixels by analysis/run_sudd.py. */
'use strict';
(function () {
const U = window.ULAKLib;
const $ = id => document.getElementById(id);
const GIBS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi';
const GIBS_LAYER = 'NISAR_L2_Geocoded_Polarimetric_Covariance';
const DEFAULT_AOI = [30.55, 7.00, 30.95, 7.40]; // W,S,E,N - must match analysis/run_sudd.py DEFAULT_AOI
const COLORS = { hh: '#3987e5', hv: '#d95926', rain: '#199e70',
  hyp: { hh_up_double_bounce: '#3987e5', both_down_specular: '#d95926', hv_up_volume: '#199e70', other_change: '#c98500' } };
const HYP_LABEL = { hh_up_double_bounce: 'HH up more than HV (double-bounce hypothesis)', both_down_specular: 'HH and HV down (specular / open-water hypothesis)',
  hv_up_volume: 'HV up more than HH (volume / growth hypothesis)', other_change: 'Other large change' };
const LINK_HOSTS = ['nasa.gov', 'alaska.edu'];

const S = { catalog: null, power: null, report: null, ts: null, tier: 'CATALOG', reportTier: null, before: null, after: null,
  map: null, base: null, layers: { a: null, b: null }, cells: null, frame: null, aoi: null, aoiBox: DEFAULT_AOI,
  visible: true, layerMode: 'gibs', cell: null, temporalCell: null, gibsTimer: null, playTimer: null };

// ---------- DOM helpers (textContent only; never innerHTML with data) ----------
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
const svgNS = 'http://www.w3.org/2000/svg';
function sv(tag, attrs) { const e = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v)); return e; }
function svText(attrs, text) { const t = sv('text', attrs); t.textContent = text; return t; }
function safeHref(url) {
  try { const u = new URL(url); if (u.protocol !== 'https:') return null;
    return LINK_HOSTS.some(h => u.hostname === h || u.hostname.endsWith('.' + h)) ? u.href : null; } catch (_) { return null; }
}
function link(text, url) { const h = safeHref(url); return h ? el('a', { href: h, target: '_blank', rel: 'noopener' }, text) : el('span', {}, text); }
function setStatus(id, s, cls) { const n = $(id); n.textContent = s; n.className = 'status' + (cls ? ' ' + cls : ''); }

function setTier(tier, extra) {
  S.tier = tier;
  $('tierBanner').className = 'tier tier-' + tier;
  $('tierLabel').textContent = U.TIERS[tier].label;
  $('tierText').textContent = U.TIERS[tier].text + (extra ? ' - ' + extra : '');
}

async function getJSON(url, optional) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) { if (optional && r.status === 404) return null; throw new Error(url + ': HTTP ' + r.status); }
  const text = await r.text();
  if (text.length > U.MAX_REPORT_BYTES) throw new Error(url + ' too large');
  return { data: JSON.parse(text), bytes: text.length };
}

// ---------- map ----------
function initMap() {
  S.map = L.map('map', { zoomControl: false, keyboard: true }).setView([7.2, 30.75], 10);
  L.control.zoom({ position: 'bottomright' }).addTo(S.map);
  L.control.scale({ position: 'bottomleft', imperial: false }).addTo(S.map);
  S.base = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap contributors' }).addTo(S.map);
  S.base.on('tileerror', () => { S.baseErrors = (S.baseErrors || 0) + 1; });
  S.map.createPane('paneA'); S.map.getPane('paneA').style.zIndex = 430; S.map.getPane('paneA').style.pointerEvents = 'none';
  S.map.createPane('paneB'); S.map.getPane('paneB').style.zIndex = 420; S.map.getPane('paneB').style.pointerEvents = 'none';
  S.map.on('move zoom resize viewreset zoomend moveend', refreshClip);
  S.map.on('moveend', () => { const c = S.map.getCenter(); $('coords').textContent = c.lat.toFixed(4) + '° · ' + c.lng.toFixed(4) + '°'; });
  S.map.on('click', ev => selectTemporalCell(ev.latlng.lat, ev.latlng.lng));
}

function refreshClip() {
  if (!S.map) return;
  const pct = Number($('swipe').value);
  $('swipeValue').textContent = pct + '%';
  $('swipe').setAttribute('aria-valuetext', pct + ' percent of the map shows observation A');
  const single = S.layerMode === 'delta' || S.layerMode === 'hyp' || S.layerMode.startsWith('ts_');
  $('divider').style.display = single ? 'none' : 'block';
  $('divider').style.left = pct + '%';
  const pane = S.map.getPane('paneA');
  if (single) { pane.style.clip = ''; return; }
  const size = S.map.getSize();
  const nw = S.map.containerPointToLayerPoint([0, 0]);
  const se = S.map.containerPointToLayerPoint(size);
  const x = nw.x + size.x * pct / 100;
  // Leaflet panes are absolutely positioned 0x0 boxes, so we clip with a pixel rect in layer coordinates.
  pane.style.clip = 'rect(' + nw.y + 'px, ' + x + 'px, ' + se.y + 'px, ' + nw.x + 'px)';
}

function clearRadar() {
  for (const k of ['a', 'b']) if (S.layers[k]) { S.map.removeLayer(S.layers[k]); S.layers[k] = null; }
  clearTimeout(S.gibsTimer);
}

function gibsLayer(date, pane) {
  return L.tileLayer.wms(GIBS, { layers: GIBS_LAYER, format: 'image/png', transparent: true, version: '1.1.1', time: date,
    tileSize: 256, pane, attribution: 'NASA GIBS · NASA–ISRO NISAR · ASF DAAC', crossOrigin: true });
}

function overlayLayer(name, pane) {
  const ov = S.report && S.report.overlays && S.report.overlays[name];
  if (!ov || typeof ov.file !== 'string' || !/^[A-Za-z0-9_.-]+\.png$/.test(ov.file)) return null;
  return L.imageOverlay('data/' + ov.file, ov.bounds_latlon, { pane, opacity: 0.95, interactive: false,
    attribution: 'Derived from NASA–ISRO NISAR GCOV (ULAK pipeline)' });
}

function temporalOverlay(file, pane) {
  const bounds = S.ts && S.ts.overlays && S.ts.overlays.frame_bounds_latlon;
  if (!bounds || typeof file !== 'string' || !/^ts\/[A-Za-z0-9_.-]+\.png$/.test(file)) return null;
  return L.imageOverlay('data/' + file, bounds, { pane, opacity: 0.95, interactive: false,
    attribution: 'Measured NASA–ISRO NISAR GCOV · ULAK temporal pipeline' });
}

function loadTemporalLayer() {
  if (!S.ts) { setStatus('mapStatus', 'The measured temporal result is unavailable.', 'warn'); return; }
  const date = $('tsDate').value || S.ts.compatibility.dates[0];
  const frame = S.ts.overlays.frames.find(f => f.date === date);
  let file = null, label = '';
  if (S.layerMode === 'ts_hh') { file = frame && frame.hh; label = date + ' · HH γ⁰'; }
  if (S.layerMode === 'ts_hv') { file = frame && frame.hv; label = date + ' · HV γ⁰'; }
  const staticLayers = {
    ts_delta_hh: ['delta_hh_first_last', 'First→last ΔHH'], ts_delta_hv: ['delta_hv_first_last', 'First→last ΔHV'],
    ts_trend_hh: ['trend_hh', 'HH temporal trend'], ts_persistence_hh: ['persistence_hh', 'HH persistence']
  };
  if (staticLayers[S.layerMode]) {
    const [key, lab] = staticLayers[S.layerMode], layer = S.ts.overlays.layers[key];
    file = layer && layer.file; label = lab;
  }
  if (!file) {
    setStatus('mapStatus', S.layerMode === 'ts_hv' ? date + ' has no measured HV channel; no value is interpolated.' : 'Temporal overlay is unavailable.', 'warn');
    $('badgeA').textContent = label || 'No measured layer'; $('badgeB').textContent = 'MEASURED · QC-screened';
    return;
  }
  S.layers.a = temporalOverlay(file, 'paneA');
  if (S.layers.a) S.layers.a.addTo(S.map);
  $('badgeA').textContent = label; $('badgeB').textContent = 'MEASURED · QC-screened';
  setStatus('mapStatus', label + '. Display overlay only; statistics use the native 100 m grid. 6 Oct is excluded by QC.');
}

function loadRadar() {
  const a = S.before, b = S.after;
  if (!a || !b) return;
  clearRadar();
  $('badgeA').textContent = 'A · ' + a.acquisition_date;
  $('badgeB').textContent = 'B · ' + b.acquisition_date;
  if (S.layerMode.startsWith('ts_')) {
    loadTemporalLayer();
  } else if (S.layerMode === 'gibs') {
    const st = { loaded: 0, errors: 0, pending: 2 };
    S.layers.b = gibsLayer(b.acquisition_date, 'paneB');
    S.layers.a = gibsLayer(a.acquisition_date, 'paneA');
    for (const lay of [S.layers.a, S.layers.b]) {
      lay.on('tileload', () => { st.loaded++; });
      lay.on('tileerror', () => { st.errors++; });
      lay.on('load', () => {
        st.pending--;
        if (st.pending > 0) return;
        clearTimeout(S.gibsTimer);
        if (st.errors && !st.loaded) {
          // Defer: Leaflet fires 'load' inside _tileReady and keeps using the layer's map afterwards,
          // so removing the layer synchronously here would null its map mid-call.
          if (hasMeasuredOverlays()) { setTimeout(() => fallbackToMeasured('NASA GIBS tiles failed (' + st.errors + ' errors).'), 0); return; }
          setStatus('mapStatus', 'NASA GIBS tiles failed (' + st.errors + ' errors). Check the connection or try NASA Worldview.', 'bad');
        }
        else setStatus('mapStatus', 'NASA GIBS daily mosaics for ' + a.acquisition_date + ' (A) and ' + b.acquisition_date + ' (B): ' + st.loaded + ' tiles' +
          (st.errors ? ', ' + st.errors + ' failed' : '') + '. Visual only; transparent areas mean no mosaic data.');
      });
    }
    S.layers.b.addTo(S.map); S.layers.a.addTo(S.map);
    setStatus('mapStatus', 'Requesting NASA GIBS mosaics for ' + a.acquisition_date + ' and ' + b.acquisition_date + '…');
    S.gibsTimer = setTimeout(() => {
      if (st.pending <= 0) return;
      if (st.loaded === 0 && hasMeasuredOverlays()) { fallbackToMeasured('NASA GIBS did not answer within 20 s.'); return; }
      setStatus('mapStatus', 'NASA GIBS has not answered after 20 s (' + st.loaded + ' tiles so far). Tiles may be slow or blocked; the catalog and measured layers still work.', 'warn');
    }, 20000);
  } else {
    const r = S.report;
    if (!r || !r.overlays) setStatus('mapStatus', 'No measured overlay yet. Run scripts\\ulak_run_sudd.ps1 to produce one from real NISAR pixels.', 'warn');
    else {
      const pa = (r.provenance.before.acquisition_begin_utc || '').slice(0, 10), pb = (r.provenance.after.acquisition_begin_utc || '').slice(0, 10);
      if (S.layerMode === 'hh') { S.layers.b = overlayLayer('after_hh', 'paneB'); S.layers.a = overlayLayer('before_hh', 'paneA');
        $('badgeA').textContent = 'A · ' + pa + ' HH'; $('badgeB').textContent = 'B · ' + pb + ' HH'; }
      if (S.layerMode === 'delta') { S.layers.a = overlayLayer('delta_hh', 'paneA'); $('badgeA').textContent = 'ΔHH = B − A'; $('badgeB').textContent = pa + ' → ' + pb; }
      if (S.layerMode === 'hyp') { S.layers.a = overlayLayer('hypotheses', 'paneA'); $('badgeA').textContent = 'Hypotheses'; $('badgeB').textContent = pa + ' → ' + pb; }
      for (const lay of [S.layers.b, S.layers.a]) if (lay) { lay.on('error', () => setStatus('mapStatus', 'Measured overlay image could not be loaded.', 'bad')); lay.addTo(S.map); }
      const synth = S.reportTier === 'SYNTHETIC';
      let msg = 'Measured layer ' + pa + ' → ' + pb + '. Reprojected for display only; statistics use the native grid.';
      if (synth) msg += ' SOFTWARE TEST FIXTURE - not an observation.';
      if (S.before.acquisition_date !== pa || S.after.acquisition_date !== pb) msg += ' Note: this differs from the dates selected above.';
      setStatus('mapStatus', msg, synth ? 'warn' : '');
    }
  }
  if (!S.visible) for (const k of ['a', 'b']) if (S.layers[k]) S.map.removeLayer(S.layers[k]);
  refreshClip();
  renderLegend();
}

function hasMeasuredOverlays() {
  return !!(S.report && S.report.schema === 'ulak-change-v2' && S.report.overlays && S.report.overlays.before_hh);
}
function setLayerMode(mode) {
  S.layerMode = mode;
  const r = document.querySelector('input[name=layer][value=' + mode + ']'); if (r) r.checked = true;
}
function fallbackToMeasured(reason) {
  setLayerMode('hh'); loadRadar();
  setStatus('mapStatus', reason + ' Switched automatically to the locally derived, measured NISAR HH layers (real GCOV pixels).', 'warn');
}

function drawFootprints() {
  const g = S.catalog.granules[0];
  if (S.frame) S.map.removeLayer(S.frame);
  S.frame = L.polygon(g.footprint_lonlat.map(([lo, la]) => [la, lo]), { color: '#9caec4', weight: 1, dashArray: '4 4', fill: false, interactive: false }).addTo(S.map);
  const aoi = (S.report && S.report.study_area && S.report.study_area.aoi_bbox_wsen) || DEFAULT_AOI;
  if (S.aoi) S.map.removeLayer(S.aoi);
  S.aoi = L.rectangle([[aoi[1], aoi[0]], [aoi[3], aoi[2]]], { color: '#59dbc6', weight: 2, fill: false, interactive: false }).addTo(S.map);
  S.aoiBox = aoi;
}

function drawCells() {
  if (S.cells) { S.map.removeLayer(S.cells); S.cells = null; }
  const r = S.report;
  if (!r || !r.geojson || !$('showCells').checked) return;
  S.cells = L.geoJSON(r.geojson, {
    style: f => { const c = COLORS.hyp[f.properties && f.properties.dominant_hypothesis] || '#f6c16e';
      return { color: c, weight: 1.5, fillColor: c, fillOpacity: 0.18 }; },
    onEachFeature: (f, layer) => {
      layer.on('click', () => selectCell(f.properties || {}));
      layer.bindTooltip(U.safeText(HYP_LABEL[f.properties && f.properties.dominant_hypothesis] || 'Candidate change', 80), { sticky: true });
    }
  }).addTo(S.map);
}

function selectCell(p) {
  S.cell = p || null;
  renderPassport();
  if (p) $('passportPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderLegend() {
  const box = $('legend'); box.replaceChildren();
  if (S.layerMode === 'gibs') { box.append(el('span', { class: 'pill VISUAL' }, 'visual'), ' NASA GIBS false-colour NISAR GCOV mosaic. Colours are not calibrated dB values; see the NASA Worldview legend.'); return; }
  if (S.layerMode === 'hh') { box.append(el('span', { class: 'ramp gray', 'aria-hidden': 'true' }), ' HH γ⁰: −25 dB (dark) to 0 dB (bright)'); return; }
  if (S.layerMode === 'delta') { box.append(el('span', { class: 'ramp div', 'aria-hidden': 'true' }), ' ΔHH: −6 dB (blue, decrease) · 0 (gray) · +6 dB (red, increase)'); return; }
  if (S.layerMode === 'ts_hh') { box.append(el('span', { class: 'ramp gray', 'aria-hidden': 'true' }), ' Measured HH γ⁰: −22 to −2 dB; transparent = no valid data.'); return; }
  if (S.layerMode === 'ts_hv') { box.append(el('span', { class: 'ramp gray', 'aria-hidden': 'true' }), ' Measured HV γ⁰: −30 to −12 dB; 24 Sep is missing, not interpolated.'); return; }
  if (S.layerMode.startsWith('ts_delta') || S.layerMode === 'ts_trend_hh') { box.append(el('span', { class: 'ramp div', 'aria-hidden': 'true' }), ' Blue = decrease · gray = near zero · red = increase.'); return; }
  if (S.layerMode === 'ts_persistence_hh') { box.append('Persistence classes at the 3 dB gate; robust raw+normalised area is below 0.11%.'); return; }
  for (const [k, c] of Object.entries(COLORS.hyp)) { const sw = el('span', { class: 'swatch', 'aria-hidden': 'true' }); sw.style.background = c; box.append(el('span', { class: 'leg' }, sw, HYP_LABEL[k])); }
}

// ---------- passport ----------
function row(label, value, tier, sub) {
  const v = el('div', { class: 'pass-value' }, value);
  if (sub) v.append(el('small', { class: 'sub' }, sub));
  return el('div', { class: 'passport' }, el('span', { class: 'pass-label' }, label, tier ? el('span', { class: 'pill ' + tier }, U.TIERS[tier].label.toLowerCase()) : null), v);
}
function badge(status) { return el('span', { class: 'badge ' + status }, status === 'NOT_AVAILABLE' ? 'N/A' : status); }
function reportMatchesSelection() {
  const r = S.report;
  if (!r || r.schema !== 'ulak-change-v2' || !S.before || !S.after) return false;
  return String(r.provenance.before.acquisition_begin_utc).slice(0, 10) === S.before.acquisition_date &&
         String(r.provenance.after.acquisition_begin_utc).slice(0, 10) === S.after.acquisition_date;
}
function currentChecks() { return reportMatchesSelection() ? S.report.compatibility_checks : U.catalogChecks(S.before, S.after); }
function localSolar(utc, lon) {
  const t = Date.parse(utc); if (!Number.isFinite(t)) return '';
  const d = new Date(t + lon / 15 * 3600000);
  return String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0');
}

function renderPassport() {
  const box = $('passport'); box.replaceChildren();
  const a = S.before, b = S.after, r = S.report;
  const measured = reportMatchesSelection();
  const rp = measured ? r.provenance : null;
  const ga = measured ? { granule_ur: rp.before.granule_ur, begin_utc: rp.before.acquisition_begin_utc, cmr: rp.before.cmr_record } : { granule_ur: a.granule_ur, begin_utc: a.begin_utc, cmr: a.cmr_record };
  const gb = measured ? { granule_ur: rp.after.granule_ur, begin_utc: rp.after.acquisition_begin_utc, cmr: rp.after.cmr_record } : { granule_ur: b.granule_ur, begin_utc: b.begin_utc, cmr: b.cmr_record };
  if (!measured && r && r.schema === 'ulak-change-v2') box.append(el('p', { class: 'status warn' }, 'The loaded measurement covers a different pair; this passport shows catalog facts only for the pair selected above.'));
  $('passportScope').textContent = S.cell ? 'Scope: candidate cell ' + U.safeText(S.cell.cell_id, 20) + '. Use "Back to whole-pair passport" to return.' :
    'Scope: the ' + (measured ? 'measured' : 'selected') + ' pair of observations. Click a candidate cell on the map to see its own passport.';
  const tierObs = measured ? (S.reportTier === 'SYNTHETIC' ? 'SYNTHETIC' : 'MEASURED') : 'CATALOG';

  box.append(el('h3', {}, '1 · Original satellite source'));
  box.append(row('Mission / product', 'NASA–ISRO NISAR, L-SAR, Level-2 GCOV', 'CATALOG', U.safeText(S.catalog.collection.title, 120) + ' (' + U.safeText(S.catalog.collection.cmr_concept_id, 30) + ')'));
  box.append(row('Observation A', link(U.safeText(ga.granule_ur, 120), ga.cmr), 'CATALOG'));
  box.append(row('Observation B', link(U.safeText(gb.granule_ur, 120), gb.cmr), 'CATALOG'));
  box.append(el('h3', {}, '2 · Acquisition dates'));
  const lon = (S.aoiBox[0] + S.aoiBox[2]) / 2;
  box.append(row('Acquired (UTC)', U.safeText(ga.begin_utc, 40) + ' → ' + U.safeText(gb.begin_utc, 40), 'CATALOG',
    U.days(ga.begin_utc, gb.begin_utc) + ' days apart · about ' + localSolar(ga.begin_utc, lon) + ' local solar time (pre-dawn) · ascending pass, left-looking'));
  box.append(el('h3', {}, '3 · Measurement and polarization'));
  box.append(row('Quantity', 'γ⁰ backscatter, terrain-corrected, linear power → dB (10·log₁₀)', 'CATALOG', 'Frequency A, 20 MHz, documented 20 m posting; HH = HHHH, HV = HVHV'));
  if (measured) box.append(row('Processing', 'Multilook ' + r.processing.multilook_factor + '×' + r.processing.multilook_factor + ' → ' + U.fmt(r.processing.analysis_spacing_m) + ' m; ' + U.safeText(r.processing.crs, 20), tierObs, U.safeText(r.processing.resampling_for_statistics, 80)));
  box.append(el('h3', {}, '4 · Observed backscatter change'));
  if (measured && S.cell) {
    box.append(row('Cell ΔHH / ΔHV', U.signed(S.cell.median_delta_hh_db) + ' dB / ' + U.signed(S.cell.median_delta_hv_db) + ' dB', tierObs,
      'Changed fraction ' + U.fmt(S.cell.changed_fraction * 100, 0) + '% of ' + U.fmt(S.cell.valid_samples) + ' samples'));
  } else if (measured) {
    const s = r.statistics;
    box.append(row('Median ΔHH / ΔHV', U.signed(s.delta_hh_db.median) + ' dB / ' + U.signed(s.delta_hv_db.median) + ' dB', tierObs,
      'Robust spread σ ≈ ' + U.fmt(s.delta_hh_db.robust_sigma, 2) + ' / ' + U.fmt(s.delta_hv_db.robust_sigma, 2) + ' dB over ' + U.fmt(s.valid_pixels) + ' samples'));
    const ss = r.diagnostics && r.diagnostics.scene_shift;
    if (ss) box.append(row('Scene-wide shift', U.fmt(ss.fraction_dhh_positive * 100, 0) + '% of pixels brighter in HH', tierObs,
      'Tile medians ' + U.signed(ss.tile_median_dhh_range_db[0]) + ' to ' + U.signed(ss.tile_median_dhh_range_db[1]) + ' dB: spatially variable, so not a pure calibration offset; a uniform component cannot be excluded with two dates.'));
  } else {
    box.append(row('Measured change', 'Not measured yet; no number is shown on purpose', 'UNAVAILABLE', 'Run scripts\\ulak_run_sudd.ps1 (Earthdata Login) to measure this pair from real pixels.'));
  }
  box.append(el('h3', {}, '5 · Data quality and compatibility checks'));
  const ul = el('ul', { class: 'checks' });
  for (const c of currentChecks()) ul.append(el('li', {}, badge(c.status), ' ', U.safeText(c.description, 110), el('small', { class: 'sub' }, U.safeText(c.detail, 220) + ' · evidence: ' + U.safeText(c.evidence, 30))));
  box.append(ul);
  box.append(el('h3', {}, '6 · Interpretation and uncertainty'));
  const h = (measured && S.cell) ? r.hypotheses.find(x => x.id === S.cell.dominant_hypothesis) : null;
  if (h) {
    box.append(row('Dominant hypothesis', HYP_LABEL[h.id] || U.safeText(h.label, 80), tierObs, 'Rule: ' + U.safeText(h.rule, 120)));
    box.append(row('Consistent with', U.safeText(h.consistent_with, 200), null, 'Screening rule only: not a probability, not a confirmed event.'));
  } else if (measured) {
    const t = r.statistics.thresholds_db;
    box.append(row('Screening gates', 'T_HH ' + U.fmt(t.T_HH, 2) + ' dB · T_HV ' + U.fmt(t.T_HV, 2) + ' dB · R ' + U.fmt(t.R_ratio, 1) + ' dB', tierObs, 'max(floor, 3 × robust σ); heuristic, not calibrated'));
    const sens = r.diagnostics && r.diagnostics.threshold_sensitivity;
    if (sens) {
      const a = sens.as_reported.counts, c = sens.median_centred.counts;
      box.append(row('Robustness', 'HV-dominant increase: ' + U.fmt(a.hv_up_volume) + ' → ' + U.fmt(c.hv_up_volume) + ' (robust)', tierObs,
        'HH-dominant increase: ' + U.fmt(a.hh_up_double_bounce) + ' → ' + U.fmt(c.hh_up_double_bounce) + ' if the median shift is treated as non-change (NOT robust).'));
    }
  } else {
    box.append(row('Interpretation', 'None yet. Physical hypotheses are attached only to measured changes.', null, 'At L-band, HH often rises when water lies beneath emergent vegetation (double bounce), but this response is not unique.'));
  }
  box.append(el('h3', {}, '7 · Independent validation available'));
  const rain = S.power ? U.sumBetween(S.power.dates, S.power.PRECTOTCORR, ga.begin_utc.slice(0, 10), gb.begin_utc.slice(0, 10)) : null;
  box.append(row('Rainfall between dates', rain === null ? '—' : U.fmt(rain, 0) + ' mm (NASA POWER, point estimate)', 'CATALOG', 'Context only: Sudd flooding is dominated by White Nile inflow, not local rain.'));
  box.append(row('Inundation reference', 'None compared in this project', 'UNAVAILABLE', 'A gauge record, field survey or validated water map is required before calling any cell "flooded".'));
  box.append(el('h3', {}, '8 · Reasons this result might mislead'));
  const reasons = el('ul', { class: 'reasons' });
  const alts = h ? h.alternatives : ['Soil moisture or rain on the canopy can raise backscatter without flooding',
    'Wind roughening changes open-water backscatter', 'PROVISIONAL products (CRID P05023) may be reprocessed in 2027',
    'Speckle, residual geolocation and equatorial ionospheric effects', 'A GIBS colour difference is never a dB measurement'];
  for (const s of alts) reasons.append(el('li', {}, U.safeText(s, 200)));
  box.append(reasons);
  if (S.cell) { const back = el('button', { class: 'outline', type: 'button' }, 'Back to whole-pair passport'); back.addEventListener('click', () => selectCell(null)); box.append(back); }
  if (measured && r.geojson && r.geojson.features.length) {
    box.append(el('h3', {}, 'Top candidate cells (keyboard access)'));
    const list = el('div', { class: 'celllist' });
    for (const f of r.geojson.features.slice(0, 8)) {
      const p = f.properties || {}; const btn = el('button', { class: 'outline small', type: 'button' }, U.safeText(p.cell_id, 20) + ' · ' + U.signed(p.median_delta_hh_db, 1) + ' dB HH');
      btn.addEventListener('click', () => { selectCell(p); const c = f.geometry.coordinates[0]; S.map.fitBounds(c.map(([lo, la]) => [la, lo]), { maxZoom: 13 }); });
      list.append(btn);
    }
    box.append(list);
  }
}

// ---------- quantitative panel ----------
function renderStats() {
  const r = S.report;
  if (r && r.schema === 'ulak-change-v2') {
    $('valid').textContent = U.fmt(r.statistics.valid_pixels);
    $('dhh').textContent = U.signed(r.statistics.delta_hh_db.median) + ' dB';
    $('dhv').textContent = U.signed(r.statistics.delta_hv_db.median) + ' dB';
  } else if (r) {
    $('valid').textContent = U.fmt(r.statistics.valid_pixels); $('dhh').textContent = U.signed(r.statistics.median_delta_db) + ' dB'; $('dhv').textContent = '—';
  } else for (const id of ['valid', 'dhh', 'dhv']) $(id).textContent = '—';
  renderHistogram();
  renderRobustness();
}
function tipShow(evt, text) { const t = $('tip'); t.textContent = text; t.hidden = false; t.style.left = (evt.clientX + 12) + 'px'; t.style.top = (evt.clientY + 12) + 'px'; }
function tipHide() { $('tip').hidden = true; }

function renderHistogram() {
  const box = $('hist'); box.replaceChildren();
  const r = S.report;
  if (!r || r.schema !== 'ulak-change-v2' || !r.histograms) { box.append(el('p', { class: 'muted' }, 'No measurement loaded, so no distribution is drawn.')); return; }
  const wrap = el('div', { class: 'multiples' });
  for (const [key, label, color, tkey] of [['delta_hh', 'ΔHH', COLORS.hh, 'T_HH'], ['delta_hv', 'ΔHV', COLORS.hv, 'T_HV']]) {
    const h = r.histograms[key]; if (!h) continue;
    const W = 300, H = 130, m = { l: 10, r: 10, t: 18, b: 24 };
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label + ' histogram of ' + h.n + ' samples' });
    const max = Math.max(1, ...h.counts), e = h.bin_edges_db, x0 = e[0], x1 = e[e.length - 1];
    const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r), Y = v => H - m.b - v / max * (H - m.t - m.b);
    svg.append(sv('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'axis' }));
    for (const t of [-15, -10, -5, 0, 5, 10, 15]) { svg.append(sv('line', { x1: X(t), x2: X(t), y1: H - m.b, y2: H - m.b + 3, class: 'axis' })); svg.append(svText({ x: X(t), y: H - 8, class: 'tick', 'text-anchor': 'middle' }, t)); }
    const T = r.statistics.thresholds_db[tkey];
    for (const s of [-1, 1]) svg.append(sv('line', { x1: X(s * T), x2: X(s * T), y1: m.t, y2: H - m.b, class: 'thresh' }));
    h.counts.forEach((c, i) => {
      const bx = X(e[i]) + 1, bw = Math.max(1, X(e[i + 1]) - X(e[i]) - 2), by = Y(c);
      svg.append(sv('rect', { x: bx, y: by, width: bw, height: Math.max(0, H - m.b - by), rx: 1.5, fill: color }));
      const hit = sv('rect', { x: X(e[i]), y: m.t, width: X(e[i + 1]) - X(e[i]), height: H - m.t - m.b, fill: 'transparent' });
      hit.addEventListener('mousemove', ev => tipShow(ev, label + ' ' + e[i] + ' to ' + e[i + 1] + ' dB: ' + c.toLocaleString('en') + ' samples'));
      hit.addEventListener('mouseleave', tipHide); svg.append(hit);
    });
    svg.append(svText({ x: m.l, y: 12, class: 'lbl' }, label + ' · dashed lines = ±' + U.fmt(T, 1) + ' dB gate'));
    wrap.append(el('div', { class: 'mult' }, svg));
  }
  box.append(wrap);
}

function renderRobustness() {
  const box = $('robust'); box.replaceChildren();
  const r = S.report, sens = r && r.diagnostics && r.diagnostics.threshold_sensitivity;
  if (!sens) return;
  const cols = [['as_reported', 'As reported'], ['median_centred', 'Shift removed'], ['floor_only_3db', '3 dB gates']];
  const rowsDef = [['hh_up_double_bounce', 'HH up > HV'], ['both_down_specular', 'HH & HV down'],
                   ['hv_up_volume', 'HV up > HH'], ['other_change', 'Other change']];
  const t = el('table', { class: 'robust' }, el('caption', {}, 'Candidate 100 m pixels under three gate choices. "Shift removed" assumes the scene-wide median change is not real. Sensitivity, not accuracy.'));
  t.append(el('thead', {}, el('tr', {}, el('th', { scope: 'col' }, 'Class'), ...cols.map(c => el('th', { scope: 'col' }, c[1])))));
  const tb = el('tbody');
  for (const [k, lab] of rowsDef) tb.append(el('tr', {}, el('th', { scope: 'row' }, lab), ...cols.map(c => el('td', {}, U.fmt(sens[c[0]].counts[k])))));
  tb.append(el('tr', { class: 'total' }, el('th', { scope: 'row' }, 'All candidates'), ...cols.map(c => el('td', {}, U.fmt(sens[c[0]].candidates), el('br'), el('small', {}, U.fmt(sens[c[0]].candidate_fraction * 100, 1) + '%')))));
  t.append(tb); box.append(t);
}

// ---------- time series + rain ----------
const T0 = Date.parse('2026-06-01T00:00:00Z'), T1 = Date.parse('2026-11-01T00:00:00Z');
function monthTicks(svg, X, y) {
  for (const mo of ['2026-06-01', '2026-07-01', '2026-08-01', '2026-09-01', '2026-10-01', '2026-11-01']) {
    const t = Date.parse(mo + 'T00:00:00Z'); svg.append(sv('line', { x1: X(t), x2: X(t), y1: y, y2: y + 4, class: 'axis' }));
    svg.append(svText({ x: X(t) + 2, y: y + 16, class: 'tick' }, new Date(t).toLocaleString('en', { month: 'short', timeZone: 'UTC' })));
  }
}
function legendItem(c, t) { const sw = el('span', { class: 'swatch line', 'aria-hidden': 'true' }); sw.style.background = c; return el('span', { class: 'leg' }, sw, t); }

function temporalRows(region) {
  if (!S.ts) return null;
  const dates = S.ts.compatibility.dates;
  if (region === 'aoi') return dates.map((date, i) => ({ date,
    hh_median_db: S.ts.time_series.aoi_pixel_median_hh_db[i], hv_median_db: S.ts.time_series.aoi_pixel_median_hv_db[i],
    ratio_median_db: Number.isFinite(S.ts.time_series.aoi_pixel_median_hv_db[i]) ? S.ts.time_series.aoi_pixel_median_hv_db[i] - S.ts.time_series.aoi_pixel_median_hh_db[i] : null }));
  return dates.map((date, i) => ({ date,
    hh_median_db: S.ts.time_series.hh_db[region][i] && S.ts.time_series.hh_db[region][i].median,
    hv_median_db: S.ts.time_series.hv_db[region][i] && S.ts.time_series.hv_db[region][i].median,
    ratio_median_db: S.ts.time_series.hv_minus_hh_db[region][i] && S.ts.time_series.hv_minus_hh_db[region][i].median }));
}

function renderSeries() {
  const box = $('series'); box.replaceChildren();
  const W = 900, H = 200, m = { l: 44, r: 96, t: 12, b: 26 };
  const X = t => m.l + (t - T0) / (T1 - T0) * (W - m.l - m.r);
  const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Median HH and HV backscatter per NISAR acquisition' });
  const region = $('tsRegion') ? $('tsRegion').value : 'aoi';
  const ts = temporalRows(region) || ((S.report && Array.isArray(S.report.time_series)) ? S.report.time_series : []);
  const pts = { hh: [], hv: [], ratio: [] };
  for (const e of ts) { const t = Date.parse(e.date + 'T03:34:00Z'); if (Number.isFinite(e.hh_median_db)) pts.hh.push([t, e.hh_median_db, e]); if (Number.isFinite(e.hv_median_db)) pts.hv.push([t, e.hv_median_db, e]); if (Number.isFinite(e.ratio_median_db)) pts.ratio.push([t, e.ratio_median_db, e]); }
  const all = pts.hh.concat(pts.hv, pts.ratio).map(p => p[1]);
  const lo = all.length ? Math.floor(Math.min(...all) - 1) : -25, hi = all.length ? Math.ceil(Math.max(...all) + 1) : -5;
  const Y = v => H - m.b - (v - lo) / (hi - lo) * (H - m.t - m.b);
  const step = Math.max(1, Math.round((hi - lo) / 4));
  for (let v = lo; v <= hi; v += step) { svg.append(sv('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: 'grid' })); svg.append(svText({ x: m.l - 6, y: Y(v) + 3, class: 'tick', 'text-anchor': 'end' }, v)); }
  monthTicks(svg, X, H - m.b);
  for (const g of S.catalog.granules) { const t = Date.parse(g.begin_utc); svg.append(sv('line', { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: g.frequency_a_polarizations.includes('HV') ? 'acq' : 'acq hh' })); }
  const pairOnly = S.report && S.report.schema === 'ulak-change-v2' && !ts.length;
  if (!all.length) svg.append(svText({ x: (W - m.r + m.l) / 2, y: H / 2, class: 'lbl', 'text-anchor': 'middle' },
    pairOnly ? 'Pair-only run: the 10-date series has not been computed yet (run ulak_run_sudd.ps1 without -PairOnly).'
             : 'Acquisition dates shown. Measured medians appear after the pipeline runs on real pixels.'));
  for (const [k, name, color] of [['hh', 'HH', COLORS.hh], ['hv', 'HV', COLORS.hv], ['ratio', 'HV−HH', '#aa78e8']]) {
    const p = pts[k]; if (!p.length) continue;
    svg.append(sv('polyline', { points: p.map(q => X(q[0]) + ',' + Y(q[1])).join(' '), fill: 'none', stroke: color, 'stroke-width': 2 }));
    for (const q of p) { const c = sv('circle', { cx: X(q[0]), cy: Y(q[1]), r: 4.5, fill: color, stroke: '#121c2c', 'stroke-width': 2 });
      c.addEventListener('mousemove', ev => tipShow(ev, name + ' ' + q[2].date + ': ' + q[1].toFixed(2) + ' dB (' + region.replace('_', ' ') + ')')); c.addEventListener('mouseleave', tipHide); svg.append(c); }
    const last = p[p.length - 1]; svg.append(svText({ x: X(last[0]) + 8, y: Y(last[1]) + 4, class: 'lbl' }, name + ' ' + last[1].toFixed(1) + ' dB'));
  }
  box.append(svg);
  if (all.length) box.append(el('div', { class: 'legend inline' }, legendItem(COLORS.hh, 'HH'), legendItem(COLORS.hv, 'HV'), legendItem('#aa78e8', 'HV−HH'), ' · QC-screened; 24 Sep has HH only'));
  renderTable(ts);
  renderTemporalFinding();
}

function selectTemporalCell(lat, lon) {
  if (!S.ts || !S.ts.cells || lon < 30.55 || lon >= 30.95 || lat <= 7.0 || lat > 7.4) return;
  const c = Math.floor((lon - 30.55) / 0.01), r = Math.floor((7.4 - lat) / 0.01);
  if (r < 0 || r >= 40 || c < 0 || c >= 40) return;
  S.temporalCell = { r, c, lat: 7.4 - (r + 0.5) * 0.01, lon: 30.55 + (c + 0.5) * 0.01 };
  if (S.temporalMarker) S.map.removeLayer(S.temporalMarker);
  S.temporalMarker = L.circleMarker([S.temporalCell.lat, S.temporalCell.lon], { radius: 6, color: '#f6c16e', weight: 2, fillOpacity: 0.2 }).addTo(S.map);
  renderTemporalCell();
}

function renderTemporalCell() {
  const chart = $('cellSeries'), pass = $('temporalPassport'); chart.replaceChildren(); pass.replaceChildren();
  if (!S.temporalCell || !S.ts) { pass.append(el('p', { class: 'muted' }, 'No cell selected.')); return; }
  const { r, c, lat, lon } = S.temporalCell, dates = S.ts.compatibility.dates;
  const hh = S.ts.cells.hh_db.map(a => a && a[r][c]), hv = S.ts.cells.hv_db.map(a => a && a[r][c]);
  const rows = dates.map((date, i) => ({ date, hh_median_db: hh[i], hv_median_db: hv[i] }));
  const table = el('table', {}, el('thead', {}, el('tr', {}, ...['Date', 'HH dB', 'HV dB'].map(x => el('th', { scope: 'col' }, x)))));
  const tb = el('tbody'); rows.forEach(x => tb.append(el('tr', {}, el('td', {}, x.date), el('td', {}, U.fmt(x.hh_median_db, 2)), el('td', {}, U.fmt(x.hv_median_db, 2))))); table.append(tb); chart.append(table);
  const code = S.ts.cells.labels[r][c], names = { C: 'wetland corridor', W: 'western floodplain', E: 'eastern floodplain', '.': 'unassigned transition' };
  const firstLast = a => { const v = a.filter(Number.isFinite); return v.length > 1 ? v[v.length - 1] - v[0] : null; };
  const interpretation = S.ts.cells.interpretation[r][c].replaceAll('_', ' ');
  pass.append(row('Cell centre', lat.toFixed(3) + '° N, ' + lon.toFixed(3) + '° E', 'MEASURED', '0.01° analysis cell; row ' + r + ', column ' + c),
    row('MODIS-defined region', names[code], 'VISUAL', 'MCD12Q1 2023/2024 rendered classes; contextual stratification, not truth'),
    row('Observed first→last', 'HH ' + U.signed(firstLast(hh), 2) + ' dB · HV ' + U.signed(firstLast(hv), 2) + ' dB', 'MEASURED', 'Missing HV is preserved as missing; linear-power means precede dB conversion'),
    row('Rule-based label', interpretation, 'MEASURED', 'A consistency label, not a causal classification'),
    row('HH vs DSWx water ρ', U.fmt(S.ts.cells.rho_hh_vs_water[r][c], 2), 'MEASURED', 'Eight one-day-offset Sentinel-1 comparisons; DSWx-S1 is independent radar context, not ground truth'),
    row('Stable land cover', S.ts.cells.modis_stable_wet_pct[r][c] + '% wet · ' + S.ts.cells.modis_stable_savanna_pct[r][c] + '% savanna', 'VISUAL', 'Approximate WMS-resampled fractions'));
}

function renderTemporalFinding() {
  const box = $('temporalFinding'); if (!box) return; box.replaceChildren();
  if (!S.ts) { box.append('Measured temporal analysis unavailable.'); return; }
  const g = S.ts.decision_gate, p = S.ts.persistence;
  box.append(el('b', {}, 'Observation-level decision: ' + g.outcome + '. '),
    'Structured east-margin versus corridor changes survive the spatial block bootstrap. At the strict 3 dB persistence gate, robust raw+normalised change covers ',
    (100 * p.hh_T3.robust_both_fraction).toFixed(2) + '% (HH) and ' + (100 * p.hv_T3.robust_both_fraction).toFixed(2) + '% (HV). ',
    'DSWx-S1 supplies independent C-band context, but the first→last NISAR/DSWx change correlation is near zero and no ground validation exists. Physical attribution remains ambiguous.');
}

function renderRain() {
  const box = $('rain'); box.replaceChildren();
  if (!S.power) { box.append(el('p', { class: 'muted' }, 'NASA POWER context file not available.')); return; }
  const W = 900, H = 130, m = { l: 44, r: 96, t: 8, b: 26 };
  const X = t => m.l + (t - T0) / (T1 - T0) * (W - m.l - m.r);
  const vals = S.power.PRECTOTCORR, max = Math.max(5, ...vals.filter(v => v >= 0));
  const Y = v => H - m.b - v / max * (H - m.t - m.b);
  const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Daily precipitation from NASA POWER, June to October 2026' });
  for (const v of [0, Math.round(max / 2), Math.round(max)]) { svg.append(sv('line', { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: 'grid' })); svg.append(svText({ x: m.l - 6, y: Y(v) + 3, class: 'tick', 'text-anchor': 'end' }, v)); }
  const bw = (W - m.l - m.r) / ((T1 - T0) / 86400000) - 1;
  S.power.dates.forEach((d, i) => { const v = vals[i]; if (!(v >= 0)) return; const t = Date.parse(d + 'T00:00:00Z');
    const rr = sv('rect', { x: X(t), y: Y(v), width: Math.max(1, bw), height: H - m.b - Y(v), fill: COLORS.rain, rx: 1 });
    rr.addEventListener('mousemove', ev => tipShow(ev, d + ': ' + v + ' mm/day (NASA POWER PRECTOTCORR)')); rr.addEventListener('mouseleave', tipHide); svg.append(rr); });
  for (const g of S.catalog.granules) { const t = Date.parse(g.begin_utc); svg.append(sv('line', { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'acq' })); }
  monthTicks(svg, X, H - m.b);
  box.append(svg);
  const cl = S.power.CLOUD_AMT, valid = cl.filter(v => v >= 0), n50 = valid.filter(v => v >= 50).length;
  const lastValid = S.power.dates[cl.map(v => v >= 0).lastIndexOf(true)];
  $('cloudNote').textContent = 'Cloud context (NASA POWER CLOUD_AMT, same point): at least 50% cloud cover on ' + n50 + ' of ' + valid.length +
    ' days with data (1 Jun to ' + lastValid + '); later values were not yet published at retrieval. This motivates radar, but does not prove that any particular optical image was unusable.';
}

function renderTable(ts) {
  const box = $('obsTable'); box.replaceChildren();
  const t = el('table', {}, el('caption', {}, 'NISAR L2 GCOV PROVISIONAL acquisitions, stack 086_A_005 (NASA CMR, queried ' + U.safeText(S.catalog.queried_utc, 25) + ')'));
  t.append(el('thead', {}, el('tr', {}, ...['Date', 'Start (UTC)', 'Polarizations', 'Orbit', 'Orbit fidelity', 'CRID', 'Size', 'HH median dB', 'HV median dB', 'Record'].map(hd => el('th', { scope: 'col' }, hd)))));
  const tb = el('tbody');
  const byDate = Object.fromEntries((ts || []).map(e => [e.date, e]));
  for (const g of S.catalog.granules) {
    const e = byDate[g.acquisition_date] || {};
    tb.append(el('tr', {}, el('td', {}, g.acquisition_date), el('td', {}, g.begin_utc.slice(11, 19)), el('td', {}, g.frequency_a_polarizations.join('+')),
      el('td', {}, String(g.orbit_number)), el('td', {}, U.FIDELITY[g.orbit_fidelity_token] || g.orbit_fidelity_token), el('td', {}, g.granule_ur.split('_')[13]),
      el('td', {}, (g.h5.bytes / 1e9).toFixed(2) + ' GB'), el('td', {}, U.fmt(e.hh_median_db, 2)), el('td', {}, U.fmt(e.hv_median_db, 2)), el('td', {}, link('CMR', g.cmr_record))));
  }
  t.append(tb); box.append(t);
}

// ---------- report handling ----------
function applyReport(rep, bytes, origin) {
  const v = U.validateReport(rep, bytes);
  if (!v.ok) { setStatus('evidenceStatus', 'Report rejected (' + origin + '): ' + v.errors.slice(0, 3).join('; '), 'bad'); return false; }
  S.report = rep; S.reportTier = v.tier; S.cell = null;
  if (rep.schema === 'ulak-change-v2') {
    const pa = String(rep.provenance.before.acquisition_begin_utc || '').slice(0, 10), pb = String(rep.provenance.after.acquisition_begin_utc || '').slice(0, 10);
    const ga = S.catalog.granules.find(g => g.acquisition_date === pa), gb = S.catalog.granules.find(g => g.acquisition_date === pb);
    if (ga && gb) { S.before = ga; S.after = gb; $('before').value = pa; $('after').value = pb; }
  }
  const synth = v.tier === 'SYNTHETIC';
  if (v.tier === 'MEASURED' && hasMeasuredOverlays() && S.layerMode === 'gibs' && !S.userPickedLayer) setLayerMode('hh');
  setTier(v.tier, synth ? 'the loaded report is a software test fixture' : U.safeText(origin, 80));
  setStatus('evidenceStatus', (synth ? 'SOFTWARE TEST FIXTURE loaded - not an observation. ' : v.tier === 'MEASURED' ? 'Measured report loaded from real NISAR pixels. ' : 'Legacy report loaded; provenance is user-declared. ') +
    'Candidate changes only; see the passport for checks and caveats.' + (v.warnings.length ? ' ' + v.warnings.join(' ') : ''), (synth || v.tier === 'USER_DECLARED') ? 'warn' : 'good');
  drawFootprints(); fitStudy(); drawCells(); renderStats(); renderPassport(); renderSeries(); loadRadar();
  return true;
}
function clearReport() {
  S.report = null; S.reportTier = null; S.cell = null; drawCells(); setTier('CATALOG', 'no measurement loaded');
  setStatus('evidenceStatus', 'No measurement report loaded. No quantitative claims are made.'); $('evidence').value = '';
  if (S.layerMode !== 'gibs') { document.querySelector('input[name=layer][value=gibs]').checked = true; S.layerMode = 'gibs'; }
  drawFootprints(); renderStats(); renderPassport(); renderSeries(); loadRadar();
}
async function importFile(file) {
  if (file.size > U.MAX_REPORT_BYTES) { setStatus('evidenceStatus', 'File too large (limit 5 MB).', 'bad'); return; }
  let rep; try { rep = JSON.parse(await file.text()); } catch (e) { setStatus('evidenceStatus', 'Import failed: not valid JSON.', 'bad'); return; }
  applyReport(rep, file.size, 'imported file ' + U.safeText(file.name, 60));
}
function exportReport() {
  const md = U.buildStudyReport({ tier: S.tier, generatedUtc: new Date().toISOString(), areaName: 'Central Sudd, South Sudan - NISAR frame 086_A_005',
    aoi: S.aoiBox, before: S.before, after: S.after, checks: currentChecks(), report: reportMatchesSelection() ? S.report : null,
    cell: S.cell, rainMm: S.power ? U.sumBetween(S.power.dates, S.power.PRECTOTCORR, S.before.acquisition_date, S.after.acquisition_date) : null,
    limitations: (S.report && S.report.limitations) || ['No measurement has been loaded; this report documents catalog-verified observations only.'] });
  const blob = new Blob([md], { type: 'text/markdown' }), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = 'ulak-study-report-' + S.before.acquisition_date + '_' + S.after.acquisition_date + '.md';
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  S.lastExport = md;
}

// ---------- controls ----------
function fillSelects() {
  for (const id of ['before', 'after']) {
    const s = $(id); s.replaceChildren();
    for (const g of S.catalog.granules) {
      const tags = [g.frequency_a_polarizations.join('+')]; if (g.orbit_fidelity_token === 'F') tags.push('forecast orbit');
      s.append(el('option', { value: g.acquisition_date }, g.acquisition_date + ' · ' + tags.join(' · ') + ' · cycle ' + g.cycle));
    }
  }
  $('before').value = '2026-06-20'; $('after').value = '2026-10-18';
  S.before = S.catalog.granules.find(g => g.acquisition_date === '2026-06-20');
  S.after = S.catalog.granules.find(g => g.acquisition_date === '2026-10-18');
}

function setupTemporalControls() {
  const sel = $('tsDate'); sel.replaceChildren();
  if (!S.ts) { sel.append(el('option', {}, 'Temporal result unavailable')); sel.disabled = true; return; }
  for (const date of S.ts.compatibility.dates) {
    const hv = S.ts.compatibility.hv_dates.includes(date);
    sel.append(el('option', { value: date }, date + (hv ? ' · HH+HV' : ' · HH only')));
  }
  sel.value = S.ts.compatibility.dates[0];
  sel.addEventListener('change', () => { if (S.layerMode.startsWith('ts_')) loadRadar(); });
  $('tsPrev').addEventListener('click', () => stepTemporal(-1));
  $('tsNext').addEventListener('click', () => stepTemporal(1));
  $('tsPlay').addEventListener('click', toggleTemporalPlay);
  $('tsRegion').addEventListener('change', renderSeries);
}

function stepTemporal(delta) {
  if (!S.ts) return;
  const dates = S.ts.compatibility.dates, i = dates.indexOf($('tsDate').value);
  $('tsDate').value = dates[(i + delta + dates.length) % dates.length];
  if (!['ts_hh', 'ts_hv'].includes(S.layerMode)) setLayerMode('ts_hh');
  loadRadar();
}

function toggleTemporalPlay() {
  if (S.playTimer) { clearInterval(S.playTimer); S.playTimer = null; $('tsPlay').textContent = 'Play'; return; }
  if (!S.ts) return;
  setLayerMode('ts_hh'); loadRadar(); $('tsPlay').textContent = 'Pause';
  S.playTimer = setInterval(() => stepTemporal(1), 1100);
}
function onPairChange() {
  S.before = S.catalog.granules.find(g => g.acquisition_date === $('before').value);
  S.after = S.catalog.granules.find(g => g.acquisition_date === $('after').value);
  S.cell = null; renderPassport();
  const bad = U.catalogChecks(S.before, S.after).filter(c => c.status === 'FAIL');
  if (bad.length) setStatus('mapStatus', 'This pair fails: ' + bad.map(c => c.description).join('; ') + '. It can be viewed but should not be compared quantitatively.', 'warn');
  else setStatus('mapStatus', 'Pair passes catalog checks. Press "Load NISAR imagery" to view the GIBS mosaics.');
}
function fitStudy() {
  if ($('region').value === 'frame' && S.frame) S.map.fitBounds(S.frame.getBounds(), { padding: [10, 10] });
  else if (S.aoi) S.map.fitBounds(S.aoi.getBounds(), { padding: [20, 20] });
}
function locate() {
  const lat = Number($('lat').value), lon = Number($('lon').value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 85 || Math.abs(lon) > 180) { setStatus('mapStatus', 'Enter a valid latitude (±85°) and longitude (±180°).', 'bad'); return; }
  $('region').value = 'custom'; S.map.setView([lat, lon], 11);
  const inFrame = S.frame && S.frame.getBounds().contains([lat, lon]);
  setStatus('mapStatus', inFrame ? 'Position is inside frame 086_A_005.' : 'Position is outside the analysed frame: only the visual GIBS layer can be shown here.', inFrame ? '' : 'warn');
}

async function boot() {
  if (typeof L === 'undefined' || !U) { $('mapStatus').textContent = 'The map library failed to load. Serve the web folder over HTTP: py -m http.server 8000 --directory web'; return; }
  initMap();
  try { S.catalog = (await getJSON('data/catalog.json')).data; }
  catch (e) {
    setTier('UNAVAILABLE', 'observation catalog could not be loaded');
    setStatus('mapStatus', location.protocol === 'file:' ? 'Open the app through a local web server (py -m http.server 8000 --directory web); browsers block data files on file://.' : 'Catalog load failed: ' + e.message, 'bad');
    return;
  }
  try { S.power = (await getJSON('data/power.json')).data; } catch (_) { S.power = null; }
  try { const t = await getJSON('data/timeseries.json', true); S.ts = t ? t.data : null; }
  catch (e) { S.ts = null; setStatus('evidenceStatus', 'Temporal result could not be read: ' + e.message, 'warn'); }
  fillSelects(); setupTemporalControls(); drawFootprints(); fitStudy();
  setTier('CATALOG', S.catalog.granules.length + ' real acquisitions of frame 086_A_005 verified in NASA CMR');
  let loaded = false;
  try { const r = await getJSON('data/sudd_report.json', true); if (r) loaded = applyReport(r.data, r.bytes, 'web/data/sudd_report.json'); }
  catch (e) { setStatus('evidenceStatus', 'Bundled report could not be read: ' + e.message, 'bad'); }
  if (!loaded) { setStatus('evidenceStatus', 'No measured pair report yet, so pairwise change is not claimed.'); renderStats(); renderPassport(); renderSeries(); loadRadar(); }
  else renderSeries();
  renderTemporalCell();
  renderRain();
  $('swipe').addEventListener('input', refreshClip);
  $('refresh').addEventListener('click', loadRadar);
  $('before').addEventListener('change', onPairChange); $('after').addEventListener('change', onPairChange);
  $('region').addEventListener('change', () => { if ($('region').value !== 'custom') fitStudy(); });
  $('go').addEventListener('click', locate);
  $('fit').addEventListener('click', () => { $('region').value = 'sudd'; fitStudy(); });
  $('toggleMap').addEventListener('click', () => { S.visible = !S.visible; for (const k of ['a', 'b']) if (S.layers[k]) { if (S.visible) S.layers[k].addTo(S.map); else S.map.removeLayer(S.layers[k]); }
    $('toggleMap').textContent = S.visible ? 'Hide radar layer' : 'Show radar layer'; refreshClip(); });
  for (const r of document.querySelectorAll('input[name=layer]')) r.addEventListener('change', e => { S.userPickedLayer = true; S.layerMode = e.target.value; loadRadar(); });
  $('showCells').addEventListener('change', drawCells);
  $('evidence').addEventListener('change', e => { if (e.target.files && e.target.files[0]) importFile(e.target.files[0]); });
  $('clearEvidence').addEventListener('click', clearReport);
  $('export').addEventListener('click', exportReport);
  window.addEventListener('resize', refreshClip);
  window.__ULAK = S; // exposed for automated browser QA only
}
document.addEventListener('DOMContentLoaded', boot);
})();
