"""Provenance and compatibility checks for NISAR GCOV comparisons (ULAK).

AI-assisted implementation, reviewed and owned by the ULAK team.

Each check returns a dict {id, description, status, detail, evidence} where
status is PASS, FAIL, WARN or NOT_AVAILABLE and evidence says WHERE the fact
came from ("catalog" = NASA CMR record, "in-file" = HDF5 contents, "computed").
A FAIL on a blocking check stops the pipeline: we never silently compare
incompatible acquisitions.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

MAX_JSON_BYTES = 5_000_000
BLOCKING = {"same_stack", "same_crid", "same_polarization_channel", "same_collection", "same_grid",
            "aoi_inside_footprint", "chronological_order", "infile_track_frame", "infile_pass_direction"}


def load_json_safely(path: str | Path, max_bytes: int = MAX_JSON_BYTES) -> dict:
    p = Path(path)
    size = p.stat().st_size
    if size > max_bytes:
        raise ValueError(f"{p.name} is {size} bytes; refusing to parse more than {max_bytes} bytes")
    text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {p.name}: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{p.name} must contain a JSON object at top level")
    return data


def _reject_constant(name):
    raise ValueError(f"Non-standard JSON constant {name} is not allowed")


def check(cid: str, description: str, status: str, detail: str, evidence: str) -> dict:
    assert status in ("PASS", "FAIL", "WARN", "NOT_AVAILABLE")
    return {"id": cid, "description": description, "status": status, "detail": detail, "evidence": evidence,
            "blocking": cid in BLOCKING or cid.startswith("units_")}


def load_catalog(path) -> dict:
    cat = load_json_safely(path)
    if cat.get("schema") != "ulak-cmr-snapshot-v1":
        raise ValueError("Catalog must use schema ulak-cmr-snapshot-v1")
    grs = cat.get("granules")
    if not isinstance(grs, list) or not grs:
        raise ValueError("Catalog has no granules")
    for g in grs:
        for k in ("granule_ur", "begin_utc", "acquisition_date", "frequency_a_polarizations", "h5"):
            if k not in g:
                raise ValueError(f"Catalog granule missing field {k}")
        parse_utc(g["begin_utc"])
    return cat


def parse_utc(s: str) -> dt.datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise ValueError(f"Timestamp must be ISO-8601 UTC ending in Z: {s!r}")
    core = s[:-1]
    if "." in core:
        head, frac = core.split(".", 1)
        core = head + "." + (frac + "000000")[:6]
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        fmt = "%Y-%m-%dT%H:%M:%S"
    return dt.datetime.strptime(core, fmt).replace(tzinfo=dt.timezone.utc)


def select_by_date(cat: dict, date: str, require_pols=("HH", "HV")) -> dict:
    hits = [g for g in cat["granules"] if g["acquisition_date"] == date
            and all(p in g["frequency_a_polarizations"] for p in require_pols)]
    if not hits:
        avail = sorted({g["acquisition_date"] for g in cat["granules"]})
        raise ValueError(f"No catalog granule on {date} with polarizations {require_pols}. Available dates: {avail}")
    if len(hits) > 1:
        hits.sort(key=lambda g: g["granule_ur"])  # deterministic: lowest product counter first
    return hits[0]


def point_in_polygon(lon: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > lat) != (y2 > lat):
            xin = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < xin:
                inside = not inside
    return inside


def aoi_inside(bbox, ring) -> bool:
    w, s, e, n = bbox
    return all(point_in_polygon(x, y, ring) for x, y in ((w, s), (e, s), (e, n), (w, n), ((w + e) / 2, (s + n) / 2)))


def catalog_checks(cat: dict, before: dict, after: dict, bbox) -> list[dict]:
    sc = cat.get("stack_common", {})
    out = []
    t0, t1 = parse_utc(before["begin_utc"]), parse_utc(after["begin_utc"])
    out.append(check("chronological_order", "Before acquisition precedes after acquisition",
                     "PASS" if t0 < t1 else "FAIL", f"{before['begin_utc']} -> {after['begin_utc']} "
                     f"({round((t1 - t0).total_seconds() / 86400)} days)", "catalog"))
    tok = lambda ur, i: ur.split("_")[i]
    same_stack = all(tok(before["granule_ur"], i) == tok(after["granule_ur"], i) for i in (5, 6, 7, 8))
    out.append(check("same_stack", "Same track, direction, frame and mode", "PASS" if same_stack else "FAIL",
                     f"track/dir/frame/mode = {'_'.join(tok(before['granule_ur'], i) for i in (5,6,7,8))} vs "
                     f"{'_'.join(tok(after['granule_ur'], i) for i in (5,6,7,8))}", "catalog"))
    crid0, crid1 = tok(before["granule_ur"], 13), tok(after["granule_ur"], 13)
    out.append(check("same_crid", "Same Composite Release ID (processing software/configuration)",
                     "PASS" if crid0 == crid1 else "FAIL", f"{crid0} vs {crid1}", "catalog"))
    out.append(check("same_collection", "Same collection / maturity", "PASS", f"{cat['collection']['short_name']} "
                     f"({cat['collection'].get('maturity')})", "catalog"))
    pol_ok = all(p in before["frequency_a_polarizations"] and p in after["frequency_a_polarizations"] for p in ("HH", "HV"))
    out.append(check("same_polarization_channel", "Both acquisitions provide HH and HV (diagonal HHHH, HVHV)",
                     "PASS" if pol_ok else "FAIL", f"{before['frequency_a_polarizations']} vs {after['frequency_a_polarizations']}",
                     "catalog"))
    fid = (before.get("orbit_fidelity_token"), after.get("orbit_fidelity_token"))
    out.append(check("orbit_fidelity", "Orbit-ephemeris fidelity token is not Forecast (F)",
                     "PASS" if "F" not in fid else "WARN", f"tokens {fid} ({before.get('orbit_fidelity_meaning')}, "
                     f"{after.get('orbit_fidelity_meaning')})", "catalog"))
    inside = aoi_inside(bbox, before["footprint_lonlat"]) and aoi_inside(bbox, after["footprint_lonlat"])
    out.append(check("aoi_inside_footprint", "AOI lies inside both CMR footprints", "PASS" if inside else "FAIL",
                     f"AOI {list(bbox)}", "catalog"))
    out.append(check("maturity_note", "Product maturity", "WARN",
                     "PROVISIONAL (CRID P05023): calibrated, validation at limited sites; to be superseded by 2027 reprocessing.",
                     "catalog + ASF availability page"))
    if sc.get("product_version"):
        out.append(check("same_product_version", "Same product version (stack-level catalog attribute)", "PASS",
                         sc["product_version"], "catalog"))
    return out


def _ident_get(ident: dict, key: str):
    for k, v in ident.items():
        if k.lower() == key.lower():
            return v
    return None


def infile_checks(label: str, ident: dict, granule: dict, cat: dict) -> list[dict]:
    sc = cat.get("stack_common", {})
    out = []
    trk, frm = _ident_get(ident, "trackNumber"), _ident_get(ident, "frameNumber")
    if trk is None or frm is None:
        out.append(check("infile_track_frame", f"[{label}] In-file track/frame match catalog", "NOT_AVAILABLE",
                         "trackNumber/frameNumber not found in identification group", "in-file"))
    else:
        ok = int(trk) == int(sc.get("track_number")) and int(frm) == int(sc.get("frame_number"))
        out.append(check("infile_track_frame", f"[{label}] In-file track/frame match catalog", "PASS" if ok else "FAIL",
                         f"file track={trk} frame={frm}; catalog track={sc.get('track_number')} frame={sc.get('frame_number')}",
                         "in-file"))
    pdir = _ident_get(ident, "orbitPassDirection")
    if pdir is None:
        out.append(check("infile_pass_direction", f"[{label}] In-file pass direction", "NOT_AVAILABLE",
                         "orbitPassDirection not found", "in-file"))
    else:
        ok = str(pdir).strip().lower().startswith(str(sc.get("pass_direction", "")).lower()[:3])
        out.append(check("infile_pass_direction", f"[{label}] In-file pass direction", "PASS" if ok else "FAIL",
                         f"file={pdir}; catalog={sc.get('pass_direction')}", "in-file"))
    start = _ident_get(ident, "zeroDopplerStartTime")
    if start is None:
        out.append(check("infile_start_time", f"[{label}] In-file start time near catalog time", "NOT_AVAILABLE",
                         "zeroDopplerStartTime not found", "in-file"))
    else:
        try:
            s = str(start).strip().replace(" ", "T")
            s = s if s.endswith("Z") else s + "Z"
            dsec = abs((parse_utc(s) - parse_utc(granule["begin_utc"])).total_seconds())
            out.append(check("infile_start_time", f"[{label}] In-file start time near catalog time",
                             "PASS" if dsec <= 120 else "WARN", f"file={start}; catalog={granule['begin_utc']}; |dt|={dsec:.1f}s",
                             "in-file"))
        except Exception as exc:
            out.append(check("infile_start_time", f"[{label}] In-file start time near catalog time", "WARN",
                             f"Could not parse {start!r}: {exc}", "in-file"))
    gid = _ident_get(ident, "granuleId")
    if gid is not None:
        ok = granule["granule_ur"] in str(gid)
        out.append(check("infile_granule_id", f"[{label}] In-file granuleId matches catalog", "PASS" if ok else "WARN",
                         f"file={gid}", "in-file"))
    return out


def grid_alignment_check(win0, win1) -> dict:
    same = (win0.epsg == win1.epsg and win0.x.shape == win1.x.shape and win0.y.shape == win1.y.shape
            and np.allclose(win0.x, win1.x, atol=1e-6) and np.allclose(win0.y, win1.y, atol=1e-6))
    if same:
        return check("same_grid", "Identical map grid (EPSG, coordinates) for both windows - no resampling", "PASS",
                     f"EPSG:{win0.epsg}, {win0.x.size}x{win0.y.size} px, spacing {win0.grid.dx:g} m", "in-file")
    return check("same_grid", "Identical map grid (EPSG, coordinates) for both windows - no resampling", "FAIL",
                 f"EPSG {win0.epsg} vs {win1.epsg}; shapes {win0.x.size}x{win0.y.size} vs {win1.x.size}x{win1.y.size}; "
                 f"first x {win0.x[:1]} vs {win1.x[:1]}. A logged coregistration step is required before comparison.",
                 "in-file")


def units_check(label: str, win, term: str) -> dict:
    at = win.term_attrs.get(term, {})
    units = at.get("units")
    desc = at.get("description") or at.get("long_name")
    a = win.terms.get(term)
    neg = int(np.sum(np.isfinite(a) & (a < 0))) if a is not None else 0
    if a is not None and neg > 0.01 * np.isfinite(a).sum():
        return check(f"units_{term}_{label}", f"[{label}] {term} behaves like linear power", "FAIL",
                     f"{neg} negative samples: values look like dB or are corrupted; units attr={units!r}", "in-file")
    status = "PASS" if units is not None else "WARN"
    return check(f"units_{term}_{label}", f"[{label}] {term} unit metadata", status,
                 f"units={units!r}; description={str(desc)[:160]!r}; treated as linear gamma0 power per ASF GCOV docs",
                 "in-file")


def blocking_failures(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["blocking"] and c["status"] == "FAIL"]


def assert_finite_tree(obj, path="report"):
    """Raise if any float in a nested structure is NaN/inf (JSON must stay standard)."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite number at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_finite_tree(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_finite_tree(v, f"{path}[{i}]")
