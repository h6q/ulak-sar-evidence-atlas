#!/usr/bin/env python3
"""Automated browser QA for the ULAK web app (Playwright + Chrome/Chromium). AI-assisted; reviewed by the team.

    py -m pip install playwright && py -m playwright install chromium
    py qa/browser_qa.py --site web --out qa/results/real            # shipped app (catalog mode)
    py qa/browser_qa.py --site <dir-with-synthetic-report> --out qa/results/synthetic --expect-report

Writes screenshots, console log and results.json. Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import threading
import time
from pathlib import Path


def serve(site: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="web")
    ap.add_argument("--out", default="qa/results/real")
    ap.add_argument("--expect-report", action="store_true")
    ap.add_argument("--expect-measured", action="store_true", help="web/data holds a real MEASURED report")
    ap.add_argument("--chrome", default=None, help="Path to a Chrome/Chromium executable (optional)")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    srv = serve(Path(a.site).resolve())
    url = f"http://127.0.0.1:{srv.server_port}/index.html"
    results, console = [], []

    def ok(name, cond, detail=""):
        results.append({"check": name, "pass": bool(cond), "detail": str(detail)[:400]})
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))

    with sync_playwright() as p:
        kw = {"executable_path": a.chrome} if a.chrome else {}
        br = p.chromium.launch(headless=True, **kw)
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        pg.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
        pg.goto(url, wait_until="domcontentloaded")
        pg.wait_for_function("window.__ULAK && window.__ULAK.catalog", timeout=15000)
        time.sleep(1.5)
        tier = pg.text_content("#tierLabel")
        ok("catalog loaded (10 real acquisitions)", pg.eval_on_selector_all("#before option", "o => o.length") == 10)
        ok("default pair 2026-06-20 -> 2026-10-18", pg.input_value("#before") == "2026-06-20" and pg.input_value("#after") == "2026-10-18")
        ok("passport has 8 numbered sections", pg.eval_on_selector_all("#passport h3", "h => h.filter(x => /^[1-8] ·/.test(x.textContent)).length") == 8)
        ok("rain chart rendered from NASA POWER", pg.eval_on_selector_all("#rain rect", "r => r.length") > 100)
        ok("cloud note computed", "of 91 days" in (pg.text_content("#cloudNote") or ""), pg.text_content("#cloudNote"))
        ok("table view lists 10 acquisitions", pg.eval_on_selector_all("#obsTable tbody tr", "r => r.length") == 10)
        if a.expect_measured:
            ok("tier is Measured (real report auto-loaded)", tier == "Measured", tier)
            ok("measured HH layer selected by default", pg.is_checked("input[name=layer][value=hh]"))
            ok("measured overlays shown on the map", pg.eval_on_selector_all(".leaflet-image-layer", "i => i.filter(x => x.complete && x.naturalWidth > 0).length") >= 2)
            ok("median dHH shown", pg.text_content("#dhh") == "+1.08 dB", pg.text_content("#dhh"))
            ok("robustness table shown", pg.eval_on_selector_all("#robust tbody tr", "r => r.length") == 5)
            ok("passport shows robustness row", "Robustness" in (pg.text_content("#passport") or ""))
            ok("histogram bars drawn", pg.eval_on_selector_all("#hist rect", "r => r.length") > 50)
            ok("candidate cells drawn", pg.eval_on_selector_all(".leaflet-overlay-pane path", "p => p.length") > 100)
            ok("QC-screened temporal result loaded", pg.eval_on_selector_all("#tsDate option", "o => o.length") == 9)
            ok("QC-failed 6 Oct omitted from primary timeline", pg.eval_on_selector_all("#tsDate option", "o => o.every(x => x.value !== '2026-10-06')"))
            ok("HH, HV and ratio temporal series drawn", pg.eval_on_selector_all("#series polyline", "p => p.length") >= 3)
            pg.check("input[name=layer][value=ts_hh]"); time.sleep(0.5)
            ok("measured temporal overlay added", pg.eval_on_selector_all(".leaflet-image-layer", "i => i.length") >= 1)
            pg.evaluate("window.__ULAK.map.fire('click', {latlng: L.latLng(7.2, 30.75)})"); time.sleep(0.3)
            ok("map click opens temporal cell passport", "Observed first" in (pg.text_content("#temporalPassport") or ""))
            pg.screenshot(path=str(out / "00_measured_initial.png"), full_page=True)
        elif not a.expect_report:
            ok("tier is Catalog-verified without a report", tier == "Catalog-verified", tier)
            ok("no quantitative numbers without measurement", pg.text_content("#dhh") == "—" and pg.text_content("#valid") == "—")
            ok("histogram withheld without measurement", "no distribution" in (pg.text_content("#hist") or ""))
            ok("all catalog checks PASS for primary pair", pg.eval_on_selector_all(".checks .badge", "b => b.every(x => x.textContent === 'PASS')"))
        pg.screenshot(path=str(out / "01_desktop_initial.png"), full_page=True)
        # GIBS lifecycle: status must leave the 'Requesting' state (loaded, failed or timeout message)
        if a.expect_measured:
            pg.check("input[name=layer][value=gibs]")
        pg.click("#refresh")
        deadline = time.time() + 25
        st = ""
        while time.time() < deadline:
            st = pg.text_content("#mapStatus") or ""
            if not st.startswith("Requesting"):
                break
            time.sleep(0.5)
        ok("map status leaves 'Requesting' state (no indefinite spinner)", not st.startswith("Requesting"), st)
        if a.expect_measured:
            ok("GIBS loads or falls back to measured layers", ("Switched automatically" in st and pg.is_checked("input[name=layer][value=hh]")) or "NASA GIBS daily mosaics" in st, st)
        results.append({"check": "gibs_status_text", "pass": True, "detail": st})
        # swipe clip
        pg.fill("#swipe", "30")
        pg.dispatch_event("#swipe", "input")
        clip = pg.evaluate("window.__ULAK.map.getPane('paneA').style.clip")
        ok("swipe sets pixel clip rect on before-pane", clip.startswith("rect("), clip)
        ok("divider follows swipe", pg.evaluate("document.getElementById('divider').style.left") == "30%")
        # incompatible pair warning (SHSH single-pol date)
        pg.select_option("#after", "2026-09-24")
        ok("single-pol pair flagged as incompatible", "fails" in (pg.text_content("#mapStatus") or ""), pg.text_content("#mapStatus"))
        ok("polarization check FAIL shown in passport", pg.eval_on_selector_all(".checks .badge.FAIL", "b => b.length") >= 1)
        pg.select_option("#after", "2026-10-18")
        # malformed import
        bad = out / "_bad.json"; bad.write_text("{oops")
        pg.set_input_files("#evidence", str(bad))
        time.sleep(0.4)
        ok("malformed JSON import rejected with message", "not valid JSON" in (pg.text_content("#evidenceStatus") or ""))
        swapped = out / "_swapped.json"
        swapped.write_text(json.dumps({"schema": "ulak-change-v2", "data_status": "MEASURED", "provenance": {"before": {"granule_ur": "a", "pixel_source": "local_file"}, "after": {"granule_ur": "b", "pixel_source": "local_file"}},
                                       "compatibility_checks": [], "statistics": {}, "hypotheses": [], "warnings": [], "limitations": [],
                                       "geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[7.1, 130.7], [7.2, 130.7], [7.2, 130.8], [7.1, 130.7]]]}}]}}))
        pg.set_input_files("#evidence", str(swapped))
        time.sleep(0.4)
        ok("report with lat/lon swapped is rejected", "rejected" in (pg.text_content("#evidenceStatus") or ""), pg.text_content("#evidenceStatus"))
        xss = out / "_xss.json"
        xss.write_text(json.dumps({"schema": "ulak-change-v1", "statistics": {"valid_pixels": 5, "median_delta_db": 1.0}, "geojson": {"type": "FeatureCollection", "features": []},
                                   "input": {"before": "<img src=x onerror=window.__pwned=1>"}}))
        pg.set_input_files("#evidence", str(xss))
        time.sleep(0.4)
        ok("untrusted strings are not executed", pg.evaluate("window.__pwned === undefined"))
        ok("legacy v1 report marked user-declared", pg.text_content("#tierLabel") == "User-declared", pg.text_content("#tierLabel"))
        pg.click("#clearEvidence"); time.sleep(0.3)
        if a.expect_report:
            pg.reload(); pg.wait_for_function("window.__ULAK && window.__ULAK.report", timeout=15000); time.sleep(1)
            t = pg.text_content("#tierLabel")
            ok("synthetic report is labelled Software test (never Measured)", t == "Software test", t)
            ok("stats populated from report", pg.text_content("#valid") != "—")
            ok("histogram bars drawn", pg.eval_on_selector_all("#hist rect", "r => r.length") > 50)
            ok("time-series points drawn", pg.eval_on_selector_all("#series circle", "c => c.length") >= 9)
            ok("candidate cells drawn on map", pg.eval_on_selector_all(".leaflet-overlay-pane path", "p => p.length") > 2)
            pg.check("input[name=layer][value=hyp]"); time.sleep(0.8)
            ok("hypothesis overlay image added", pg.eval_on_selector_all(".leaflet-image-layer", "i => i.length") >= 1)
            pg.screenshot(path=str(out / "02_desktop_synthetic_hypotheses.png"), full_page=False)
            pg.check("input[name=layer][value=hh]"); time.sleep(0.8)
            pg.screenshot(path=str(out / "03_desktop_synthetic_hh_swipe.png"), full_page=False)
            btn = pg.query_selector(".celllist button")
            ok("keyboard-accessible cell list present", btn is not None)
            if btn:
                btn.focus(); pg.keyboard.press("Enter"); time.sleep(0.5)
                ok("cell passport opens via keyboard", "candidate cell" in (pg.text_content("#passportScope") or ""))
                pg.screenshot(path=str(out / "04_cell_passport.png"), full_page=True)
        with pg.expect_download() as dl:
            pg.click("#export")
        path = out / "exported_study_report.md"
        dl.value.save_as(str(path))
        md = path.read_text(encoding="utf-8")
        ok("study report exported in English with provenance", md.startswith("# ULAK SAR Evidence Atlas") and "NISAR_L2_PR_GCOV_023_086_A_005" in md)
        # mobile
        m = br.new_page(viewport={"width": 375, "height": 812}, is_mobile=True)
        m.goto(url, wait_until="domcontentloaded"); m.wait_for_function("window.__ULAK && window.__ULAK.catalog", timeout=15000); time.sleep(1.2)
        overflow = m.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        ok("no horizontal overflow at 375 px", overflow <= 1, overflow)
        m.screenshot(path=str(out / "05_mobile_375.png"), full_page=True)
        # keyboard: skip link + focus visible
        pg.goto(url); pg.wait_for_function("window.__ULAK && window.__ULAK.catalog", timeout=15000)
        pg.keyboard.press("Tab")
        ok("first Tab focuses skip link", pg.evaluate("document.activeElement.className") == "skip")
        br.close()
    srv.shutdown()
    errors = [c for c in console if c.startswith(("error", "pageerror"))]
    # Network failures for external tiles are expected in an offline sandbox; JS exceptions are not.
    js_errors = [c for c in errors if "pageerror" in c or "TypeError" in c or "ReferenceError" in c]
    ok("no JavaScript exceptions", not js_errors, js_errors[:3])
    (out / "console.log").write_text("\n".join(console), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    failed = [r for r in results if not r["pass"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
