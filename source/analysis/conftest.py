# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Pytest configuration and SYNTHETIC test fixtures.

Everything produced here is a SOFTWARE TEST FIXTURE. It mimics the documented
GCOV group layout so the reader and pipeline can be exercised offline. It is
never an observation and must never be displayed as one.
"""
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parent
REAL_CATALOG = REPO / "data" / "catalog" / "sudd_086_A_005_cmr_snapshot.json"

EPSG = 32636
DX = 20.0
TEST_AOI = (30.70, 7.10, 30.73, 7.13)


def _utm(lon, lat):
    from rasterio.warp import transform
    xs, ys = transform("EPSG:4326", f"EPSG:{EPSG}", [lon], [lat])
    return xs[0], ys[0]


def make_synthetic_gcov(path: Path, *, seed: int, start_time: str, change: bool, track: int = 86,
                        pass_dir: str = "Ascending", terms=("HHHH", "HVHV"), x_shift: float = 0.0,
                        store_db: bool = False, n: int = 260):
    """Write a small GCOV-like HDF5 file (SYNTHETIC). Returns the path."""
    import h5py
    cx, cy = _utm(30.715, 7.115)
    x0 = round((cx - n * DX / 2) / DX) * DX + DX / 2 + x_shift
    y0 = round((cy + n * DX / 2) / DX) * DX - DX / 2
    x = x0 + DX * np.arange(n)
    y = y0 - DX * np.arange(n)
    rng = np.random.default_rng(seed)
    hh = 0.05 * rng.gamma(25, 1 / 25, size=(n, n))   # ~-13 dB, mild speckle (25 looks)
    hv = 0.01 * rng.gamma(25, 1 / 25, size=(n, n))   # ~-20 dB
    if change:
        hh[40:100, 40:100] *= 10 ** (6 / 10)   # +6 dB HH
        hv[40:100, 40:100] *= 10 ** (1 / 10)   # +1 dB HV  -> double-bounce hypothesis
        hh[140:200, 140:200] *= 10 ** (-7 / 10)
        hv[140:200, 140:200] *= 10 ** (-7 / 10)  # both down -> specular hypothesis
    hh[0:3, :] = np.nan                         # fill rows
    data = {"HHHH": hh, "HVHV": hv}
    with h5py.File(path, "w") as f:
        g = f.create_group("/science/LSAR/GCOV/grids/frequencyA")
        xd = g.create_dataset("xCoordinates", data=x)
        xd.attrs["description"] = np.bytes_("CF compliant dimension associated with the X coordinate of pixel centers")
        g.create_dataset("yCoordinates", data=y)
        g.create_dataset("xCoordinateSpacing", data=DX)
        g.create_dataset("yCoordinateSpacing", data=-DX)
        p = g.create_dataset("projection", data=np.uint32(EPSG))
        p.attrs["epsg_code"] = np.int32(EPSG)
        for t in terms:
            arr = data[t].astype("float32")
            if store_db:
                arr = (10 * np.log10(arr)).astype("float32")
            d = g.create_dataset(t, data=arr, chunks=(64, 64))
            d.attrs["units"] = np.bytes_("1")
            d.attrs["description"] = np.bytes_("SYNTHETIC test fixture - not an observation")
        m = np.ones((n, n), dtype="uint8")
        m[0:3, :] = 255
        md = g.create_dataset("mask", data=m)
        md.attrs["_FillValue"] = np.uint8(255)
        # HDF5 dimension scales, as in real NISAR GCOV files: this creates DIMENSION_LIST attributes
        # (arrays of h5py.Reference) on the rasters and REFERENCE_LIST (compound with references) on the coordinates.
        g["yCoordinates"].make_scale("yCoordinates")
        g["xCoordinates"].make_scale("xCoordinates")
        for name in list(terms) + ["mask"]:
            g[name].dims[0].attach_scale(g["yCoordinates"])
            g[name].dims[1].attach_scale(g["xCoordinates"])
        g.create_dataset("numberOfLooks", data=np.full((n, n), 25.0, dtype="float32"))
        ident = f.create_group("/science/LSAR/identification")
        ident.create_dataset("trackNumber", data=np.uint32(track))
        ident.create_dataset("frameNumber", data=np.uint16(5))
        ident.create_dataset("orbitPassDirection", data=np.bytes_(pass_dir))
        ident.create_dataset("zeroDopplerStartTime", data=np.bytes_(start_time))
        ident.create_dataset("granuleId", data=np.bytes_(path.stem))
    return path


@pytest.fixture
def real_catalog():
    return json.loads(REAL_CATALOG.read_text(encoding="utf-8"))


@pytest.fixture
def synthetic_stack(tmp_path, real_catalog):
    """Two synthetic granules named like real catalog entries + a catalog flagged synthetic_fixture."""
    cat = copy.deepcopy(real_catalog)
    cat["synthetic_fixture"] = True
    cat["granules"] = [g for g in cat["granules"] if g["acquisition_date"] in ("2026-06-20", "2026-10-18")]
    d = tmp_path / "h5"
    d.mkdir()
    for i, g in enumerate(cat["granules"]):
        make_synthetic_gcov(d / g["h5"]["name"], seed=10 + i, start_time=g["begin_utc"][:-1] + "000",
                            change=(i == 1))
    cpath = tmp_path / "catalog.json"
    cpath.write_text(json.dumps(cat), encoding="utf-8")
    return {"catalog": cpath, "h5dir": d, "cat": cat, "tmp": tmp_path}
