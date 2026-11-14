#!/usr/bin/env python3
"""Re-verify the committed CMR snapshot against the live NASA CMR catalog (public; no login).

AI-assisted implementation (ULAK). Uses only the Python standard library.

    py analysis/nisar_catalog.py            # compares and prints PASS/DIFF per granule
    py analysis/nisar_catalog.py --stack 086_A_006 --save data/catalog/other.json   # explore another stack
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAP = REPO / "data" / "catalog" / "sudd_086_A_005_cmr_snapshot.json"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"


def fetch(short_name: str, stack: str) -> list[dict]:
    q = urllib.parse.urlencode({"short_name": short_name, "attribute[]": f"string,STACK_ID,{stack}",
                                "page_size": 200, "sort_key": "start_date"})
    req = urllib.request.Request(f"{CMR}?{q}", headers={"User-Agent": "ULAK-SpaceApps2026/0.3"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"CMR HTTP {r.status}")
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for it in data.get("items", []):
        u = it["umm"]
        h5 = next((f for f in u["DataGranule"]["ArchiveAndDistributionInformation"] if f["Name"] == u["GranuleUR"] + ".h5"), {})
        out.append({"granule_ur": u["GranuleUR"], "cmr_concept_id": it["meta"]["concept-id"],
                    "begin_utc": u["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
                    "md5": h5.get("Checksum", {}).get("Value"), "bytes": h5.get("SizeInBytes"),
                    "orbit_number": (u.get("OrbitCalculatedSpatialDomains") or [{}])[0].get("OrbitNumber")})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", default=str(SNAP))
    p.add_argument("--collection", default="NISAR_L2_GCOV_PROVISIONAL_V1")
    p.add_argument("--stack", default="086_A_005")
    p.add_argument("--save", help="Write the live listing to this JSON path")
    a = p.parse_args(argv)
    live = fetch(a.collection, a.stack)
    print(f"Live CMR: {len(live)} granules for {a.collection} stack {a.stack}")
    if a.save:
        Path(a.save).write_text(json.dumps(live, indent=1), encoding="utf-8")
        print(f"Saved {a.save}")
    if a.stack != "086_A_005":
        return 0
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    lv = {g["granule_ur"]: g for g in live}
    bad = 0
    for g in snap["granules"]:
        L = lv.get(g["granule_ur"])
        if L is None:
            print(f"MISSING  {g['granule_ur']}")
            bad += 1
            continue
        same = (L["cmr_concept_id"] == g["cmr_concept_id"] and L["md5"] == g["h5"]["md5"]
                and L["bytes"] == g["h5"]["bytes"] and L["begin_utc"] == g["begin_utc"])
        print(f"{'PASS' if same else 'DIFF'}     {g['acquisition_date']}  {g['granule_ur'][-50:]}")
        bad += 0 if same else 1
    extra = set(lv) - {g["granule_ur"] for g in snap["granules"]}
    for e in sorted(extra):
        print(f"NEW      {e}  (not in snapshot; review before use)")
    print("RESULT:", "snapshot matches live CMR" if bad == 0 else f"{bad} differences - review before analysis")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
