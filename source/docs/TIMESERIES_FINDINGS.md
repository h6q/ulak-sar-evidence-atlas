# QC-screened temporal findings: central Sudd, 20 Jun–18 Oct 2026

**Evidence level:** measured NISAR backscatter with independent-sensor context. These results do not establish flooding, vegetation growth, or causality.

## Analysis population and QC

| Item | Result |
|---|---|
| NISAR acquisitions ingested | 10 (stack 086_A_005, CRID P05023) |
| Primary temporal dates | 9 HH dates; 8 HV dates |
| Explicit exceptions | 24 Sep is HH-only; 6 Oct fails QC and is excluded from primary inference; 7 Aug was not acquired during the documented instrument gap |
| Common support | 195,538 cells at 100 m = 1,955.38 km² |
| Grid | 444 × 444, EPSG:32636, identical registration and radiometric convention |
| Input integrity | cache arrays, shapes and SHA-256 values verified before analysis |

The primary gate is **INFORMATIVE**: the series is long enough to describe structured change, but not to identify a unique physical cause.

## What changed

The wetland corridor and adjacent savanna margins diverged after removing the AOI-wide common mode. By 18 October:

| Relative change from first date | Wetland corridor | East margin |
|---|---:|---:|
| HH | −0.91 dB, 95% block-bootstrap CI [−0.98, −0.83] | +0.74 dB [ +0.35, +1.10 ] |
| HV | −1.10 dB [−1.20, −0.97] | +0.89 dB [ +0.60, +1.33 ] |

First-to-last region contrasts agree with that spatial structure. Corridor minus east is −1.65 dB in HH (CI [−2.02, −1.25]) and −2.00 dB in HV (CI [−2.47, −1.68]). The corridor-minus-west and corridor-minus-east HV−HH contrasts are also negative. West-minus-east uncertainty overlaps zero for several metrics, so the evidence supports a corridor-versus-margin contrast more strongly than a consistent east-versus-west ordering.

The raw regional series are not monotonic. They rise and fall, with prominent fluctuations around 19 August and 12 September. This is evidence against describing the season as one smooth transition.

## Persistence is rare

Strict persistence requires a cell to exceed 3 dB in both its raw and AOI-normalised histories, not merely on one date.

| Channel | Persistent cells | Fraction of common support |
|---|---:|---:|
| HH | 211 / 195,538 | 0.1079% |
| HV | 193 / 195,538 | 0.0987% |

This reconciles the temporal result with the audited two-date baseline: many pair candidates are episodic or common-mode-sensitive rather than consistently persistent throughout the season.

## Independent-sensor context

Eight NISAR dates have a nearby OPERA DSWx-S1 rendering, usually one day earlier. The 20 June baseline has no matched DSWx-S1 acquisition and is not fabricated or interpolated.

* First-to-last spatial association is near zero: Spearman ρ = −0.0027 for ΔHH versus Δwater and −0.0200 for ΔHV versus Δwater.
* Across 491 cells with variable DSWx water histories, the median temporal correlation is 0.233 (permutation p = 0.157).
* Seventy-one cells have |ρ| ≥ 0.7 versus a null mean of 27.9 (count p = 0.032). Spatial dependence and multiple testing mean this count is a screening signal, not a confirmation map.
* Rule-consistency labels contain 71 “water-linked”, 15 “vegetation-consistent” and 1,514 “unresolved” cells. These are descriptive labels, not causal classes.

OPERA DSWx-S1/HLS products in this repository are exact-palette decodes of NASA GIBS renderings. They are independent sensor context, not original GeoTIFF science products or field truth. HLS optical observations also cannot see water beneath a closed canopy.

## Stratified by an independent radar classification (verified 2026-11-14)

Cells are grouped by the OPERA DSWx-S1 class they hold on **all eight** matched dates (class fraction ≥ 0.5 for inundated vegetation or open water; water fraction ≤ 0.05 for not-water). Group membership is fixed, so composition does not change through time. Values are the median first-to-last change (20 Jun → 18 Oct) of 0.01° cell means, with 95% spatial block-bootstrap intervals from `timeseries_results.json` → `dswx_strata`.

| DSWx-S1 group | Cells | 20 Jun HH level | ΔHH | ΔHV |
|---|---:|---:|---:|---:|
| Inundated vegetation | 155 | −11.2 dB | **+2.10 dB** [1.99, 2.37] | +1.24 dB [1.08, 1.62] |
| Open water | 48 | −14.0 dB | +0.65 dB [0.21, 0.88] | −0.13 dB [−0.62, 0.31] |
| Not water | 259 | −6.6 dB | +0.44 dB [0.38, 0.50] | +0.18 dB [0.04, 0.26] |

`analysis/verify_findings.py` recomputes these from the raw cache and reference text files without importing the analysis modules: +2.09, +0.67 and +0.44 dB (agreement within 0.02 dB). The inundated-vegetation minus not-water difference is +1.65 dB [1.52, 1.90]; with a coarser 3 × 3-cell block bootstrap the interval is [1.42, 2.30].

**Baseline-matched check.** Cells that start darker tend to brighten more, so the groups were also compared within the same 20 June HH level. The contrast remains: −13 to −11 dB: +2.35 vs +1.38 dB; −11 to −9 dB: +2.31 vs +0.64 dB; −9 to −7 dB: +2.00 vs +0.99 dB (inundated-vegetation group vs all other non-open-water cells).

**Where.** Among cells with ≥ 80% stable savanna, ΔHH is −0.03 dB at the corridor centreline, peaks at +2.77 dB [2.40, 2.98] 10–14 km west and +2.98 dB [2.57, 3.19] 14–18 km east, and falls again beyond (`distance_profile`).

**Limits that must travel with these numbers.**
* DSWx-S1 is a Sentinel-1 C-band classification whose inundated-vegetation class is derived from the dual-polarisation ratio together with a wetland land-cover mask. It is a different sensor and algorithm, not field truth, and it was read here as a NASA GIBS rendering. Agreement between two radar products is an association, not validated flooding.
* HV rose too in the inundated-vegetation group, so vegetation growth or a rain-wet canopy cannot be separated from a water effect.
* 125 of the 155 inundated-vegetation cells lie in the MODIS west-margin region (one spatial cluster); the eastern brightening peak is **not** mapped as inundated vegetation by DSWx-S1 (2 cells).
* The 20 June baseline has no matched DSWx-S1 date; classes describe 1 July–17 October.
* The first-to-last *change* in DSWx-S1 water fraction is uncorrelated with ΔHH (ρ = −0.003): DSWx-S1 says these cells were already inundated in July, so this is brightening within a class, not newly mapped water.

## Interpretation boundary

The defensible conclusion is that the 2026 NISAR series contains a repeatable spatial contrast: the permanent-wetland corridor becomes relatively darker than the AOI common mode while adjacent margins, especially the east margin, become relatively brighter. The response fluctuates and strict persistence is rare. Possible contributors include changing inundation geometry, vegetation volume, canopy wetness, wind-roughened water, soil moisture, incidence-angle effects and residual radiometric variation.

The analysis does **not** support the statements “the Sudd flooded by X km²”, “vegetation grew by X%”, or “NISAR detected water under vegetation with known accuracy.” Those claims require gauge, field or original validated reference data.

## Reproducible outputs

* Results: `data/derived/timeseries/timeseries_results.json`
* Web payload: `web/data/timeseries.json`
* Figures and animation: `data/derived/timeseries/figures/`
* Web temporal tiles: `web/data/ts/`
* Reference provenance: `data/reference/reference_provenance.json`
* Analysis entry point: `analysis/timeseries.py`
* Reference verifier: `analysis/fetch_reference.py`

Uncertainty uses 2 × 2-cell spatial block bootstrap (about 2.2 km blocks, 2,000 replicates). Rain associations are descriptive, use only one NASA POWER point, and are not causal tests.
