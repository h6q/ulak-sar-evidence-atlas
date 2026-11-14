"""Read a small area-of-interest window from a NISAR L2 GCOV HDF5 granule.

ULAK - SAR Evidence Atlas (NASA Space Apps Challenge 2026).
AI-assisted implementation (generative AI was used to draft this module);
the ULAK team reviews, runs and owns the scientific decisions.

Design rules
------------
* Never guess the file layout silently. The documented group
  ``/science/LSAR/GCOV/grids/frequency{A|B}`` (ASF NISAR docs, GCOV page) is
  *checked* in the real file; if anything is missing we raise with the list of
  what the file actually contains.
* Read only the AOI window (HTTP range requests when the file is remote), so a
  ~1.8 GB granule is never downloaded in full.
* Record every attribute we relied on (units, descriptions, fill values) so the
  report can show *evidence* for its unit and registration assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Any

import numpy as np

GRID_ROOT = "/science/LSAR/GCOV/grids"
IDENT_GROUP = "/science/LSAR/identification"
DIAGONAL_TERMS = ("HHHH", "HVHV", "VHVH", "VVVV")
# identification keys we try to compare against the CMR catalog when present
IDENT_KEYS_OF_INTEREST = (
    "trackNumber", "frameNumber", "orbitPassDirection", "zeroDopplerStartTime",
    "zeroDopplerEndTime", "absoluteOrbitNumber", "granuleId", "productVersion",
    "compositeReleaseId", "isFullFrame", "listOfFrequencies", "lookDirection",
    "productType", "processingType", "radarBand", "missionId", "isUrgentObservation",
)


class GCOVLayoutError(ValueError):
    """Raised when the HDF5 file does not contain the expected GCOV layout."""


MAX_JSON_ITEMS = 64
MAX_STR = 4000


def _ref_name(ref, h5file):
    """Resolve an HDF5 object reference to the referenced object's path, if possible."""
    if h5file is None:
        return None
    try:
        return h5file[ref].name
    except Exception:
        return None


def to_jsonable(value: Any, h5file=None, _depth: int = 0) -> Any:
    """Explicitly convert HDF5/NumPy metadata to JSON-safe values.

    Never returns an object json cannot encode. Representations:
    * bytes / numpy bytes          -> UTF-8 text (invalid bytes replaced)
    * numpy scalars                -> Python int/float/bool; non-finite floats -> None
    * h5py object reference        -> {"hdf5_object_reference": "/path"} (or "<unresolved>"); null ref -> None
    * h5py region reference        -> {"hdf5_region_reference": "/path" or "<unresolved>"}
    * structured (compound) values -> {field: value}
    * arrays                       -> list (<= 64 items) else a "<array shape=.. dtype=..>" summary
    * anything else                -> "<unserializable: TypeName>" (explicit, never silent)
    """
    import h5py
    if _depth > 8:
        return "<max depth reached>"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if len(value) <= MAX_STR else value[:MAX_STR] + "...<truncated>"
    if isinstance(value, (bytes, bytearray, np.bytes_)):
        return to_jsonable(bytes(value).decode("utf-8", errors="replace").rstrip("\x00").strip(), h5file, _depth + 1)
    if isinstance(value, h5py.RegionReference):
        if not value:
            return None
        return {"hdf5_region_reference": _ref_name(value, h5file) or "<unresolved>"}
    if isinstance(value, h5py.Reference):
        if not value:
            return None
        return {"hdf5_object_reference": _ref_name(value, h5file) or "<unresolved>"}
    if isinstance(value, np.void):  # one record of a compound type (e.g. REFERENCE_LIST)
        if value.dtype.names:
            return {n: to_jsonable(value[n], h5file, _depth + 1) for n in value.dtype.names}
        return f"<opaque bytes len={len(bytes(value))}>"
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return to_jsonable(value[()], h5file, _depth + 1)
        if value.size > MAX_JSON_ITEMS:
            return f"<array shape={list(value.shape)} dtype={value.dtype}>"
        return [to_jsonable(v, h5file, _depth + 1) for v in value.reshape(-1)]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, (complex, np.complexfloating)):
        c = complex(value)
        return {"real": to_jsonable(c.real), "imag": to_jsonable(c.imag)}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v, h5file, _depth + 1) for v in list(value)[:MAX_JSON_ITEMS]]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, h5file, _depth + 1) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return f"<unserializable: {type(value).__name__}>"


def decode(value: Any) -> Any:
    """Backward-compatible alias (no file handle, so references stay unresolved but JSON-safe)."""
    return to_jsonable(value)


def attrs_dict(obj, limit: int = 40) -> dict:
    """All attributes of an HDF5 object as JSON-safe values; references resolved to object paths."""
    h5file = getattr(obj, "file", None)
    out = {}
    for i, k in enumerate(obj.attrs.keys()):
        if i >= limit:
            out["_truncated"] = True
            break
        try:
            out[str(k)] = to_jsonable(obj.attrs[k], h5file)
        except Exception as exc:  # unreadable attribute type: say so explicitly
            out[str(k)] = f"<unreadable attribute: {type(exc).__name__}>"
    return out


def read_identification(h5) -> dict:
    """Return scalar/small datasets under /science/LSAR/identification."""
    if IDENT_GROUP not in h5:
        return {"_missing_group": IDENT_GROUP}
    grp = h5[IDENT_GROUP]
    out = {}
    for name, obj in grp.items():
        if hasattr(obj, "shape") and (obj.shape == () or (len(obj.shape) == 1 and obj.shape[0] <= 64)):
            try:
                out[name] = to_jsonable(obj[()], h5)
            except Exception as exc:  # pragma: no cover
                out[name] = f"<unreadable: {type(exc).__name__}>"
    return out


def list_group(h5, path: str) -> list[str]:
    if path not in h5:
        return []
    return sorted(h5[path].keys())


def frequency_group(h5, frequency: str = "A"):
    if frequency not in ("A", "B"):
        raise ValueError("frequency must be 'A' or 'B'")
    path = f"{GRID_ROOT}/frequency{frequency}"
    if path not in h5:
        raise GCOVLayoutError(
            f"Expected GCOV group {path} not found. Groups under {GRID_ROOT}: {list_group(h5, GRID_ROOT)}; "
            f"top-level: {sorted(h5.keys())}")
    return h5[path], path


def available_terms(group) -> list[str]:
    return [t for t in DIAGONAL_TERMS if t in group]


def _registration_from_description(desc: str | None) -> tuple[str, bool]:
    """Infer pixel registration from the coordinate dataset description.

    Returns (registration, evidenced). registration in {'center','edge'}.
    If the description is silent we assume 'center' and report evidenced=False.
    """
    if desc:
        d = str(desc).lower()
        if "center" in d or "centre" in d:
            return "center", True
        if "corner" in d or "edge" in d or "upper left" in d or "upper-left" in d:
            return "edge", True
    return "center", False


@dataclass
class GridInfo:
    epsg: int
    x: np.ndarray
    y: np.ndarray
    dx: float
    dy: float
    registration: str
    registration_evidenced: bool
    x_attrs: dict
    y_attrs: dict
    projection_attrs: dict

    def window_transform(self, r0: int, c0: int):
        from rasterio.transform import Affine
        if self.registration == "center":
            x0 = float(self.x[c0]) - self.dx / 2.0
            y0 = float(self.y[r0]) - self.dy / 2.0
        else:
            x0 = float(self.x[c0])
            y0 = float(self.y[r0])
        return Affine(self.dx, 0.0, x0, 0.0, self.dy, y0)


def grid_info(group) -> GridInfo:
    missing = [k for k in ("xCoordinates", "yCoordinates", "projection") if k not in group]
    if missing:
        raise GCOVLayoutError(f"GCOV frequency group lacks {missing}; contains {sorted(group.keys())}")
    x = np.asarray(group["xCoordinates"][()], dtype="float64")
    y = np.asarray(group["yCoordinates"][()], dtype="float64")
    if x.ndim != 1 or y.ndim != 1 or x.size < 2 or y.size < 2:
        raise GCOVLayoutError("xCoordinates/yCoordinates must be 1-D vectors with at least 2 elements")
    proj = group["projection"]
    pattrs = attrs_dict(proj)
    epsg = pattrs.get("epsg_code")
    if epsg is None:
        try:
            epsg = int(decode(proj[()]))
        except Exception:
            epsg = None
    if epsg is None:
        raise GCOVLayoutError(f"Cannot determine EPSG code from projection dataset attributes: {pattrs}")
    epsg = int(epsg)
    dxs = np.diff(x)
    dys = np.diff(y)
    dx, dy = float(np.median(dxs)), float(np.median(dys))
    if dx <= 0:
        raise GCOVLayoutError("xCoordinates must increase")
    if not (np.allclose(dxs, dx, rtol=0, atol=abs(dx) * 1e-6) and np.allclose(dys, dy, rtol=0, atol=abs(dy) * 1e-6)):
        raise GCOVLayoutError("Coordinate spacing is not uniform; refusing to build an affine transform")
    for name in ("xCoordinateSpacing", "yCoordinateSpacing"):
        if name in group:
            declared = float(decode(group[name][()]))
            actual = dx if name.startswith("x") else dy
            if not math.isclose(declared, actual, rel_tol=1e-6, abs_tol=1e-6):
                raise GCOVLayoutError(f"{name}={declared} disagrees with coordinate vector spacing {actual}")
    xa, ya = attrs_dict(group["xCoordinates"]), attrs_dict(group["yCoordinates"])
    convention = xa.get("pixel_coordinate_convention")
    reg, evid = _registration_from_description(convention if convention is not None else xa.get("description"))
    return GridInfo(epsg, x, y, dx, dy, reg, evid, xa, ya, pattrs)


def densify_bbox(bbox, n: int = 16):
    """bbox = (west, south, east, north) lon/lat -> densified ring lon/lat lists."""
    w, s, e, nn = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < nn <= 90):
        raise ValueError(f"Invalid lon/lat bbox (west,south,east,north): {bbox}")
    lons, lats = [], []
    for t in np.linspace(0, 1, n):
        lons += [w + (e - w) * t, e, e - (e - w) * t, w]
        lats += [s, s + (nn - s) * t, nn, nn - (nn - s) * t]
    return lons, lats


def aoi_window(grid: GridInfo, bbox_lonlat) -> tuple[int, int, int, int]:
    """Return (r0, r1, c0, c1) half-open index window covering the AOI."""
    from rasterio.warp import transform as warp_transform
    lons, lats = densify_bbox(bbox_lonlat)
    xs, ys = warp_transform("EPSG:4326", f"EPSG:{grid.epsg}", lons, lats)
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    cols = np.where((grid.x >= xmin) & (grid.x <= xmax))[0]
    rows = np.where((grid.y >= ymin) & (grid.y <= ymax))[0]
    if cols.size == 0 or rows.size == 0:
        raise ValueError("AOI does not overlap this granule's grid")
    full = (xmin >= grid.x.min() and xmax <= grid.x.max() and ymin >= grid.y.min() and ymax <= grid.y.max())
    if not full:
        raise ValueError("AOI is only partially inside this granule's grid; choose an AOI fully inside the frame")
    return int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1


@dataclass
class GCOVWindow:
    frequency: str
    group_path: str
    epsg: int
    transform: Any
    window: tuple[int, int, int, int]
    x: np.ndarray
    y: np.ndarray
    terms: dict = field(default_factory=dict)          # name -> float32 2-D linear power
    term_attrs: dict = field(default_factory=dict)
    mask: np.ndarray | None = None
    mask_attrs: dict = field(default_factory=dict)
    nlooks: np.ndarray | None = None
    identification: dict = field(default_factory=dict)
    grid: GridInfo | None = None
    available_terms: list = field(default_factory=list)
    group_keys: list = field(default_factory=list)
    extra_metadata: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def checksum(self, name: str) -> str:
        arr = np.ascontiguousarray(self.terms[name])
        return hashlib.sha256(arr.tobytes()).hexdigest()


def find_datasets(h5, needle: str, root: str = "/science/LSAR/GCOV/metadata", limit: int = 20) -> dict:
    """Search dataset names containing `needle` (case-insensitive) under root; return scalar values."""
    found = {}
    if root not in h5:
        return found
    needle_l = needle.lower()

    def visitor(name, obj):
        if len(found) >= limit:
            return True
        if needle_l in name.lower() and hasattr(obj, "shape") and obj.shape in ((), (1,)):
            try:
                found[f"{root}/{name}"] = to_jsonable(obj[()], h5)
            except Exception:
                pass
        return None

    h5[root].visititems(visitor)
    return found


def read_gcov_window(h5, bbox_lonlat, *, frequency: str = "A", terms=("HHHH", "HVHV"),
                     read_nlooks: bool = False) -> GCOVWindow:
    group, path = frequency_group(h5, frequency)
    grid = grid_info(group)
    r0, r1, c0, c1 = aoi_window(grid, bbox_lonlat)
    present = available_terms(group)
    win = GCOVWindow(frequency=frequency, group_path=path, epsg=grid.epsg,
                     transform=grid.window_transform(r0, c0), window=(r0, r1, c0, c1),
                     x=grid.x[c0:c1].copy(), y=grid.y[r0:r1].copy(), grid=grid,
                     available_terms=present, group_keys=sorted(group.keys()))
    if not grid.registration_evidenced:
        win.warnings.append("Pixel registration not stated in xCoordinates metadata; pixel-centre registration assumed.")
    for t in terms:
        if t not in group:
            continue  # caller decides whether a missing term is fatal (e.g. SHSH granules have no HVHV)
        ds = group[t]
        if ds.ndim != 2:
            raise GCOVLayoutError(f"{path}/{t} is not 2-D (shape {ds.shape})")
        if ds.shape != (grid.y.size, grid.x.size):
            raise GCOVLayoutError(f"{path}/{t} shape {ds.shape} != (len(y), len(x)) = {(grid.y.size, grid.x.size)}")
        if ds.dtype.kind == "c":
            raise GCOVLayoutError(f"{path}/{t} is complex; diagonal terms must be real-valued power")
        a = np.asarray(ds[r0:r1, c0:c1], dtype="float32")
        at = attrs_dict(ds)
        fill = at.get("_FillValue")
        if isinstance(fill, (int, float)) and fill is not None and math.isfinite(float(fill)):
            a = np.where(a == np.float32(fill), np.float32(np.nan), a)
        win.terms[t] = a
        win.term_attrs[t] = at
    if "mask" in group:
        m = np.asarray(group["mask"][r0:r1, c0:c1])
        win.mask = m
        win.mask_attrs = attrs_dict(group["mask"])
    if read_nlooks and "numberOfLooks" in group:  # optional: same size as a backscatter layer
        win.nlooks = np.asarray(group["numberOfLooks"][r0:r1, c0:c1], dtype="float32")
    win.identification = read_identification(h5)
    try:
        win.extra_metadata = find_datasets(h5, "Convention")
    except Exception as exc:  # pragma: no cover
        win.warnings.append(f"Metadata search failed: {type(exc).__name__}")
    return win


def mask_rules(attrs: dict) -> list[str]:
    """Validity rules derived ONLY from what the file's own mask attributes state."""
    rules = []
    fv = attrs.get("_FillValue")
    if isinstance(fv, (int, float)) and not isinstance(fv, bool):
        rules.append(f"mask == {fv} (declared _FillValue: outside acquisition extent) -> invalid")
    desc = str(attrs.get("description", "")).lower()
    if "value 0" in desc and ("partially focused" in desc or "invalid" in desc):
        rules.append("mask == 0 (description: partially focused or invalid radar samples) -> invalid")
    return rules


def mask_summary(mask: np.ndarray | None, attrs: dict) -> dict:
    if mask is None:
        return {"present": False}
    vals, counts = np.unique(mask, return_counts=True)
    order = np.argsort(counts)[::-1][:20]
    inv = invalid_from_mask(mask, attrs)
    return {"present": True, "dtype": str(mask.dtype), "attributes": attrs,
            "value_counts_top20": {str(to_jsonable(vals[i])): int(counts[i]) for i in order},
            "validity_rules_applied": mask_rules(attrs),
            "invalid_samples": int(inv.sum()) if inv is not None else 0,
            "applied_as_validity": bool(mask_rules(attrs)),
            "note": ("Only rules stated by the file's own mask attributes are applied; other values (subswath numbers) are "
                     "recorded, not interpreted.")}


def invalid_from_mask(mask: np.ndarray | None, attrs: dict) -> np.ndarray | None:
    if mask is None:
        return None
    rules = mask_rules(attrs)
    if not rules:
        return None
    inv = np.zeros(mask.shape, dtype=bool)
    fv = attrs.get("_FillValue")
    if isinstance(fv, (int, float)) and not isinstance(fv, bool):
        inv |= mask == fv
    if any(r.startswith("mask == 0") for r in rules):
        inv |= mask == 0
    return inv
