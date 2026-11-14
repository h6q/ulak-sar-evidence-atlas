# ULAK — Beneath the Canopy

**NASA Space Apps Challenge 2026 · Challenge: Dancing with the SARs**
**Team ULAK:** Yiğitcan Ufuk Demir and Batuhan Türkyılmaz

An evidence-first atlas of what the NASA-ISRO NISAR L-band radar measured over the Sudd wetlands (South Sudan) during the 2026 wet season, and how far each measurement can be trusted.

* **Live app:** https://h6q.github.io/ulak-sar-evidence-atlas/
* **Seven-slide demo:** https://h6q.github.io/ulak-sar-evidence-atlas/demo/ULAK_demo_7_slides_FINAL.pdf
* **Scientific source code, tests and documentation:** [`source/`](source/)

> ULAK reports measured radar backscatter and its uncertainty. It is a screening and learning tool. It is **not** a flood-detection or flood-warning system, and it makes no flood-extent or accuracy claim.

## Research question

Can a multi-temporal NISAR L-band HH/HV time series reveal spatially coherent seasonal changes in the Sudd wetlands, and can those changes be distinguished from radiometric uncertainty, vegetation effects and possible inundation?

## Data

| Dataset | Identifier | Role |
|---|---|---|
| NISAR L2 GCOV PROVISIONAL V1 (ASF DAAC) | Collection `C2854338529-ASF`, DOI [10.5067/NIL2GCOV-P1](https://doi.org/10.5067/NIL2GCOV-P1), CRID P05023 | Measurements (gamma0 HH and HV, frequency A, 20 m) |
| OPERA DSWx-S1 V1 (PO.DAAC) | DOI [10.5067/OPDSWS1-L3V1](https://doi.org/10.5067/OPDSWS1-L3V1) | Independent-sensor context (Sentinel-1 C-band) |
| OPERA DSWx-HLS V1 (PO.DAAC) | DOI [10.5067/OPDSW-PL3V1](https://doi.org/10.5067/OPDSW-PL3V1) | Optical context, cloud-masked |
| MODIS MCD12Q1 v061 IGBP (LP DAAC) | DOI [10.5067/MODIS/MCD12Q1.061](https://doi.org/10.5067/MODIS/MCD12Q1.061) | Fixed analysis regions |
| NASA POWER Daily API | point 30.75° E, 7.25° N | Rain and cloud context |

* NISAR stack **086_A_005**: track 86 ascending, frame 5; 10 acquisitions from 2026-06-20 to 2026-10-18. Granule IDs, MD5 checksums and footprints are in [`source/data/catalog/sudd_086_A_005_cmr_snapshot.json`](source/data/catalog/sudd_086_A_005_cmr_snapshot.json).
* Study window (W, S, E, N): 30.55, 7.00, 30.95, 7.40.
* The OPERA and MODIS layers were read as NASA GIBS WMS renderings and decoded exactly from their published colour palettes. Request URLs and checksums: [`source/data/reference/reference_provenance.json`](source/data/reference/reference_provenance.json).

No satellite rasters are stored in this repository. The pipeline reads them from NASA with your own Earthdata Login.

## Main verified findings

Nine of the ten acquisitions pass quality control (6 October is excluded by a pattern-based rule that never looks at change magnitude; 24 September has HH only). Common support: 195,538 cells of 100 m (1,955 km²). Change is first to last date, 20 June → 18 October 2026. Intervals are 95% spatial block-bootstrap confidence intervals.

| Group, fixed by OPERA DSWx-S1 class on all 8 matched dates | Cells (0.01°) | HH change | HV change |
|---|---:|---:|---:|
| Inundated vegetation | 155 | **+2.10 dB** [1.99, 2.37] | +1.24 dB [1.08, 1.62] |
| Open water | 48 | +0.65 dB [0.21, 0.88] | −0.13 dB [−0.62, 0.31] |
| Not water | 259 | +0.44 dB [0.38, 0.50] | +0.18 dB [0.04, 0.26] |

* Among savanna cells, HH brightening peaks 10–14 km west (+2.77 dB) and 14–18 km east (+2.98 dB) of the permanent-wetland corridor centreline and is about zero at the centre.
* Relative to the scene-wide change, the corridor became darker (HH −0.91 dB, HV −1.10 dB) and the east margin brighter (HH +0.74 dB, HV +0.89 dB).
* Strict persistent change (more than 3 dB in both the raw and the normalised series) covers only 0.108% (HH) and 0.099% (HV) of the area.
* An independent script, [`source/analysis/verify_findings.py`](source/analysis/verify_findings.py), recomputes the group results from the raw cache without importing the analysis modules and agrees within 0.02 dB.

Full results: [`source/docs/TIMESERIES_FINDINGS.md`](source/docs/TIMESERIES_FINDINGS.md), [`source/docs/RESULTS.md`](source/docs/RESULTS.md), machine-readable [`source/docs/results/timeseries_results.json`](source/docs/results/timeseries_results.json), figures in [`source/docs/figures/`](source/docs/figures/).

## Scientific limitations

* **No ground truth.** No river-gauge or field data were available. OPERA DSWx-S1 is itself a radar-derived classification (it also uses a land-cover mask), so agreement between NISAR and DSWx-S1 is an association between two radar products, not validated flooding.
* **Water and vegetation are not separated.** HV rose together with HH in the inundated-vegetation group; vegetation growth or a rain-wet canopy can produce the same signal.
* **Spatial clustering.** 125 of the 155 inundated-vegetation cells lie in one western belt; the eastern brightening peak is not mapped as inundated by DSWx-S1.
* **Provisional products.** The NISAR data are PROVISIONAL (CRID P05023); residual calibration effects cannot be excluded. The cause of the 6 October anomaly is not known.
* **Baseline gap.** The 20 June baseline has no matching DSWx-S1 date.
* **Rendered reference layers.** GIBS renderings are resampled visualisations; class areas at 0.01° are approximate.
* One study area and one season. Results should not be generalised.

## How the analysis works

1. **Catalog verification** (`nisar_catalog.py`, `provenance.py`): granule IDs, times, checksums and footprints are checked against NASA CMR.
2. **Window read** (`gcov_reader.py`, `run_sudd.py`): only the study window of the `HHHH` and `HVHV` layers is range-read over HTTPS from each GCOV HDF5 file and cached with a SHA-256 hash.
3. **Compatibility and QC** (`provenance.py`, `timeseries.py`): same track, frame, mode, release, grid and units; mask handling; a spatial-pattern QC rule for whole dates.
4. **Change analysis** (`sar_change.py`, `timeseries.py`): 5 × 5 multilooking in linear power to 100 m, dB conversion, region statistics on regions fixed in advance from MODIS land cover, common-mode versus region-relative change, trend, persistence, block-bootstrap intervals and permutation tests.
5. **Independent context** (`reference_data.py`, `fetch_reference.py`): palette-exact decoding of OPERA DSWx and MODIS layers, with checksums and cross-sums.
6. **Audit** (`audit_measurement.py`, `verify_findings.py`): independent recomputation of headline numbers.
7. **Outputs** (`report_builder.py`, `ts_figures.py`): JSON reports, overlays and figures used by the web app.

Method details: [`source/docs/METHODOLOGY.md`](source/docs/METHODOLOGY.md). Data sources: [`source/docs/DATA_SOURCES.md`](source/docs/DATA_SOURCES.md).

## Repository layout

```
/                      deployed static web app (GitHub Pages): index.html, app.js, lib.js, styles.css, data/, vendor/, demo/
source/analysis/       Python analysis modules and pytest tests
source/scripts/        Windows PowerShell setup/run scripts, package builder with credential scan
source/tests/web/      JavaScript unit tests for the app logic
source/qa/             Playwright browser checks
source/data/           catalog snapshot, NASA POWER extract, decoded reference layers, audit results (small text files only)
source/docs/           methodology, data sources, results, test report, figures
```

The web app at the repository root is plain HTML, CSS and JavaScript with a vendored copy of Leaflet 1.9.4. It needs no build step and no server code.

## Reproduce

Requirements: Python 3.10 or newer, Git, and (optional) Node.js 20+ for the JavaScript tests. Commands are for Windows PowerShell.

```powershell
git clone https://github.com/h6q/ulak-sar-evidence-atlas.git
cd ulak-sar-evidence-atlas\source
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r analysis\requirements.txt

# The scripts expect a working copy of the site in source\web (ignored by Git):
New-Item -ItemType Directory -Force web | Out-Null
Copy-Item ..\index.html, ..\app.js, ..\lib.js, ..\styles.css web
Copy-Item ..\data, ..\vendor, ..\demo web -Recurse -Force

# Tests that need no NASA download
.\.venv\Scripts\python.exe -m pytest analysis -q
node --test tests\web\lib.test.js
```

To repeat the measurements you need a free NASA Earthdata Login (https://urs.earthdata.nasa.gov/) with the ASF data-use terms accepted, and a user token (*Generate Token* on your profile page).

```powershell
# Reads the 10 study windows from NASA (about 10 x 60 MB cache, not the 1.8 GB files).
# The script asks for the token at a hidden prompt and removes it from the session afterwards.
powershell -ExecutionPolicy Bypass -File scripts\ulak_run_sudd.ps1

.\.venv\Scripts\python.exe analysis\timeseries.py          # time series, statistics, figures, web payload
.\.venv\Scripts\python.exe analysis\verify_findings.py     # independent recomputation of the headline numbers
.\.venv\Scripts\python.exe analysis\audit_measurement.py   # audit of the two-date report
py -m http.server 8000 --directory web                     # view the app at http://localhost:8000
```

**Never put your Earthdata token in a file in this repository, in a commit or in an issue.** The pipeline reads it only from the `EARTHDATA_TOKEN` environment variable or the hidden prompt and never writes it to disk.

Dependencies: NumPy, rasterio, h5py, fsspec, aiohttp, pyproj, Pillow, Matplotlib, pytest (see [`source/analysis/requirements.txt`](source/analysis/requirements.txt)); Playwright only for `source/qa/browser_qa.py`.

Test status at release (2026-11-14): 55 Python tests, 11 JavaScript tests and 34/34 browser checks passed on the team's full working copy. In a fresh clone one Python test is skipped because it needs the locally built NISAR cache. Details: [`source/docs/TEST_REPORT.md`](source/docs/TEST_REPORT.md).

## Use of AI tools

This project was built with substantial help from generative AI assistants, used under the team's direction: **ChatGPT and Codex (OpenAI)** and **Claude (Anthropic)**. They were used to:

* search and summarise official NASA, ASF and Space Apps documentation and query public NASA catalogs;
* draft most of the Python, JavaScript and PowerShell code and the automated tests;
* help design, implement and independently re-check the statistical analysis;
* draft documentation, the submission text and slide text, and write the code that plots the charts.

The team chose the challenge and study area, obtained the data with its own Earthdata credentials, ran the code on its own computer, and is responsible for the scientific interpretation. All numbers come from running the code on real NISAR data; none were generated by an AI model. No AI-generated images, video or audio are used: images are NASA GIBS renderings, real application screenshots or charts plotted from measured values. No NASA or ISRO logos or mission identifiers are used, and no endorsement by NASA or ISRO is implied.

## Licence and attribution

* Team ULAK's own code and documentation: MIT License, see [`LICENSE`](LICENSE).
* Third-party components and data: see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
* NISAR data: NASA-ISRO SAR Mission, distributed by the Alaska Satellite Facility DAAC. OPERA DSWx products contain modified Copernicus Sentinel data. Basemap © OpenStreetMap contributors.
