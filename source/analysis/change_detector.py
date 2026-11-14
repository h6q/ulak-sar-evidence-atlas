#!/usr/bin/env python3
"""ULAK GCOV change candidates (v0.1). Original 2026 Space Apps work.

Takes two ALIGNED, GEOCODED, RADIOMETRICALLY COMPARABLE single-band GeoTIFFs
exported from NISAR GCOV (for example via NASA Harmony). Input values should
represent the same polarization's positive linear gamma0 power or dB.

NOT a validated hazard classifier, deformation estimator, or false alarm rate.
No NASA or ISRO approval or endorsement is implied.
AI-assisted code (generative AI drafted parts of this module); reviewed by the ULAK team.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import transform as coord_transform
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))


def process_arrays(before: np.ndarray, after: np.ndarray, *, unit: str = 'linear', floor_db: float = 3.0,
                   sigma: float = 3.0, nodata_before: float | None = None,
                   nodata_after: float | None = None):
    """Return candidate mask, robust delta diagnostic, and summary statistics.

    Classification threshold is max(floor_db, sigma * 1.4826 * MAD(delta)).
    No automatic median shift correction: absolute radiometric change remains visible.
    The robust MAD is diagnostic, not an uncertainty/confidence calibration.
    """
    before = np.asarray(before, dtype='float64')
    after = np.asarray(after, dtype='float64')
    if before.shape != after.shape or before.ndim != 2:
        raise ValueError('Both arrays must be aligned 2D images with matching shape.')
    if unit not in ('linear', 'db'):
        raise ValueError('unit must be linear or db')
    valid = np.isfinite(before) & np.isfinite(after)
    if nodata_before is not None and np.isfinite(nodata_before): valid &= (before != nodata_before)
    if nodata_after is not None and np.isfinite(nodata_after): valid &= (after != nodata_after)
    if unit == 'linear':
        valid &= (before > 0) & (after > 0)
    n = int(valid.sum())
    if n < 10:
        raise ValueError('Too few valid paired pixels for meaningful comparison (need at least 10).')
    delta = np.full(before.shape, np.nan, dtype='float64')
    if unit == 'linear':
        delta[valid] = 10.0 * (np.log10(after[valid]) - np.log10(before[valid]))
    else:
        delta[valid] = after[valid] - before[valid]
    values = delta[valid]
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    robust_scatter = 1.4826 * mad
    threshold = max(float(floor_db), float(sigma) * robust_scatter)
    # Criterion indicates large DIFFERENCES, not known event classes.
    mask = valid & (np.abs(delta) >= threshold)
    stats = {
        'valid_pixels':n,
        'candidate_pixels':int(mask.sum()),
        'candidate_fraction':float(mask.sum()/n),
        'threshold_db':float(threshold),
        'median_delta_db':med,
        'robust_scatter_db':float(robust_scatter),
        'unit':unit,
        'method':'absolute paired backscatter difference with robust MAD gate',
    }
    return mask, delta, stats


def cell_geojson(mask:np.ndarray, valid:np.ndarray, dataset, *, block_size:int=32,
                 min_fraction:float=0.30, max_features:int=300):
    """Coarse footprints; candidate cell summary, NOT pixel-precise affected area."""
    h,w=mask.shape
    cells=[]
    for row in range(0,h,block_size):
        for col in range(0,w,block_size):
            v=valid[row:row+block_size,col:col+block_size]
            denom=int(v.sum())
            if denom < 10: continue
            m=mask[row:row+block_size,col:col+block_size]
            frac=float(m.sum()/denom)
            if frac>=min_fraction: cells.append((frac,row,col,min(row+block_size,h),min(col+block_size,w)))
    cells=sorted(cells,reverse=True)[:max_features]
    features=[]
    for frac,r0,c0,r1,c1 in cells:
        pts=[]
        for c,r in [(c0,r0),(c1,r0),(c1,r1),(c0,r1),(c0,r0)]:
            x,y=dataset.transform@(c,r)
            if dataset.crs is None: raise ValueError('Input file must have a CRS.')
            if dataset.crs.to_epsg()!=4326:
                xs,ys=coord_transform(dataset.crs,'EPSG:4326',[float(x)],[float(y)])
                x,y=xs[0],ys[0]
            pts.append([round(float(x),6),round(float(y),6)])
        features.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[pts]},
                         'properties':{'fraction_candidate':round(frac,3),'note':'coarse exploratory bin'}})
    return {'type':'FeatureCollection','features':features}


def _load_sidecar(path):
    """Optional provenance sidecar written by run_sudd.py next to each GeoTIFF."""
    if path is None:
        return None
    from provenance import load_json_safely
    meta = load_json_safely(path)
    for k in ('granule_ur', 'polarization', 'dataset_path'):
        if k not in meta:
            raise ValueError(f'Sidecar {Path(path).name} lacks required field {k}')
    return meta


def compare_geotiffs(before, after, *, unit='linear', polarization, maturity, floor_db=3.0,
                     before_meta=None, after_meta=None):
    """Compare two single-band GeoTIFFs; returns a ulak-change-v1 report dict.

    Provenance is 'sidecar_verified' when both sidecars exist and agree with each other
    and with --polarization; otherwise it is explicitly 'user_declared'.
    """
    if not (isinstance(floor_db, (int, float)) and math.isfinite(floor_db) and floor_db > 0):
        raise ValueError('floor_db must be a finite positive number')
    mb, ma = _load_sidecar(before_meta), _load_sidecar(after_meta)
    prov_status = 'user_declared'
    if mb is not None or ma is not None:
        if mb is None or ma is None:
            raise ValueError('Provide sidecars for BOTH rasters or for neither.')
        pols = {mb['polarization'], ma['polarization'], polarization}
        if len(pols) != 1:
            raise ValueError(f'Polarization mismatch: before={mb["polarization"]} after={ma["polarization"]} '
                             f'declared={polarization}. Refusing to compare different channels.')
        if mb['granule_ur'] == ma['granule_ur']:
            raise ValueError('Before and after sidecars reference the same granule.')
        prov_status = 'sidecar_verified'
    with rasterio.open(before) as a, rasterio.open(after) as b:
        if a.count < 1 or b.count < 1:
            raise ValueError('Each GeoTIFF must contain at least one band.')
        if a.crs is None or b.crs is None:
            raise ValueError('GeoTIFFs need a valid geospatial CRS')
        if (a.width, a.height, a.crs, a.transform) != (b.width, b.height, b.crs, b.transform):
            raise ValueError('CRS, pixel grid, transform or dimensions differ. Co-register/reproject FIRST; never silently resample.')
        x = a.read(1, masked=False); y = b.read(1, masked=False)
        if unit == 'linear':
            finite = np.isfinite(x) & np.isfinite(y)
            if a.nodata is not None and np.isfinite(a.nodata): finite &= (x != a.nodata)
            if b.nodata is not None and np.isfinite(b.nodata): finite &= (y != b.nodata)
            if finite.any() and (np.mean(x[finite] < 0) > 0.01 or np.mean(y[finite] < 0) > 0.01):
                raise ValueError('Many negative values: inputs look like dB, not linear power. Use --unit db.')
        mask, delta, s = process_arrays(x, y, unit=unit, floor_db=floor_db, nodata_before=a.nodata, nodata_after=b.nodata)
        valid = np.isfinite(delta)
        crs_warning = ('Input CRS geographic; use projected equal-area CRS before area estimates.' if a.crs.is_geographic
                       else 'No affected-area estimate produced; coarse candidate cells are only a visualization.')
        geo = cell_geojson(mask, valid, a)
        s['positive_candidates'] = int((mask & (delta > 0)).sum())
        s['negative_candidates'] = int((mask & (delta < 0)).sum())
        report = {'schema': 'ulak-change-v1', 'provenance_status': prov_status,
                  'input': {'before': Path(before).name, 'after': Path(after).name,
                            'polarization_declared_by_user': polarization, 'maturity_declared_by_user': maturity,
                            'before_granule': mb['granule_ur'] if mb else None,
                            'after_granule': ma['granule_ur'] if ma else None,
                            'projection': a.crs.to_string(), 'shape': [a.height, a.width],
                            'geotransform': list(a.transform)[:6]},
                  'statistics': s, 'geojson': geo, 'warnings': [
                      ('Granule identity and polarization verified from run_sudd.py sidecars.' if mb else
                       'Acquisition dates, orbit, incidence angle and product maturity were NOT independently checked (user-declared).'),
                      'Same polarization, product units and radiometric calibration must be independently confirmed.',
                      'Change candidates are NOT confirmed floods, damage or subsidence; no causality inferred.',
                      'MAD is a robust variability measure; this is NOT a calibrated probability/confidence score.',
                      crs_warning,
                      'Potentially different GCOV processing versions could create artificial changes.']}
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', required=True, help='Before GCOV channel GeoTIFF')
    p.add_argument('--after', required=True, help='After GCOV channel GeoTIFF')
    p.add_argument('--unit', choices=['linear', 'db'], default='linear')
    p.add_argument('--polarization', required=True, help='Same channel in both, e.g. HHHH or VVVV')
    p.add_argument('--maturity', required=True, choices=['PROVISIONAL', 'VALIDATED', 'BETA'])
    p.add_argument('--before-meta', help='Optional provenance sidecar JSON (written by run_sudd.py)')
    p.add_argument('--after-meta', help='Optional provenance sidecar JSON (written by run_sudd.py)')
    p.add_argument('--output', default='change_report.json')
    p.add_argument('--floor-db', type=float, default=3.0)
    args = p.parse_args(argv)
    if args.floor_db <= 0:
        p.error('--floor-db must be positive')
    report = compare_geotiffs(args.before, args.after, unit=args.unit, polarization=args.polarization,
                              maturity=args.maturity, floor_db=args.floor_db,
                              before_meta=args.before_meta, after_meta=args.after_meta)
    s = report['statistics']
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Wrote {path} | valid={s["valid_pixels"]:,} candidates={s["candidate_pixels"]:,} threshold={s["threshold_db"]:.2f} dB')
    print('WARNING: exploratory screen, not a validated geophysical detection.')


if __name__ == '__main__':
    main()
