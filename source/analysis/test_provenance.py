# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Provenance, catalog and JSON-safety tests. Uses the REAL CMR snapshot (metadata only)."""
import copy
import json

import pytest

import provenance as pv

AOI = (30.55, 7.00, 30.95, 7.40)


def test_real_catalog_loads_and_primary_pair_passes(real_catalog, tmp_path):
    p = tmp_path / "c.json"; p.write_text(json.dumps(real_catalog))
    cat = pv.load_catalog(p)
    b, a = pv.select_by_date(cat, "2026-06-20"), pv.select_by_date(cat, "2026-10-18")
    checks = pv.catalog_checks(cat, b, a, AOI)
    assert not pv.blocking_failures(checks)
    by = {c["id"]: c for c in checks}
    assert by["same_crid"]["status"] == "PASS"
    assert by["orbit_fidelity"]["status"] == "PASS"
    assert by["aoi_inside_footprint"]["status"] == "PASS"


def test_polarization_mismatch_rejected(real_catalog):
    # 2026-09-24 is single-pol SHSH (HH only) in the real catalog
    with pytest.raises(ValueError, match="polarizations"):
        pv.select_by_date(real_catalog, "2026-09-24", require_pols=("HH", "HV"))
    b = pv.select_by_date(real_catalog, "2026-06-20")
    shsh = pv.select_by_date(real_catalog, "2026-09-24", require_pols=("HH",))
    checks = pv.catalog_checks(real_catalog, b, shsh, AOI)
    assert any(c["id"] == "same_polarization_channel" and c["status"] == "FAIL" for c in checks)


def test_forecast_orbit_is_warned(real_catalog):
    b = pv.select_by_date(real_catalog, "2026-07-14")  # filename token F = Forecast
    a = pv.select_by_date(real_catalog, "2026-10-18")
    by = {c["id"]: c for c in pv.catalog_checks(real_catalog, b, a, AOI)}
    assert by["orbit_fidelity"]["status"] == "WARN"


def test_inconsistent_dates_crid_and_aoi(real_catalog):
    b = pv.select_by_date(real_catalog, "2026-06-20")
    a = pv.select_by_date(real_catalog, "2026-10-18")
    ids = lambda cs: {c["id"] for c in pv.blocking_failures(cs)}
    assert "chronological_order" in ids(pv.catalog_checks(real_catalog, a, b, AOI))
    a2 = copy.deepcopy(a); a2["granule_ur"] = a2["granule_ur"].replace("P05023", "P05036")
    assert "same_crid" in ids(pv.catalog_checks(real_catalog, b, a2, AOI))
    assert "aoi_inside_footprint" in ids(pv.catalog_checks(real_catalog, b, a, (35.0, 7.0, 35.2, 7.2)))
    a3 = copy.deepcopy(a); a3["granule_ur"] = a3["granule_ur"].replace("_086_A_005_", "_158_A_005_")
    assert "same_stack" in ids(pv.catalog_checks(real_catalog, b, a3, AOI))


def test_unknown_date_lists_available(real_catalog):
    with pytest.raises(ValueError, match="Available dates"):
        pv.select_by_date(real_catalog, "2026-08-07")   # documented instrument data gap


def test_parse_utc_and_bad_timestamps():
    t = pv.parse_utc("2026-06-20T03:34:36.000000Z")
    assert t.hour == 3 and t.tzinfo is not None
    assert pv.parse_utc("2026-10-18T03:35:07.999342Z").microsecond == 999342
    for bad in ("2026-06-20", "2026-06-20T03:34:36", 20260620, "2026-13-01T00:00:00Z"):
        with pytest.raises((ValueError, TypeError)):
            pv.parse_utc(bad)


def test_point_in_polygon_lonlat_order(real_catalog):
    ring = real_catalog["granules"][0]["footprint_lonlat"]
    assert pv.point_in_polygon(30.75, 7.2, ring)       # lon, lat inside
    assert not pv.point_in_polygon(7.2, 30.75, ring)   # swapped order is outside


def test_json_safety(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="Malformed"):
        pv.load_json_safely(p)
    p.write_text('{"a": NaN}')
    with pytest.raises(ValueError):
        pv.load_json_safely(p)
    p.write_text("[1,2]")
    with pytest.raises(ValueError, match="object"):
        pv.load_json_safely(p)
    p.write_text('{"a": "' + "x" * 200 + '"}')
    with pytest.raises(ValueError, match="refusing"):
        pv.load_json_safely(p, max_bytes=100)


def test_catalog_schema_enforced(tmp_path, real_catalog):
    c = copy.deepcopy(real_catalog); c["schema"] = "other"
    p = tmp_path / "c.json"; p.write_text(json.dumps(c))
    with pytest.raises(ValueError, match="schema"):
        pv.load_catalog(p)
    c = copy.deepcopy(real_catalog); c["granules"] = []
    p.write_text(json.dumps(c))
    with pytest.raises(ValueError, match="no granules"):
        pv.load_catalog(p)
    c = copy.deepcopy(real_catalog); c["granules"][0]["begin_utc"] = "yesterday"
    p.write_text(json.dumps(c))
    with pytest.raises(ValueError):
        pv.load_catalog(p)


def test_real_catalog_integrity(real_catalog):
    """The committed snapshot must be internally consistent (verified against live CMR on 2026-11-14)."""
    g = real_catalog["granules"]
    assert len(g) == real_catalog["cmr_hits"] == 10
    assert len({x["h5"]["md5"] for x in g}) == 10
    assert all(x["granule_ur"].split("_")[13] == "P05023" for x in g)
    assert all(x["h5"]["https"].endswith(x["granule_ur"] + ".h5") for x in g)
    assert sum(1 for x in g if x["frequency_a_polarizations"] == ["HH", "HV"]) == 9


def test_baseline_days_rounded_not_truncated(real_catalog):
    # 2026-10-18 starts 4 s earlier in the day than 2026-06-20: timedelta.days would say 119
    b, a = pv.select_by_date(real_catalog, "2026-06-20"), pv.select_by_date(real_catalog, "2026-10-18")
    c = {x["id"]: x for x in pv.catalog_checks(real_catalog, b, a, AOI)}["chronological_order"]
    assert "(120 days)" in c["detail"]
