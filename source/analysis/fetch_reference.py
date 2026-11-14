# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Re-fetch and verify the independent/contextual GIBS reference snapshot.

This intentionally verifies the compact checked-in products instead of silently
overwriting them. GIBS is a rendered/composited access route, not a replacement
for granule-level OPERA GeoTIFF provenance.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_data as R  # noqa: E402

WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
LAYERS = {
    "modis": ("MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual", 400, R.PALETTE_DSWX_HLS),
    "s1": ("OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1", 200, R.PALETTE_DSWX_S1),
    "hls": ("OPERA_L3_Dynamic_Surface_Water_Extent-HLS", 200, R.PALETTE_DSWX_HLS),
}
# MODIS IGBP has a distinct categorical palette. Only classes present in this
# AOI are needed for the deterministic region check.
MODIS_RGB = {
    # GIBS classification/legend ids (0-based), matching the compact snapshot.
    (33, 138, 33): 0, (49, 204, 49): 1, (152, 204, 49): 2, (150, 250, 150): 3,
    (141, 186, 141): 4, (186, 141, 141): 5, (245, 222, 179): 6, (218, 235, 157): 7,
    (255, 213, 0): 8, (240, 185, 103): 9, (71, 131, 181): 10, (250, 239, 115): 11,
    (255, 0, 0): 12, (153, 147, 86): 13, (255, 255, 255): 14, (191, 191, 189): 15,
    (134, 202, 227): 16, (100, 100, 100): 17,
}


def wms_url(layer: str, date: str, size: int) -> str:
    q = {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.1.1", "LAYERS": layer,
         "SRS": "EPSG:4326", "BBOX": ",".join(map(str, R.AOI)), "WIDTH": size, "HEIGHT": size,
         "FORMAT": "image/png", "TRANSPARENT": "true", "TIME": date}
    return WMS + "?" + urllib.parse.urlencode(q)


def fetch_rgba(layer: str, date: str, size: int) -> tuple[np.ndarray, str]:
    url = wms_url(layer, date, size)
    req = urllib.request.Request(url, headers={"User-Agent": "ULAK-reference-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=90) as response:
        data = response.read()
    rgba = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))
    if rgba.shape != (size, size, 4):
        raise ValueError(f"unexpected WMS image shape {rgba.shape} for {url}")
    return rgba, url


def decode(rgba: np.ndarray, palette: dict) -> np.ndarray:
    arr, unknown = R.decode_palette(rgba, palette)
    if unknown:
        raise ValueError(f"palette decode produced {unknown} unknown pixels")
    return arr


def counts_by_cell(arr: np.ndarray, code: int) -> np.ndarray:
    if arr.shape != (200, 200):
        raise ValueError("DSWx verification expects the documented 200 x 200 WMS grid")
    return (arr == code).reshape(40, 5, 40, 5).sum(axis=(1, 3))


def region_counts(arr: np.ndarray, labels: np.ndarray, codes: list[int]) -> dict:
    fine_labels = np.repeat(np.repeat(labels, 5, axis=0), 5, axis=1)
    out = {}
    for label in list(R.REGION_CODES) + ["ALL"]:
        m = np.ones(arr.shape, bool) if label == "ALL" else fine_labels == label
        out[label] = [int(((arr == code) & m).sum()) for code in codes]
    return out


def verify_remote(ref_dir: Path) -> None:
    ref = R.load_reference(ref_dir, verify=True)
    prov = ref.provenance
    modis = []
    for date in prov["layers"]["modis_igbp"]["times"]:
        rgba, url = fetch_rgba(prov["layers"]["modis_igbp"]["layer"], date, 400)
        modis.append(decode(rgba, MODIS_RGB))
        print(f"verified fetch {date} {url}")
    defined = R.define_regions(modis[0], modis[1])
    if defined["labels"] != ["".join(row) for row in ref.labels]:
        raise ValueError("remote MODIS rendering no longer reproduces the checked-in region labels")

    for date in ref.s1_dates:
        rgba, url = fetch_rgba(prov["layers"]["dswx_s1"]["layer"], date, 200)
        arr = decode(rgba, R.PALETTE_DSWX_S1)
        if not np.array_equal(counts_by_cell(arr, 3), np.rint(ref.s1_iv[date] * 25).astype(int)):
            raise ValueError(f"remote DSWx-S1 IV rendering changed for {date}")
        if not np.array_equal(counts_by_cell(arr, 1), np.rint(ref.s1_ow[date] * 25).astype(int)):
            raise ValueError(f"remote DSWx-S1 open-water rendering changed for {date}")
        if region_counts(arr, ref.labels, [0, 1, 3, 250, 251, 255]) != ref.tables["S1"][date]:
            raise ValueError(f"remote DSWx-S1 region table changed for {date}")
        print(f"verified decode {date} {url}")

    for date in prov["layers"]["dswx_hls"]["times"]:
        rgba, url = fetch_rgba(prov["layers"]["dswx_hls"]["layer"], date, 200)
        arr = decode(rgba, R.PALETTE_DSWX_HLS)
        if region_counts(arr, ref.labels, [0, 1, 2, 3, 4, 255]) != ref.tables["HLS"][date]:
            raise ValueError(f"remote DSWx-HLS region table changed for {date}")
        print(f"verified decode {date} {url}")


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-dir", type=Path, default=root / "data/reference")
    ap.add_argument("--remote", action="store_true", help="Re-fetch every documented GIBS rendering and compare")
    args = ap.parse_args(argv)
    ref = R.load_reference(args.ref_dir, verify=True)
    print(json.dumps({"local_checksums": "PASS", "cross_sums": len(R.cross_check(ref)),
                      "s1_dates_with_pixels": len(ref.s1_dates)}, indent=2))
    if args.remote:
        verify_remote(args.ref_dir)
        print("remote renderings reproduce the checked-in compact products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

