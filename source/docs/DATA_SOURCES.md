# Data sources and attribution (checked 2026-11-14)

| Source | What we use | Access | URL | Status in repo |
|---|---|---|---|---|
| NASA-ISRO NISAR L2 GCOV PROVISIONAL (ASF DAAC) | HHHH and HVHV gamma0 windows for stack 086_A_005 | Earthdata Login (free) | https://search.asf.alaska.edu/#/?dataset=NISAR · collection C2854338529-ASF · DOI https://doi.org/10.5067/NIL2GCOV-P1 | **All 10 AOI windows retrieved and cache-hash verified 2026-11-14** |
| NASA CMR | Granule metadata (IDs, times, footprints, MD5, sizes, attributes) | Public | https://cmr.earthdata.nasa.gov/search/ | `data/catalog/sudd_086_A_005_cmr_snapshot.json` |
| ASF NISAR documentation | Product layout, maturity, CRIDs, naming, data gap, PROVISIONAL known issues (https://nisar-docs.asf.alaska.edu/provisional-known-issues/) | Public | https://nisar-docs.asf.alaska.edu/gcov/ · https://nisar-docs.asf.alaska.edu/availability-overview/ · https://nisar-docs.asf.alaska.edu/naming-conventions/ | Cited in docs |
| ASF NISAR Cookbook (BSD-3-Clause) | HTTPS streaming pattern (bearer token + fsspec) | Public | https://asfopensarlab.github.io/NISAR_Cookbook/search-stream-nisar-asf-search | Pattern reimplemented, attributed |
| NASA GIBS WMS | Layer `NISAR_L2_Geocoded_Polarimetric_Covariance` (rendered daily mosaic; GetCapabilities verified 2026-11-14; time ranges include 2026-04-14..2026-07-27 and 2026-08-10..2026-11-11) | Public | https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi | Visual layer only |
| NASA Worldview | Link for visual exploration | Public | https://worldview.earthdata.nasa.gov/ | Link |
| NASA POWER Daily API v2.10.3 | PRECTOTCORR (mm/day) and CLOUD_AMT (%) at 30.75 E, 7.25 N, 2026-06-01..10-31 | Public | https://power.larc.nasa.gov/ | `data/ancillary/nasa_power_sudd_2026.json` |
| NASA GIBS · OPERA DSWx-S1/HLS | Dynamic surface-water renderings from Sentinel-1 and HLS | Public | `OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1`; `OPERA_L3_Dynamic_Surface_Water_Extent-HLS` | Exact palette-decoded 0.01° cell products in `data/reference/`; contextual, not ground truth |
| NASA GIBS · MODIS MCD12Q1 v061 IGBP | Annual land-cover rendering used to define descriptive corridor/margin masks | Public | `MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual` | 2023/2024 products in `data/reference/`; exact palette decode |
| OpenStreetMap | Basemap tiles | Public | https://www.openstreetmap.org/copyright | © OpenStreetMap contributors (ODbL) |
| Leaflet 1.9.4 | Map library | BSD-2-Clause | https://leafletjs.com/ | Vendored in `web/vendor/leaflet` with LICENSE |
| NumPy, h5py, rasterio, fsspec, aiohttp, Pillow, pytest, Playwright | Python tooling | Open source (BSD/MIT/Apache) | PyPI | `analysis/requirements.txt` |

Calibration context: NISAR calibration presentation, Fringe 2026 (https://fringe2026.esa.int/iframe-agenda/files/ID_282.pdf), which reports an approximately 1 dB radiometric accuracy requirement.

Space agency partner: **ISRO** is the NISAR co-mission partner (https://www.isro.gov.in/NISAR.html).

No NASA, ISRO or ASF logos, insignia or mission branding are used. No endorsement is implied. The repository contains no AI-generated images, video or audio.

## NISAR granules (stack 086_A_005, PROVISIONAL, CRID P05023)
| Date | Granule (CMR concept) | Polarizations | Notes |
|---|---|---|---|
| 2026-06-20 | `…_023_086_A_005_2005_DHDH_A_20260620T033436_20260620T033510_P05023_N_F_J_001` (G4244913851-ASF) | HH+HV | **Primary before** |
| 2026-07-02 | `…_024_…_20260702T033435_…_N_F_J_001` (G4247072963-ASF) | HH+HV | |
| 2026-07-14 | `…_025_…_20260714T033435_…_F_F_J_001` (G4253179735-ASF) | HH+HV | Forecast orbit token |
| 2026-07-26 | `…_026_…_20260726T033434_…` (G4263471732-ASF) | HH+HV | |
| 2026-08-19 | `…_028_…_20260819T033433_…` (G4286321313-ASF) | HH+HV | after instrument gap |
| 2026-08-31 | `…_029_…_20260831T033432_…` (G4295911632-ASF) | HH+HV | |
| 2026-09-12 | `…_030_…_20260912T033432_…` (G4310656751-ASF) | HH+HV | |
| 2026-09-24 | `…_031_…_SHSH_…_20260924T033432_…` (G4324154258-ASF) | HH | single-pol |
| 2026-10-06 | `…_032_…_20261006T033432_…` (G4349559481-ASF) | HH+HV | smaller file (1.61 GB) |
| 2026-10-18 | `…_033_086_A_005_2005_DHDH_A_20261018T033432_20261018T033507_P05023_N_F_J_001` (G4379033365-ASF) | HH+HV | **Primary after** |

Full names, MD5 checksums, sizes, footprints and HTTPS/S3 URLs are in the snapshot JSON. Re-verify at any time with `analysis/nisar_catalog.py`.

The compact GIBS reference products and cross-sums can be re-verified locally, or re-fetched from the documented public endpoints, with `analysis/fetch_reference.py --remote`. A successful re-fetch on 2026-11-14 reproduced every stored table exactly.
