"""ULAK scientific investigation: multi-temporal NISAR L-band HH/HV analysis (Sudd, 086_A_005).

Reads the verified window cache written by run_sudd.py (one .npz + .meta.json
per date, HTTPS range reads of NISAR L2 GCOV PROVISIONAL), and independent
reference data (analysis/reference_data.py).  Produces time series, change,
trend, persistence, uncertainty, cross-sensor and hypothesis diagnostics.

Design rules (fixed before results were computed):
* Regions come from MODIS IGBP only (reference_data.REGION_RULE), never from
  NISAR change values.
* All averaging is in linear power; dB only for display/differences.
* Every normalised quantity is reported next to its raw value; normalisation
  (subtracting the AOI-wide median change of the same date) assumes that the
  AOI-wide median pixel did not physically change, which is NOT known to be true
  in a wet season.  It isolates spatially *differential* change only.
* Statistical change (exceeds noise) and physical interpretation are separate
  outputs.  Interpretation requires independent corroboration.

AI-assisted implementation; the ULAK team owns the scientific decisions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_data as R  # noqa: E402

VERSION = "0.4.0"
ML = 5                      # 20 m -> 100 m
DB_FLOOR = 1e-6             # linear power floor before log (only for exact zeros)
N_BOOT = 2000
SEED = 20261114
PERSIST_T_DEFAULT = 3.0
PERSIST_T_SENSITIVITY = (1.5, 2.0, 3.0, 4.0)
# Cell interpretation rule (fixed before computing results)
INTERP_RULE = {
    "water_linked": "DSWx-S1 (OW+IV) fraction range over matched dates >= 0.20 AND "
                    "|Spearman rho(NISAR cell HH dB, DSWx OW+IV)| >= 0.70 (n = matched dates)",
    "vegetation_consistent": "DSWx-S1 (OW+IV) range < 0.10 AND HV first->last change >= +1.0 dB raw AND "
                             ">= +1.0 dB after common-mode removal AND (HV-HH) change >= +0.5 dB AND "
                             "Theil-Sen HV slope > 0",
    "unresolved": "everything else (includes cells without HV or DSWx variation)",
}
DECISION_GATE = {
    "a_structured_differential_change": "a region's common-mode-removed first->last change (HH or HV) has a "
                                        "95% block-bootstrap CI excluding 0 and |median| >= 0.5 dB",
    "b_independent_association": "cell-level NISAR HH vs DSWx-S1 water temporal association beats the "
                                 "date-permutation null at p < 0.05",
    "c_persistent_area": "persistent change (T = 3 dB, raw AND normalised) covers >= 1 % of the valid area",
    "outcome": "Sudd is INFORMATIVE if any of a/b/c holds, otherwise AMBIGUOUS -> run the same pipeline, "
               "unchanged, on the predefined alternatives (Okavango, Congo) before any interpretation",
}


# ----------------------------------------------------------------------------
# helpers

def to_db(lin):
    lin = np.asarray(lin, dtype="float64")
    out = np.full(lin.shape, np.nan)
    ok = np.isfinite(lin) & (lin >= 0)
    out[ok] = 10.0 * np.log10(np.maximum(lin[ok], DB_FLOOR))
    return out


def block_stats(lin: np.ndarray, valid: np.ndarray, k: int = ML, min_valid: float = 0.8):
    """k x k block mean (linear) and within-block coefficient of variation."""
    h, w = (lin.shape[0] // k) * k, (lin.shape[1] // k) * k
    a = np.where(valid[:h, :w], lin[:h, :w], np.nan).astype("float64").reshape(h // k, k, w // k, k)
    n = np.isfinite(a).sum(axis=(1, 3))
    total = np.nansum(a, axis=(1, 3))
    total2 = np.nansum(a * a, axis=(1, 3))
    mean = np.full(n.shape, np.nan, dtype="float64")
    mean2 = np.full(n.shape, np.nan, dtype="float64")
    np.divide(total, n, out=mean, where=n > 0)
    np.divide(total2, n, out=mean2, where=n > 0)
    std = np.sqrt(np.maximum(mean2 - mean * mean, 0.0))
    cv = np.full(n.shape, np.nan, dtype="float64")
    np.divide(std, mean, out=cv, where=np.isfinite(mean) & (mean != 0))
    bad = n < min_valid * k * k
    mean[bad] = np.nan
    cv[bad] = np.nan
    return mean, cv, n


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def boot_median(values: np.ndarray, rng, n_boot=N_BOOT, alpha=0.05):
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if v.size < 5:
        return {"median": float(np.median(v)) if v.size else None, "lo": None, "hi": None, "n": int(v.size)}
    idx = rng.integers(0, v.size, size=(n_boot, v.size))
    meds = np.median(v[idx], axis=1)
    return {"median": float(np.median(v)), "lo": float(np.quantile(meds, alpha / 2)),
            "hi": float(np.quantile(meds, 1 - alpha / 2)), "n": int(v.size)}


def boot_median_diff(a: np.ndarray, b: np.ndarray, rng, n_boot=N_BOOT, alpha=0.05):
    """median(a) - median(b); a and b are independent cell samples."""
    a = a[np.isfinite(a)]; b = b[np.isfinite(b)]
    if a.size < 5 or b.size < 5:
        return {"diff": None, "lo": None, "hi": None}
    ia = rng.integers(0, a.size, size=(n_boot, a.size)); ib = rng.integers(0, b.size, size=(n_boot, b.size))
    d = np.median(a[ia], axis=1) - np.median(b[ib], axis=1)
    return {"diff": float(np.median(a) - np.median(b)), "lo": float(np.quantile(d, alpha / 2)),
            "hi": float(np.quantile(d, 1 - alpha / 2))}


def _finite_spatial_blocks(values: np.ndarray, mask: np.ndarray, block: int = 2) -> list[np.ndarray]:
    """Return finite values grouped in fixed, non-overlapping spatial blocks."""
    values = np.asarray(values, float)
    mask = np.asarray(mask, bool)
    if values.ndim != 2 or mask.shape != values.shape:
        raise ValueError("spatial bootstrap expects a 2-D value grid and same-shape mask")
    blocks = []
    for r in range(0, values.shape[0], block):
        for c in range(0, values.shape[1], block):
            v = values[r:r + block, c:c + block]
            m = mask[r:r + block, c:c + block] & np.isfinite(v)
            if m.any():
                blocks.append(v[m])
    return blocks


def block_boot_median(values: np.ndarray, mask: np.ndarray, rng, *, block: int = 2,
                      n_boot=N_BOOT, alpha=0.05) -> dict:
    """Median and CI from a fixed-grid spatial block bootstrap.

    The 0.01-degree analysis cells are resampled as 2 x 2 blocks by default
    (about 2.2 km at this latitude). This preserves short-range spatial
    dependence more honestly than resampling individual cells.
    """
    blocks = _finite_spatial_blocks(values, mask, block)
    v = np.concatenate(blocks) if blocks else np.array([], dtype=float)
    out = {"median": float(np.median(v)) if v.size else None, "lo": None, "hi": None,
           "n": int(v.size), "blocks": len(blocks), "bootstrap": f"spatial_{block}x{block}_cells"}
    if v.size < 5 or not blocks:
        return out
    meds = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        picked = rng.integers(0, len(blocks), size=len(blocks))
        meds[i] = np.median(np.concatenate([blocks[j] for j in picked]))
    out["lo"] = float(np.quantile(meds, alpha / 2))
    out["hi"] = float(np.quantile(meds, 1 - alpha / 2))
    return out


def block_boot_median_diff(values: np.ndarray, mask_a: np.ndarray, mask_b: np.ndarray, rng, *,
                           block: int = 2, n_boot=N_BOOT, alpha=0.05) -> dict:
    """Difference of regional medians with independent spatial-block resampling."""
    ba = _finite_spatial_blocks(values, mask_a, block)
    bb = _finite_spatial_blocks(values, mask_b, block)
    va = np.concatenate(ba) if ba else np.array([], dtype=float)
    vb = np.concatenate(bb) if bb else np.array([], dtype=float)
    out = {"diff": float(np.median(va) - np.median(vb)) if va.size and vb.size else None,
           "lo": None, "hi": None, "blocks_a": len(ba), "blocks_b": len(bb),
           "bootstrap": f"spatial_{block}x{block}_cells"}
    if va.size < 5 or vb.size < 5 or not ba or not bb:
        return out
    d = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        ia = rng.integers(0, len(ba), size=len(ba))
        ib = rng.integers(0, len(bb), size=len(bb))
        d[i] = np.median(np.concatenate([ba[j] for j in ia])) - np.median(np.concatenate([bb[j] for j in ib]))
    out["lo"] = float(np.quantile(d, alpha / 2))
    out["hi"] = float(np.quantile(d, 1 - alpha / 2))
    return out


def spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 4 or np.nanstd(x[ok]) == 0 or np.nanstd(y[ok]) == 0:
        return None
    return float(rows_spearman(x[ok][None, :], y[ok][None, :])[0])


def rank_rows(a: np.ndarray) -> np.ndarray:
    """Average ranks along axis 1 (no NaNs expected)."""
    a = np.asarray(a, float)
    out = np.empty_like(a, dtype=float)
    for r, row in enumerate(a):
        order = np.argsort(row, kind="mergesort")
        sorted_row = row[order]
        ranks = np.empty(row.size, dtype=float)
        start = 0
        while start < row.size:
            end = start + 1
            while end < row.size and sorted_row[end] == sorted_row[start]:
                end += 1
            ranks[order[start:end]] = 0.5 * (start + 1 + end)
            start = end
        out[r] = ranks
    return out


def theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Median pairwise slope (Theil-Sen slope, without intercept/CI)."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x))
              if x[j] != x[i]]
    return float(np.median(slopes)) if slopes else float("nan")


def rows_spearman(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise Spearman rho; constant rows return NaN without warnings."""
    ra, rb = rank_rows(a), rank_rows(b)
    ra -= ra.mean(1, keepdims=True)
    rb -= rb.mean(1, keepdims=True)
    num = (ra * rb).sum(1)
    den = np.sqrt((ra ** 2).sum(1) * (rb ** 2).sum(1))
    out = np.full(num.shape, np.nan, dtype=float)
    np.divide(num, den, out=out, where=den > 0)
    return out


def phase_correlation(a: np.ndarray, b: np.ndarray):
    """Shift (dy, dx) in pixels that best aligns b to a (sub-pixel, parabolic)."""
    a = np.nan_to_num(a - np.nanmean(a)); b = np.nan_to_num(b - np.nanmean(b))
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2(a * win), np.fft.fft2(b * win)
    cp = fa * np.conj(fb)
    cp /= np.maximum(np.abs(cp), 1e-12)
    r = np.real(np.fft.ifft2(cp))
    py, px = np.unravel_index(np.argmax(r), r.shape)

    def sub(arr, i, n):
        l, c, rr = arr[(i - 1) % n], arr[i], arr[(i + 1) % n]
        den = l - 2 * c + rr
        return 0.0 if den == 0 else 0.5 * (l - rr) / den
    dy = py + sub(r[:, px], py, r.shape[0]); dx = px + sub(r[py, :], px, r.shape[1])
    if dy > r.shape[0] / 2: dy -= r.shape[0]
    if dx > r.shape[1] / 2: dx -= r.shape[1]
    peak = float(r[py, px])
    return float(dy), float(dx), peak


# ----------------------------------------------------------------------------
# loading

@dataclass
class Layer:
    date: str
    granule: str
    utc: str
    orbit_token: str
    hh: np.ndarray            # 100 m linear
    hv: np.ndarray | None
    hh_cv: np.ndarray         # within-block CV of 20 m HH
    hv_cv: np.ndarray | None
    nvalid: np.ndarray
    meta: dict


def load_layers(cache_dir: Path, log=print, coreg_crop: int = 1024):
    import reference_data  # noqa: F401  (keeps import order explicit)
    metas = sorted(Path(cache_dir).glob("*.meta.json"))
    if not metas:
        raise FileNotFoundError(f"no cache windows in {cache_dir}")
    layers, ref_grid, coreg, ref_crop = [], None, [], None
    for mpath in metas:
        meta = json.loads(mpath.read_text(encoding="utf-8"))
        npz = mpath.with_name(mpath.name.replace(".meta.json", ".npz"))
        if not npz.exists():
            raise FileNotFoundError(f"cache metadata has no matching NPZ: {mpath.name}")
        z = np.load(npz, allow_pickle=False)
        required = {"x", "y", "mask"} | {"term_" + t for t in meta.get("available_terms", [])}
        missing = required - set(z.files)
        if missing:
            raise ValueError(f"cache {npz.name} lacks arrays {sorted(missing)}")
        x, y = z["x"], z["y"]
        grid = (meta["epsg"], tuple(meta["transform"]), x.shape, y.shape, float(x[0]), float(y[0]))
        if ref_grid is None:
            ref_grid = grid
        elif grid != ref_grid:
            raise ValueError(f"grid mismatch for {mpath.name}: {grid} vs {ref_grid}")
        mask = z["mask"]
        if mask.shape != (y.size, x.size):
            raise ValueError(f"cache mask/grid shape mismatch for {npz.name}: {mask.shape} vs {(y.size, x.size)}")
        rules = (meta.get("mask_attrs") or {})
        invalid = (mask == 255) | (mask == 0)
        if "_FillValue" in rules and rules["_FillValue"] not in (255,):
            invalid |= mask == rules["_FillValue"]
        out = {}
        for term in ("HHHH", "HVHV"):
            key = "term_" + term
            if key not in z.files:
                out[term] = (None, None)
                continue
            lin = z[key].astype("float32")
            if lin.shape != mask.shape:
                raise ValueError(f"cache term/grid shape mismatch for {npz.name} {term}: {lin.shape} vs {mask.shape}")
            expected = (meta.get("sha256_float32") or {}).get(term)
            got = hashlib.sha256(np.ascontiguousarray(lin).tobytes()).hexdigest()
            if not expected or got != expected:
                raise ValueError(f"cache integrity check failed for {npz.name} {term}: {got} != {expected}")
            v = ~invalid & np.isfinite(lin) & (lin >= 0)
            mean, cv, n = block_stats(lin, v)
            out[term] = (mean, cv)
            if term == "HHHH":
                nvalid = n
                h0, w0 = lin.shape
                cy, cx = h0 // 2, w0 // 2
                crop = to_db(np.where(v, lin, np.nan)[cy - coreg_crop // 2: cy + coreg_crop // 2,
                                                       cx - coreg_crop // 2: cx + coreg_crop // 2])
                crop = np.where(np.isfinite(crop), crop, np.nanmedian(crop))
                if ref_crop is None:
                    ref_crop = crop
                    coreg.append({"date": meta["granule_ur"].split("_")[11][:8], "dy_px": 0.0, "dx_px": 0.0, "peak": 1.0})
                else:
                    dy, dx, pk = phase_correlation(ref_crop, crop)
                    coreg.append({"date": meta["granule_ur"].split("_")[11][:8], "dy_px": dy, "dx_px": dx, "peak": pk})
            del lin
        ur = meta["granule_ur"]
        parts = ur.split("_")
        start = parts[11]
        date = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        layers.append(Layer(date=date, granule=ur, utc=start, orbit_token=parts[14],
                            hh=out["HHHH"][0], hv=out["HVHV"][0], hh_cv=out["HHHH"][1], hv_cv=out["HVHV"][1],
                            nvalid=nvalid, meta={k: meta[k] for k in ("epsg", "transform", "window", "read_utc",
                                                                     "pixel_source", "available_terms")}
                            | {"compositeReleaseId": meta.get("identification", {}).get("compositeReleaseId"),
                               "productVersion": meta.get("identification", {}).get("productVersion"),
                               "productSpecificationVersion": meta.get("identification", {}).get("productSpecificationVersion"),
                               "outputBackscatterExpressionConvention": meta.get("extra_metadata", {}).get(
                                   "/science/LSAR/GCOV/metadata/processingInformation/parameters/rtc/outputBackscatterExpressionConvention"),
                               "outputBackscatterNormalizationConvention": meta.get("extra_metadata", {}).get(
                                   "/science/LSAR/GCOV/metadata/processingInformation/parameters/rtc/outputBackscatterNormalizationConvention")}))
        z.close()
        log(f"loaded {date} terms={meta['available_terms']} orbit_token={parts[14]}")
    layers.sort(key=lambda L: L.date)
    for c in coreg:
        c["date"] = f"{c['date'][:4]}-{c['date'][4:6]}-{c['date'][6:]}"
    return layers, ref_grid, coreg


QC_RULE = {
    "metric": "Pearson r of 400 m HH dB images (4 x 4 blocks of the 100 m grid) between every pair of dates",
    "fail_if": "median r of the date with all other dates < 0.5 while the median pairwise r among the "
               "remaining dates is >= 0.8 (leave-one-out; symmetric, no special case for first/last date)",
    "why": "Permanent landscape structure (river channels, lakes, levees) cannot decorrelate across a 44 km "
           "scene within 12 days and then return; such a date indicates a processing, geolocation or "
           "propagation anomaly, not surface change. The rule uses spatial pattern only, never change magnitude.",
}


def _coarse(a, k=4):
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    return np.nanmean(a[:h, :w].reshape(h // k, k, w // k, k), axis=(1, 3))


def qc_dates(hh_db: np.ndarray, dates: list[str]) -> dict:
    co = [_coarse(x) for x in hh_db]

    def r(i, j):
        a, b = co[i].ravel(), co[j].ravel()
        ok = np.isfinite(a) & np.isfinite(b)
        return float(np.corrcoef(a[ok], b[ok])[0, 1])
    n = len(dates)
    M = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            M[i, j] = M[j, i] = r(i, j)
    out = {"rule": QC_RULE, "dates": {}, "failed": [], "r_matrix": [[round(float(v), 3) for v in row] for row in M]}
    for i, d in enumerate(dates):
        others = [j for j in range(n) if j != i]
        med_i = float(np.median(M[i, others]))
        pair = [M[j, k] for a, j in enumerate(others) for k in others[a + 1:]]
        med_o = float(np.median(pair)) if pair else float("nan")
        fail = med_i < 0.5 and med_o >= 0.8
        out["dates"][d] = {"median_r_with_others": med_i, "median_r_among_others": med_o, "fail": bool(fail)}
        if fail:
            out["failed"].append(d)
    return out


def lonlat_of_blocks(ref_grid, shape):
    from rasterio.warp import transform
    epsg, tr = ref_grid[0], ref_grid[1]
    dx, x0, dy, y0 = tr[0], tr[2], tr[4], tr[5]
    rows, cols = shape
    xc = x0 + (np.arange(cols) * ML + ML / 2) * dx
    yc = y0 + (np.arange(rows) * ML + ML / 2) * dy
    X, Y = np.meshgrid(xc, yc)
    lon, lat = transform(f"EPSG:{epsg}", "EPSG:4326", X.ravel().tolist(), Y.ravel().tolist())
    lon = np.asarray(lon).reshape(X.shape)
    lat = np.asarray(lat).reshape(Y.shape)
    return lon, lat, X, Y


# ----------------------------------------------------------------------------
# analysis

def cell_means(lin: np.ndarray, cr: np.ndarray, cc: np.ndarray):
    """Mean linear power per 0.01 deg cell (40x40), NaN where empty."""
    s = np.zeros((R.NCELL, R.NCELL)); n = np.zeros((R.NCELL, R.NCELL))
    ok = (cr >= 0) & np.isfinite(lin)
    np.add.at(s, (cr[ok], cc[ok]), lin[ok]); np.add.at(n, (cr[ok], cc[ok]), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = s / n
    m[n < 50] = np.nan          # require >= 50 of ~120 100 m pixels
    return m, n


def ols_slope(t_days: np.ndarray, Y: np.ndarray):
    """Per-pixel OLS slope along axis 0 (dB/day), ignoring NaN dates."""
    T = np.broadcast_to(t_days[:, None, None], Y.shape).astype(float)
    ok = np.isfinite(Y)
    n = ok.sum(0)
    T = np.where(ok, T, 0.0)
    YY = np.where(ok, Y, 0.0)
    tm = np.zeros(n.shape, dtype=float); ym = np.zeros(n.shape, dtype=float)
    np.divide(T.sum(0), n, out=tm, where=n > 0)
    np.divide(YY.sum(0), n, out=ym, where=n > 0)
    T = np.where(ok, T, np.nan)
    num = np.nansum((T - tm) * (Y - ym), 0); den = np.nansum((T - tm) ** 2, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        b = num / den
    b[n < 4] = np.nan
    return b


def persistence(delta: np.ndarray, T: float):
    """delta: (n_later, H, W) change vs first date (dB). Returns class map and counts.

    1 persistent increase: > +T on >= 75 % of later dates AND on the last 3
    2 persistent decrease: < -T likewise
    3 transient: exceeds |T| on >= 2 later dates but not persistent
    0 stable / 255 invalid
    """
    nl = delta.shape[0]
    ok = np.all(np.isfinite(delta), axis=0)
    up = (delta > T); dn = (delta < -T)
    need = math.ceil(0.75 * nl)
    pu = (up.sum(0) >= need) & up[-3:].all(0)
    pd = (dn.sum(0) >= need) & dn[-3:].all(0)
    tr = ((up | dn).sum(0) >= 2) & ~pu & ~pd
    cls = np.zeros(delta.shape[1:], np.uint8)
    cls[tr] = 3; cls[pu] = 1; cls[pd] = 2; cls[~ok] = 255
    return cls


def run(cache_dir: Path, ref_dir: Path, power_path: Path, out_dir: Path, web_dir: Path | None, *,
        make_figures: bool = True, exclude=None, log=print) -> dict:
    rng = np.random.default_rng(SEED)
    ref = R.load_reference(ref_dir)
    layers_all, ref_grid, coreg = load_layers(cache_dir, log=log)
    qc = qc_dates(np.stack([to_db(L.hh) for L in layers_all]), [L.date for L in layers_all])
    excluded = set(qc["failed"]) | set(exclude or ())
    layers = [L for L in layers_all if L.date not in excluded]
    if len(layers) < 4:
        raise ValueError(f"at least four QC-passing acquisitions are required; got {len(layers)}")
    log(f"QC failed: {qc['failed']}; excluded from main analysis: {sorted(excluded)}")
    dates = [L.date for L in layers]
    hv_dates = [L.date for L in layers if L.hv is not None]
    t_days = np.array([(parse_date(d) - parse_date(dates[0])).days for d in dates], float)
    H, W = layers[0].hh.shape
    lon, lat, X, Y = lonlat_of_blocks(ref_grid, (H, W))
    cr, cc = R.cell_of_lonlat(lon, lat)
    in_aoi = cr >= 0
    # common valid support
    hh_stack = np.stack([L.hh for L in layers])
    hv_stack = np.stack([L.hv if L.hv is not None else np.full((H, W), np.nan) for L in layers])
    valid_hh = np.all(np.isfinite(hh_stack), 0) & in_aoi
    hv_idx = [i for i, L in enumerate(layers) if L.hv is not None]
    if len(hv_idx) < 4:
        raise ValueError(f"at least four QC-passing HV acquisitions are required; got {len(hv_idx)}")
    valid_hv = np.all(np.isfinite(hv_stack[hv_idx]), 0) & in_aoi
    hh_db = np.where(valid_hh, to_db(hh_stack), np.nan)
    hv_db = np.where(valid_hv, to_db(hv_stack), np.nan)
    pixel_area_km2 = (ML * abs(ref_grid[1][0])) ** 2 / 1e6
    log(f"stack {len(dates)} dates, 100 m grid {H}x{W}, valid HH px {int(valid_hh.sum())}, HV px {int(valid_hv.sum())}")

    # ---------------- metadata / compatibility
    releases = {L.meta["compositeReleaseId"] for L in layers}
    product_versions = {L.meta["productVersion"] for L in layers}
    specification_versions = {L.meta["productSpecificationVersion"] for L in layers}
    expressions = {L.meta["outputBackscatterExpressionConvention"] for L in layers}
    normalisations = {L.meta["outputBackscatterNormalizationConvention"] for L in layers}
    if releases != {"P05023"} or len(product_versions) != 1 or len(specification_versions) != 1:
        raise ValueError(f"mixed processing collections/versions: CRID={releases}, product={product_versions}, spec={specification_versions}")
    if expressions != {"Linear power"} or normalisations != {"gamma0"}:
        raise ValueError(f"unexpected radiometric conventions: expression={expressions}, normalisation={normalisations}")
    compat = {"dates": dates, "hv_dates": hv_dates,
              "missing_hv": [d for d in dates if d not in hv_dates],
              "granules": {L.date: L.granule for L in layers},
              "orbit_tokens": {L.date: L.orbit_token for L in layers},
              "grid_identical": True, "epsg": ref_grid[0], "transform_20m": list(ref_grid[1]),
              "cache_sha256_verified": True, "crid": next(iter(releases)),
              "product_version": next(iter(product_versions)),
              "product_specification_version": next(iter(specification_versions)),
              "backscatter_expression": next(iter(expressions)), "backscatter_normalisation": next(iter(normalisations)),
              "coregistration_phase_correlation_vs_first": coreg,
              "all_dates_loaded": [L.date for L in layers_all], "qc": qc, "excluded": sorted(excluded),
              "gap": "No NISAR acquisition for the 2026-08-07 slot in the CMR snapshot (12-day cycle).",
              "notes": ["All windows share EPSG, transform and coordinate vectors exactly (checked).",
                        "Orbit token 'F' (2026-07-14) marks a non-nominal (forecast/fast) orbit ephemeris; "
                        "coregistration is checked by phase correlation instead of assumed.",
                        "2026-09-24 is a single-pol SHSH acquisition: HH only, excluded from every HV statistic."]}

    # ---------------- noise / speckle
    cv = np.stack([L.hh_cv for L in layers])
    cv_med = float(np.nanmedian(cv[:, valid_hh]))
    se_db_indep = 4.343 * cv_med / math.sqrt(ML * ML)
    # ENL of 20 m pixels from the most homogeneous decile of blocks (per date)
    enl = []
    for L in layers:
        c = L.hh_cv[valid_hh]
        q = np.nanquantile(c, 0.1)
        enl.append(float(1.0 / np.nanmedian(c[c <= q]) ** 2))
    # split-half (checkerboard) estimate from the first date is not possible from block stats; use
    # temporal differences of the most stable cells as an empirical upper bound instead.
    d_consec_hh = np.diff(hh_db, axis=0)
    mad = [float(1.4826 * np.nanmedian(np.abs(d - np.nanmedian(d)))) for d in d_consec_hh]
    noise = {"within_block_cv_median_hh": cv_med,
             "se_100m_db_if_independent": se_db_indep,
             "enl_20m_homogeneous_decile": enl,
             "enl_20m_median": float(np.median(enl)),
             "consecutive_diff_robust_sd_db_hh": dict(zip([f"{a}->{b}" for a, b in zip(dates[:-1], dates[1:])], mad)),
             "interpretation": "The independence-based SE is a LOWER bound (20 m GCOV samples are spatially "
                               "correlated). The robust SD of consecutive-date differences is an UPPER bound on "
                               "noise because it also contains real change. The 3 dB gate exceeds both by a wide margin."}

    # ---------------- cells
    cell_hh = np.full((len(dates), R.NCELL, R.NCELL), np.nan)
    cell_hv = np.full_like(cell_hh, np.nan)
    for i in range(len(dates)):
        cell_hh[i], ncell = cell_means(np.where(valid_hh, hh_stack[i], np.nan), cr, cc)
        if i in hv_idx:
            cell_hv[i], _ = cell_means(np.where(valid_hv, hv_stack[i], np.nan), cr, cc)
    cell_hh_db, cell_hv_db = to_db(cell_hh), to_db(cell_hv)
    cell_ratio_db = cell_hv_db - cell_hh_db
    regions = {name: ref.region_mask(name) for name in R.REGION_ORDER}
    regions["aoi"] = np.isfinite(cell_hh_db[0])
    region_info = {name: {"cells": int(m.sum()), "area_km2_approx": float(m.sum() * 1.1 * 1.1)} for name, m in regions.items()}
    # sensitivity: region medians for ALL loaded dates, including QC-failed ones (not used elsewhere)
    incl = {"dates": [L.date for L in layers_all], "hh_db": {}, "hv_db": {}}
    for L in layers_all:
        ch = to_db(cell_means(np.where(in_aoi, L.hh, np.nan), cr, cc)[0])
        cv_ = to_db(cell_means(np.where(in_aoi, L.hv, np.nan), cr, cc)[0]) if L.hv is not None else None
        for name, m in regions.items():
            incl["hh_db"].setdefault(name, []).append(float(np.nanmedian(ch[m])))
            incl["hv_db"].setdefault(name, []).append(None if cv_ is None else float(np.nanmedian(cv_[m])))

    # ---------------- time series per region
    def series(cell_db, idx):
        out = {}
        for name, m in regions.items():
            out[name] = [boot_median(cell_db[i][m], rng) if i in idx else None for i in range(len(dates))]
        return out
    all_idx = list(range(len(dates)))
    ts = {"hh_db": series(cell_hh_db, all_idx), "hv_db": series(cell_hv_db, hv_idx),
          "hv_minus_hh_db": series(cell_ratio_db, hv_idx)}
    # pixel-level AOI medians (100 m) for comparison with the earlier pair report
    ts["aoi_pixel_median_hh_db"] = [float(np.nanmedian(hh_db[i][valid_hh])) for i in all_idx]
    ts["aoi_pixel_median_hv_db"] = [float(np.nanmedian(hv_db[i][valid_hv])) if i in hv_idx else None for i in all_idx]

    # change vs first date: raw, common mode, normalised, region differentials
    def change(cell_db, idx):
        base = cell_db[idx[0]]
        raw, norm, cm = {}, {}, []
        for i in idx:
            d = cell_db[i] - base
            cmode = float(np.nanmedian(d[regions["aoi"]]))
            cm.append({"date": dates[i], "aoi_median_change_db": cmode})
            for name, m in regions.items():
                raw.setdefault(name, []).append({"date": dates[i], **block_boot_median(d, m, rng)})
                norm.setdefault(name, []).append({"date": dates[i], **block_boot_median(d - cmode, m, rng)})
        return {"raw": raw, "normalised": norm, "common_mode": cm}
    chg = {"hh": change(cell_hh_db, all_idx), "hv": change(cell_hv_db, hv_idx),
           "hv_minus_hh": change(cell_ratio_db, hv_idx)}

    # first -> last differential between regions (raw; uniform offsets cancel)
    first, last = 0, len(dates) - 1
    diffs = {}
    for pol, cdb, i0, i1 in (("hh", cell_hh_db, first, last), ("hv", cell_hv_db, hv_idx[0], hv_idx[-1]),
                             ("hv_minus_hh", cell_ratio_db, hv_idx[0], hv_idx[-1])):
        d = cdb[i1] - cdb[i0]
        diffs[pol] = {f"{a}-{b}": block_boot_median_diff(d, regions[a], regions[b], rng)
                      for a, b in (("corridor", "west_margin"), ("corridor", "east_margin"),
                                   ("west_margin", "east_margin"))}

    # range-dependence check (H0 non-uniform calibration): change vs easting within each margin
    east_km = (X - X.mean()) / 1000.0
    cell_e = np.full((R.NCELL, R.NCELL), np.nan)
    s = np.zeros_like(cell_e); n = np.zeros_like(cell_e)
    ok = cr >= 0
    np.add.at(s, (cr[ok], cc[ok]), east_km[ok]); np.add.at(n, (cr[ok], cc[ok]), 1)
    with np.errstate(invalid="ignore"):
        cell_e = s / n
    rng_dep = {}
    for pol, cdb, i0, i1 in (("hh", cell_hh_db, first, last), ("hv", cell_hv_db, hv_idx[0], hv_idx[-1])):
        d = cdb[i1] - cdb[i0]
        rr = {}
        for name in ("west_margin", "east_margin", "corridor", "aoi"):
            m = regions[name] & np.isfinite(d) & np.isfinite(cell_e)
            if m.sum() > 10:
                b = np.polyfit(cell_e[m], d[m], 1)[0]
                # bootstrap slope
                idx = np.nonzero(m.ravel())[0]
                bs = []
                for _ in range(500):
                    j = rng.choice(idx, idx.size)
                    bs.append(np.polyfit(cell_e.ravel()[j], d.ravel()[j], 1)[0])
                rr[name] = {"slope_db_per_km_easting": float(b), "lo": float(np.quantile(bs, .025)),
                            "hi": float(np.quantile(bs, .975)), "cells": int(m.sum())}
        we = boot_median_diff(d[regions["west_margin"]], d[regions["east_margin"]], rng)
        de = float(np.nanmedian(cell_e[regions["west_margin"]]) - np.nanmedian(cell_e[regions["east_margin"]]))
        rr["west_minus_east_change_db"] = we
        rr["west_minus_east_easting_km"] = de
        rr["predicted_by_within_margin_slope_db"] = (
            None if "west_margin" not in rr or "east_margin" not in rr else
            float(0.5 * (rr["west_margin"]["slope_db_per_km_easting"] + rr["east_margin"]["slope_db_per_km_easting"]) * de))
        rng_dep[pol] = rr

    # ---------------- per-pixel maps: consecutive, first-last, trend, persistence
    d_first_last_hh = hh_db[last] - hh_db[first]
    d_first_last_hv = hv_db[hv_idx[-1]] - hv_db[hv_idx[0]]
    slope_hh = ols_slope(t_days, hh_db) * 30.0
    slope_hv = ols_slope(t_days[hv_idx], hv_db[hv_idx]) * 30.0
    cm_hh = np.array([np.nanmedian((hh_db[i] - hh_db[0])[valid_hh]) for i in all_idx])
    cm_hv = np.array([np.nanmedian((hv_db[i] - hv_db[hv_idx[0]])[valid_hv]) for i in hv_idx])
    delta_hh = hh_db[1:] - hh_db[0]
    delta_hv = hv_db[hv_idx[1:]] - hv_db[hv_idx[0]]
    pers = {}
    pers_maps = {}
    for T in PERSIST_T_SENSITIVITY:
        for pol, delt, cm, vmask in (("hh", delta_hh, cm_hh[1:], valid_hh), ("hv", delta_hv, cm_hv[1:], valid_hv)):
            raw_c = persistence(delt, T)
            nrm_c = persistence(delt - cm[:, None, None], T)
            both_up = (raw_c == 1) & (nrm_c == 1); both_dn = (raw_c == 2) & (nrm_c == 2)
            nv = int(vmask.sum())
            pers[f"{pol}_T{T:g}"] = {
                "valid_px": nv,
                "raw": {k: int(((raw_c == v) & vmask).sum()) for k, v in (("persistent_increase", 1), ("persistent_decrease", 2), ("transient", 3))},
                "normalised": {k: int(((nrm_c == v) & vmask).sum()) for k, v in (("persistent_increase", 1), ("persistent_decrease", 2), ("transient", 3))},
                "robust_both": {"persistent_increase": int((both_up & vmask).sum()), "persistent_decrease": int((both_dn & vmask).sum())},
            }
            pers[f"{pol}_T{T:g}"]["robust_both_fraction"] = (int((both_up & vmask).sum()) + int((both_dn & vmask).sum())) / max(nv, 1)
            if T == PERSIST_T_DEFAULT:
                m = np.where(vmask, raw_c, 255).astype(np.uint8)
                m[(m == 1) & ~both_up] = 4     # raw-only persistent increase (vanishes after normalisation)
                m[(m == 2) & ~both_dn] = 5
                pers_maps[pol] = m
    # region breakdown of robust persistent change
    for pol in ("hh", "hv"):
        m = pers_maps[pol]
        brk = {}
        for name in R.REGION_ORDER + ("unassigned",):
            code = {v: k for k, v in R.REGION_CODES.items()}[name]
            sel = (cr >= 0) & (ref.labels[np.clip(cr, 0, 39), np.clip(cc, 0, 39)] == code) & (m != 255)
            brk[name] = {"valid_px": int(sel.sum()), **{k: int(((m == v) & sel).sum()) for k, v in
                         (("robust_increase", 1), ("robust_decrease", 2), ("raw_only_increase", 4), ("raw_only_decrease", 5), ("transient", 3))}}
        pers[f"{pol}_T3_by_region"] = brk

    # ---------------- independent data: DSWx-S1 matched to NISAR (S1 date = NISAR - 1 day)
    match = {}
    for d in dates:
        s1 = (parse_date(d) - dt.timedelta(days=1)).isoformat()
        if s1 in ref.s1_iv:
            match[d] = s1
    mdates = [d for d in dates if d in match]
    mi = [dates.index(d) for d in mdates]
    iv = np.stack([ref.s1_iv[match[d]] for d in mdates]); ow = np.stack([ref.s1_ow[match[d]] for d in mdates])
    water = iv + ow
    s1_tab = R.region_fraction_table(ref, "S1")
    hls_tab = R.region_fraction_table(ref, "HLS")

    # class signatures: NISAR values in cells that DSWx-S1 classifies consistently
    sig = {}
    for j, d in enumerate(mdates):
        i = dates.index(d)
        groups = {"open_water_ge80": ow[j] >= 0.8, "inundated_veg_ge80": iv[j] >= 0.8,
                  "not_water_ge95": (1 - water[j]) >= 0.95}
        sig[d] = {}
        for gname, gm in groups.items():
            gm = gm & np.isfinite(cell_hh_db[i])
            sig[d][gname] = {"cells": int(gm.sum()),
                             "hh_db_median": float(np.nanmedian(cell_hh_db[i][gm])) if gm.any() else None,
                             "hv_db_median": float(np.nanmedian(cell_hv_db[i][gm])) if gm.any() and i in hv_idx else None,
                             "hv_minus_hh_db_median": float(np.nanmedian(cell_ratio_db[i][gm])) if gm.any() and i in hv_idx else None}

    # spatial association per date (cells)
    spatial = {}
    for j, d in enumerate(mdates):
        i = dates.index(d)
        spatial[d] = {"rho_hh_vs_iv": spearman(cell_hh_db[i].ravel(), iv[j].ravel()),
                      "rho_hh_vs_ow": spearman(cell_hh_db[i].ravel(), ow[j].ravel()),
                      "rho_hv_vs_ow": spearman(cell_hv_db[i].ravel(), ow[j].ravel()) if i in hv_idx else None,
                      "rho_ratio_vs_iv": spearman(cell_ratio_db[i].ravel(), iv[j].ravel()) if i in hv_idx else None}

    # change association first matched -> last matched
    i0, i1 = mi[0], mi[-1]
    dn_hh = (cell_hh_db[i1] - cell_hh_db[i0]).ravel()
    dw = (water[-1] - water[0]).ravel(); div = (iv[-1] - iv[0]).ravel()
    change_assoc = {"nisar_span": [dates[i0], dates[i1]], "dswx_span": [match[dates[i0]], match[dates[i1]]],
                    "rho_dHH_vs_dWater": spearman(dn_hh, dw), "rho_dHH_vs_dIV": spearman(dn_hh, div)}
    if i1 in hv_idx and i0 in hv_idx:
        change_assoc["rho_dHV_vs_dWater"] = spearman((cell_hv_db[i1] - cell_hv_db[i0]).ravel(), dw)
    # superblock bootstrap CI (2x2 cells) for the change association
    sb = (np.arange(R.NCELL)[:, None] // 2) * 20 + (np.arange(R.NCELL)[None, :] // 2)
    sbv = sb.ravel()
    ok = np.isfinite(dn_hh) & np.isfinite(dw)
    blocks = np.unique(sbv[ok])
    bs = []
    for _ in range(500):
        pick = rng.choice(blocks, blocks.size)
        sel = np.concatenate([np.nonzero((sbv == b) & ok)[0] for b in pick])
        r_ = spearman(dn_hh[sel], dw[sel])
        if r_ is not None:
            bs.append(r_)
    change_assoc["rho_dHH_vs_dWater_ci95_superblock"] = [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))]

    # temporal association per cell + permutation null (joint date permutation)
    nm = len(mdates)
    Yh = cell_hh_db[mi].reshape(nm, -1).T          # cells x dates
    Wt = water.reshape(nm, -1).T
    vary = (np.nanmax(Wt, 1) - np.nanmin(Wt, 1)) >= 0.20
    okc = np.all(np.isfinite(Yh), 1) & vary & (np.nanstd(Wt, 1) > 0)
    rho_cells = np.full(Yh.shape[0], np.nan)
    if okc.sum() >= 5:
        rho_cells[okc] = rows_spearman(Yh[okc], Wt[okc])
        obs = float(np.nanmedian(rho_cells[okc]))
        obs_abs07 = int((np.abs(rho_cells[okc]) >= 0.7).sum())
        null_med, null_abs = [], []
        prng = np.random.default_rng(SEED + 1)
        for _ in range(999):
            p = prng.permutation(nm)
            rr_ = rows_spearman(Yh[okc][:, p], Wt[okc])
            null_med.append(np.median(rr_)); null_abs.append(int((np.abs(rr_) >= 0.7).sum()))
        null_med = np.array(null_med); null_abs = np.array(null_abs)
        temporal = {"cells_tested": int(okc.sum()), "median_rho": obs,
                    "p_two_sided_median": float((np.sum(np.abs(null_med) >= abs(obs)) + 1) / 1000),
                    "cells_abs_rho_ge_0.7": obs_abs07,
                    "null_mean_cells_abs_rho_ge_0.7": float(null_abs.mean()),
                    "p_count_ge_obs": float((np.sum(null_abs >= obs_abs07) + 1) / 1000),
                    "matched_dates": mdates, "dswx_dates": [match[d] for d in mdates]}
    else:
        temporal = {"cells_tested": int(okc.sum()), "note": "too few cells with DSWx water variation >= 0.20"}

    # region-level temporal association
    region_temporal = {}
    for name in R.REGION_ORDER + ("aoi",):
        nh = [ts["hh_db"][name][i]["median"] for i in mi]
        key = name if name != "aoi" else "aoi"
        fr = [s1_tab[match[d]][key if key != "aoi" else "aoi"] for d in mdates]
        region_temporal[name] = {
            "rho_hh_vs_iv": spearman(nh, [f["inundated_vegetation"] for f in fr]),
            "rho_hh_vs_ow": spearman(nh, [f["open_water"] for f in fr]),
            "rho_hh_norm_vs_iv": spearman([a - b for a, b in zip(nh, [chg["hh"]["common_mode"][i]["aoi_median_change_db"] for i in mi])],
                                          [f["inundated_vegetation"] for f in fr]),
            "n": nm}

    # ---------------- rain (NASA POWER) and common mode
    power = json.loads(Path(power_path).read_text(encoding="utf-8"))
    pd_ = dict(zip(power["dates"], power["PRECTOTCORR"]))
    def antecedent(d, k):
        day = parse_date(d)
        vals = [pd_.get((day - dt.timedelta(days=j)).isoformat(), None) for j in range(1, k + 1)]
        vals = [v for v in vals if v is not None and v > -900]
        return float(sum(vals)) if len(vals) == k else None
    # POWER daily values are in local solar time; NISAR passes at ~06:34 LST, so the acquisition
    # day's own total falls mostly AFTER the image: antecedent windows end the day before.
    rain = {d: {"prev1": antecedent(d, 1), "prev3": antecedent(d, 3), "prev7": antecedent(d, 7),
                "prev14": antecedent(d, 14)} for d in dates}
    cm_series_hh = [c["aoi_median_change_db"] for c in chg["hh"]["common_mode"]]
    cm_series_hv = [c["aoi_median_change_db"] for c in chg["hv"]["common_mode"]]
    rain_assoc = {f"rho_commonmode_hh_vs_rain_{k}": spearman(cm_series_hh, [rain[d][k] for d in dates]) for k in ("prev1", "prev3", "prev7")}
    rain_assoc.update({f"rho_commonmode_hv_vs_rain_{k}": spearman(cm_series_hv, [rain[d][k] for d in hv_dates]) for k in ("prev1", "prev3", "prev7")})
    rain_assoc["n_hh"] = len(dates); rain_assoc["n_hv"] = len(hv_dates)
    rain_assoc["note"] = "n <= 10 dates: |rho| must exceed ~0.65 to be nominally significant; wind is NOT available (POWER request did not include WS2M/WS10M)."
    # region raw change = a + b * antecedent rain + c * days  (primary window prev7 fixed a priori; prev3 secondary)
    rain_model = {}
    for pol, idx in (("hh", all_idx), ("hv", hv_idx)):
        for name in R.REGION_ORDER + ("aoi",):
            y = np.array([r_["median"] for r_ in chg[pol]["raw"][name]])
            tt = t_days[idx]
            for win in ("prev7", "prev3"):
                x = np.array([rain[dates[i]][win] for i in idx], float)
                if not np.all(np.isfinite(x)):
                    continue
                A = np.column_stack([np.ones_like(tt), x, tt])
                coef, res, rk, _ = np.linalg.lstsq(A, y, rcond=None)
                yhat = A @ coef
                dof = max(len(y) - 3, 1)
                s2 = float(((y - yhat) ** 2).sum() / dof)
                cov = s2 * np.linalg.inv(A.T @ A)
                ss_tot = float(((y - y.mean()) ** 2).sum())
                rain_model[f"{pol}:{name}:{win}"] = {
                    "rain_coef_db_per_10mm": float(coef[1] * 10), "rain_se": float(math.sqrt(cov[1, 1]) * 10),
                    "trend_db_per_30d": float(coef[2] * 30), "trend_se": float(math.sqrt(cov[2, 2]) * 30),
                    "r2": float(1 - ((y - yhat) ** 2).sum() / ss_tot) if ss_tot > 0 else None, "n": int(len(y)),
                    "rho_change_vs_rain": spearman(y, x)}
    rain_assoc["model_note"] = ("OLS with n = 9 (HH) / 8 (HV) dates and 3 parameters: descriptive only; SE assume "
                                "independent residuals; point rain from one POWER grid cell (~0.5 deg) for the AOI.")

    # where: change versus signed distance from the corridor centreline (MODIS-defined geometry)
    dist_km = np.array([[(c_ + 0.5 - ref.centreline[r_]) * 1.104 for c_ in range(R.NCELL)] for r_ in range(R.NCELL)])
    sav_cells = ref.sav4 >= 80
    bins = np.arange(-22, 24, 4)
    profile = {"bins_km": bins.tolist(), "note": "negative = west of the centreline; cells with >= 80 % stable "
               "savanna only (land-cover held constant); 95 % cell bootstrap CI", "series": {}}
    peak_i = int(np.argmax(cm_series_hh))
    for lab_, cdb, i0, i1 in (("hh_first_last", cell_hh_db, first, last), ("hv_first_last", cell_hv_db, hv_idx[0], hv_idx[-1]),
                              (f"hh_first_peak_{dates[peak_i]}", cell_hh_db, first, peak_i)):
        d = cdb[i1] - cdb[i0]
        rows = []
        for b0, b1 in zip(bins[:-1], bins[1:]):
            m = sav_cells & (dist_km >= b0) & (dist_km < b1) & np.isfinite(d)
            rows.append({"from_km": float(b0), "to_km": float(b1), **boot_median(d[m], rng)})
        profile["series"][lab_] = rows

    # independent physical strata from DSWx-S1 (class held on ALL matched dates; composition fixed)
    strata = {"persistent_open_water": np.all(ow >= 0.5, 0), "persistent_inundated_veg": np.all(iv >= 0.5, 0),
              "persistent_not_water": np.all(water <= 0.05, 0)}
    strata_ts = {}
    for sname, sm in strata.items():
        strata_ts[sname] = {"cells": int(sm.sum())}
        for pol, cdb, idx in (("hh", cell_hh_db, all_idx), ("hv", cell_hv_db, hv_idx), ("hv_minus_hh", cell_ratio_db, hv_idx)):
            base = cdb[idx[0]]
            strata_ts[sname][pol] = [{"date": dates[i], "level": boot_median(cdb[i][sm], rng)["median"],
                                      **boot_median((cdb[i] - base)[sm], rng)} for i in idx]

    # persistent open water (DSWx OW >= 0.8 on all matched dates): radar dark-water stability
    pow_cells = np.all(ow >= 0.8, 0)
    pow_series = [float(np.nanmedian(cell_hh_db[i][pow_cells])) if pow_cells.any() else None for i in all_idx]

    # ---------------- cell interpretation (rule fixed in INTERP_RULE)
    interp = np.full((R.NCELL, R.NCELL), "unresolved", dtype=object)
    wrange = water.max(0) - water.min(0)
    rho_grid = rho_cells.reshape(R.NCELL, R.NCELL)
    full_rho = np.full(R.NCELL * R.NCELL, np.nan)
    okr = np.all(np.isfinite(Yh), 1) & (np.nanstd(Wt, 1) > 0) & (np.nanstd(Yh, 1) > 0)
    full_rho[okr] = rows_spearman(Yh[okr], Wt[okr])
    full_rho = full_rho.reshape(R.NCELL, R.NCELL)
    hv0, hv1 = hv_idx[0], hv_idx[-1]
    d_hv = cell_hv_db[hv1] - cell_hv_db[hv0]
    d_ratio = cell_ratio_db[hv1] - cell_ratio_db[hv0]
    cm_hv_last = chg["hv"]["common_mode"][-1]["aoi_median_change_db"]
    hv_slope = np.full((R.NCELL, R.NCELL), np.nan)
    th = t_days[hv_idx]
    for r_ in range(R.NCELL):
        for c_ in range(R.NCELL):
            yv = cell_hv_db[hv_idx, r_, c_]
            if np.all(np.isfinite(yv)):
                hv_slope[r_, c_] = theil_sen_slope(th, yv) * 30.0
    water_linked = (wrange >= 0.20) & (np.abs(full_rho) >= 0.70)
    veg = (wrange < 0.10) & (d_hv >= 1.0) & ((d_hv - cm_hv_last) >= 1.0) & (d_ratio >= 0.5) & (hv_slope > 0)
    interp[veg] = "vegetation_consistent"
    interp[water_linked] = "water_linked"
    interp[~np.isfinite(cell_hh_db[0])] = "no_data"
    interp_counts = {k: int((interp == k).sum()) for k in ("water_linked", "vegetation_consistent", "unresolved", "no_data")}
    interp_by_region = {name: {k: int(((interp == k) & ref.region_mask(name)).sum()) for k in interp_counts}
                        for name in R.REGION_ORDER + ("unassigned",)}

    # ---------------- decision gate
    gate_a = []
    for pol in ("hh", "hv"):
        for name in R.REGION_ORDER:
            last_n = chg[pol]["normalised"][name][-1]
            if last_n["lo"] is not None and (last_n["lo"] > 0 or last_n["hi"] < 0) and abs(last_n["median"]) >= 0.5:
                gate_a.append(f"{pol}:{name} {last_n['median']:+.2f} dB [{last_n['lo']:+.2f},{last_n['hi']:+.2f}]")
    gate_b = temporal.get("p_two_sided_median", 1.0) < 0.05 or temporal.get("p_count_ge_obs", 1.0) < 0.05
    gate_c = max(pers["hh_T3"]["robust_both_fraction"], pers["hv_T3"]["robust_both_fraction"]) >= 0.01
    gate = {"criteria": DECISION_GATE, "a": gate_a, "b": bool(gate_b), "c": bool(gate_c),
            "c_values": {"hh": pers["hh_T3"]["robust_both_fraction"], "hv": pers["hv_T3"]["robust_both_fraction"]},
            "outcome": "INFORMATIVE" if (gate_a or gate_b or gate_c) else "AMBIGUOUS"}

    results = {
        "schema": "ulak-timeseries-v1", "software": f"ulak timeseries.py {VERSION}",
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "MEASURED", "product": "NISAR L2 GCOV PROVISIONAL (CRID P05023), frequency A, gamma0 HH/HV",
        "compatibility": compat, "grid_100m": {"rows": H, "cols": W, "pixel_area_km2": pixel_area_km2,
                                               "valid_hh_px": int(valid_hh.sum()), "valid_hv_px": int(valid_hv.sum())},
        "regions": {"rule": R.REGION_RULE, "info": region_info},
        "uncertainty_methods": {
            "regional_change_ci": "2x2 analysis-cell (~2.2 km) fixed-grid spatial block bootstrap, 2000 replicates",
            "regional_level_ci": "individual 0.01-degree analysis-cell bootstrap, 2000 replicates",
            "change_association_ci": "2x2 analysis-cell superblock bootstrap, 500 replicates",
            "temporal_association_null": "999 joint date permutations; preserves the spatial field within each date",
        },
        "noise": noise, "time_series": ts, "sensitivity_including_excluded_dates": incl, "change_vs_first": chg, "region_differentials_first_last": diffs,
        "range_dependence_check": rng_dep, "persistence": pers,
        "independent": {"dswx_s1_match": match, "dswx_s1_region_fractions": s1_tab, "dswx_hls_region_fractions": hls_tab,
                        "class_signatures": sig, "spatial_association": spatial, "change_association": change_assoc,
                        "temporal_association_cells": temporal, "temporal_association_regions": region_temporal,
                        "persistent_open_water_cells": int(pow_cells.sum()), "persistent_open_water_hh_db": pow_series},
        "rain": {"source": power["request"], "antecedent_mm": rain, "association": rain_assoc,
                 "rain_plus_trend_model": rain_model},
        "distance_profile": profile, "dswx_strata": strata_ts,
        "interpretation": {"rule": INTERP_RULE, "counts": interp_counts, "by_region": interp_by_region},
        "decision_gate": gate,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    R_assert_finite_json(results)
    (out_dir / "timeseries_results.json").write_text(json.dumps(results, indent=1, allow_nan=False), encoding="utf-8")
    log(f"wrote {out_dir / 'timeseries_results.json'}")

    arrays = dict(dates=dates, hv_idx=hv_idx, hh_db=hh_db, hv_db=hv_db, d_first_last_hh=d_first_last_hh,
                  d_first_last_hv=d_first_last_hv, slope_hh=slope_hh, slope_hv=slope_hv, pers_maps=pers_maps,
                  cell_hh_db=cell_hh_db, cell_hv_db=cell_hv_db, cell_ratio_db=cell_ratio_db, iv=iv, ow=ow,
                  mdates=mdates, match=match, interp=interp, full_rho=full_rho, hv_slope=hv_slope,
                  transform=ref_grid[1], epsg=ref_grid[0], valid_hh=valid_hh, valid_hv=valid_hv, ref=ref)
    if make_figures:
        import ts_figures
        ts_figures.make_all(results, arrays, out_dir / "figures", log=log)
    if web_dir is not None:
        import ts_figures
        ts_figures.write_web(results, arrays, web_dir, log=log)
    return results


def R_assert_finite_json(obj, path="$"):
    """Replace NaN/inf by None in-place-safe copy check (JSON must be strict)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, float) and not math.isfinite(v):
                obj[k] = None
            else:
                R_assert_finite_json(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, float) and not math.isfinite(v):
                obj[i] = None
            else:
                R_assert_finite_json(v, f"{path}[{i}]")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--cache-dir", default=str(root / "data/derived/cache"))
    ap.add_argument("--ref-dir", default=str(root / "data/reference"))
    ap.add_argument("--power", default=str(root / "data/ancillary/nasa_power_sudd_2026.json"))
    ap.add_argument("--out-dir", default=str(root / "data/derived/timeseries"))
    ap.add_argument("--web-dir", default=str(root / "web/data"))
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--no-web", action="store_true")
    a = ap.parse_args(argv)
    run(Path(a.cache_dir), Path(a.ref_dir), Path(a.power), Path(a.out_dir),
        None if a.no_web else Path(a.web_dir), make_figures=not a.no_figures)


if __name__ == "__main__":
    main()
