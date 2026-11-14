# Methodology - ULAK "Beneath the Canopy" (Sudd)

*Status: applied to the real 2026-06-20 / 2026-10-18 pair and the QC-screened 2026 wet-season series (results in `docs/RESULTS.md` and `docs/TIMESERIES_FINDINGS.md`; pair audit in `docs/AUDIT_REPORT.md`). AI-assisted drafting; the ULAK team owns and reviews the science.*

## 1. Question
Can NASA-ISRO NISAR L-band radar reveal changes in inundation beneath emergent vegetation in the Sudd wetlands (South Sudan) during the 2026 wet season, where cloud cover often limits optical imagery?

We **screen for candidate radar backscatter changes** and attach physical hypotheses with their alternatives. We do **not** classify floods, estimate flooded area or report accuracy.

## 2. Data selection (catalog evidence, 2026-11-14)
* Product: NISAR L2 GCOV, collection `NISAR_L2_GCOV_PROVISIONAL_V1` (C2854338529-ASF), CRID P05023.
* Stack `086_A_005`: track 86, ascending, frame 5, left-looking, mode 2005 (Frequency A 20 MHz and Frequency B 5 MHz), full frame.
* 10 acquisitions from 2026-06-20 to 2026-10-18 on a 12-day repeat. Nine are dual-pol HH+HV; 2026-09-24 is HH-only. The 2026-08-07 repeat falls in the documented instrument gap.
* Primary pair: **2026-06-20 to 2026-10-18** (120 days). Both have the same CRID, product version 1.0.11, SAS ISCE3 0.25.16 and a near-real-time orbit token.
* 2026-07-14 carries a *Forecast* orbit token. It is flagged and never used as a pair member.
* The region screen (Sudd, Congo, Okavango; plus the withdrawn Mississippi) is in `data/catalog/candidate_regions_2026-11-14.json`.

## 3. Pixel access
`analysis/run_sudd.py` opens each granule over HTTPS with the team's Earthdata bearer token. It reads only the AOI window from `/science/LSAR/GCOV/grids/frequencyA/{HHHH,HVHV}` using range requests (fsspec + h5py), the access pattern shown in the ASF NISAR Cookbook.

The reader **checks** the documented layout in the real file and fails if anything is missing:
* the frequency group and coordinate vectors;
* the `projection.epsg_code` attribute;
* uniform spacing, and a dataset shape equal to `(len(y), len(x))`.

Pixel registration is read from the `xCoordinates` description. If the description does not state it, pixel-centre registration is assumed and flagged.

## 4. Compatibility checks (blocking unless noted)
**Catalog checks** (from the NASA CMR record):
* chronological order;
* same stack and mode;
* same CRID;
* same collection;
* HH and HV present on both dates;
* AOI inside both CMR footprints;
* orbit fidelity (WARN only).

**In-file checks** (from the HDF5 identification group, where present):
* track and frame;
* pass direction;
* start time within 120 s of the catalog;
* granule ID.

**Grid and unit checks:**
* **Units:** the values must behave like linear power. More than 1% negative samples is a FAIL.
* **Same grid:** the same EPSG code and identical coordinate vectors. No resampling is ever done silently; a mismatch stops the run and writes `BLOCKED_checks.json`.

## 5. Radiometric processing
1. Mask: only rules stated by the file's own mask attributes are applied. The real files say `_FillValue` 255 means outside the acquisition and value 0 means partially focused or invalid samples; both are excluded. Other values (subswath numbers) are kept. Non-positive or non-finite backscatter is also invalid. In the Sudd AOI every pixel has mask = 1.
2. Incoherent multilooking: k x k block mean **in linear power** (default k = 5, giving 100 m from 20 m). A block needs at least 50% valid samples.
3. dB = 10·log10(linear). ΔHH = HH_after - HH_before. ΔHV likewise. The ratio change is ΔR = ΔHH - ΔHV.
4. No median-shift correction is applied. A scene-wide median change of 1 dB or more triggers a warning, because it may be real (seasonal inundation) or an artefact (moisture, calibration, geometry).

## 6. Screening gates and hypotheses (heuristic)
Per channel, T = max(3 dB, 3 × 1.4826 × MAD(Δ)). R = 2 dB.

| Class | Rule | Consistent with | Main alternatives |
|---|---|---|---|
| HH up more than HV | ΔHH ≥ T_HH and ΔR ≥ R | water beneath emergent vegetation (double bounce) | wet or flattened stems, soil moisture, structures, edge speckle |
| HH and HV down | ΔHH ≤ -T_HH and ΔHV ≤ -T_HV | transition to smooth open water / submergence | burning, grazing or cutting, drying, calm wind, calibration |
| HV up more than HH | ΔHV ≥ T_HV and ΔR < 0 | vegetation growth (volume scattering) | wind-roughened water, regrowth, rain-wetted canopy |
| Other | \|Δ\| ≥ T, not above | unspecified | data quality, any of the above |

Physical basis (qualitative): Hess, Melack & Simonett (1990), *Int. J. Remote Sensing* 11(7), on radar detection of flooding beneath forest canopies; Hess et al. (1995), *IEEE TGRS* 33(4), on L/C-band SIR-C delineation of Amazon floodplain inundation and vegetation. These references support the *direction* of the responses. They do not support our numeric thresholds, which are screening choices.

MAD is a variability measure, **not** a confidence or probability.

## 7. Spatial and temporal products
* Candidate cells: 10 × 10 multilooked pixels (1 km), kept when at least 20% of their samples changed. Each cell carries its class fractions, median ΔHH and ΔHV, and the status "CANDIDATE - not confirmed flooding". GeoJSON is `[lon, lat]` and validated.
* Time series: 10 acquisitions are ingested, then QC is applied before inference. The 6 Oct acquisition fails QC and is excluded; 24 Sep contributes HH only. The primary series therefore contains nine HH dates and eight HV dates on 195,538 common 100 m cells (1,955.38 km²).
* Regional inference uses MODIS-IGBP-derived wetland-corridor, west-margin and east-margin masks on the common support. AOI common-mode change is reported separately from region-minus-common-mode change.
* Uncertainty for region medians and first-to-last differences uses 2 × 2-cell spatial blocks (about 2.2 km) with 2,000 bootstrap replicates. Theil-Sen slope and Spearman association are descriptive; constant series return an explicit undefined result instead of a numerical warning.
* Strict persistence requires |change| > 3 dB in both the raw and AOI-normalised series, rather than a one-date exceedance.
* Display overlays are reprojected to EPSG:4326 *for display only*. All statistics use the native UTM grid.

## 7b. Audit diagnostics (in every report: `diagnostics`)
* **Scene-wide shift:** fraction of pixels brighter; 4 × 4 tile medians; medians by quartile of the before-date HH; persistently dark pixels (HH < −15 dB on both dates).
* **Threshold sensitivity:** counts as reported, after re-centring the differences on the scene median (assumes the shift is not real change), and with fixed 3 dB gates.
* **Independent re-computation:** `analysis/audit_measurement.py` re-derives the statistics from the GeoTIFFs with separate code. It also checks integrity hashes, the grid, overlay bounds (< 150 m) and cell coordinates.
* **Pixel registration:** not stated in the file, so centre registration is assumed. This affects absolute placement by up to 10 m and has no effect on ΔdB (identical grids).

## 8. Context, not validation
* NASA POWER daily precipitation and cloud amount at 30.75° E, 7.25° N (coarse reanalysis or satellite-derived).
* OPERA DSWx-S1/HLS and MODIS IGBP are exact-palette decodes of public NASA GIBS renderings. They provide independent-sensor and land-cover context, not field truth or original GeoTIFF measurements.
* Sudd inundation is driven mainly by White Nile inflow, so local rainfall is context only.
* No gauge or field survey has been compared. OPERA comparisons are labelled contextual and cannot convert a radar response into a confirmed flood class.

## 9. Known limitations
* PROVISIONAL maturity, with a 2027 reprocessing announced.
* Speckle remains after multilooking.
* Equatorial ionospheric effects; acquisitions are pre-dawn (about 05:37 local solar time).
* Wind on open water.
* The incidence angle is not yet sampled per pixel; the same track and frame implies nearly identical nominal geometry.
* AOI chosen by the team, with no stratification by land cover.
