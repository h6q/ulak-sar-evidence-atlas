# Third-party notices

The MIT licence in `LICENSE` applies only to Team ULAK's own code and documentation. The items below keep their own terms.

## Software redistributed in this repository

| Component | Where | Licence |
|---|---|---|
| Leaflet 1.9.4 | `vendor/leaflet/` | BSD 2-Clause; full text in `vendor/leaflet/LICENSE` (kept unchanged) |

## Software used but not redistributed

Installed by the user from their own package index; each keeps its own licence: NumPy, rasterio (and GDAL), h5py (and HDF5), fsspec, aiohttp, pyproj (and PROJ), Pillow, Matplotlib, pytest, Playwright, PptxGenJS.

The HTTPS range-read access pattern for NISAR files follows the approach shown in the ASF NISAR Cookbook (BSD 3-Clause): https://asfopensarlab.github.io/NISAR_Cookbook/. No code was copied verbatim from it.

## Data and imagery

| Source | Use here | Terms and attribution |
|---|---|---|
| NISAR L2 GCOV PROVISIONAL V1, NASA-ISRO SAR Mission, ASF DAAC, DOI 10.5067/NIL2GCOV-P1 | Derived statistics, small display overlays in `data/` | NASA Earth science data are openly shared under the EOSDIS data use policy; cite the dataset DOI |
| OPERA DSWx-S1 V1, DOI 10.5067/OPDSWS1-L3V1, and OPERA DSWx-HLS V1, DOI 10.5067/OPDSW-PL3V1 (PO.DAAC) | Decoded class fractions in `source/data/reference/` | Openly shared; **contains modified Copernicus Sentinel data** |
| MODIS MCD12Q1 v061 (LP DAAC), DOI 10.5067/MODIS/MCD12Q1.061 | Region definition in `source/data/reference/` | Openly shared; cite Friedl & Sulla-Menashe (2022) |
| NASA GIBS imagery services | Source of the rendered reference layers and of the mosaics shown in the slides | "We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS)." |
| NASA POWER Daily API | `source/data/ancillary/nasa_power_sudd_2026.json` | Data obtained from the NASA Langley Research Center POWER Project, funded through the NASA Earth Science Directorate Applied Science Program |
| NASA CMR | Catalog snapshot in `source/data/catalog/` | Public metadata |
| OpenStreetMap | Basemap tiles loaded by the app at run time (not stored here) | © OpenStreetMap contributors, ODbL: https://www.openstreetmap.org/copyright |

## Names and marks

NASA, ISRO, NISAR, ESA and Copernicus names are used only to identify data sources. No logos or mission identifiers are used. This project is not endorsed by NASA, ISRO or ESA.
