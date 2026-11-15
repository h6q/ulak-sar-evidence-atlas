# ULAK — Beneath the Canopy

**NASA Space Apps Challenge 2026 · Challenge: Dancing with the SARs**
**Team ULAK:** Yiğitcan Ufuk Demir and Batuhan Türkyılmaz

An evidence-first atlas of NASA-ISRO NISAR L-band radar over the Sudd wetlands of South Sudan. It shows what the radar measured during the 2026 wet season and how far each measurement can be trusted.

* **Live web app:** https://h6q.github.io/ulak-sar-evidence-atlas/
* **Seven-slide demo (PDF):** https://h6q.github.io/ulak-sar-evidence-atlas/demo/ULAK_demo_7_slides_FINAL.pdf
* **Scientific source code, tests and documentation:** [`source/`](source/)

## Research question

Can a multi-temporal NISAR L-band HH/HV time series reveal spatially coherent seasonal change in the Sudd, and can that change be told apart from radiometric uncertainty, vegetation effects and possible inundation?

We did not set out to prove flooding. Every result is reported with its uncertainty and with the evidence against it.

## NASA data and identifiers

| Data | Identifier | Role |
|---|---|---|
| NISAR L2 GCOV PROVISIONAL V1 (ASF DAAC) | Collection `C2854338529-ASF`, DOI [10.5067/NIL2GCOV-P1](https://doi.org/10.5067/NIL2GCOV-P1) | The measurement: gamma0 HH and HV, frequency A |
| NISAR stack | `086_A_005` (track 86 ascending, frame 5), release CRID `P05023`, 10 granules, 2026-06-20 to 2026-10-18 | Listed with MD5 and footprints in [`source/data/catalog/sudd_086_A_005_cmr_snapshot.json`](source/data/catalog/sudd_086_A_005_cmr_snapshot.json) |
| OPERA DSWx-S1 V1 (PO.DAAC) | DOI [10.5067/OPDSWS1-L3V1](https://doi.org/10.5067/OPDSWS1-L3V1) | Independent radar-based water classes (via NASA GIBS) |
| OPERA DSWx-HLS V1 (PO.DAAC) | DOI [10.5067/OPDSW-PL3V1](https://doi.org/10.5067/OPDSW-PL3V1) | Cloud-masked optical water context (via NASA GIBS) |
| MODIS Land Cover MCD12Q1 v061 (LP DAAC) | DOI [10.5067/MODIS/MCD12Q1.061](https://doi.org/10.5067/MODIS/MCD12Q1.061) | Fixes the analysis regions in advance (via NASA GIBS) |
| NASA POWER Daily API | point 30.75° E, 7.25° N | Rain and cloud context |
| NASA CMR, NASA GIBS | public APIs | Catalog verification, reference renderings |

Study area: 30.55–30.95° E, 7.00–7.40° N. Exact request URLs and checksums of the reference layers are in [`source/data/reference/reference_provenance.json`](source/data/reference/reference_provenance.json).

## Main verified findings

Nine of the ten acquisitions pass quality control (24 September has HH only; 6 October is excluded by a pattern-based rule). The common support is 195,538 cells of 100 m (1,955 km²). Changes are from 20 June to 18 October 2026; the group intervals below are 95% intervals from resampling individual 0.01° analysis cells; regional (common-mode-removed) comparisons use a spatial block bootstrap.

| Cells grouped by OPERA DSWx-S1 class fractions sampled from NASA GIBS renderings (criterion met on all 8 matched dates) | Cells | HH change | HV change |
|---|---:|---:|---:|
| Inundated vegetation | 155 | **+2.10 dB** [1.99, 2.37] | +1.24 dB [1.08, 1.62] |
| Open water | 48 | +0.65 dB [0.21, 0.88] | −0.13 dB [−0.62, 0.31] |
| Not water | 259 | +0.44 dB [0.38, 0.50] | +0.18 dB [0.04, 0.26] |

* Among savanna cells, HH brightening peaks 10–14 km west (+2.77 dB) and 14–18 km east (+2.98 dB) of the permanent-wetland corridor and is about zero at its centre.
* Relative to the scene-wide change, the corridor darkened (HH −0.91 dB, HV −1.10 dB) and the east margin brightened (HH +0.74 dB, HV +0.89 dB).
* Strict persistence (more than 3 dB in both raw and normalised series) covers only 0.108% (HH) and 0.099% (HV) of the area. Most large changes are episodic.
* An independent script, [`source/analysis/verify_findings.py`](source/analysis/verify_findings.py), reproduces the group results within 0.02 dB. The contrast also survives matching cells on their 20 June HH level.

Full account: [`source/docs/TIMESERIES_FINDINGS.md`](source/docs/TIMESERIES_FINDINGS.md) and [`source/docs/RESULTS.md`](source/docs/RESULTS.md).

## Scientific limitations

* **No flooding is claimed.** OPERA DSWx-S1 is itself a Sentinel-1 radar classification that also uses a land-cover mask. It is not field truth. Agreement between two radar products is an association, not validation.
* HV rose together with HH, so vegetation growth or a rain-wet canopy cannot be separated from water beneath vegetation.
* 125 of the 155 inundated-vegetation cells form one western belt. The eastern brightening peak is not mapped as inundated by DSWx-S1.
* The NISAR products are PROVISIONAL. The 20 June baseline has no matching DSWx-S1 date. The cause of the 6 October anomaly is not known.
* DSWx and MODIS layers were read as NASA GIBS renderings (exact class decoding, resampled geometry), not as the original GeoTIFFs.
* No river-gauge or field observations were available. ULAK is a screening and learning tool, not an operational flood-alert system.

## How the analysis works

1. **Catalog verification.** Granule IDs, times, MD5 values and footprints are stored and re-checked against NASA CMR (`nisar_catalog.py`, `provenance.py`).
2. **Windowed reading.** Only the study window (2224 × 2220 pixels at 20 m) of the `HHHH` and `HVHV` layers is read from each GCOV HDF5 file over HTTPS range requests, then cached with a SHA-256 hash (`run_sudd.py`, `gcov_reader.py`).
3. **Compatibility and QC.** Same track, frame, release, grid and units are required (24 September is a single-polarisation SHSH acquisition with HH only). A date whose 400 m image does not correlate with the other dates is excluded; the rule never uses change magnitude (`timeseries.py`).
4. **Statistics.** 5 × 5 multilooking in linear power, then dB. Regions come from MODIS land cover only. Scene-wide change is reported next to region-relative change. Regional change intervals use a spatial block bootstrap; DSWx group and distance-profile intervals use resampling of individual 0.01° analysis cells; associations use date-permutation nulls.
5. **Independent context.** DSWx-S1, DSWx-HLS and MODIS reference cells with checksums and cross-sums (`reference_data.py`, `fetch_reference.py`).
6. **Audit.** `audit_measurement.py` and `verify_findings.py` recompute the headline numbers by separate code paths.

Method details: [`source/docs/METHODOLOGY.md`](source/docs/METHODOLOGY.md). Sources: [`source/docs/DATA_SOURCES.md`](source/docs/DATA_SOURCES.md).

## Repository layout

| Path | Content |
|---|---|
| `index.html`, `app.js`, `lib.js`, `styles.css`, `data/`, `demo/`, `vendor/` | The deployed static web app (GitHub Pages serves the repository root) |
| `source/analysis/` | Python analysis modules and their pytest tests |
| `source/scripts/` | Windows PowerShell setup and run scripts; static-package builder with a credential scan |
| `source/data/` | Small public inputs only: CMR catalog snapshot, NASA POWER extract, reference cells, manifests, audit results |
| `source/docs/` | Methodology, data sources, results, audit and test reports |
| `source/tests/web/`, `source/qa/` | JavaScript logic tests and the browser QA script |

Satellite pixels are **not** stored here. Running the pipeline writes them to `source/data/derived/`, which is git-ignored. The published result blocks are in [`data/timeseries.json`](data/timeseries.json).

## Reproduce the results

Requirements: Windows PowerShell, Python 3.10 or newer, Node.js 18 or newer (for the JavaScript tests), and a free [NASA Earthdata Login](https://urs.earthdata.nasa.gov/) account that has accepted the ASF data-use terms.

```powershell
git clone https://github.com/h6q/ulak-sar-evidence-atlas.git
cd ulak-sar-evidence-atlas\source
powershell -ExecutionPolicy Bypass -File scripts\ulak_setup.ps1      # virtual environment, dependencies, tests, live CMR check
powershell -ExecutionPolicy Bypass -File scripts\ulak_run_sudd.ps1   # reads the 10 study windows; asks for your Earthdata token at a hidden prompt
.\.venv\Scripts\python.exe analysis\timeseries.py                    # time-series analysis, figures, web payload
.\.venv\Scripts\python.exe analysis\verify_findings.py               # independent recomputation of the headline findings
```

Tests (no credentials or satellite data needed):

```powershell
.\.venv\Scripts\python.exe -m pytest analysis -q
node --test tests\web\lib.test.js
```

**Earthdata authentication.** Create a token at https://urs.earthdata.nasa.gov/ (Generate Token). The run script asks for it at a hidden prompt, or reads the `EARTHDATA_TOKEN` environment variable for the current session. The token is never written to disk, logs or outputs. Never commit a token, `.netrc` or `.env` file.

To view your own results in the app, copy the site files next to the outputs and serve them locally:

```powershell
Copy-Item ..\index.html, ..\app.js, ..\lib.js, ..\styles.css -Destination web
Copy-Item ..\vendor -Destination web -Recurse
py -m http.server 8000 --directory web
```

Dependencies are pinned by range in [`source/analysis/requirements.txt`](source/analysis/requirements.txt): NumPy, SciPy, h5py, rasterio, pyproj, fsspec, aiohttp, Matplotlib, Pillow, pytest. The web app uses Leaflet 1.9.4 (vendored) and no build step.

## Use of AI tools

Generative AI assistants (OpenAI ChatGPT and Codex, Anthropic Claude) were used under the team's direction to search and summarise official documentation, draft Python, JavaScript and PowerShell code and tests, help design and independently re-check the statistical analysis, and draft documentation and slide text. AI-assisted source files say so in their first lines. Every number comes from running the code on real NISAR data; none was produced by a language model. No AI-generated images, video or audio are used, and no NASA or ISRO logos or mission identifiers. The choice of challenge and study area, data acquisition with the team's own credentials, and the final scientific interpretation are the team's.

## Licence and attribution

Team ULAK's own code and documentation: MIT License, see [`LICENSE`](LICENSE). Third-party components and data keep their own terms, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

NISAR data courtesy of NASA and ISRO, distributed by the Alaska Satellite Facility DAAC. OPERA products contain modified Copernicus Sentinel data. Basemap © OpenStreetMap contributors. No NASA or ISRO endorsement is implied.
