# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Independent reference data for the ULAK time-series investigation.

Everything in this module is *independent of NISAR*:

* MODIS Combined IGBP land cover (MCD12Q1, 2023 and 2024) defines the fixed
  analysis regions **before** any NISAR change statistic is looked at.
* OPERA DSWx-S1 (Sentinel-1 C-band) gives an independent radar-based
  open-water / inundated-vegetation classification for 11 dates.
* OPERA DSWx-HLS (Landsat/Sentinel-2 optical) gives cloud-masked optical
  surface water for the low-cloud dates (region summaries only).

All three were read as NASA GIBS WMS renderings (EPSG:4326, nearest-neighbour,
exact palette-colour decoding with zero unknown colours).  They are therefore
*rendered* products, not the original GeoTIFFs: classes are exact, geometry is
resampled to the WMS grid.  See ``data/reference/reference_provenance.json``.

Cell grid (shared by everything here): 40 x 40 cells of 0.01 degree covering
lon 30.55-30.95 E, lat 7.00-7.40 N; row 0 is the northern edge (7.40 N).

Text encodings (compact, diff-able, verified by SHA-256 and by cross-sums
against the region tables):
* ``#IV <date>`` / ``#OW <date>`` blocks: 40 rows x 40 chars, ``chr(97+n)``
  where ``n`` (0..25) is the number of DSWx-S1 pixels of the 0.002 degree WMS grid
  (5 x 5 per cell) in class 3 (inundated vegetation) or class 1 (open water).
* ``#LABEL``: region label per cell: ``C`` corridor, ``W`` west margin,
  ``E`` east margin, ``.`` not assigned (transition / mixed).
* ``#WET4`` / ``#SAV4``: MODIS stable-wetland / stable-savanna pixel count per
  cell (of 100 pixels at 0.001 degree), divided by 4 and rounded, as ``chr(97+n)``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

AOI = (30.55, 7.00, 30.95, 7.40)          # W, S, E, N
CELL_DEG = 0.01
NCELL = 40
S1_PX_PER_CELL = 25                         # 5 x 5 pixels of the 0.002 deg grid
REGION_CODES = {"C": "corridor", "W": "west_margin", "E": "east_margin", ".": "unassigned"}
REGION_ORDER = ("corridor", "west_margin", "east_margin")

# Exact GIBS palettes (colormaps v1.3) used for decoding.
PALETTE_DSWX_S1 = {(255, 255, 255): 0, (0, 0, 255): 1, (0, 255, 0): 3,
                   (200, 200, 200): 250, (128, 128, 128): 251}
PALETTE_DSWX_HLS = {(255, 255, 255): 0, (0, 0, 255): 1, (180, 213, 244): 2,
                    (0, 255, 255): 3, (175, 175, 175): 4}
TRANSPARENT_CODE = 255
UNKNOWN_CODE = 254

# Region rule parameters (fixed before NISAR region statistics were computed).
REGION_RULE = {
    "stable_wet": "IGBP class in {10 Permanent Wetlands, 16 Water Bodies} in BOTH 2023 and 2024",
    "stable_savanna": "IGBP class 8 (Savannas) in BOTH 2023 and 2024",
    "corridor_min_wet_fraction": 0.60,
    "margin_min_savanna_fraction": 0.95,
    "margin_buffer_cells": 1,
    "buffer_trigger_wet_fraction": 0.05,
    "centreline": "per cell-row median column of stable-wet pixels, gaps linearly "
                  "interpolated, then running median over 5 cell rows",
    "side": "margin cell is west if its centre column < centreline, else east",
}


# ----------------------------------------------------------------------------
# palette decoding (used by fetch_reference.py; unit-tested)

def decode_palette(rgba: np.ndarray, palette: dict) -> tuple[np.ndarray, int]:
    """Map an RGBA image (H, W, 4) to class codes. Alpha 0 -> 255; unknown -> 254."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an RGBA array of shape (H, W, 4)")
    h, w, _ = rgba.shape
    out = np.full((h, w), UNKNOWN_CODE, dtype=np.uint8)
    rgb = rgba[..., :3].astype(np.int32)
    key = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
    for (r, g, b), code in palette.items():
        out[key == ((r << 16) | (g << 8) | b)] = code
    out[rgba[..., 3] == 0] = TRANSPARENT_CODE
    return out, int((out == UNKNOWN_CODE).sum())


# ----------------------------------------------------------------------------
# region definition from MODIS (Python implementation of the documented rule)

def _median(v):
    return float(np.median(v)) if len(v) else None


def define_regions(lc2023: np.ndarray, lc2024: np.ndarray, *, px_per_cell: int = 10) -> dict:
    """Apply REGION_RULE to two IGBP class grids (same shape, row 0 = north).

    Returns labels (list of strings), wet/savanna fractions per cell and the
    smoothed centreline (cell-column units).
    """
    if lc2023.shape != lc2024.shape:
        raise ValueError("land-cover grids differ in shape")
    h, w = lc2023.shape
    if h % px_per_cell or w % px_per_cell:
        raise ValueError("grid not divisible into cells")
    m, n = h // px_per_cell, w // px_per_cell
    wet_px = np.isin(lc2023, (10, 16)) & np.isin(lc2024, (10, 16))
    sav_px = (lc2023 == 8) & (lc2024 == 8) & ~wet_px
    wf = wet_px.reshape(m, px_per_cell, n, px_per_cell).mean(axis=(1, 3))
    sf = sav_px.reshape(m, px_per_cell, n, px_per_cell).mean(axis=(1, 3))
    cen = []
    for R in range(m):
        cols = np.nonzero(wet_px[R * px_per_cell:(R + 1) * px_per_cell])[1] / px_per_cell
        cen.append(_median(cols))
    known = [i for i, v in enumerate(cen) if v is not None]
    if not known:
        raise ValueError("no stable wetland pixels: corridor undefined")
    for R in range(m):
        if cen[R] is None:
            lo = max([k for k in known if k < R], default=None)
            hi = min([k for k in known if k > R], default=None)
            cen[R] = cen[hi] if lo is None else cen[lo] if hi is None else \
                cen[lo] + (cen[hi] - cen[lo]) * (R - lo) / (hi - lo)
    cs = [float(np.median(cen[max(0, R - 2):R + 3])) for R in range(m)]
    eps = 1e-9
    trig = wf >= REGION_RULE["buffer_trigger_wet_fraction"] - eps
    buf = np.zeros_like(trig)
    k = REGION_RULE["margin_buffer_cells"]
    for dr in range(-k, k + 1):
        for dc in range(-k, k + 1):
            sh = np.zeros_like(trig)
            rs = slice(max(0, dr), m + min(0, dr)); rd = slice(max(0, -dr), m + min(0, -dr))
            cs_ = slice(max(0, dc), n + min(0, dc)); cd = slice(max(0, -dc), n + min(0, -dc))
            sh[rd, cd] = trig[rs, cs_]
            buf |= sh
    labels = []
    for R in range(m):
        row = []
        for C in range(n):
            if wf[R, C] >= REGION_RULE["corridor_min_wet_fraction"] - eps:
                row.append("C")
            elif not buf[R, C] and sf[R, C] >= REGION_RULE["margin_min_savanna_fraction"] - eps:
                row.append("W" if (C + 0.5) < cs[R] else "E")
            else:
                row.append(".")
        labels.append("".join(row))
    return {"labels": labels, "wet_fraction": wf, "savanna_fraction": sf, "centreline": cs}


# ----------------------------------------------------------------------------
# text formats

def encode_counts(grid: np.ndarray) -> list[str]:
    g = np.asarray(grid)
    if g.min() < 0 or g.max() > 25:
        raise ValueError("counts must be within 0..25")
    return ["".join(chr(97 + int(v)) for v in row) for row in g]


def decode_rows(rows: list[str]) -> np.ndarray:
    if len(rows) != NCELL or any(len(r) != NCELL for r in rows):
        raise ValueError("cell grid must be 40 x 40")
    arr = np.array([[ord(c) - 97 for c in r] for r in rows], dtype=np.int16)
    if arr.min() < 0 or arr.max() > 25:
        raise ValueError("invalid character in cell grid")
    return arr


def parse_blocks(text: str) -> dict[str, list[str]]:
    blocks, cur = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            cur = line[1:].strip()
            blocks[cur] = []
        elif line.strip():
            if cur is None:
                raise ValueError("data before first header")
            blocks[cur].append(line.strip())
    return blocks


def sha256_text(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class Reference:
    labels: np.ndarray                     # (40, 40) str
    wet4: np.ndarray
    sav4: np.ndarray
    centreline: list
    s1_dates: list
    s1_iv: dict                            # date -> (40,40) fraction 0..1
    s1_ow: dict
    tables: dict
    provenance: dict = field(default_factory=dict)

    def region_mask(self, region: str) -> np.ndarray:
        code = {v: k for k, v in REGION_CODES.items()}[region]
        return self.labels == code


def load_reference(ref_dir: Path, *, verify: bool = True) -> Reference:
    ref_dir = Path(ref_dir)
    prov_path = ref_dir / "reference_provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists() else {}
    if verify and prov.get("files"):
        for name, meta in prov["files"].items():
            got = sha256_text(ref_dir / name)
            if got != meta["sha256"]:
                raise ValueError(f"checksum mismatch for {name}: {got} != {meta['sha256']}")
    reg = parse_blocks((ref_dir / "modis_regions_cells.txt").read_text(encoding="utf-8"))
    labels = np.array([list(r) for r in reg["LABEL"]])
    if labels.shape != (NCELL, NCELL) or not set(np.unique(labels)) <= set(REGION_CODES):
        raise ValueError("bad label grid")
    centre_key = [k for k in reg if k.startswith("CENTRE")][0]
    centre = [float(v) for v in centre_key.split(" ", 1)[1].split(",")]
    iv_b = parse_blocks((ref_dir / "dswx_s1_iv_cells.txt").read_text(encoding="utf-8"))
    ow_b = parse_blocks((ref_dir / "dswx_s1_ow_cells.txt").read_text(encoding="utf-8"))
    iv = {k.split()[1]: decode_rows(v) / S1_PX_PER_CELL for k, v in iv_b.items()}
    ow = {k.split()[1]: decode_rows(v) / S1_PX_PER_CELL for k, v in ow_b.items()}
    if sorted(iv) != sorted(ow):
        raise ValueError("IV and OW dates differ")
    tables = json.loads((ref_dir / "region_tables.json").read_text(encoding="utf-8"))
    ref = Reference(labels=labels, wet4=decode_rows(reg["WET4"]) * 4, sav4=decode_rows(reg["SAV4"]) * 4,
                    centreline=centre, s1_dates=sorted(iv), s1_iv=iv, s1_ow=ow, tables=tables,
                    provenance=prov)
    if verify:
        cross_check(ref)
    return ref


def cross_check(ref: Reference) -> list[str]:
    """Cell grids summed per region must equal the independently computed region tables."""
    msgs = []
    for d in ref.s1_dates:
        t = ref.tables["S1"][d]
        for code in REGION_CODES:
            m = ref.labels == code
            iv = int(round((ref.s1_iv[d][m] * S1_PX_PER_CELL).sum()))
            ow = int(round((ref.s1_ow[d][m] * S1_PX_PER_CELL).sum()))
            if iv != t[code][2] or ow != t[code][1]:
                raise ValueError(f"cell/table mismatch {d} {code}: IV {iv} vs {t[code][2]}, OW {ow} vs {t[code][1]}")
        msgs.append(f"{d}: cell sums == region table")
    return msgs


def cell_of_lonlat(lon, lat):
    """Cell (row, col) for lon/lat arrays; -1 outside the AOI."""
    lon = np.asarray(lon, float); lat = np.asarray(lat, float)
    c = np.floor((lon - AOI[0]) / CELL_DEG + 1e-9).astype(int)
    r = np.floor((AOI[3] - lat) / CELL_DEG + 1e-9).astype(int)
    ok = (c >= 0) & (c < NCELL) & (r >= 0) & (r < NCELL)
    return np.where(ok, r, -1), np.where(ok, c, -1)


def cell_centre(r, c):
    return AOI[0] + (c + 0.5) * CELL_DEG, AOI[3] - (r + 0.5) * CELL_DEG


def region_fraction_table(ref: Reference, product: str = "S1") -> dict:
    """Region x date fractions from the region tables (valid = classified, not 25x)."""
    out = {}
    codes = {"S1": [0, 1, 3, 250, 251, 255], "HLS": [0, 1, 2, 3, 4, 255]}[product]
    for d, regs in sorted(ref.tables[product].items()):
        out[d] = {}
        for code, name in list(REGION_CODES.items()) + [("ALL", "aoi")]:
            cnt = dict(zip(codes, regs[code]))
            if product == "S1":
                valid = cnt[0] + cnt[1] + cnt[3]
                out[d][name] = {"valid_px": valid,
                                "open_water": cnt[1] / valid if valid else None,
                                "inundated_vegetation": cnt[3] / valid if valid else None}
            else:
                clear = cnt[0] + cnt[1] + cnt[2]
                total = sum(regs[code])
                out[d][name] = {"clear_px": clear, "clear_fraction": clear / total if total else 0.0,
                                "cloud_px": cnt[4], "nodata_px": cnt[255],
                                "open_water": cnt[1] / clear if clear else None,
                                "partial_surface_water": cnt[2] / clear if clear else None}
    return out
