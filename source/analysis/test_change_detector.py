# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
import numpy as np
import pytest
from change_detector import process_arrays

def test_known_linear_power_change():
    a=np.ones((20,20));b=a.copy();b[0:4,0:5]=10**(4/10)
    mask,delta,s=process_arrays(a,b)
    assert mask.sum()==20
    assert np.isclose(delta[0,0],4)
    assert s['valid_pixels']==400
    assert s['threshold_db']==3.0

def test_identical_images_no_candidates():
    a=np.ones((12,12));m,_,s=process_arrays(a,a)
    assert not m.any() and s['candidate_pixels']==0

def test_zero_and_nodata_are_excluded():
    a=np.ones((12,12));b=np.ones((12,12));a[0,0]=0;a[0,1]=-9999
    _,delta,s=process_arrays(a,b,nodata_before=-9999)
    assert s['valid_pixels']==142
    assert np.isnan(delta[0,0]) and np.isnan(delta[0,1])

def test_different_shape_rejected():
    with pytest.raises(ValueError,match='aligned'):
        process_arrays(np.ones((11,12)),np.ones((12,12)))

def test_db_mode():
    a=np.zeros((10,10));b=a.copy();b[:2,:2]=5
    m,delta,s=process_arrays(a,b,unit='db')
    assert m.sum()==4 and np.isclose(delta[0,0],5)

def test_insufficient_valid_data():
    with pytest.raises(ValueError,match='Too few'):
        process_arrays(np.zeros((12,12)),np.zeros((12,12)))


# ---- v0.3 additions: GeoTIFF CLI provenance / alignment / unit tests (SYNTHETIC rasters) ----
import json as _json
import rasterio as _rio
from rasterio.transform import from_origin as _from_origin
from change_detector import compare_geotiffs


def _tif(path, arr, transform=None, crs="EPSG:32636", nodata=None):
    t = transform or _from_origin(250000, 790000, 20, 20)
    with _rio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                   dtype="float32", crs=crs, transform=t, nodata=nodata) as d:
        d.write(arr.astype("float32"), 1)
    return path


def _side(path, pol, ur):
    path.write_text(_json.dumps({"granule_ur": ur, "polarization": pol, "dataset_path": f"/x/{pol}"}))
    return path


def test_geotiff_transform_mismatch_rejected(tmp_path):
    a = _tif(tmp_path / "a.tif", np.ones((20, 20)))
    b = _tif(tmp_path / "b.tif", np.ones((20, 20)), transform=_from_origin(250010, 790000, 20, 20))
    with pytest.raises(ValueError, match="never silently resample"):
        compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL")


def test_geotiff_crs_mismatch_rejected(tmp_path):
    a = _tif(tmp_path / "a.tif", np.ones((20, 20)))
    b = _tif(tmp_path / "b.tif", np.ones((20, 20)), crs="EPSG:32635")
    with pytest.raises(ValueError, match="differ"):
        compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL")


def test_geotiff_polarization_mismatch_via_sidecars(tmp_path):
    a = _tif(tmp_path / "a.tif", np.ones((20, 20))); b = _tif(tmp_path / "b.tif", np.ones((20, 20)))
    sa, sb = _side(tmp_path / "a.json", "HHHH", "G1"), _side(tmp_path / "b.json", "HVHV", "G2")
    with pytest.raises(ValueError, match="Polarization mismatch"):
        compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL", before_meta=sa, after_meta=sb)
    with pytest.raises(ValueError, match="BOTH"):
        compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL", before_meta=sa)


def test_geotiff_sidecar_verified_and_signed_counts(tmp_path):
    x = np.ones((20, 20)); y = x.copy(); y[:5, :5] = 10 ** 0.5; y[10:15, 10:15] = 10 ** -0.5
    a = _tif(tmp_path / "a.tif", x); b = _tif(tmp_path / "b.tif", y)
    rep = compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL",
                           before_meta=_side(tmp_path / "a.json", "HHHH", "G1"),
                           after_meta=_side(tmp_path / "b.json", "HHHH", "G2"))
    assert rep["provenance_status"] == "sidecar_verified"
    assert rep["statistics"]["positive_candidates"] == 25 and rep["statistics"]["negative_candidates"] == 25
    rep2 = compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL")
    assert rep2["provenance_status"] == "user_declared"
    lon, lat = rep2["geojson"]["features"][0]["geometry"]["coordinates"][0][0] if rep2["geojson"]["features"] else (31.0, 7.0)
    assert 29 < lon < 34 and 5 < lat < 9


def test_geotiff_db_values_rejected_as_linear(tmp_path):
    a = _tif(tmp_path / "a.tif", np.full((20, 20), -13.0)); b = _tif(tmp_path / "b.tif", np.full((20, 20), -12.0))
    with pytest.raises(ValueError, match="look like dB"):
        compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL", unit="linear")
    rep = compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL", unit="db")
    assert rep["statistics"]["median_delta_db"] == pytest.approx(1.0)


def test_geotiff_nodata_masked(tmp_path):
    x = np.ones((20, 20)); x[0, :] = -9999
    a = _tif(tmp_path / "a.tif", x, nodata=-9999); b = _tif(tmp_path / "b.tif", np.ones((20, 20)), nodata=-9999)
    rep = compare_geotiffs(a, b, polarization="HHHH", maturity="PROVISIONAL", unit="linear")
    assert rep["statistics"]["valid_pixels"] == 380
