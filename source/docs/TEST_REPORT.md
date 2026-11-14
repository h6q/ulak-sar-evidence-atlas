# Test report (2026-11-14)

Unit tests use synthetic fixtures or catalog metadata. The v0.4 integration checks also verify already-retrieved real NISAR cache products and public NASA GIBS reference renderings; they test processing integrity, not scientific accuracy or ground truth.

## Baseline (before any edits)
* Command: `python -m pytest analysis -q`, Linux VM on the team PC, Python 3.10.12 venv with numpy 2.2.6, rasterio 1.4.4, h5py 3.16, pytest 9.2.
* Result: **6 passed** (the original synthetic tests).

## After changes
| Suite | Command | Environment | Result |
|---|---|---|---|
| Python analysis | `python -m pytest analysis -q -p no:cacheprovider` | Claude sandbox, Python 3.13, rasterio 1.5.2 | **50 passed** (v0.3.2) |
| Python analysis | same | Team PC Linux VM, Python 3.10, rasterio 1.4.4 | **50 passed** (v0.3.2) |
| Python analysis, temporal release | `.\.venv\Scripts\python.exe -m pytest analysis -q` | Windows venv | **55 passed** (v0.4) |
| Browser QA, temporal measured app | `.\.venv\Scripts\python.exe qa\browser_qa.py --site web --out qa/results/timeseries_final --expect-measured --chrome <chrome.exe>` | Windows, installed Chrome | **34/34** |
| Reference reproducibility | `.\.venv\Scripts\python.exe analysis\fetch_reference.py --remote` | Windows, live NASA GIBS | **all stored MODIS and OPERA tables reproduced exactly** |
| Browser QA, real measured report | `python qa/browser_qa.py --site web --out qa/results/measured --expect-measured` | Headless Chrome, offline sandbox | **30/30** |
| Independent measurement audit | `python analysis/audit_measurement.py` | Team PC Linux VM, real GeoTIFFs | **21/21** |
| Live app with real tiles | manual + scripted checks in the team's browser (`localhost:8000`) | Windows, real internet | GIBS 41 tiles + OSM loaded; measured overlays 446×446 shown; swipe, layers, cell passport OK |
| Web logic (Node) | `node --test tests/web/lib.test.js` | Node 22 (sandbox) and team PC VM | **11 passed** |
| Browser QA, shipped app | `python qa/browser_qa.py --site web --out qa/results/real` | Headless Chrome via Playwright, offline sandbox | **24/24** |
| Browser QA, synthetic-report copy | `python qa/browser_qa.py --site <qa copy> --out qa/results/synthetic_fixture --expect-report` | same | **28/28** |
| Windows PowerShell scripts | `scripts\ulak_setup.ps1` | **Not executed by the assistant** (no Windows shell) | Team to run |

## What the new tests cover
* **dB units:** linear-power multilooking (not dB averaging); dB-stored inputs rejected (pipeline and GeoTIFF CLI).
* **Alignment:** GeoTIFF transform/CRS mismatch rejected; HDF5 grid offset of 10 m blocks the pipeline (exit 3, `BLOCKED_checks.json`).
* **No-data:** `_FillValue` mask, NaN fill rows, GeoTIFF nodata (with a fix for nodata being mistaken for dB values).
* **Provenance:**
  * polarization mismatch via sidecars or single-pol date;
  * CRID, stack, chronology and AOI-outside failures;
  * Forecast-orbit warning;
  * wrong in-file track;
  * MD5 mismatch in local mode.
* **JSON safety:** malformed JSON, NaN/Infinity, non-object, oversize, wrong schema, blocking checks embedded in a report, `MEASURED` without a pixel source.
* **GeoJSON:** `[lon, lat]` order checked in Python and JavaScript; swapped coordinates rejected.
* **Empty data:** empty arrays, all-invalid arrays, empty FeatureCollection.
* **Security:**
  * the HTTPS path is tested against a local range server;
  * the bearer token arrives only in the `Authorization` header and never appears in reports or sidecars;
  * HTML or script injection in imported strings is not executed.
* **Real catalog integrity:** 10 granules, unique MD5s, one CRID, URLs consistent with granule names.
* **Browser:**
  * catalog load and default pair;
  * the 8-section passport;
  * charts and table;
  * the GIBS status leaving "Requesting" (offline it reports "tiles failed (40 errors)");
  * swipe clip, incompatible-pair warning, imports, export;
  * keyboard skip link and keyboard cell list;
  * no horizontal overflow at 375 px;
  * no JavaScript exceptions.

## Defects found and fixed by the tests
1. The "values look like dB" unit check was not blocking, so the pipeline continued and crashed later. It is now blocking.
2. The GeoTIFF CLI counted declared nodata (-9999) as negative power and wrongly rejected valid data. Nodata is now excluded.
3. Range reads fetched almost the whole small test file with 4 MiB blocks. The block size is now configurable and the test asserts partial transfer.
4. With a measured report loaded, the passport ignored the user's newly selected pair, so an incompatible pair showed no FAIL. The passport now follows the selection.

Earlier audit defects in the v0.1 web app (fixed):
* The status stayed "Connecting to NASA GIBS imagery…" forever, because the before-layer was recreated without its listeners.
* The swipe applied a percentage `clip-path` to a zero-size Leaflet pane, so it did not clip correctly.

## Real-data incident (v0.3.1, 2026-11-14 10:09)
The first real run (team PC, Windows, Python 3.14) authenticated and range-read the 2026-06-20 HH/HV window (rows 5324-7548, cols 8874-11094; 111 s). It then crashed while writing the GeoTIFF sidecar: `TypeError: Object of type Reference is not JSON serializable`. The cause was the HDF5 dimension-scale attribute `DIMENSION_LIST` (arrays of `h5py.Reference`).

Fixes:
* **Explicit serializer:** `gcov_reader.to_jsonable`.
  * Object and region references resolve to the referenced dataset path, e.g. `/science/LSAR/GCOV/grids/frequencyA/yCoordinates`.
  * Compound attributes (`REFERENCE_LIST`), NumPy scalars and arrays, and bytes are converted explicitly.
  * Unknown types become `"<unserializable: Type>"`, never silently dropped.
* **Verified window cache:** each window is saved, with SHA-256 checks, *before* any further processing, so a later failure never costs another network read.
* **Credential safety:** a scrubbed UTF-8 log written by Python; scrubbed tracebacks; a refusal to write any JSON that contains the token.
* **Data volume:** `numberOfLooks` is no longer read by default, saving one float layer of transfer.

Regression tests (`analysis/test_hdf5_metadata.py`; the fixture now carries real HDF5 dimension scales):
* reproduces the exact `DIMENSION_LIST` failure;
* checks type coverage;
* checks GeoTIFF and sidecar metadata;
* checks secret scrubbing.

The HTTPS test now also checks cache reuse (0 bytes on rerun) and corruption recovery.

## v0.3.2 audit of the real run
* The independent audit (`docs/AUDIT_REPORT.md`) recomputes valid pixels, medians, gates and class counts from the GeoTIFFs with separate code. It also checks the integrity hashes (GeoTIFF = sidecar = report), overlay bounds (59 m < 100 m display pixel) and the first cell. Result: 21/21.
* A visual georeference check against OpenStreetMap shows the radar swamp corridor and channel coinciding with the mapped wetland and river (`docs/media/app_georef_check_osm.png`). This is qualitative, not a validation.
* Defects fixed:
  * the chronology detail truncated 119.99 days to "119";
  * a Leaflet `_fadeAnimated` null crash when the GIBS fallback removed a layer inside Leaflet's own tile callback (now deferred);
  * the robustness table overflowed at narrow widths.
* Credential scan (`scripts/build_public_package.py`, plus a manual JWT/Bearer/.netrc search including the UTF-16 log, GeoTIFFs and cache archives): clean.

## v0.4 temporal checks
* Cache NPZ presence, array shape and SHA-256 are verified before analysis.
* Mixed processing version, CRID, radiometric convention or insufficient HH/HV dates stop inference.
* Block statistics, constant-series Spearman and block-bootstrap helpers run without RuntimeWarnings; the full temporal run succeeds with `RuntimeWarning` promoted to an error.
* Browser QA checks the 9-date primary timeline, explicit 6 Oct exclusion, missing 24 Sep HV, three temporal plot series, temporal overlays and a map-click cell passport.
* Final seven-slide deck: package integrity, 7-slide count, exact 16:9 dimensions, Arial/Calibri policy, template fidelity and first-party PPTX re-import all pass; every slide was rendered and inspected at full size.

## Not tested
* Native PowerPoint application opening; the final PPTX passed structural import and rendering instead.
* Screen-reader walkthrough.

Evidence: `qa/results/*/results.json`, `console.log`, screenshots. Screenshots in `qa/results/synthetic_fixture/` show **synthetic test data** and must never be presented as observations.

## Final hand-off run (2026-11-14)
| Check | Command | Environment | Result |
|---|---|---|---|
| Python | `python3 -m pytest analysis -q -p no:cacheprovider` | Team PC Linux VM, Python 3.10 | **55 passed** (first run: 1 failure caused only by a missing `fsspec` install in the VM; passed after installing it) |
| JavaScript | `node --test tests/web/lib.test.js` | Team PC Linux VM | **11 passed** |
| Browser QA on rebuilt package | `python3 browser_qa.py --site <unzipped dist/ulak_site.zip> --expect-measured` | headless Chromium (assistant sandbox) | **34/34** |
| Independent findings recompute | `python3 analysis/verify_findings.py` | Team PC Linux VM | +2.09 / +0.67 / +0.44 dB vs +2.10 / +0.65 / +0.44 dB in the results file |
| Package + credential scan | `python3 scripts/build_public_package.py` | Team PC Linux VM | 44 files, 8.70 MB; site clean; repo clean |
| Deck | pptx `validate.py`; LibreOffice render of 7 slides, each inspected | assistant sandbox | passed; not opened in Microsoft PowerPoint |
