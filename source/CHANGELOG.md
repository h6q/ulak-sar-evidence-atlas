# Changelog

## 2026-11-14 v0.4 - QC-screened temporal evidence
- Processed all 10 cached NISAR acquisitions on a common 100 m grid; primary inference uses 9 QC-pass dates (24 Sep HH-only, 6 Oct excluded by QC).
- Added checksum-verified temporal inputs, warning-free block statistics, spatial block-bootstrap confidence intervals, Spearman tests, trend and strict persistence products.
- Added independent-sensor context from OPERA DSWx-S1/HLS and MODIS IGBP GIBS renderings, with exact palette decoding and remote reproducibility checks. These are context, not ground truth.
- Added the timeline player, HH/HV/Δ/trend/persistence overlays, region comparison and per-cell temporal passport to the web app.
- Added `analysis/test_timeseries.py` and `analysis/fetch_reference.py`; Python suite is 55/55, JavaScript 11/11 and measured browser QA 34/34.
- Updated the seven-slide deck and supporting documentation. The source deck remains unchanged; final temporal deck is `docs/ULAK_demo_7_slides_timeseries.pptx`.
- Fixed the PowerShell wrapper so fully cached runs do not request an Earthdata token.

## 2026-11-14 v0.3.2 - real measurements audited
- The team ran the real pair (2026-06-20 → 2026-10-18) over HTTPS range reads. The report was regenerated from the verified window cache (no network, no token) with new diagnostics.
- New `analysis/audit_measurement.py`: an independent re-computation from the GeoTIFFs. It passes 21/21 on the original and the regenerated report.
- Each report now carries diagnostics: the scene-shift analysis (tiles, brightness strata, dark pixels) and threshold sensitivity (as reported / shift removed / 3 dB gates).
- Mask rules now follow the file's own description: value 0 (partially focused) is invalid, as well as 255 (outside the acquisition).
- Fixed: the baseline day count is now rounded (it showed 119 instead of 120); a Leaflet crash when the GIBS fallback ran inside a tile callback.
- Web:
  - opens on the measured HH layer when a MEASURED report exists;
  - automatically falls back to the measured layers if NASA GIBS fails;
  - shows a robustness table, plus shift and robustness rows in the passport;
  - explains pair-only runs.
- Token is lazy (asked only on a cache miss).
- `scripts/build_public_package.py` builds the static site (`dist/`) with a credential scan.
- Docs: RESULTS.md, AUDIT_REPORT.md; slides updated with real measurements and live-app screenshots.
- Tests: 50 Python, 11 JavaScript, browser QA 30/30 (measured) + 24/24 (catalog) + 28/28 (synthetic).

## 2026-11-14 v0.3.1 - real-data fix
- Fixed the real-run crash `Object of type Reference is not JSON serializable` (HDF5 `DIMENSION_LIST`). Added an explicit HDF5/NumPy-to-JSON serializer that resolves references to dataset paths.
- Added a verified window cache (`data/derived/cache`, SHA-256 checked) that is written immediately after each HTTPS range read and reused on rerun.
- GeoTIFF tags and sidecars now carry the source granule, polarization, acquisition start/end UTC, CRS, transform, shape, spacing, nodata and units attribute.
- Credentials are scrubbed from the log (UTF-8, written by Python), from tracebacks and from all JSON; any write containing the token is refused.
- `numberOfLooks` is opt-in (`--read-nlooks`), reducing transfer.
- Tests: 42 → 47 Python tests.

## 2026-11-14 v0.3 - "Beneath the Canopy" (Sudd), AI-assisted, team review pending
- **Study area changed by team decision** from Kütahya/Mississippi to the central Sudd wetlands. Sudd, Congo and Okavango were screened in NASA CMR (`data/catalog/candidate_regions_2026-11-14.json`).
- Added a real NASA CMR snapshot of NISAR GCOV stack 086_A_005 (10 granules), verified 10/10 against live CMR; `data/manifest.json`; NASA POWER rainfall and cloud context.
- New real-data pipeline `analysis/run_sudd.py`, built from these modules:
  - `gcov_reader.py`: layout-checked HDF5 window reads over HTTPS.
  - `provenance.py`: catalog and in-file checks, safe JSON.
  - `sar_change.py`: dual-pol screening.
  - `report_builder.py`: report schema v2, overlays, validation.
  - `nisar_catalog.py`: live re-verification.
- Secure PowerShell workflow (`scripts/ulak_setup.ps1`, `scripts/ulak_run_sudd.ps1`): hidden token prompt, nothing stored, full-download fallback with MD5 check.
- `change_detector.py` keeps its API and gains:
  - provenance sidecars (polarization mismatch is now caught, not declared);
  - dB-input detection;
  - signed candidate counts;
  - fixes for nodata handling and the deprecated transform operator.
- Web app reworked (same layout and style):
  - real acquisition selectors;
  - evidence tiers (Measured / Catalog-verified / Visual / Software test);
  - an 8-part Evidence Passport, including a per-cell passport;
  - measured layers;
  - ΔHH/ΔHV histogram, time series and rainfall chart;
  - English study-report export;
  - safe import validation;
  - vendored Leaflet;
  - accessibility (skip link, focus, keyboard cell list, table view);
  - mobile layout.
- Fixed v0.1 defects:
  - an indefinite "Connecting to NASA GIBS…" status (listeners were lost when the layer was recreated);
  - the swipe clip applied to a zero-size Leaflet pane.
- Tests: 6 → 42 Python, plus 11 Node tests, plus automated browser QA (24/24 shipped app, 28/28 synthetic-report copy).
- Docs: METHODOLOGY, DATA_SOURCES, REPORT_SCHEMA, TEST_REPORT, STATUS, DEPLOYMENT, SPACE_APPS_SUBMISSION, JUDGING_SELF_REVIEW, BLOCKERS; 7-slide English demo deck.
- **Not done:** real pixel processing (needs the team's Earthdata token), measured results, deployment, final submission.

## 2026-11-14 v0.1 (starter, not final submission)
- Added original ULAK front-end with date-controlled NASA GIBS WMS comparison, field study navigator and scientific caution panels.
- Added numerical georeferenced change screening pipeline for aligned single-band GCOV intensity GeoTIFF pairs.
- Added six passing synthetic unit tests.
- Added data manifest example, source-backed plans, Claude master brief, English submission template and disclosure rules.
