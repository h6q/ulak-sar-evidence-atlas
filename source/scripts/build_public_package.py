#!/usr/bin/env python3
"""Build the public, static deployment package and scan it (and the repo) for credentials.

AI-assisted script (ULAK). Publishing itself is NOT done here; the team decides where and when.

    py scripts/build_public_package.py
Outputs: dist/ulak_site/ (static site = contents of web/), dist/ulak_site.zip, dist/PACKAGE_MANIFEST.json
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
SITE = DIST / "ulak_site"
MAX_SITE_BYTES = 25_000_000
SECRET_PATTERNS = [
    (re.compile(rb"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"), "JWT-like token"),
    (re.compile(rb"Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer credential"),
    (re.compile(rb"(?i)(earthdata_token|password|passwd|secret)\s*[:=]\s*['\"][^'\"\s]{8,}"), "credential assignment"),
    (re.compile(rb"(?i)machine\s+urs\.earthdata\.nasa\.gov"), ".netrc entry"),
]
SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "dist"}


def scan(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.name.lower() in (".netrc", "_netrc", ".env") or p.suffix == ".token":
            hits.append(f"{p.relative_to(root)}: credential file name")
            continue
        data = p.read_bytes()
        if p.suffix == ".npz":
            with zipfile.ZipFile(p) as z:
                data = b"".join(z.read(n) for n in z.namelist())
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 logs (Windows PowerShell 5.1)
            data = data.decode("utf-16", errors="ignore").encode("utf-8")
        for rx, label in SECRET_PATTERNS:
            if rx.search(data):
                hits.append(f"{p.relative_to(root)}: {label}")
    return hits


def main() -> int:
    web = REPO / "web"
    report = web / "data" / "sudd_report.json"
    if not report.exists():
        print("WARNING: web/data/sudd_report.json missing - the package will run in catalog-only mode.")
    else:
        status = json.loads(report.read_text(encoding="utf-8")).get("data_status")
        if status != "MEASURED":
            print(f"REFUSING: bundled report has data_status={status!r}; only MEASURED reports may be published.")
            return 2
    # Overwrite in place (works even where deleting files is restricted), then drop stale files.
    shutil.copytree(web, SITE, ignore=shutil.ignore_patterns("*.tmp", "__pycache__"), dirs_exist_ok=True)
    wanted = {p.relative_to(web) for p in web.rglob("*") if p.is_file() and not p.name.endswith(".tmp")}
    for p in sorted(SITE.rglob("*")):
        if p.is_file() and p.relative_to(SITE) not in wanted:
            try:
                p.unlink()
            except OSError as exc:
                print(f"REFUSING: stale file {p.relative_to(SITE)} could not be removed ({exc}); delete dist/ and rerun.")
                return 4
    files, total = [], 0
    for p in sorted(SITE.rglob("*")):
        if p.is_file():
            b = p.read_bytes(); total += len(b)
            files.append({"path": str(p.relative_to(SITE)).replace("\\", "/"), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    if total > MAX_SITE_BYTES:
        print(f"REFUSING: site is {total} bytes (> {MAX_SITE_BYTES})"); return 3
    site_hits, repo_hits = scan(SITE), scan(REPO)
    zpath = DIST / "ulak_site.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:  # mode "w" truncates an existing zip
        for f in files:
            z.write(SITE / f["path"], f["path"])
    man = {"package": "ULAK SAR Evidence Atlas static site", "files": files, "total_bytes": total,
           "credential_scan_site": site_hits or "clean", "credential_scan_repo": repo_hits or "clean",
           "excluded_by_design": ["data/derived (GeoTIFFs, cache, logs)", "data/raw", ".venv", "credentials"],
           "note": "Not published. Upload dist/ulak_site/ (or the zip) to static hosting only after team authorization."}
    (DIST / "PACKAGE_MANIFEST.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    print(f"Site: {len(files)} files, {total/1e6:.2f} MB -> {SITE}  |  zip: {zpath.name}")
    print("Credential scan (site):", site_hits or "clean")
    print("Credential scan (repo):", repo_hits or "clean")
    return 1 if (site_hits or repo_hits) else 0


if __name__ == "__main__":
    sys.exit(main())
