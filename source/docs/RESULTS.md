# Measured results: central Sudd, NISAR GCOV, 20 Jun 2026 → 18 Oct 2026

**Status: MEASURED from real NISAR pixels, independently re-computed (21/21 audit checks, `docs/AUDIT_REPORT.md`).**
These are *candidate radar backscatter changes*. Nothing here is confirmed flooding.
Every number below is copied from `web/data/sudd_report.json` (v0.3.2) or `data/audit/audit_results.json`.

The pair result below is the audited baseline. The completed QC-screened temporal analysis is reported separately in `docs/TIMESERIES_FINDINGS.md`: nine primary dates show a corridor-versus-margin pattern, but strict >3 dB persistence covers only 0.108% of common cells in HH and 0.099% in HV.

## Data
| Item | Value |
|---|---|
| Before | `NISAR_L2_PR_GCOV_023_086_A_005_2005_DHDH_A_20260620T033436_20260620T033510_P05023_N_F_J_001` (CMR G4244913851-ASF), 2026-06-20 03:34:36 UTC |
| After | `NISAR_L2_PR_GCOV_033_086_A_005_2005_DHDH_A_20261018T033432_20261018T033507_P05023_N_F_J_001` (CMR G4379033365-ASF), 2026-10-18 03:34:32 UTC |
| Collection | NISAR_L2_GCOV_PROVISIONAL_V1 (C2854338529-ASF), DOI 10.5067/NIL2GCOV-P1, CRID P05023, product version 1.0.11 |
| Access | HTTPS range reads of the AOI window only (rows 5324-7548, cols 8874-11094 of frequency A), team PC, 14 Nov 2026; about 70 s per date |
| Layers | `/science/LSAR/GCOV/grids/frequencyA/HHHH` and `HVHV`: γ⁰, linear power, units attribute "1" |
| Grid | EPSG:32636, 20 m posting, 2224 × 2220 px. The identical grid on both dates was verified, so there is no resampling |
| Analysis | 5 × 5 linear-power multilook → 100 m. **197,136 valid pixels = 1,971.4 km²**. Mask = 1 (valid) everywhere |
| Checks | 22 compatibility checks: 21 PASS, 1 WARN (PROVISIONAL maturity) |

## Backscatter levels (AOI medians)
| | 20 Jun | 18 Oct | Change |
|---|---|---|---|
| HH (dB) | −7.82 | −6.62 | **+1.08** (robust σ 1.64) |
| HV (dB) | −17.00 | −15.84 | **+0.50** (robust σ 1.53) |

77.9% of pixels are brighter in HH, and 64.1% are brighter in HV.

## Scene-wide shift: what it is and is not
* **It is spatially variable.** Medians over 16 tiles (about 11 km each) range from +0.37 to +2.47 dB (ΔHH) and from −0.49 to +1.83 dB (ΔHV).
* **It depends on the 20 June brightness.** By quartile of 20 June HH:
  * darkest quartile: ΔHH +1.59 dB (ΔHV +0.67);
  * second quartile: ΔHH +1.42 dB;
  * third quartile: ΔHH +0.80 dB;
  * brightest quartile: ΔHH +0.62 dB (ΔHV +0.15).
* **Persistently dark pixels** (HH < −15 dB on both dates, n = 13,673, likely open water) show ΔHH +1.24 dB. Open-water backscatter depends strongly on wind, so these are not a stable reference.
* **Calibration context:** a NISAR calibration presentation (Fringe 2026) reports residuals within ±0.25 dB over an Amazon reference target, against a radiometric accuracy requirement of about 1 dB. A +1 dB median is therefore of the same order as the requirement.
* **Conclusion:** the spatial and brightness-dependent structure indicates more than a uniform offset. However, with two dates and no stable reference targets, **a uniform radiometric component cannot be excluded or quantified**. The shift is reported, not corrected.

## Candidate changes (heuristic gates; see `docs/METHODOLOGY.md`)
| Class (100 m pixels) | As reported (T_HH 4.92, T_HV 4.59 dB) | Shift removed (median re-centred) | Fixed 3 dB gates |
|---|---|---|---|
| HV up more than HH (volume / growth hypothesis) | **7,495** | **5,980** | 15,594 |
| HH up more than HV (double-bounce hypothesis) | 1,012 | 135 | 7,094 |
| HH and HV down (specular / open-water hypothesis) | 672 | 1,158 | 1,865 |
| Other large change | 3,141 | 1,371 | 17,341 |
| **All candidates** | **12,320 (6.25%, 123.2 km²)** | 8,644 (4.38%, 86.4 km²) | 41,894 (21.25%) |

**Robust finding.** HV-dominant increases remain the largest class under both gate centrings: 7,495 pixels as reported, 5,980 with the shift removed, about 3.0-3.8% of the AOI. They are consistent with an increase in volume scattering (for example vegetation growth over the wet season), but other causes are possible: wind-roughened water, regrowth after flooding, or a rain-wetted canopy.

**Not robust.** HH-dominant "double-bounce" candidates drop from 1,012 to 135 when the median shift is removed. With the shift removed, HH decreases (1,419) outnumber HH increases (709). **We therefore make no claim of newly flooded vegetation from this pair.**

**Gate choice matters.** Fixed 3 dB gates would flag 21% of the AOI. The adaptive gates (3 × robust σ) are what we report.

## Spatial pattern (visual reading of the app maps, `docs/media/app_hypotheses_cells.png`)
* 182 one-kilometre candidate cells: 125 HV-dominant, 40 other, 10 HH-dominant, 7 HH-and-HV-down.
* The cells cluster in bands on the plains **east and west** of the main Bahr el Jebel swamp corridor. Few cells fall inside the corridor that OpenStreetMap maps as wetland.
* In the ΔHH map, the swamp corridor appears near-unchanged or slightly darker, and the largest HH increases lie on the surrounding plains.

## Context (not validation)
* NASA POWER: 459 mm of precipitation between the two dates at 30.75° E, 7.25° N. Cloud cover was ≥ 50% on 74 of 91 days (1 Jun-30 Aug).
* **No independent inundation reference was compared.** Sudd inundation is driven mainly by White Nile inflow.

## What we can and cannot say
* ✅ L-band backscatter over the central Sudd AOI was higher on 18 Oct than on 20 Jun 2026 over most of the area, by a spatially variable amount.
* ✅ The most robust localized change is an HV-dominant increase on the plains flanking the permanent swamp.
* ❌ We cannot say any area was flooded, newly inundated beneath vegetation, or damaged.
* ❌ We cannot attribute the scene-wide shift to a single cause.
* ✅ The 10 acquisitions were processed. After QC, the observed changes fluctuate through the season rather than forming one gradual monotonic transition; strict persistent change is rare. See `docs/TIMESERIES_FINDINGS.md`.
