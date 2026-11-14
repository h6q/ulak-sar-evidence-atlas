# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Regression tests for HDF5 metadata serialization (real-data failure on 2026-11-14:
TypeError: Object of type Reference is not JSON serializable, from DIMENSION_LIST). SYNTHETIC files only."""
import json

import h5py
import numpy as np
import pytest
import rasterio

import gcov_reader as gr
import run_sudd
from conftest import TEST_AOI, make_synthetic_gcov

G = "/science/LSAR/GCOV/grids/frequencyA"


def test_dimension_list_reproduces_original_failure_and_is_fixed(tmp_path):
    p = make_synthetic_gcov(tmp_path / "g.h5", seed=1, start_time="2026-06-20T03:34:36.000000000", change=False)
    with h5py.File(p) as f:
        ds = f[f"{G}/HHHH"]
        assert "DIMENSION_LIST" in ds.attrs
        raw = {k: ds.attrs[k] for k in ds.attrs}
        with pytest.raises(TypeError):                       # the exact failure seen on real data
            json.dumps({"attributes": {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in raw.items()}})
        safe = gr.attrs_dict(ds)
    text = json.dumps(safe, allow_nan=False)                 # now serializes
    dl = safe["DIMENSION_LIST"]
    # DIMENSION_LIST is variable-length: one list of attached scale references per dimension (y, x)
    assert dl == [[{"hdf5_object_reference": f"{G}/yCoordinates"}], [{"hdf5_object_reference": f"{G}/xCoordinates"}]]
    assert safe["units"] == "1" and "SYNTHETIC" in safe["description"]
    assert "Reference" not in text


def test_reference_list_compound_attribute(tmp_path):
    p = make_synthetic_gcov(tmp_path / "g.h5", seed=1, start_time="x", change=False)
    with h5py.File(p) as f:
        safe = gr.attrs_dict(f[f"{G}/yCoordinates"])
    json.dumps(safe, allow_nan=False)
    refs = safe["REFERENCE_LIST"]
    assert isinstance(refs, list) and refs and all(isinstance(r, dict) for r in refs)
    paths = {v["hdf5_object_reference"] for r in refs for v in r.values() if isinstance(v, dict)}
    assert f"{G}/HHHH" in paths
    assert safe["CLASS"] == "DIMENSION_SCALE"


def test_to_jsonable_covers_metadata_types(tmp_path):
    with h5py.File(tmp_path / "r.h5", "w") as f:
        d = f.create_dataset("d", data=np.arange(10))
        ref, rref = d.ref, d.regionref[2:4]
        null = h5py.Reference()
        cases = {
            "np_int": np.int32(7), "np_uint": np.uint64(9), "np_float": np.float32(1.5), "np_bool": np.bool_(True),
            "nan": np.float64("nan"), "inf": float("inf"), "bytes": b"Ascending\x00", "np_bytes": np.bytes_(b"HH"),
            "byte_array": np.array([b"A", b"B"]), "small_array": np.array([1.0, np.nan]), "big_array": np.zeros(1000),
            "scalar_array": np.array(5), "ref": ref, "null_ref": null, "region_ref": rref,
            "tuple": (np.int8(1), b"x", ref), "complex": np.complex64(1 + 2j), "object": object(),
        }
        out = gr.to_jsonable(cases, f)
    json.dumps(out, allow_nan=False)
    assert out["np_int"] == 7 and out["np_uint"] == 9 and out["np_float"] == 1.5 and out["np_bool"] is True
    assert out["nan"] is None and out["inf"] is None
    assert out["bytes"] == "Ascending" and out["np_bytes"] == "HH" and out["byte_array"] == ["A", "B"]
    assert out["small_array"] == [1.0, None] and out["big_array"].startswith("<array shape=[1000]")
    assert out["scalar_array"] == 5
    assert out["ref"] == {"hdf5_object_reference": "/d"} and out["null_ref"] is None
    assert out["region_ref"] == {"hdf5_region_reference": "/d"}
    assert out["tuple"] == [1, "x", {"hdf5_object_reference": "/d"}]
    assert out["complex"] == {"real": 1.0, "imag": 2.0}
    assert out["object"] == "<unserializable: object>"   # explicit, never silent
    assert gr.to_jsonable(ref) == {"hdf5_object_reference": "<unresolved>"}   # no file handle


def test_geotiff_and_sidecar_keep_essential_metadata(synthetic_stack, tmp_path):
    web, der = tmp_path / "web", tmp_path / "derived"
    rc = run_sudd.main(["--catalog", str(synthetic_stack["catalog"]), "--source", "local", "--local-dir",
                        str(synthetic_stack["h5dir"]), "--aoi", *map(str, TEST_AOI), "--web-out", str(web),
                        "--derived-dir", str(der), "--no-series"])
    assert rc == 0
    g = synthetic_stack["cat"]["granules"][0]
    tif = der / "2026-06-20_HHHH_freqA_gamma0_linear.tif"
    with rasterio.open(tif) as d:
        tags = d.tags()
        assert d.crs.to_epsg() == 32636 and np.isnan(d.nodata) and d.transform.a == 20.0
        assert tags["SOURCE_GRANULE"] == g["granule_ur"] and tags["POLARIZATION"] == "HH"
        assert tags["ACQUISITION_START_UTC"] == g["begin_utc"] and tags["UNITS_ATTRIBUTE"] == "1"
    side = json.loads(tif.with_suffix(".json").read_text())
    for k in ("granule_ur", "acquisition_begin_utc", "crs", "transform", "shape", "nodata", "units_attribute",
              "polarization", "sha256_float32"):
        assert side[k] not in (None, ""), k
    assert side["attributes"]["DIMENSION_LIST"][0][0]["hdf5_object_reference"].endswith("yCoordinates")
    rep = json.loads((web / "sudd_report.json").read_text())
    assert rep["provenance"]["before"]["term_attributes"]["HHHH"]["DIMENSION_LIST"][1][0]["hdf5_object_reference"].endswith("xCoordinates")


def test_secrets_scrubbed_from_log_and_traceback(tmp_path, capsys, monkeypatch):
    log = tmp_path / "run.log"
    monkeypatch.setattr(run_sudd, "_SECRETS", ["sekret-token-XYZ"])
    monkeypatch.setattr(run_sudd, "_LOG_FILE", log)

    def boom(argv=None):
        raise RuntimeError("upstream said: Authorization: Bearer sekret-token-XYZ rejected")
    monkeypatch.setattr(run_sudd, "main", boom)
    assert run_sudd.cli() == 1
    err = capsys.readouterr()
    assert "sekret-token-XYZ" not in err.err + err.out
    assert "sekret-token-XYZ" not in log.read_text(encoding="utf-8")
    assert "REDACTED" in log.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="credential"):
        run_sudd.dump_json({"x": "has sekret-token-XYZ inside"}, tmp_path / "o.json")
    assert not (tmp_path / "o.json").exists()


def test_mask_rules_follow_file_description():
    desc = ("Mask indicating the subswath number associated with valid GCOV samples. A GCOV sample is only considered valid "
            "if it is generated from fully-focused radar samples. If at least one radar sample in the averaging set is "
            "partially focused or invalid, the corresponding mask pixel will contain the value 0. GCOV pixels outside of "
            "the radar acquisition extent are filled with the value 255")   # verbatim from the real 2026-06-20 granule
    m = np.array([[0, 1, 2, 255]], dtype="uint8")
    inv = gr.invalid_from_mask(m, {"_FillValue": 255, "description": desc})
    assert inv.tolist() == [[True, False, False, True]]
    assert len(gr.mask_rules({"_FillValue": 255, "description": desc})) == 2
    assert gr.invalid_from_mask(m, {"_FillValue": 255}).tolist() == [[False, False, False, True]]
    assert gr.invalid_from_mask(m, {}) is None
    s = gr.mask_summary(m, {"_FillValue": 255, "description": desc})
    assert s["invalid_samples"] == 2 and s["value_counts_top20"]["1"] == 1


def test_diagnostics_and_threshold_sensitivity():
    import sar_change as sc
    rng = np.random.default_rng(0)
    n = 200
    hh0 = 0.05 * rng.gamma(30, 1 / 30, (n, n)); hv0 = 0.01 * rng.gamma(30, 1 / 30, (n, n))
    hh1 = hh0 * 10 ** 0.1 * rng.gamma(30, 1 / 30, (n, n)); hv1 = hv0 * 10 ** 0.05 * rng.gamma(30, 1 / 30, (n, n))
    hh1[:20, :20] *= 10 ** 0.8                                     # a real +8 dB HH patch
    res = sc.dual_pol_change(hh0, hv0, hh1, hv1)
    d = sc.diagnostics(res, tiles=4, pixel_area_m2=1e4)
    ss = d["scene_shift"]
    assert 0.5 < ss["median_dhh_db"] < 1.5 and ss["fraction_dhh_positive"] > 0.6
    assert len(ss["tile_medians"]) == 4 and len(ss["strata_by_before_hh_quartile"]) == 4
    sens = d["threshold_sensitivity"]
    assert set(sens) == {"as_reported", "median_centred", "floor_only_3db"}
    assert sens["as_reported"]["counts"] == res["stats"]["class_counts"]
    assert sens["as_reported"]["candidate_area_km2"] == pytest.approx(sens["as_reported"]["candidates"] * 0.01)
    # the injected patch survives re-centring
    assert sens["median_centred"]["counts"]["hh_up_double_bounce"] >= 300
    json.dumps(gr.to_jsonable(d), allow_nan=False)
