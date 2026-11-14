"""Dual-polarization L-band backscatter change screening (ULAK "Beneath the Canopy").

AI-assisted implementation; scientific rules below are *heuristic screening
criteria* chosen and owned by the ULAK team. They are NOT a validated flood
classifier and produce no probabilities.

Physical basis (qualitative, literature):
* At L-band, inundation beneath emergent vegetation or forest commonly *raises*
  HH backscatter through a trunk/stem - water "double-bounce" path, while HV
  (volume scattering) changes less. (Hess, Melack & Simonett 1990, Int. J.
  Remote Sensing 11(7); Hess et al. 1995, IEEE TGRS 33(4).)
* Smooth open water is a specular reflector: both HH and HV drop to low values,
  unless wind roughens the surface.
* Vegetation growth / biomass increase tends to raise HV (volume scattering).
None of these responses is unique; soil moisture, rain on the canopy, wind,
burning, harvesting, geometry or calibration can mimic them. Every class is
therefore labelled a *hypothesis* and carries its alternatives.
"""
from __future__ import annotations

import math
import numpy as np

CLASS_STABLE = 0
CLASS_HH_UP_DOUBLE_BOUNCE = 1
CLASS_BOTH_DOWN_SPECULAR = 2
CLASS_HV_UP_VOLUME = 3
CLASS_OTHER_CHANGE = 4
CLASS_INVALID = 255

HYPOTHESES = [
    {"code": CLASS_HH_UP_DOUBLE_BOUNCE, "id": "hh_up_double_bounce",
     "label": "HH increase exceeding HV increase",
     "rule": "dHH >= T_HH and (dHH - dHV) >= R",
     "consistent_with": "New or deeper water beneath emergent vegetation (enhanced double-bounce).",
     "alternatives": ["Wet or flattened vegetation changing stem orientation", "Soil-moisture increase on bare/sparse ground",
                      "Structural change (e.g. new built objects)", "Speckle or residual geolocation error at boundaries"]},
    {"code": CLASS_BOTH_DOWN_SPECULAR, "id": "both_down_specular",
     "label": "HH and HV both decrease",
     "rule": "dHH <= -T_HH and dHV <= -T_HV",
     "consistent_with": "Transition toward smooth open water (specular reflection) or vegetation submergence.",
     "alternatives": ["Vegetation loss by burning, grazing or cutting", "Drying of a previously wet rough surface",
                      "Calm-wind conditions on existing water (wind roughening on the earlier date)", "Calibration offset"]},
    {"code": CLASS_HV_UP_VOLUME, "id": "hv_up_volume",
     "label": "HV increase exceeding HH increase",
     "rule": "dHV >= T_HV and (dHH - dHV) < 0",
     "consistent_with": "Vegetation growth / biomass increase (volume scattering).",
     "alternatives": ["Wind-roughened open water", "Vegetation recovering after flood recession", "Rain-wetted canopy"]},
    {"code": CLASS_OTHER_CHANGE, "id": "other_change",
     "label": "Other large change",
     "rule": "|dHH| >= T_HH or |dHV| >= T_HV, not in the classes above",
     "consistent_with": "Unspecified; requires inspection.",
     "alternatives": ["Any of the processes above", "Data quality issue"]},
]


def to_db(linear: np.ndarray) -> np.ndarray:
    """10*log10 of positive finite linear power; everything else -> NaN."""
    a = np.asarray(linear, dtype="float64")
    out = np.full(a.shape, np.nan)
    ok = np.isfinite(a) & (a > 0)
    out[ok] = 10.0 * np.log10(a[ok])
    return out


def block_mean(linear: np.ndarray, k: int, min_valid_fraction: float = 0.5) -> np.ndarray:
    """Average linear power in non-overlapping k x k blocks (incoherent multilooking).

    Averaging is done in LINEAR power (never in dB). Blocks with fewer than
    `min_valid_fraction` valid samples become NaN. Edge remainders are dropped.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    a = np.asarray(linear, dtype="float64")
    if a.ndim != 2:
        raise ValueError("block_mean expects a 2-D array")
    if k == 1:
        out = a.copy()
        out[~(np.isfinite(out) & (out > 0))] = np.nan
        return out
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    if h == 0 or w == 0:
        raise ValueError("Array smaller than one multilook block")
    a = a[:h, :w]
    ok = np.isfinite(a) & (a > 0)
    s = np.where(ok, a, 0.0).reshape(h // k, k, w // k, k).sum(axis=(1, 3))
    n = ok.reshape(h // k, k, w // k, k).sum(axis=(1, 3))
    out = np.full(s.shape, np.nan)
    good = n >= max(1, int(math.ceil(min_valid_fraction * k * k)))
    out[good] = s[good] / n[good]
    return out


def robust_stats(values: np.ndarray) -> dict:
    v = np.asarray(values, dtype="float64")
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0}
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return {"n": int(v.size), "median": med, "robust_sigma": 1.4826 * mad,
            "p05": float(np.percentile(v, 5)), "p25": float(np.percentile(v, 25)),
            "p75": float(np.percentile(v, 75)), "p95": float(np.percentile(v, 95)),
            "mean": float(np.mean(v)), "min": float(np.min(v)), "max": float(np.max(v))}


def gate(delta: np.ndarray, floor_db: float, sigma: float) -> float:
    st = robust_stats(delta)
    if st["n"] == 0:
        raise ValueError("No valid differences")
    return max(float(floor_db), float(sigma) * st["robust_sigma"])


def classify(d_hh, d_hv, valid, t_hh: float, t_hv: float, ratio_db: float) -> np.ndarray:
    """Apply the screening rules (see HYPOTHESES) to dB differences. Pure function, reused for sensitivity runs."""
    d_ratio = d_hh - d_hv
    cls = np.full(d_hh.shape, CLASS_INVALID, dtype="uint8")
    cls[valid] = CLASS_STABLE
    with np.errstate(invalid="ignore"):
        c1 = valid & (d_hh >= t_hh) & (d_ratio >= ratio_db)
        c2 = valid & (d_hh <= -t_hh) & (d_hv <= -t_hv)
        c3 = valid & (d_hv >= t_hv) & (d_ratio < 0) & ~c1
        big = valid & ((np.abs(d_hh) >= t_hh) | (np.abs(d_hv) >= t_hv))
        c4 = big & ~(c1 | c2 | c3)
    cls[c4] = CLASS_OTHER_CHANGE
    cls[c3] = CLASS_HV_UP_VOLUME
    cls[c2] = CLASS_BOTH_DOWN_SPECULAR
    cls[c1] = CLASS_HH_UP_DOUBLE_BOUNCE
    return cls


def class_counts(cls: np.ndarray) -> dict:
    counts = {h["id"]: int((cls == h["code"]).sum()) for h in HYPOTHESES}
    counts["stable"] = int((cls == CLASS_STABLE).sum())
    return counts


def dual_pol_change(hh0, hv0, hh1, hv1, *, floor_db: float = 3.0, sigma: float = 3.0,
                    ratio_db: float = 2.0, min_valid: int = 10) -> dict:
    """Screen co-registered linear-power HH/HV pairs for change hypotheses.

    Inputs must be on the SAME grid (caller verifies). Returns arrays (dB) and a
    stats dict. No median-shift correction is applied: a scene-wide offset is
    reported (and warned about) rather than silently removed.
    """
    arrs = [np.asarray(a, dtype="float64") for a in (hh0, hv0, hh1, hv1)]
    shape = arrs[0].shape
    if any(a.shape != shape for a in arrs) or len(shape) != 2:
        raise ValueError("All four inputs must be aligned 2-D arrays with identical shape")
    for p in (floor_db, sigma, ratio_db):
        if not (isinstance(p, (int, float)) and math.isfinite(p) and p > 0):
            raise ValueError("floor_db, sigma and ratio_db must be finite positive numbers")
    db = [to_db(a) for a in arrs]
    valid = np.all([np.isfinite(d) for d in db], axis=0)
    n = int(valid.sum())
    if n < min_valid:
        raise ValueError(f"Too few valid paired pixels ({n}) for a meaningful comparison (need >= {min_valid}).")
    d_hh = np.where(valid, db[2] - db[0], np.nan)
    d_hv = np.where(valid, db[3] - db[1], np.nan)
    d_ratio = d_hh - d_hv
    t_hh = gate(d_hh[valid], floor_db, sigma)
    t_hv = gate(d_hv[valid], floor_db, sigma)
    cls = classify(d_hh, d_hv, valid, t_hh, t_hv, ratio_db)
    counts = class_counts(cls)
    with np.errstate(invalid="ignore"):
        signed = {
            "hh_increase_pixels": int((valid & (d_hh >= t_hh)).sum()),
            "hh_decrease_pixels": int((valid & (d_hh <= -t_hh)).sum()),
            "hv_increase_pixels": int((valid & (d_hv >= t_hv)).sum()),
            "hv_decrease_pixels": int((valid & (d_hv <= -t_hv)).sum()),
        }
    stats = {
        "valid_pixels": n,
        "thresholds_db": {"T_HH": t_hh, "T_HV": t_hv, "R_ratio": float(ratio_db),
                          "floor_db": float(floor_db), "sigma_multiplier": float(sigma)},
        "delta_hh_db": robust_stats(d_hh[valid]), "delta_hv_db": robust_stats(d_hv[valid]),
        "delta_hh_minus_hv_db": robust_stats(d_ratio[valid]),
        "before_hh_db": robust_stats(db[0][valid]), "before_hv_db": robust_stats(db[1][valid]),
        "after_hh_db": robust_stats(db[2][valid]), "after_hv_db": robust_stats(db[3][valid]),
        "class_counts": counts,
        "class_fractions": {k: v / n for k, v in counts.items()},
        "signed_counts": signed,
        "method": ("Paired L-band gamma0 differences in dB on a common grid after incoherent multilooking; "
                   "per-channel gate T = max(floor_db, sigma * 1.4826 * MAD); no median-shift correction."),
    }
    return {"d_hh": d_hh, "d_hv": d_hv, "d_ratio": d_ratio, "classes": cls, "valid": valid,
            "db": {"hh0": db[0], "hv0": db[1], "hh1": db[2], "hv1": db[3]}, "stats": stats}


def scene_shift_warning(stats: dict, limit_db: float = 1.0) -> str | None:
    """Warn when the median change is large: possible calibration/moisture/geometry effect."""
    m_hh = stats["delta_hh_db"].get("median", 0.0)
    m_hv = stats["delta_hv_db"].get("median", 0.0)
    if abs(m_hh) >= limit_db or abs(m_hv) >= limit_db:
        return (f"Scene-wide median change is large (dHH={m_hh:+.2f} dB, dHV={m_hv:+.2f} dB). This may reflect a real "
                "widespread change (e.g. seasonal inundation or vegetation growth) OR a radiometric/geometry/moisture "
                "effect; no correction was applied.")
    return None


def diagnostics(res: dict, *, tiles: int = 4, pixel_area_m2: float | None = None) -> dict:
    """Audit diagnostics for a dual_pol_change result: where does the scene-wide shift come from,
    and how sensitive are the candidate counts to the gate choice? Descriptive only."""
    d_hh, d_hv, valid = res["d_hh"], res["d_hv"], res["valid"]
    st = res["stats"]
    t = st["thresholds_db"]
    h, w = d_hh.shape
    tile_rows = []
    for i in range(tiles):
        row = []
        for j in range(tiles):
            sl = (slice(i * h // tiles, (i + 1) * h // tiles), slice(j * w // tiles, (j + 1) * w // tiles))
            v = valid[sl]
            row.append({"median_dhh_db": float(np.median(d_hh[sl][v])) if v.any() else None,
                        "median_dhv_db": float(np.median(d_hv[sl][v])) if v.any() else None, "n": int(v.sum())})
        tile_rows.append(row)
    tm_hh = [c["median_dhh_db"] for r in tile_rows for c in r if c["median_dhh_db"] is not None]
    tm_hv = [c["median_dhv_db"] for r in tile_rows for c in r if c["median_dhv_db"] is not None]
    hh0 = res["db"]["hh0"]
    qs = np.percentile(hh0[valid], [25, 50, 75])
    edges = [-np.inf, *qs, np.inf]
    strata = []
    for k in range(4):
        m = valid & (hh0 >= edges[k]) & (hh0 < edges[k + 1])
        strata.append({"before_hh_db_range": [None if not np.isfinite(edges[k]) else float(edges[k]),
                                              None if not np.isfinite(edges[k + 1]) else float(edges[k + 1])],
                       "n": int(m.sum()), "median_dhh_db": float(np.median(d_hh[m])), "median_dhv_db": float(np.median(d_hv[m]))})
    dark = valid & (res["db"]["hh0"] < -15) & (res["db"]["hh1"] < -15)
    med_hh, med_hv = st["delta_hh_db"]["median"], st["delta_hv_db"]["median"]
    sens = {
        "as_reported": {"description": "gates centred on 0 dB (no shift correction)", "T_HH": t["T_HH"], "T_HV": t["T_HV"],
                        "counts": st["class_counts"]},
        "median_centred": {"description": "differences re-centred on the scene median before gating (assumes the median shift is NOT a real change)",
                           "T_HH": t["T_HH"], "T_HV": t["T_HV"],
                           "counts": class_counts(classify(d_hh - med_hh, d_hv - med_hv, valid, t["T_HH"], t["T_HV"], t["R_ratio"]))},
        "floor_only_3db": {"description": "fixed 3 dB gates, no shift correction", "T_HH": 3.0, "T_HV": 3.0,
                           "counts": class_counts(classify(d_hh, d_hv, valid, 3.0, 3.0, t["R_ratio"]))},
    }
    for v in sens.values():
        n = sum(c for k, c in v["counts"].items() if k != "stable")
        v["candidates"] = n
        v["candidate_fraction"] = n / st["valid_pixels"]
        if pixel_area_m2:
            v["candidate_area_km2"] = n * pixel_area_m2 / 1e6
    return {
        "scene_shift": {"median_dhh_db": med_hh, "median_dhv_db": med_hv,
                        "fraction_dhh_positive": float((d_hh[valid] > 0).mean()),
                        "fraction_dhv_positive": float((d_hv[valid] > 0).mean()),
                        "tile_grid": f"{tiles}x{tiles}", "tile_medians": tile_rows,
                        "tile_median_dhh_range_db": [min(tm_hh), max(tm_hh)], "tile_median_dhv_range_db": [min(tm_hv), max(tm_hv)],
                        "strata_by_before_hh_quartile": strata,
                        "persistently_dark_pixels": {"rule": "HH < -15 dB on both dates", "n": int(dark.sum()),
                                                     "median_dhh_db": float(np.median(d_hh[dark])) if dark.sum() >= 10 else None,
                                                     "median_dhv_db": float(np.median(d_hv[dark])) if dark.sum() >= 10 else None}},
        "threshold_sensitivity": sens,
        "interpretation_note": ("A positive median shift that appears in every tile and stratum cannot be separated, with two dates "
                                "and no stable reference targets, into real widespread change (wetter soils, vegetation water content, "
                                "inundation), acquisition conditions, or a residual radiometric offset between PROVISIONAL products."),
    }
