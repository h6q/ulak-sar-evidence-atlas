# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Unit tests for dual-pol change maths (SYNTHETIC arrays only)."""
import numpy as np
import pytest

import sar_change as sc


def test_to_db_linear_power_and_invalid():
    a = np.array([[1.0, 0.1, 0.0], [-1.0, np.nan, 10.0]])
    d = sc.to_db(a)
    assert d[0, 0] == pytest.approx(0.0)
    assert d[0, 1] == pytest.approx(-10.0)
    assert d[1, 2] == pytest.approx(10.0)
    assert np.isnan(d[0, 2]) and np.isnan(d[1, 0]) and np.isnan(d[1, 1])


def test_block_mean_averages_linear_not_db():
    a = np.array([[1.0, 100.0], [1.0, 100.0]])
    m = sc.block_mean(a, 2)
    assert m.shape == (1, 1)
    assert m[0, 0] == pytest.approx(50.5)           # linear mean
    assert sc.to_db(m)[0, 0] != pytest.approx(10.0)  # not the dB mean (which would be 10 dB)


def test_block_mean_nan_handling_and_edges():
    a = np.ones((5, 5))
    a[0, 0] = np.nan
    a[0, 1] = 0.0
    m = sc.block_mean(a, 2)
    assert m.shape == (2, 2)                         # remainder row/col dropped
    assert m[0, 0] == pytest.approx(1.0)             # 2 of 4 valid >= 50 %
    b = np.full((2, 2), np.nan); b[0, 0] = 1.0
    assert np.isnan(sc.block_mean(b, 2)[0, 0])       # 1 of 4 valid < 50 %
    with pytest.raises(ValueError):
        sc.block_mean(np.ones((1, 1)), 2)


def _pair(n=40):
    hh0 = np.full((n, n), 0.05); hv0 = np.full((n, n), 0.01)
    hh1 = hh0.copy(); hv1 = hv0.copy()
    hh1[:10, :10] *= 10 ** 0.6; hv1[:10, :10] *= 10 ** 0.1      # +6 / +1 dB
    hh1[20:30, 20:30] *= 10 ** -0.7; hv1[20:30, 20:30] *= 10 ** -0.7  # -7 / -7 dB
    hv1[30:35, 0:10] *= 10 ** 0.8                                # HV +8 dB only
    return hh0, hv0, hh1, hv1


def test_dual_pol_classes_and_signed_counts():
    r = sc.dual_pol_change(*_pair())
    cls = r["classes"]
    assert (cls[:10, :10] == sc.CLASS_HH_UP_DOUBLE_BOUNCE).all()
    assert (cls[20:30, 20:30] == sc.CLASS_BOTH_DOWN_SPECULAR).all()
    assert (cls[30:35, 0:10] == sc.CLASS_HV_UP_VOLUME).all()
    st = r["stats"]
    assert st["class_counts"]["hh_up_double_bounce"] == 100
    assert st["signed_counts"]["hh_increase_pixels"] == 100
    assert st["signed_counts"]["hh_decrease_pixels"] == 100
    assert r["d_hh"][0, 0] == pytest.approx(6.0)
    assert st["thresholds_db"]["T_HH"] == pytest.approx(3.0)   # MAD=0 -> floor


def test_dual_pol_shape_mismatch_and_bad_params():
    hh0, hv0, hh1, hv1 = _pair()
    with pytest.raises(ValueError, match="aligned"):
        sc.dual_pol_change(hh0, hv0[:-1], hh1, hv1)
    with pytest.raises(ValueError, match="finite positive"):
        sc.dual_pol_change(hh0, hv0, hh1, hv1, floor_db=float("nan"))
    with pytest.raises(ValueError, match="finite positive"):
        sc.dual_pol_change(hh0, hv0, hh1, hv1, sigma=-1)


def test_dual_pol_empty_or_all_invalid():
    z = np.zeros((12, 12))
    with pytest.raises(ValueError, match="Too few"):
        sc.dual_pol_change(z, z, z, z)
    e = np.zeros((0, 0))
    with pytest.raises(ValueError):
        sc.dual_pol_change(e, e, e, e)


def test_scene_shift_warning():
    hh0, hv0, _, _ = _pair()
    r = sc.dual_pol_change(hh0, hv0, hh0 * 10 ** 0.2, hv0)
    assert sc.scene_shift_warning(r["stats"]) is not None
    r2 = sc.dual_pol_change(*_pair())
    assert sc.scene_shift_warning(r2["stats"]) is None
