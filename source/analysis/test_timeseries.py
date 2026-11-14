# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Regression tests for the measured multi-temporal analysis."""
from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest

import timeseries as ts
import ts_figures as figs

REPO = Path(__file__).resolve().parents[1]


def test_numerical_helpers_are_warning_free():
    lin = np.full((10, 10), np.nan, dtype=float)
    valid = np.zeros_like(lin, dtype=bool)
    y = np.full((5, 3, 4), np.nan, dtype=float)
    y[:, 0, 0] = [1, 2, 3, 4, 5]
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        mean, cv, n = ts.block_stats(lin, valid, k=5)
        slope = ts.ols_slope(np.arange(5), y)
        rgba = figs._gray(np.array([[np.nan, -20.0, -2.0]]), -22, -2)
    assert np.isnan(mean).all() and np.isnan(cv).all() and not n.any()
    assert slope[0, 0] == pytest.approx(1.0) and np.isnan(slope[1:, :]).all()
    assert rgba.shape == (1, 3, 4) and rgba[0, 0, 3] == 0


def test_rows_spearman_constant_row_is_nan_without_warning():
    a = np.array([[1, 2, 3, 4], [7, 7, 7, 7]], dtype=float)
    b = np.array([[4, 3, 2, 1], [1, 2, 3, 4]], dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        got = ts.rows_spearman(a, b)
    assert got[0] == pytest.approx(-1.0)
    assert np.isnan(got[1])


def test_spatial_block_bootstrap_is_deterministic_and_records_method():
    values = np.arange(36, dtype=float).reshape(6, 6)
    mask = np.ones_like(values, dtype=bool)
    a = ts.block_boot_median(values, mask, np.random.default_rng(42), n_boot=100)
    b = ts.block_boot_median(values, mask, np.random.default_rng(42), n_boot=100)
    assert a == b
    assert a["median"] == pytest.approx(17.5)
    assert a["blocks"] == 9 and a["bootstrap"] == "spatial_2x2_cells"
    assert a["lo"] <= a["median"] <= a["hi"]


def test_load_layers_rejects_cache_checksum_mismatch(tmp_path):
    metas = sorted((REPO / "data/derived/cache").glob("*.meta.json"))
    if not metas:
        pytest.skip("needs a local NISAR window cache (created by scripts/ulak_run_sudd.ps1); not shipped publicly")
    src_meta = metas[0]
    src_npz = src_meta.with_name(src_meta.name.replace(".meta.json", ".npz"))
    dst_meta = tmp_path / src_meta.name
    dst_npz = tmp_path / src_npz.name
    shutil.copy2(src_npz, dst_npz)
    meta = json.loads(src_meta.read_text(encoding="utf-8"))
    meta["sha256_float32"][meta["available_terms"][0]] = "0" * 64
    dst_meta.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="cache integrity check failed"):
        ts.load_layers(tmp_path, log=lambda *_: None, coreg_crop=32)


def test_real_reference_files_pass_checksums_and_cross_sums():
    ref = ts.R.load_reference(REPO / "data/reference", verify=True)
    assert ref.labels.shape == (40, 40)
    assert len(ref.s1_dates) == 11
    assert ref.tables["S1"]["2026-06-05"]["ALL"][-1] == 40000

