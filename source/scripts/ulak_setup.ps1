# ULAK - one-time local setup (Windows PowerShell 5.1+). AI-assisted script; review before running.
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts\ulak_setup.ps1
# Creates .venv with your existing Python (py launcher, tested target: 3.14), installs dependencies, runs tests.
# Native tools (pip, python) may write warnings to stderr; PowerShell 5.1 would abort on those
# under "Stop", so we use "Continue" and check $LASTEXITCODE explicitly after each step.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== ULAK setup ==" -ForegroundColor Cyan
py --version
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv (does not touch system Python)..."
    py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv with the py launcher" }
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $py -m pip install -r analysis\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed. If a wheel is missing for your Python version, install Python 3.13 and run: py -3.13 -m venv .venv" }

Write-Host "`n== Running automated tests ==" -ForegroundColor Cyan
& $py -m pytest analysis -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "Tests failed - do not proceed to real-data processing until fixed." }

Write-Host "`n== Checking committed NISAR catalog against live NASA CMR (public, no login) ==" -ForegroundColor Cyan
& $py analysis\nisar_catalog.py
Write-Host "`nSetup complete. Next: scripts\ulak_run_sudd.ps1" -ForegroundColor Green
