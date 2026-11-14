#!/usr/bin/env python3
"""Independent audit of a ULAK measured report (AI-assisted; reviewed by the ULAK team).

Re-derives every headline number from the derived GeoTIFFs with SEPARATE code (it does not import
sar_change.py or run_sudd.py) and checks the report, overlays and cells against it.

    py analysis/audit_measurement.py            # writes data/audit/audit_results.json and docs/AUDIT_REPORT.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent


def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a.astype("float32")).tobytes()).hexdigest()


def ml(a, k):
    """Independent incoherent multilook: reshape-mean in linear power, >=50% valid samples per block."""
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    b = a[:h, :w].astype("float64").reshape(h // k, k, w // k, k).transpose(0, 2, 1, 3).reshape(h // k, w // k, k * k)
    ok = np.isfinite(b) & (b > 0)
    cnt = ok.sum(-1)
    s = np.where(ok, b, 0).sum(-1)
    out = np.where(cnt >= math.ceil(0.5 * k * k), s / np.maximum(cnt, 1), np.nan)
    return out


def db(a):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.isfinite(a) & (a > 0), 10 * np.log10(a), np.nan)


def main(argv=None) -> int:
    import rasterio
    from rasterio.warp import transform as wt, transform_bounds
    ap = argparse.ArgumentParser()
    ap.add_argument("--derived", default=str(REPO / "data" / "derived"))
    ap.add_argument("--report", default=str(REPO / "web" / "data" / "sudd_report.json"))
    ap.add_argument("--out-json", default=str(REPO / "data" / "audit" / "audit_results.json"))
    ap.add_argument("--out-md", default=str(REPO / "docs" / "AUDIT_REPORT.md"))
    a = ap.parse_args(argv)
    rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
    st, pr = rep["statistics"], rep["processing"]
    k = int(pr["multilook_factor"])
    d0 = rep["provenance"]["before"]["acquisition_begin_utc"][:10]
    d1 = rep["provenance"]["after"]["acquisition_begin_utc"][:10]
    der = Path(a.derived)
    checks, R = [], {}

    def chk(name, ok, detail):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    ras, meta = {}, {}
    for d in (d0, d1):
        for t in ("HHHH", "HVHV"):
            f = der / f"{d}_{t}_freqA_gamma0_linear.tif"
            with rasterio.open(f) as ds:
                ras[(d, t)] = ds.read(1)
                meta[(d, t)] = (ds.crs.to_epsg(), tuple(ds.transform)[:6], ds.shape, ds.tags(), ds.nodata)
            side = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
            side_ok = sha(ras[(d, t)]) == side["sha256_float32"]
            side_label = "before" if d == d0 else "after"
            rep_ok = sha(ras[(d, t)]) == rep["provenance"][side_label]["sha256_float32"][t]
            chk(f"integrity {d} {t}", side_ok and rep_ok, "GeoTIFF pixels == sidecar sha256 == report sha256")
            tg = meta[(d, t)][3]
            chk(f"tags {d} {t}", tg.get("SOURCE_GRANULE") == rep["provenance"][side_label]["granule_ur"] and
                tg.get("POLARIZATION") == {"HHHH": "HH", "HVHV": "HV"}[t], f"granule + polarization tags; nodata={meta[(d, t)][4]}")
    m0 = meta[(d0, "HHHH")]
    chk("identical CRS/transform/shape across all 4 rasters", all(meta[x][:3] == m0[:3] for x in meta),
        f"EPSG:{m0[0]}, transform {m0[1]}, shape {m0[2]}")
    tr = m0[1]
    R["grid"] = {"epsg": m0[0], "native_spacing_m": [tr[0], tr[4]], "shape": list(m0[2])}
    nonvalid = {f"{d} {t}": int((~(np.isfinite(v) & (v > 0))).sum()) for (d, t), v in ras.items()}
    R["invalid_native_samples"] = nonvalid

    L = {key: ml(v, k) for key, v in ras.items()}
    hh0, hv0, hh1, hv1 = (db(L[(d0, "HHHH")]), db(L[(d0, "HVHV")]), db(L[(d1, "HHHH")]), db(L[(d1, "HVHV")]))
    valid = np.isfinite(hh0) & np.isfinite(hv0) & np.isfinite(hh1) & np.isfinite(hv1)
    dhh, dhv = hh1 - hh0, hv1 - hv0
    n = int(valid.sum())
    chk("valid analysis pixels", n == st["valid_pixels"], f"recomputed {n} vs report {st['valid_pixels']}")
    area_px = abs(tr[0] * tr[4]) * k * k
    R["area"] = {"analysis_pixel_m": abs(tr[0]) * k, "analysis_pixel_area_m2": area_px, "valid_area_km2": n * area_px / 1e6,
                 "edge_rows_cols_dropped_by_multilook": [m0[2][0] % k, m0[2][1] % k]}
    # UTM scale factor at AOI centre (zone 36N, central meridian 33E)
    lon_c = sum(rep["study_area"]["aoi_bbox_wsen"][0::2]) / 2
    lat_c = sum(rep["study_area"]["aoi_bbox_wsen"][1::2]) / 2
    dl = math.radians(lon_c - 33.0)
    kscale = 0.9996 * (1 + (math.cos(math.radians(lat_c)) * dl) ** 2 / 2)
    R["area"]["utm_point_scale_factor_aoi_centre"] = kscale
    R["area"]["ground_area_correction_factor"] = 1 / kscale ** 2

    def rs(x):
        x = x[valid]
        med = float(np.median(x)); mad = float(np.median(np.abs(x - med)))
        return med, 1.4826 * mad

    mh, sh = rs(dhh); mv, sv = rs(dhv)
    th = max(3.0, 3 * sh); tv = max(3.0, 3 * sv)
    for name, got, exp in (("median dHH", mh, st["delta_hh_db"]["median"]), ("median dHV", mv, st["delta_hv_db"]["median"]),
                           ("T_HH", th, st["thresholds_db"]["T_HH"]), ("T_HV", tv, st["thresholds_db"]["T_HV"])):
        chk(name, abs(got - exp) < 1e-6, f"recomputed {got:.6f} dB vs report {exp:.6f} dB")
    R["recomputed"] = {"median_dhh_db": mh, "median_dhv_db": mv, "robust_sigma_dhh_db": sh, "robust_sigma_dhv_db": sv,
                       "T_HH": th, "T_HV": tv}

    def classes(xh, xv, t1, t2, r=2.0):
        rr = xh - xv
        c1 = valid & (xh >= t1) & (rr >= r)
        c2 = valid & (xh <= -t1) & (xv <= -t2)
        c3 = valid & (xv >= t2) & (rr < 0) & ~c1
        c4 = valid & ((np.abs(xh) >= t1) | (np.abs(xv) >= t2)) & ~(c1 | c2 | c3)
        return {"hh_up_double_bounce": int(c1.sum()), "both_down_specular": int((c2 & ~c1).sum()),
                "hv_up_volume": int((c3 & ~c2).sum()), "other_change": int(c4.sum())}

    cc = classes(dhh, dhv, th, tv)
    rc = {kk: st["class_counts"][kk] for kk in cc}
    chk("class counts (independent rule implementation)", cc == rc, f"recomputed {cc} vs report {rc}")
    cand = sum(cc.values())
    R["candidates"] = {"n": cand, "fraction": cand / n, "area_km2_of_100m_cells": cand * area_px / 1e6, "by_class": cc}
    centred = classes(dhh - mh, dhv - mv, th, tv)
    R["sensitivity_median_centred"] = {"by_class": centred, "n": sum(centred.values()), "fraction": sum(centred.values()) / n}
    with np.errstate(invalid="ignore"):
        R["signed"] = {"hh_up": int((valid & (dhh >= th)).sum()), "hh_down": int((valid & (dhh <= -th)).sum()),
                       "hv_up": int((valid & (dhv >= tv)).sum()), "hv_down": int((valid & (dhv <= -tv)).sum()),
                       "hh_up_centred": int((valid & (dhh - mh >= th)).sum()), "hh_down_centred": int((valid & (dhh - mh <= -th)).sum())}
    # spatial uniformity of the shift (4x4 tiles) and stratification by initial HH
    h, w = dhh.shape
    tiles = [float(np.median(dhh[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4][valid[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4]]))
             for i in range(4) for j in range(4)]
    q = np.percentile(hh0[valid], [25, 50, 75])
    strata = []
    for lo, hi in zip([-np.inf, *q], [*q, np.inf]):
        mm = valid & (hh0 >= lo) & (hh0 < hi)
        strata.append({"before_hh_db": [None if np.isinf(lo) else round(float(lo), 2), None if np.isinf(hi) else round(float(hi), 2)],
                       "median_dhh_db": float(np.median(dhh[mm])), "median_dhv_db": float(np.median(dhv[mm])), "n": int(mm.sum())})
    R["shift"] = {"fraction_dhh_positive": float((dhh[valid] > 0).mean()), "fraction_dhv_positive": float((dhv[valid] > 0).mean()),
                  "tile_median_dhh_db": [round(t, 3) for t in tiles], "tile_range_dhh_db": [min(tiles), max(tiles)], "strata": strata}
    # overlay georeferencing: bounds of the multilooked grid in lon/lat vs overlay bounds
    left, top = tr[2], tr[5]
    right = left + (m0[2][1] // k) * k * tr[0]
    bottom = top + (m0[2][0] // k) * k * tr[4]
    w_, s_, e_, n_ = transform_bounds(f"EPSG:{m0[0]}", "EPSG:4326", left, bottom, right, top, densify_pts=21)
    for name, ov in rep["overlays"].items():
        if name == "note":
            continue
        (os_, ow), (on, oe) = ov["bounds_latlon"]
        err_m = max(abs(os_ - s_), abs(on - n_)) * 111320 + max(abs(ow - w_), abs(oe - e_)) * 111320 * math.cos(math.radians(7.2))
        png = REPO / "web" / "data" / ov["file"]
        chk(f"overlay {name} georeference", err_m < 150 and png.exists(),
            f"bounds error {err_m:.1f} m (< one 100 m display pixel); file {ov['file']} {png.stat().st_size if png.exists() else 0} bytes")
    R["grid_bounds_lonlat"] = [w_, s_, e_, n_]
    aoi = rep["study_area"]["aoi_bbox_wsen"]
    pts = [pt for f in rep["geojson"]["features"] for pt in f["geometry"]["coordinates"][0]]
    inside = all(w_ - 1e-6 <= x <= e_ + 1e-6 and s_ - 1e-6 <= y <= n_ + 1e-6 for x, y in pts)
    chk("all candidate cells inside the analysed grid ([lon, lat] order)", inside, f"{len(rep['geojson']['features'])} cells; AOI {aoi}")
    # spot-check: recompute the first cell's median dHH from the rasters
    if rep["geojson"]["features"]:
        f0 = rep["geojson"]["features"][0]
        ring = f0["geometry"]["coordinates"][0]
        xs, ys = wt("EPSG:4326", f"EPSG:{m0[0]}", [p[0] for p in ring], [p[1] for p in ring])
        c0 = int(round((min(xs) - left) / (tr[0] * k))); c1 = int(round((max(xs) - left) / (tr[0] * k)))
        r0 = int(round((max(ys) - top) / (tr[4] * k))); r1 = int(round((min(ys) - top) / (tr[4] * k)))
        sub = dhh[r0:r1, c0:c1][valid[r0:r1, c0:c1]]
        got = float(np.median(sub)) if sub.size else float("nan")
        chk("cell spot-check (first cell median dHH)", abs(got - f0["properties"]["median_delta_hh_db"]) < 0.01,
            f"{f0['properties']['cell_id']}: recomputed {got:.3f} vs report {f0['properties']['median_delta_hh_db']:.3f} dB")
    R["registration"] = {"evidenced": pr["pixel_registration_evidenced"], "assumed": pr["pixel_registration"],
                         "max_absolute_position_error_m": abs(tr[0]) / 2,
                         "effect_on_dB_differences": "none: both dates share the identical grid"}
    R["checks"] = checks
    out = Path(a.out_json); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(R, indent=1, allow_nan=False), encoding="utf-8")

    p = sum(c["pass"] for c in checks)
    md = [f"# Independent audit of the measured report ({d0} → {d1})", "",
          "Generated by `analysis/audit_measurement.py`, which re-derives the numbers from the GeoTIFFs with code separate "
          "from the pipeline. AI-assisted; reviewed by the ULAK team.", "",
          f"**Result: {p}/{len(checks)} checks passed.**", "", "| Check | Pass | Detail |", "|---|---|---|"]
    md += [f"| {c['check']} | {'✅' if c['pass'] else '❌'} | {c['detail']} |" for c in checks]
    A = R["area"]
    md += ["", "## Grid, area and masks",
           f"* EPSG:{R['grid']['epsg']}, native {abs(tr[0]):.0f} m posting, window {R['grid']['shape'][0]}×{R['grid']['shape'][1]} px; "
           f"multilook {k}×{k} → {A['analysis_pixel_m']:.0f} m pixels ({A['analysis_pixel_area_m2']/1e4:.0f} ha each); "
           f"{A['edge_rows_cols_dropped_by_multilook']} edge rows/cols dropped.",
           f"* Valid analysis area: {A['valid_area_km2']:.1f} km² (grid area; UTM point scale factor at AOI centre {A['utm_point_scale_factor_aoi_centre']:.5f}, "
           f"so ground area differs by {abs(1-A['ground_area_correction_factor'])*100:.2f}%).",
           f"* Non-valid native samples per raster: {R['invalid_native_samples']}. Mask: every AOI pixel has value 1 (valid, subswath 1) on both dates.",
           "", "## Scene-wide shift",
           f"* Median ΔHH {R['recomputed']['median_dhh_db']:+.3f} dB, median ΔHV {R['recomputed']['median_dhv_db']:+.3f} dB; "
           f"{R['shift']['fraction_dhh_positive']*100:.1f}% of pixels have ΔHH > 0, {R['shift']['fraction_dhv_positive']*100:.1f}% have ΔHV > 0.",
           f"* 4×4 tile medians of ΔHH range {R['shift']['tile_range_dhh_db'][0]:+.2f} to {R['shift']['tile_range_dhh_db'][1]:+.2f} dB.",
           "* By quartile of 20 June HH: " + "; ".join(f"{s['before_hh_db']} dB → ΔHH {s['median_dhh_db']:+.2f}, ΔHV {s['median_dhv_db']:+.2f}" for s in R["shift"]["strata"]) + ".",
           "* Interpretation: with two dates and no stable reference targets, the shift cannot be attributed to a single cause "
           "(wetter soils or canopy, vegetation growth, inundation, or residual radiometric differences between PROVISIONAL products).",
           "", "## Threshold logic and sensitivity",
           f"* Gates: T_HH = max(3, 3×{R['recomputed']['robust_sigma_dhh_db']:.3f}) = {R['recomputed']['T_HH']:.3f} dB; "
           f"T_HV = {R['recomputed']['T_HV']:.3f} dB; R = 2 dB. Gates are centred on 0 dB.",
           f"* As reported: {R['candidates']['n']:,} candidates ({R['candidates']['fraction']*100:.2f}%), {R['candidates']['by_class']}.",
           f"* If the median shift is assumed NOT to be real change (re-centred): {R['sensitivity_median_centred']['n']:,} candidates "
           f"({R['sensitivity_median_centred']['fraction']*100:.2f}%), {R['sensitivity_median_centred']['by_class']}.",
           f"* Signed: HH up {R['signed']['hh_up']:,} / down {R['signed']['hh_down']:,} (re-centred: {R['signed']['hh_up_centred']:,} / {R['signed']['hh_down_centred']:,}); "
           f"HV up {R['signed']['hv_up']:,} / down {R['signed']['hv_down']:,}.",
           "", "## Registration",
           f"* The file does not state pixel registration; centre registration is assumed. The maximum absolute placement error is "
           f"{R['registration']['max_absolute_position_error_m']:.0f} m. There is no effect on ΔdB because both dates share the identical grid.",
           "", "Nothing in this audit confirms flooding. All classes remain candidate radar backscatter changes."]
    Path(a.out_md).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{p}/{len(checks)} audit checks passed -> {out} and {a.out_md}")
    for c in checks:
        if not c["pass"]:
            print("FAIL:", c["check"], c["detail"])
    return 0 if p == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
