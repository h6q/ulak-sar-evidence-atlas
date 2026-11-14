#!/usr/bin/env python3
"""ULAK end-to-end workflow: real NISAR GCOV pixels -> dual-pol change evidence -> web report.

AI-assisted implementation (ULAK, NASA Space Apps 2026); the team runs it and
owns all scientific interpretation.

Typical use (Windows PowerShell, from the repository root):
    py analysis/run_sudd.py                      # prompts for an Earthdata token (hidden input)
    py analysis/run_sudd.py --no-series          # only the primary pair (fewer bytes)
    py analysis/run_sudd.py --source local --local-dir D:/nisar   # already downloaded .h5 files

Security: the Earthdata Login bearer token is read from the EARTHDATA_TOKEN
environment variable or typed at a hidden prompt. It is never written to disk,
logged, or embedded in any output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gcov_reader as gr  # noqa: E402
import provenance as pv  # noqa: E402
import report_builder as rb  # noqa: E402
import sar_change as sc  # noqa: E402

REPO = HERE.parent
DEFAULT_CATALOG = REPO / "data" / "catalog" / "sudd_086_A_005_cmr_snapshot.json"
DEFAULT_POWER = REPO / "data" / "ancillary" / "nasa_power_sudd_2026.json"
# Central Sudd AOI around the Bahr el Jebel channel (west, south, east, north), lon/lat degrees.
# Chosen by the team to lie well inside frame 086_A_005; verify visually on the basemap.
DEFAULT_AOI = (30.55, 7.00, 30.95, 7.40)
VERSION = "0.3.2"


_SECRETS: list[str] = []          # values that must never reach stdout, logs or files
_LOG_FILE: Path | None = None


def scrub(text: str) -> str:
    """Remove any registered secret (e.g. the Earthdata token) from text."""
    out = str(text)
    for sec in _SECRETS:
        if sec:
            out = out.replace(sec, "***REDACTED***")
    return out


def log(msg: str):
    line = scrub(f"[ULAK {dt.datetime.now().strftime('%H:%M:%S')}] {msg}")
    print(line, flush=True)
    if _LOG_FILE is not None:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def dump_json(obj, path: Path) -> None:
    """Write JSON atomically after explicit HDF5/NumPy conversion; refuse to write a registered secret."""
    text = json.dumps(gr.to_jsonable(obj), indent=1, allow_nan=False)
    if any(sec and sec in text for sec in _SECRETS):
        raise RuntimeError(f"Refusing to write {path.name}: it would contain a credential")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def get_token(env_name: str) -> str:
    tok = os.environ.get(env_name, "").strip()
    if tok:
        _SECRETS.append(tok)
        log(f"Using Earthdata token from environment variable {env_name} (value not shown).")
        return tok
    print("\nEarthdata Login bearer token required (create one at https://urs.earthdata.nasa.gov -> Generate Token).")
    print("Input is hidden and is NOT stored. Press Enter on an empty line to abort.")
    tok = getpass.getpass("Earthdata token: ").strip()
    if not tok:
        raise SystemExit("No token entered; aborting. (Nothing was downloaded.)")
    _SECRETS.append(tok)
    return tok


class Opener:
    """Opens a granule either over HTTPS (range reads) or from a local directory."""

    def __init__(self, source: str, local_dir: str | None, token, verify_md5: bool,
                 block_bytes: int = 4 * 1024 * 1024):
        # `token` may be a string or a zero-argument callable (asked only when a network read is really needed)
        self._token_src, self.local_dir, self.verify_md5 = token, local_dir, verify_md5
        self.source = source
        self._token = None
        self.block_bytes = int(block_bytes)
        self._fs = None
        self.bytes_read = {}

    @property
    def token(self):
        if self._token is None:
            self._token = self._token_src() if callable(self._token_src) else self._token_src
        return self._token

    def _http_fs(self):
        if self._fs is None:
            import fsspec
            self._fs = fsspec.filesystem("http", headers={"Authorization": f"Bearer {self.token}"},
                                         client_kwargs={"trust_env": True})
        return self._fs

    def open(self, g: dict):
        import h5py
        if self.source == "https":
            try:
                fobj = self._http_fs().open(g["h5"]["https"], "rb", block_size=self.block_bytes, cache_type="blockcache")
                return h5py.File(fobj, "r"), fobj, "https_range_read"
            except Exception as exc:
                raise RuntimeError(
                    f"HTTPS range read failed ({type(exc).__name__}: {str(exc)[:200]}). Check that the token is valid "
                    "and that you accepted the ASF/NISAR data-use terms in Earthdata Login. Fallback: rerun with "
                    "--source download (full-file download with MD5 verification).") from exc
        if self.source == "download":
            raw = Path(self.local_dir or (REPO / "data" / "raw"))
            raw.mkdir(parents=True, exist_ok=True)
            path = raw / g["h5"]["name"]
            if not path.exists():
                log(f"Downloading full granule {path.name} ({g['h5'].get('bytes', 0)/1e9:.2f} GB)...")
                tmp = path.with_suffix(".part")
                self._http_fs().get_file(g["h5"]["https"], str(tmp))
                tmp.replace(path)
            self.verify_md5 = True
            self.local_dir = str(raw)
            how = "local_file"
        else:
            how = "local_file"
        path = Path(self.local_dir) / g["h5"]["name"]
        if not path.exists():
            raise FileNotFoundError(f"Local granule not found: {path}")
        if self.verify_md5 and g["h5"].get("md5"):
            log(f"Verifying MD5 of {path.name} (this reads the whole file)...")
            h = hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(16 * 1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != g["h5"]["md5"]:
                raise ValueError(f"MD5 mismatch for {path.name}: expected {g['h5']['md5']} got {h.hexdigest()}")
        return h5py.File(path, "r"), None, how


CACHE_VERSION = 1


def _cache_key(g: dict, aoi, frequency: str, terms, read_nlooks: bool) -> str:
    raw = json.dumps({"v": CACHE_VERSION, "ur": g["granule_ur"], "md5": g["h5"].get("md5"), "aoi": [round(v, 6) for v in aoi],
                      "f": frequency, "t": sorted(terms), "nl": bool(read_nlooks)}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def save_window_cache(win, g: dict, how: str, cache_dir: Path, key: str) -> Path:
    """Persist a freshly read window (arrays + JSON-safe metadata) so later failures never cost a re-read."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    base = cache_dir / f"{g['acquisition_date']}_freq{win.frequency}_{key}"
    arrays = {f"term_{t}": a for t, a in win.terms.items()}
    if win.mask is not None:
        arrays["mask"] = win.mask
    if win.nlooks is not None:
        arrays["nlooks"] = win.nlooks
    arrays["x"], arrays["y"] = win.x, win.y
    tmp = base.with_name(base.name + ".tmp.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(base.with_suffix(".npz"))
    meta = {"cache_version": CACHE_VERSION, "granule_ur": g["granule_ur"], "pixel_source": how,
            "read_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "frequency": win.frequency, "group_path": win.group_path, "epsg": win.epsg,
            "transform": list(win.transform)[:6], "window": list(win.window),
            "grid": {"dx": win.grid.dx, "dy": win.grid.dy, "registration": win.grid.registration,
                     "registration_evidenced": win.grid.registration_evidenced, "x_attrs": win.grid.x_attrs,
                     "y_attrs": win.grid.y_attrs, "projection_attrs": win.grid.projection_attrs},
            "term_attrs": win.term_attrs, "mask_attrs": win.mask_attrs, "identification": win.identification,
            "available_terms": win.available_terms, "group_keys": win.group_keys,
            "extra_metadata": win.extra_metadata, "warnings": win.warnings,
            "sha256_float32": {t: win.checksum(t) for t in win.terms}}
    dump_json(meta, base.with_suffix(".meta.json"))
    return base


def load_window_cache(g: dict, cache_dir: Path, key: str, frequency: str):
    """Return (GCOVWindow, pixel_source) from cache, or None if absent/corrupt (then we re-read)."""
    from rasterio.transform import Affine
    base = cache_dir / f"{g['acquisition_date']}_freq{frequency}_{key}"
    npz, mjs = base.with_suffix(".npz"), base.with_suffix(".meta.json")
    if not (npz.exists() and mjs.exists()):
        return None
    try:
        meta = pv.load_json_safely(mjs)
        if meta.get("cache_version") != CACHE_VERSION or meta.get("granule_ur") != g["granule_ur"]:
            return None
        with np.load(npz, allow_pickle=False) as z:
            terms = {k[5:]: z[k] for k in z.files if k.startswith("term_")}
            mask = z["mask"] if "mask" in z.files else None
            nlooks = z["nlooks"] if "nlooks" in z.files else None
            x, y = z["x"], z["y"]
        gm = meta["grid"]
        reg, evidenced = gr._registration_from_description(
            gm.get("x_attrs", {}).get("pixel_coordinate_convention") or gm.get("x_attrs", {}).get("description"))
        warnings_ = list(meta["warnings"])
        if evidenced:
            warnings_ = [w for w in warnings_ if not w.startswith("Pixel registration not stated")]
        grid = gr.GridInfo(meta["epsg"], x, y, gm["dx"], gm["dy"], reg, evidenced,
                           gm["x_attrs"], gm["y_attrs"], gm["projection_attrs"])
        win = gr.GCOVWindow(frequency=meta["frequency"], group_path=meta["group_path"], epsg=meta["epsg"],
                            transform=Affine(*meta["transform"]), window=tuple(meta["window"]), x=x, y=y,
                            terms=terms, term_attrs=meta["term_attrs"], mask=mask, mask_attrs=meta["mask_attrs"],
                            nlooks=nlooks, identification=meta["identification"], grid=grid,
                            available_terms=meta["available_terms"], group_keys=meta["group_keys"],
                             extra_metadata=meta["extra_metadata"], warnings=warnings_)
        for t in terms:  # integrity check: cached pixels must be bit-identical to what was read
            if win.checksum(t) != meta["sha256_float32"].get(t):
                log(f"  cache integrity check FAILED for {base.name} {t}; re-reading from NASA")
                return None
        win.cache_info = {"cache_file": npz.name, "originally_read_utc": meta["read_utc"]}
        return win, meta["pixel_source"]
    except Exception as exc:
        log(f"  cache unreadable ({type(exc).__name__}); re-reading from NASA")
        return None


def read_granule(opener: Opener, g: dict, aoi, frequency: str, terms, *, cache_dir: Path | None = None,
                 read_nlooks: bool = False) -> tuple:
    key = _cache_key(g, aoi, frequency, terms, read_nlooks)
    if cache_dir is not None:
        hit = load_window_cache(g, cache_dir, key, frequency)
        if hit is not None:
            log(f"  {g['acquisition_date']}: reused verified window cache (originally {hit[1]}, no network)")
            return hit
    t0 = time.time()
    h5, fobj, how = opener.open(g)
    try:
        win = gr.read_gcov_window(h5, aoi, frequency=frequency, terms=terms, read_nlooks=read_nlooks)
    finally:
        h5.close()
        if fobj is not None:
            fobj.close()
    log(f"  read {g['acquisition_date']} {[t for t in win.terms]} window {win.window} in {time.time() - t0:.1f}s ({how})")
    if cache_dir is not None:  # persist BEFORE any further processing
        base = save_window_cache(win, g, how, cache_dir, key)
        log(f"  cached window -> {base.name}.npz")
    return win, how


def write_geotiffs(win, g: dict, out_dir: Path, how: str) -> list[str]:
    """Write each extracted term as a GeoTIFF + JSON sidecar with the essential raster metadata."""
    import rasterio
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for term, arr in win.terms.items():
        fn = out_dir / f"{g['acquisition_date']}_{term}_freq{win.frequency}_gamma0_linear.tif"
        units = win.term_attrs.get(term, {}).get("units")
        pol = {"HHHH": "HH", "HVHV": "HV", "VVVV": "VV", "VHVH": "VH"}.get(term, term)
        tmp = fn.with_name(fn.name + ".tmp")
        with rasterio.open(tmp, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                           dtype="float32", crs=f"EPSG:{win.epsg}", transform=win.transform, nodata=np.nan,
                           compress="deflate") as dst:
            dst.write(arr.astype("float32"), 1)
            dst.update_tags(SOURCE_GRANULE=g["granule_ur"], SOURCE_TERM=f"{win.group_path}/{term}",
                            POLARIZATION=pol, COVARIANCE_TERM=term,
                            ACQUISITION_START_UTC=g["begin_utc"], ACQUISITION_END_UTC=g.get("end_utc", ""),
                            UNITS_ATTRIBUTE=str(units), QUANTITY="gamma0 linear power (RTC), per ASF NISAR GCOV documentation",
                            NODATA="NaN", PIXEL_REGISTRATION=win.grid.registration, PIXEL_SOURCE=how)
            dst.set_band_description(1, f"{term} gamma0 linear power")
        tmp.replace(fn)
        side = {"granule_ur": g["granule_ur"], "cmr_concept_id": g.get("cmr_concept_id"),
                "acquisition_begin_utc": g["begin_utc"], "acquisition_end_utc": g.get("end_utc"),
                "dataset_path": f"{win.group_path}/{term}", "polarization": term, "polarization_channel": pol,
                "units_attribute": units, "attributes": win.term_attrs.get(term, {}),
                "crs": f"EPSG:{win.epsg}", "transform": list(win.transform)[:6], "shape": list(arr.shape),
                "pixel_spacing_m": [win.grid.dx, win.grid.dy], "nodata": "NaN (IEEE-754 float32)",
                "window_rows_cols": list(win.window), "epsg": win.epsg,
                "pixel_registration": win.grid.registration, "registration_evidenced": win.grid.registration_evidenced,
                "sha256_float32": win.checksum(term), "pixel_source": how,
                "extracted_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
        dump_json(side, fn.with_suffix(".json"))
        written.append(fn.name)
    return written


def apply_mask(win) -> None:
    inv = gr.invalid_from_mask(win.mask, win.mask_attrs)
    if inv is not None:
        for t in win.terms:
            win.terms[t] = np.where(inv, np.nan, win.terms[t])


def multilooked(win, k: int) -> dict:
    return {t: sc.block_mean(a, k) for t, a in win.terms.items()}


def build_parser():
    p = argparse.ArgumentParser(description="ULAK Sudd NISAR GCOV change workflow")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    p.add_argument("--power", default=str(DEFAULT_POWER))
    p.add_argument("--aoi", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"), default=DEFAULT_AOI)
    p.add_argument("--aoi-name", default="Central Sudd - Bahr el Jebel (NISAR frame 086_A_005)")
    p.add_argument("--before", default="2026-06-20", help="Acquisition date YYYY-MM-DD from the catalog")
    p.add_argument("--after", default="2026-10-18")
    p.add_argument("--frequency", default="A", choices=["A", "B"])
    p.add_argument("--multilook", type=int, default=5, help="k x k incoherent averaging before differencing")
    p.add_argument("--cell-px", type=int, default=10, help="Cell size for clickable footprints, in multilooked pixels")
    p.add_argument("--floor-db", type=float, default=3.0)
    p.add_argument("--sigma", type=float, default=3.0)
    p.add_argument("--ratio-db", type=float, default=2.0)
    p.add_argument("--series", dest="series", action="store_true", default=True)
    p.add_argument("--no-series", dest="series", action="store_false")
    p.add_argument("--source", choices=["https", "download", "local"], default="https",
                   help="https: range-read AOI only (default); download: full files to data/raw + MD5; local: existing files")
    p.add_argument("--local-dir")
    p.add_argument("--verify-md5", action="store_true", help="Local mode: verify full-file MD5 against CMR")
    p.add_argument("--token-env", default="EARTHDATA_TOKEN")
    p.add_argument("--block-mb", type=float, default=4.0, help="HTTP range-read block size in MiB")
    p.add_argument("--cache-dir", default=None,
                   help="Verified window cache (default: <derived-dir>/cache; reused on rerun; delete to force a fresh read)")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--read-nlooks", action="store_true", help="Also read numberOfLooks (+1 float layer of transfer)")
    p.add_argument("--log-file", help="UTF-8 log file (credentials are scrubbed)")
    p.add_argument("--derived-dir", default=str(REPO / "data" / "derived"))
    p.add_argument("--web-out", default=str(REPO / "web" / "data"))
    p.add_argument("--report-name", default="sudd_report.json")
    return p


def main(argv=None) -> int:
    global _LOG_FILE
    args = build_parser().parse_args(argv)
    if args.log_file:
        _LOG_FILE = Path(args.log_file)
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if args.multilook < 1 or args.cell_px < 1:
        raise SystemExit("--multilook and --cell-px must be >= 1")
    aoi = tuple(float(v) for v in args.aoi)
    gr.densify_bbox(aoi)  # validates order and ranges
    cat = pv.load_catalog(args.catalog)
    synthetic = bool(cat.get("synthetic_fixture"))
    before = pv.select_by_date(cat, args.before)
    after = pv.select_by_date(cat, args.after)
    log(f"Before: {before['granule_ur']}")
    log(f"After : {after['granule_ur']}")
    checks = pv.catalog_checks(cat, before, after, aoi)
    bad = pv.blocking_failures(checks)
    if bad:
        for c in bad:
            log(f"BLOCKING FAIL {c['id']}: {c['detail']}")
        return 2
    if args.source == "local" and not args.local_dir:
        raise SystemExit("--source local requires --local-dir")
    token = (lambda: get_token(args.token_env)) if args.source in ("https", "download") else None
    if not (0.0625 <= args.block_mb <= 64):
        raise SystemExit("--block-mb must be between 0.0625 and 64")
    opener = Opener(args.source, args.local_dir, token, args.verify_md5, int(args.block_mb * 1024 * 1024))
    if args.no_cache or args.source == "local":
        cache_dir = None
    else:  # synthetic test catalogs never share a cache directory with real data
        cache_dir = Path(args.cache_dir) if args.cache_dir else Path(args.derived_dir) / ("cache_synthetic" if synthetic else "cache")
    derived = Path(args.derived_dir)
    wins, hows = {}, {}
    for label, g in (("before", before), ("after", after)):
        win, how = read_granule(opener, g, aoi, args.frequency, ("HHHH", "HVHV"), cache_dir=cache_dir,
                                read_nlooks=args.read_nlooks)
        for t in ("HHHH", "HVHV"):
            if t not in win.terms:
                raise SystemExit(f"{label} granule lacks {t}; terms present: {win.available_terms}")
        checks += pv.infile_checks(label, win.identification, g, cat)
        checks += [pv.units_check(label, win, t) for t in ("HHHH", "HVHV")]
        write_geotiffs(win, g, derived, how)
        wins[label], hows[label] = win, how
    checks.append(pv.grid_alignment_check(wins["before"], wins["after"]))
    bad = pv.blocking_failures(checks)
    if bad:
        for c in bad:
            log(f"BLOCKING FAIL {c['id']}: {c['detail']}")
        dump_json(checks, derived / "BLOCKED_checks.json")
        return 3

    k = args.multilook
    for w in wins.values():
        apply_mask(w)
    ml0, ml1 = multilooked(wins["before"], k), multilooked(wins["after"], k)
    res = sc.dual_pol_change(ml0["HHHH"], ml0["HVHV"], ml1["HHHH"], ml1["HVHV"],
                             floor_db=args.floor_db, sigma=args.sigma, ratio_db=args.ratio_db)
    st = res["stats"]
    from rasterio.transform import Affine
    pixel_area_m2 = abs(wins["before"].grid.dx * wins["before"].grid.dy) * k * k
    diag = sc.diagnostics(res, pixel_area_m2=pixel_area_m2)
    t0 = wins["before"].transform
    ml_t = t0 @ Affine.scale(k, k)
    spacing = abs(wins["before"].grid.dx) * k
    gj = rb.cells_geojson(res["classes"], res["d_hh"], res["d_hv"], ml_t, wins["before"].epsg, cell_px=args.cell_px)
    web_out = Path(args.web_out)
    overlays = rb.write_overlays(web_out, "sudd", ml_t, wins["before"].epsg, hh0_db=res["db"]["hh0"],
                                 hh1_db=res["db"]["hh1"], d_hh=res["d_hh"], classes=res["classes"])

    series = []
    if args.series:
        log("Time series: reading every catalog acquisition over the same AOI...")
        for g in sorted(cat["granules"], key=lambda x: x["begin_utc"]):
            try:
                if g is before:
                    w = wins["before"]
                elif g is after:
                    w = wins["after"]
                else:
                    terms = ("HHHH", "HVHV") if "HV" in g["frequency_a_polarizations"] else ("HHHH",)
                    w, _ = read_granule(opener, g, aoi, args.frequency, terms, cache_dir=cache_dir,
                                        read_nlooks=args.read_nlooks)
                    apply_mask(w)
                ml = multilooked(w, k)
                same = pv.grid_alignment_check(wins["before"], w)["status"] == "PASS"
                entry = {"date": g["acquisition_date"], "granule_ur": g["granule_ur"],
                         "polarizations": g["frequency_a_polarizations"],
                         "orbit_fidelity_token": g.get("orbit_fidelity_token"),
                         "hh_median_db": None, "hv_median_db": None, "zones": {}, "same_grid_as_pair": same}
                hh = sc.to_db(ml["HHHH"])
                entry["hh_median_db"] = float(np.nanmedian(hh)) if np.isfinite(hh).any() else None
                entry["valid_fraction"] = float(np.isfinite(hh).mean())
                hv = sc.to_db(ml["HVHV"]) if "HVHV" in ml else None
                if hv is not None and np.isfinite(hv).any():
                    entry["hv_median_db"] = float(np.nanmedian(hv))
                if same and hh.shape == res["classes"].shape:
                    for hy in sc.HYPOTHESES[:3]:
                        z = res["classes"] == hy["code"]
                        if z.sum() >= 10:
                            entry["zones"][hy["id"]] = {
                                "hh_median_db": float(np.nanmedian(hh[z])),
                                "hv_median_db": (float(np.nanmedian(hv[z])) if hv is not None else None),
                                "pixels": int(z.sum())}
                series.append(entry)
            except Exception as exc:  # keep going; record the failure prominently
                series.append({"date": g["acquisition_date"], "granule_ur": g["granule_ur"],
                               "error": f"{type(exc).__name__}: {exc}"})
                log(f"  series entry failed for {g['acquisition_date']}: {exc}")

    power = None
    if Path(args.power).exists():
        pw = pv.load_json_safely(args.power)
        tot = sum(p for d, p in zip(pw["dates"], pw["PRECTOTCORR"]) if args.before <= d <= args.after and p >= 0)
        power = {"source": pw["dataset"], "request": pw["request"], "point_lonlat": pw["point_lonlat"],
                 "precip_total_mm_between_acquisitions": round(float(tot), 2),
                 "limits": pw["interpretation_limits"]}

    warnings = list(dict.fromkeys(wins["before"].warnings + wins["after"].warnings))
    sw = sc.scene_shift_warning(st)
    if sw:
        warnings.append(sw)
    for c in checks:
        if c["status"] in ("WARN", "NOT_AVAILABLE"):
            warnings.append(f"{c['id']}: {c['detail']}")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def prov(label, g):
        w = wins[label]
        return {"granule_ur": g["granule_ur"], "cmr_concept_id": g.get("cmr_concept_id"),
                "acquisition_begin_utc": g["begin_utc"], "acquisition_end_utc": g.get("end_utc"),
                "orbit_number": g.get("orbit_number"), "orbit_fidelity_token": g.get("orbit_fidelity_token"),
                "h5_https": g["h5"]["https"], "h5_md5_catalog": g["h5"].get("md5"),
                "cmr_record": g.get("cmr_record"), "qa_report_pdf": g.get("qa_report_pdf"),
                "pixel_source": hows[label], "dataset_paths": [f"{w.group_path}/{t}" for t in ("HHHH", "HVHV")],
                "term_attributes": {t: w.term_attrs.get(t, {}) for t in ("HHHH", "HVHV")},
                "window_rows_cols": list(w.window),
                "sha256_float32": {t: w.checksum(t) for t in ("HHHH", "HVHV")},
                "identification_in_file": {kk: w.identification.get(kk) for kk in gr.IDENT_KEYS_OF_INTEREST
                                           if kk in w.identification},
                "mask": gr.mask_summary(w.mask, w.mask_attrs),
                "number_of_looks_median": (float(np.nanmedian(w.nlooks)) if w.nlooks is not None else None),
                "metadata_conventions_found": w.extra_metadata,
                "available_terms": w.available_terms,
                "window_cache": getattr(w, "cache_info", None)}

    rep = {
        "schema": rb.SCHEMA, "generated_utc": now, "software": {"name": "ULAK run_sudd.py", "version": VERSION,
                                                                "ai_assisted": True},
        "data_status": "SOFTWARE_TEST_SYNTHETIC" if synthetic else "MEASURED",
        "study_area": {"name": args.aoi_name, "aoi_bbox_wsen": list(aoi), "stack_id": cat["stack_common"]["stack_id"]},
        "provenance": {"catalog_snapshot": Path(args.catalog).name, "catalog_queried_utc": cat.get("queried_utc"),
                       "collection": cat["collection"], "stack_common": cat["stack_common"],
                       "before": prov("before", before), "after": prov("after", after)},
        "compatibility_checks": checks,
        "processing": {"frequency": args.frequency, "terms": ["HHHH", "HVHV"],
                       "input_quantity": "gamma0 backscatter, linear power, radiometrically terrain corrected (ASF GCOV docs)",
                       "conversion": "dB = 10*log10(linear), positive finite values only",
                       "native_spacing_m": abs(wins["before"].grid.dx), "multilook_factor": k,
                       "analysis_spacing_m": spacing, "crs": f"EPSG:{wins['before'].epsg}",
                       "pixel_registration": wins["before"].grid.registration,
                       "pixel_registration_evidenced": wins["before"].grid.registration_evidenced,
                       "resampling_for_statistics": "none (identical grids verified)",
                       "cell_size_m": spacing * args.cell_px, "derived_geotiffs_dir": str(Path(args.derived_dir).name),
                       "analysis_pixel_area_m2": pixel_area_m2,
                       "multilook_edge_rows_cols_dropped": [int(wins["before"].terms["HHHH"].shape[0] % k),
                                                            int(wins["before"].terms["HHHH"].shape[1] % k)],
                       "registration_uncertainty_m": (0.0 if wins["before"].grid.registration_evidenced
                                                      else abs(wins["before"].grid.dx) / 2.0),
                       "registration_note": ("Registration is identical for both dates (same grid), so dB differences are "
                                             "unaffected; only absolute map placement may be off by up to half a native pixel.")},
        "statistics": st,
        "histograms": {"delta_hh": rb.histogram(res["d_hh"]), "delta_hv": rb.histogram(res["d_hv"])},
        "diagnostics": diag,
        "hypotheses": sc.HYPOTHESES,
        "geojson": gj, "overlays": overlays, "time_series": series, "ancillary": {"nasa_power": power},
        "warnings": warnings,
        "limitations": [
            "Candidate radar backscatter change only: no class is a confirmed flood, wetland conversion or damage.",
            "No independent inundation reference (gauge, field survey or validated water map) was compared in this run.",
            "Thresholds are heuristic screening gates, not calibrated probabilities or accuracies.",
            "PROVISIONAL products (CRID P05023) may change in the announced 2027 reprocessing.",
            "Speckle is reduced by multilooking but not eliminated; isolated cells may be noise.",
            "Equatorial ionospheric effects, wind on open water and rain on canopy can alter L-band backscatter.",
            "Only two dates are compared in the primary analysis; the scene-wide positive shift cannot be attributed to a single cause.",
        ],
    }
    path = web_out / args.report_name
    n = rb.write_report(rep, path)
    log(f"Report written: {path} ({n/1e3:.0f} kB); cells={len(gj['features'])}")
    log(f"dHH median {st['delta_hh_db']['median']:+.2f} dB; dHV median {st['delta_hv_db']['median']:+.2f} dB; "
        f"classes {st['class_counts']}")
    log("Reminder: these are CANDIDATE radar backscatter changes, not confirmed flooding.")
    return 0


def cli() -> int:
    """Entry point: any crash is reported with credentials scrubbed (stdout, stderr and log file)."""
    import traceback
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        tb = scrub(traceback.format_exc())
        sys.stderr.write(tb)
        if _LOG_FILE is not None:
            with open(_LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(tb)
        log("FAILED - see traceback above. Cached windows (if any) will be reused on rerun.")
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
