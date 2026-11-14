# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""HDF5 reader, GeoTIFF, report schema and end-to-end pipeline tests on SYNTHETIC fixtures."""
import json
import math

import h5py
import numpy as np
import pytest
import rasterio

import gcov_reader as gr
import report_builder as rb
import run_sudd
from conftest import TEST_AOI, make_synthetic_gcov


def test_reader_window_transform_and_registration(tmp_path):
    p = make_synthetic_gcov(tmp_path / "g.h5", seed=1, start_time="2026-06-20T03:34:36.000000000", change=False)
    with h5py.File(p) as f:
        w = gr.read_gcov_window(f, TEST_AOI)
    r0, r1, c0, c1 = w.window
    assert w.terms["HHHH"].shape == (r1 - r0, c1 - c0)
    assert w.epsg == 32636
    assert w.grid.registration == "center" and w.grid.registration_evidenced
    assert w.transform.c == pytest.approx(w.x[0] - 10.0)   # centre -> corner
    assert w.transform.f == pytest.approx(w.y[0] + 10.0)
    assert w.identification["trackNumber"] == 86
    assert gr.mask_summary(w.mask, w.mask_attrs)["applied_as_validity"] is True


def test_reader_missing_group_and_terms(tmp_path):
    p = tmp_path / "empty.h5"
    with h5py.File(p, "w") as f:
        f.create_group("/science/LSAR/GCOV/grids")
    with h5py.File(p) as f:
        with pytest.raises(gr.GCOVLayoutError, match="frequencyA"):
            gr.read_gcov_window(f, TEST_AOI)
    q = make_synthetic_gcov(tmp_path / "hh.h5", seed=2, start_time="x", change=False, terms=("HHHH",))
    with h5py.File(q) as f:
        w = gr.read_gcov_window(f, TEST_AOI)
    assert "HVHV" not in w.terms and w.available_terms == ["HHHH"]


def test_reader_rejects_partial_aoi(tmp_path):
    p = make_synthetic_gcov(tmp_path / "g.h5", seed=1, start_time="x", change=False)
    with h5py.File(p) as f:
        with pytest.raises(ValueError, match="partially"):
            gr.read_gcov_window(f, (30.70, 7.10, 30.90, 7.30))
        with pytest.raises(ValueError):
            gr.read_gcov_window(f, (30.9, 7.1, 30.7, 7.2))  # west > east


def test_registration_unknown_is_flagged():
    assert gr._registration_from_description(None) == ("center", False)
    assert gr._registration_from_description("center") == ("center", True)
    assert gr._registration_from_description("upper-left corner") == ("edge", True)


def test_cells_geojson_is_lon_lat(tmp_path):
    from rasterio.transform import Affine
    cls = np.zeros((40, 40), dtype="uint8"); cls[:20, :20] = 1
    d = np.zeros((40, 40))
    t = Affine(100, 0, 247000, 0, -100, 787000)   # UTM 36N near 30.7E 7.1N
    gj = rb.cells_geojson(cls, d, d, t, 32636, cell_px=10)
    assert len(gj["features"]) == 4
    lon, lat = gj["features"][0]["geometry"]["coordinates"][0][0]
    assert 29 < lon < 32 and 6 < lat < 8.5
    empty = rb.cells_geojson(np.zeros((40, 40), dtype="uint8"), d, d, t, 32636, cell_px=10)
    assert empty["features"] == []


def _minimal_report():
    return {"schema": rb.SCHEMA, "generated_utc": "2026-11-14T00:00:00Z", "data_status": "SOFTWARE_TEST_SYNTHETIC",
            "study_area": {}, "provenance": {"before": {"granule_ur": "a"}, "after": {"granule_ur": "b"}},
            "compatibility_checks": [], "processing": {}, "statistics": {"x": 1.0}, "histograms": {},
            "hypotheses": [], "geojson": {"type": "FeatureCollection", "features": []},
            "warnings": [], "limitations": []}


def test_validate_report_rules():
    rep = _minimal_report(); rb.validate_report(rep)
    bad = _minimal_report(); bad["statistics"]["x"] = float("nan")
    with pytest.raises(ValueError, match="Non-finite"):
        rb.validate_report(bad)
    bad = _minimal_report(); bad["schema"] = "ulak-change-v1"
    with pytest.raises(ValueError, match="schema"):
        rb.validate_report(bad)
    bad = _minimal_report(); bad["data_status"] = "MEASURED"
    with pytest.raises(ValueError, match="pixel_source"):
        rb.validate_report(bad)    # cannot claim MEASURED without stating pixel source
    bad = _minimal_report()
    bad["compatibility_checks"] = [{"id": "same_crid", "blocking": True, "status": "FAIL"}]
    with pytest.raises(ValueError, match="blocking"):
        rb.validate_report(bad)
    bad = _minimal_report()
    bad["geojson"]["features"] = [{"geometry": {"coordinates": [[[7.1, 130.7]]]}}]
    with pytest.raises(ValueError, match="lon, lat"):
        rb.validate_report(bad)
    del bad["warnings"]
    with pytest.raises(ValueError, match="missing"):
        rb.validate_report(bad)


def test_histogram_counts_and_clipping():
    h = rb.histogram(np.array([-20.0, -0.25, 0.25, 0.75, 20.0, np.nan]))
    assert h["n"] == 5 and sum(h["counts"]) == 5
    assert h["below_range"] == 1 and h["above_range"] == 1


def test_end_to_end_synthetic(synthetic_stack, tmp_path):
    web = tmp_path / "web"; der = tmp_path / "derived"
    rc = run_sudd.main(["--catalog", str(synthetic_stack["catalog"]), "--source", "local",
                        "--local-dir", str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI),
                        "--web-out", str(web), "--derived-dir", str(der), "--cell-px", "4"])
    assert rc == 0
    rep = json.loads((web / "sudd_report.json").read_text())
    rb.validate_report(rep)
    assert rep["data_status"] == "SOFTWARE_TEST_SYNTHETIC"       # never presented as measured
    cc = rep["statistics"]["class_counts"]
    assert cc["hh_up_double_bounce"] > 0 and cc["both_down_specular"] > 0
    assert rep["provenance"]["before"]["pixel_source"] == "local_file"
    assert {c["id"] for c in rep["compatibility_checks"]} >= {"same_grid", "infile_track_frame", "same_crid"}
    assert len(rep["time_series"]) == 2
    for name in ("before_hh", "after_hh", "delta_hh", "hypotheses"):
        assert (web / rep["overlays"][name]["file"]).exists()
    tifs = sorted(der.glob("*.tif"))
    assert len(tifs) == 4
    with rasterio.open(tifs[0]) as a, rasterio.open(tifs[2]) as b:
        assert a.crs.to_epsg() == 32636 and a.transform == b.transform
    side = json.loads(tifs[0].with_suffix(".json").read_text())
    assert side["polarization"] in ("HHHH", "HVHV") and len(side["sha256_float32"]) == 64
    for f in rep["geojson"]["features"]:
        lon, lat = f["geometry"]["coordinates"][0][0]
        assert 30.6 < lon < 30.8 and 7.0 < lat < 7.2


def test_pipeline_blocks_misaligned_grid(synthetic_stack, tmp_path):
    g = synthetic_stack["cat"]["granules"][1]
    make_synthetic_gcov(synthetic_stack["h5dir"] / g["h5"]["name"], seed=99, start_time=g["begin_utc"][:-1],
                        change=True, x_shift=10.0)
    rc = run_sudd.main(["--catalog", str(synthetic_stack["catalog"]), "--source", "local",
                        "--local-dir", str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI),
                        "--web-out", str(tmp_path / "w"), "--derived-dir", str(tmp_path / "d"), "--no-series"])
    assert rc == 3
    blocked = json.loads((tmp_path / "d" / "BLOCKED_checks.json").read_text())
    assert any(c["id"] == "same_grid" and c["status"] == "FAIL" for c in blocked)


def test_pipeline_blocks_wrong_track(synthetic_stack, tmp_path):
    g = synthetic_stack["cat"]["granules"][1]
    make_synthetic_gcov(synthetic_stack["h5dir"] / g["h5"]["name"], seed=5, start_time=g["begin_utc"][:-1],
                        change=True, track=158)
    rc = run_sudd.main(["--catalog", str(synthetic_stack["catalog"]), "--source", "local",
                        "--local-dir", str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI),
                        "--web-out", str(tmp_path / "w"), "--derived-dir", str(tmp_path / "d"), "--no-series"])
    assert rc == 3


def test_pipeline_rejects_db_stored_values(synthetic_stack, tmp_path):
    g = synthetic_stack["cat"]["granules"][1]
    make_synthetic_gcov(synthetic_stack["h5dir"] / g["h5"]["name"], seed=5, start_time=g["begin_utc"][:-1],
                        change=True, store_db=True)
    rc = run_sudd.main(["--catalog", str(synthetic_stack["catalog"]), "--source", "local",
                        "--local-dir", str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI),
                        "--web-out", str(tmp_path / "w"), "--derived-dir", str(tmp_path / "d"), "--no-series"])
    assert rc == 3   # units check fails (values look like dB)


def test_md5_verification_local(synthetic_stack, tmp_path):
    rc_args = ["--catalog", str(synthetic_stack["catalog"]), "--source", "local", "--verify-md5",
               "--local-dir", str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI),
               "--web-out", str(tmp_path / "w"), "--derived-dir", str(tmp_path / "d"), "--no-series"]
    with pytest.raises(ValueError, match="MD5 mismatch"):   # synthetic files do not match real CMR checksums
        run_sudd.main(rc_args)


def test_https_range_reads_transfer_only_part_of_file(synthetic_stack, tmp_path, monkeypatch):
    """Exercise the real fsspec HTTPS path against a local range-capable server (SYNTHETIC files)."""
    import http.server, re, threading
    served = {"bytes": 0, "auth": set()}
    root = synthetic_stack["h5dir"]
    big = 0
    # pad the files so they are much larger than the AOI window (as real 1.8 GB granules are)
    for g in synthetic_stack["cat"]["granules"]:
        p = root / g["h5"]["name"]
        make_synthetic_gcov(p, seed=3, start_time=g["begin_utc"][:-1], change=False, n=900)
        big += p.stat().st_size

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _file(self):
            return root / self.path.lstrip("/").split("/")[-1]

        def do_HEAD(self):
            served["auth"].add(self.headers.get("Authorization"))
            f = self._file(); self.send_response(200)
            self.send_header("Content-Length", str(f.stat().st_size)); self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self):
            served["auth"].add(self.headers.get("Authorization"))
            f = self._file(); size = f.stat().st_size
            m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            a, b = (int(m.group(1)), int(m.group(2) or size - 1)) if m else (0, size - 1)
            b = min(b, size - 1)
            with open(f, "rb") as fh:
                fh.seek(a); data = fh.read(b - a + 1)
            self.send_response(206 if m else 200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}"); self.send_header("Accept-Ranges", "bytes")
            self.end_headers(); self.wfile.write(data); served["bytes"] += len(data)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    try:
        cat = synthetic_stack["cat"]
        for g in cat["granules"]:
            g["h5"]["https"] = f"http://127.0.0.1:{srv.server_port}/x/{g['h5']['name']}"
        synthetic_stack["catalog"].write_text(json.dumps(cat))
        monkeypatch.setenv("EARTHDATA_TOKEN", "test-token-123")
        args = ["--catalog", str(synthetic_stack["catalog"]), "--source", "https",
                "--aoi", *map(str, TEST_AOI), "--web-out", str(tmp_path / "w"),
                "--derived-dir", str(tmp_path / "d"), "--no-series", "--block-mb", "0.0625"]
        rc = run_sudd.main(args)
        first_bytes = served["bytes"]
        # rerun: windows must come from the verified cache, with zero network transfer and NO credential prompt
        monkeypatch.delenv("EARTHDATA_TOKEN")
        monkeypatch.setattr(run_sudd.getpass, "getpass", lambda *a, **k: (_ for _ in ()).throw(AssertionError("token prompted")))
        rc2 = run_sudd.main(args)
        monkeypatch.setenv("EARTHDATA_TOKEN", "test-token-123")
        second_bytes = served["bytes"] - first_bytes
        # corrupt one cached array -> integrity check fails -> transparent re-read from the server
        meta = next((tmp_path / "d" / "cache_synthetic").glob("2026-06-20_*.meta.json"))
        m = json.loads(meta.read_text()); m["sha256_float32"]["HHHH"] = "0" * 64; meta.write_text(json.dumps(m))
        rc3 = run_sudd.main(args)
        third_bytes = served["bytes"] - first_bytes - second_bytes
    finally:
        srv.shutdown()
    served["bytes"] = first_bytes
    assert rc2 == 0 and second_bytes == 0, second_bytes
    assert rc3 == 0 and third_bytes > 0
    for f in (tmp_path / "d" / "cache_synthetic").glob("*.json"):
        assert "test-token-123" not in f.read_text()
    assert rc == 0
    assert served["auth"] == {"Bearer test-token-123"}
    assert 0 < served["bytes"] < 0.6 * big, (served["bytes"], big)   # AOI window << file
    rep = json.loads((tmp_path / "w" / "sudd_report.json").read_text())
    assert rep["provenance"]["before"]["pixel_source"] == "https_range_read"
    assert "test-token-123" not in json.dumps(rep)            # token never leaks into outputs
    for f in (tmp_path / "d").glob("*.json"):
        assert "test-token-123" not in f.read_text()
