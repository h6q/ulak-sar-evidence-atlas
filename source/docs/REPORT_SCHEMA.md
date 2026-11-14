# Report schema `ulak-change-v2`

Produced by `analysis/run_sudd.py`, validated by `analysis/report_builder.validate_report` (Python) and `web/lib.js validateReport` (browser). Both validators reject the same violations.

| Field | Type | Rules |
|---|---|---|
| `schema` | string | must equal `ulak-change-v2` |
| `generated_utc` | ISO-8601 Z | |
| `data_status` | `MEASURED` or `SOFTWARE_TEST_SYNTHETIC` | `MEASURED` requires `provenance.{before,after}.pixel_source` ∈ {`https_range_read`, `local_file`} |
| `study_area` | object | `aoi_bbox_wsen` [W, S, E, N] degrees |
| `provenance` | object | `before` and `after`: granule UR, CMR concept, UTC times, HTTPS URL, CMR MD5, dataset paths, HDF5 attributes, window, sha256 of extracted float32 arrays, in-file identification, mask summary |
| `compatibility_checks` | list | items `{id, description, status: PASS/WARN/FAIL/NOT_AVAILABLE, detail, evidence, blocking}`; any blocking FAIL → report rejected |
| `processing` | object | frequency, terms, quantity, conversion, spacing, multilook, CRS, registration (and whether evidenced) |
| `statistics` | object | valid samples, gates, robust stats for ΔHH, ΔHV, ΔR and the four dB layers, class counts and fractions, signed counts |
| `histograms` | object | `delta_hh`, `delta_hv`: bin edges -15..+15 dB (0.5 dB), counts, out-of-range counts |
| `hypotheses` | list | rule, consistent_with, alternatives |
| `geojson` | FeatureCollection | ≤ 1500 Polygon features, coordinates **[lon, lat]** within valid ranges |
| `overlays` | object | PNG file names (pattern `^[A-Za-z0-9_.-]+\.png$`) and Leaflet bounds `[[S, W], [N, E]]` |
| `time_series` | list | per date: AOI median HH/HV dB, zone medians, grid-identity flag, or `error` |
| `ancillary` | object | NASA POWER rain total between the two dates (context) |
| `warnings`, `limitations` | lists of strings | always shown |

Global constraints: standard JSON only (no NaN or Infinity anywhere), at most 5 MB. Strings are rendered with `textContent` only and truncated.
