"""Build and validate the ULAK change report (schema ulak-change-v2) and map overlays.

AI-assisted implementation, reviewed and owned by the ULAK team.
Overlays are DISPLAY products: they are reprojected to EPSG:4326 for the web
map. All statistics are computed on the native product grid before display.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from provenance import assert_finite_tree, MAX_JSON_BYTES
from sar_change import HYPOTHESES, CLASS_INVALID

SCHEMA = "ulak-change-v2"
MAX_FEATURES = 1500
HIST_EDGES = [round(-15 + 0.5 * i, 1) for i in range(61)]  # -15 .. +15 dB

# Categorical slots 1-4 (validated with the dataviz palette validator on the app dark surface #121c2c).
CLASS_COLORS = {1: (0x39, 0x87, 0xe5), 2: (0xd9, 0x59, 0x26), 3: (0x19, 0x9e, 0x70), 4: (0xc9, 0x85, 0x00)}


def histogram(values: np.ndarray, edges=HIST_EDGES) -> dict:
    v = np.asarray(values, dtype="float64")
    v = v[np.isfinite(v)]
    clipped_low = int((v < edges[0]).sum())
    clipped_high = int((v > edges[-1]).sum())
    counts, _ = np.histogram(np.clip(v, edges[0], edges[-1]), bins=edges)
    return {"bin_edges_db": list(edges), "counts": [int(c) for c in counts],
            "n": int(v.size), "below_range": clipped_low, "above_range": clipped_high}


def _lonlat(xs, ys, epsg: int):
    if epsg == 4326:
        return list(xs), list(ys)
    from rasterio.warp import transform as warp_transform
    return warp_transform(f"EPSG:{epsg}", "EPSG:4326", list(xs), list(ys))


def cells_geojson(classes: np.ndarray, d_hh: np.ndarray, d_hv: np.ndarray, transform, epsg: int, *,
                  cell_px: int, min_fraction: float = 0.2, max_features: int = MAX_FEATURES) -> dict:
    """Aggregate class map into square cells; GeoJSON coordinates are [lon, lat]."""
    if cell_px < 1:
        raise ValueError("cell_px must be >= 1")
    h, w = classes.shape
    cells = []
    for r in range(0, h, cell_px):
        for c in range(0, w, cell_px):
            blk = classes[r:r + cell_px, c:c + cell_px]
            valid = blk != CLASS_INVALID
            nv = int(valid.sum())
            if nv < max(4, (cell_px * cell_px) // 4):
                continue
            fr = {hy["id"]: float((blk == hy["code"]).sum()) / nv for hy in HYPOTHESES}
            changed = sum(fr.values())
            if changed < min_fraction:
                continue
            dom = max(fr, key=fr.get)
            dh = d_hh[r:r + cell_px, c:c + cell_px]
            dv = d_hv[r:r + cell_px, c:c + cell_px]
            cells.append((changed, r, c, min(r + cell_px, h), min(c + cell_px, w), fr, dom,
                          float(np.nanmedian(dh)), float(np.nanmedian(dv)), nv))
    cells.sort(key=lambda t: -t[0])
    cells = cells[:max_features]
    feats = []
    for i, (changed, r0, c0, r1, c1, fr, dom, mhh, mhv, nv) in enumerate(cells):
        corners = [(c0, r0), (c1, r0), (c1, r1), (c0, r1), (c0, r0)]
        xs, ys = zip(*[transform @ cr for cr in corners])
        lons, lats = _lonlat(xs, ys, epsg)
        ring = [[round(float(lo), 6), round(float(la), 6)] for lo, la in zip(lons, lats)]
        for lo, la in ring:
            if not (-180 <= lo <= 180 and -90 <= la <= 90):
                raise ValueError("Cell coordinate outside lon/lat range; check CRS/axis order")
        feats.append({"type": "Feature", "id": f"cell-{i:04d}",
                      "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"cell_id": f"cell-{i:04d}", "changed_fraction": round(changed, 4),
                                     "dominant_hypothesis": dom,
                                     "fractions": {k: round(v, 4) for k, v in fr.items()},
                                     "median_delta_hh_db": round(mhh, 3), "median_delta_hv_db": round(mhv, 3),
                                     "valid_samples": nv,
                                     "status": "CANDIDATE - radar backscatter change, not confirmed flooding"}})
    return {"type": "FeatureCollection", "features": feats}


def _reproject_to_4326(arr: np.ndarray, transform, epsg: int, *, nearest: bool, max_px: int = 1200):
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.transform import array_bounds
    h, w = arr.shape
    left, bottom, right, top = (array_bounds(h, w, transform)[i] for i in (0, 1, 2, 3))
    dst_t, dw, dh = calculate_default_transform(f"EPSG:{epsg}", "EPSG:4326", w, h, left, bottom, right, top)
    scale = max(dw, dh) / max_px
    if scale > 1:
        dw, dh = int(math.ceil(dw / scale)), int(math.ceil(dh / scale))
        dst_t, dw, dh = calculate_default_transform(f"EPSG:{epsg}", "EPSG:4326", w, h, left, bottom, right, top,
                                                    dst_width=dw, dst_height=dh)
    fill = 255 if nearest else np.nan
    dst = np.full((dh, dw), fill, dtype=arr.dtype if nearest else "float32")
    reproject(source=arr if nearest else arr.astype("float32"), destination=dst,
              src_transform=transform, src_crs=f"EPSG:{epsg}", dst_transform=dst_t, dst_crs="EPSG:4326",
              resampling=Resampling.nearest if nearest else Resampling.bilinear,
              src_nodata=fill, dst_nodata=fill)
    west, south, east, north = array_bounds(dh, dw, dst_t)  # rasterio order: (west, south, east, north)
    return dst, [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]]


def _save_png(rgba: np.ndarray, path: Path):
    from PIL import Image
    Image.fromarray(rgba, mode="RGBA").save(path, optimize=True)


def gray_rgba(db: np.ndarray, lo: float = -25.0, hi: float = 0.0) -> np.ndarray:
    v = np.clip((db - lo) / (hi - lo), 0, 1)
    g = np.nan_to_num(v * 255).astype("uint8")
    a = np.where(np.isfinite(db), 235, 0).astype("uint8")
    return np.dstack([g, g, g, a])


def diverging_rgba(d: np.ndarray, lim: float = 6.0) -> np.ndarray:
    """Diverging blue (decrease) <-> red (increase) with a neutral gray midpoint; alpha scales with |d|."""
    t = np.clip(np.nan_to_num(d) / lim, -1, 1)
    mid = np.array([0x38, 0x38, 0x35], dtype="float64")
    pos = np.array([0xe6, 0x67, 0x67], dtype="float64")   # red pole
    neg = np.array([0x39, 0x87, 0xe5], dtype="float64")   # blue pole
    a_ = np.abs(t)[..., None]
    col = np.where((t >= 0)[..., None], mid + (pos - mid) * a_, mid + (neg - mid) * a_)
    r, gch, b = col[..., 0], col[..., 1], col[..., 2]
    a = np.where(np.isfinite(d), 60 + 180 * np.abs(t), 0)
    return np.dstack([r, gch, b, a]).astype("uint8")


def classes_rgba(cls: np.ndarray) -> np.ndarray:
    out = np.zeros(cls.shape + (4,), dtype="uint8")
    for code, (r, g, b) in CLASS_COLORS.items():
        m = cls == code
        out[m] = (r, g, b, 210)
    return out


def write_overlays(out_dir: Path, prefix: str, transform, epsg: int, *, hh0_db, hh1_db, d_hh, classes) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, arr, kind in (("before_hh", hh0_db, "gray"), ("after_hh", hh1_db, "gray"),
                            ("delta_hh", d_hh, "div"), ("hypotheses", classes, "cls")):
        dst, bounds = _reproject_to_4326(arr, transform, epsg, nearest=(kind == "cls"))
        rgba = gray_rgba(dst) if kind == "gray" else diverging_rgba(dst) if kind == "div" else classes_rgba(dst)
        fn = f"{prefix}_{name}.png"
        _save_png(rgba, out_dir / fn)
        res[name] = {"file": fn, "bounds_latlon": bounds,
                     "render": {"gray": "HH gamma0 dB, -25 (black) to 0 (white)",
                                "div": "dHH dB, -6 (blue) to +6 (red)",
                                "cls": "hypothesis classes (see legend)"}[kind]}
    res["note"] = "Display-only reprojection to EPSG:4326; statistics computed on native UTM grid."
    return res


REQUIRED_TOP = ("schema", "generated_utc", "data_status", "study_area", "provenance", "compatibility_checks",
                "processing", "statistics", "histograms", "hypotheses", "geojson", "warnings", "limitations")
DATA_STATUSES = ("MEASURED", "SOFTWARE_TEST_SYNTHETIC")


def validate_report(rep: dict) -> None:
    """Raise ValueError if the report violates the documented schema (docs/REPORT_SCHEMA.md)."""
    if not isinstance(rep, dict):
        raise ValueError("Report must be an object")
    missing = [k for k in REQUIRED_TOP if k not in rep]
    if missing:
        raise ValueError(f"Report missing fields {missing}")
    if rep["schema"] != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    if rep["data_status"] not in DATA_STATUSES:
        raise ValueError(f"data_status must be one of {DATA_STATUSES}")
    prov = rep["provenance"]
    for side in ("before", "after"):
        if side not in prov or "granule_ur" not in prov[side]:
            raise ValueError(f"provenance.{side}.granule_ur required")
        if rep["data_status"] == "MEASURED" and prov[side].get("pixel_source") not in ("https_range_read", "local_file"):
            raise ValueError("MEASURED reports must state pixel_source as https_range_read or local_file")
    fails = [c for c in rep["compatibility_checks"] if c.get("blocking") and c.get("status") == "FAIL"]
    if fails:
        raise ValueError(f"Report contains blocking failed checks: {[c['id'] for c in fails]}")
    gj = rep["geojson"]
    if gj.get("type") != "FeatureCollection" or not isinstance(gj.get("features"), list):
        raise ValueError("geojson must be a FeatureCollection")
    if len(gj["features"]) > MAX_FEATURES:
        raise ValueError("Too many features")
    for f in gj["features"]:
        ring = f["geometry"]["coordinates"][0]
        for lo, la in ring:
            if not (-180 <= lo <= 180 and -90 <= la <= 90):
                raise ValueError("GeoJSON coordinates must be [lon, lat] within valid ranges")
    assert_finite_tree(rep)
    size = len(json.dumps(rep, allow_nan=False).encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"Report too large ({size} bytes)")


def write_report(rep: dict, path: Path) -> int:
    validate_report(rep)
    text = json.dumps(rep, indent=1, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return len(text)
