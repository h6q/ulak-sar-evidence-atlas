# ULAK - process REAL NISAR GCOV data for the central Sudd AOI and publish results into web\data.
# AI-assisted script; review before running.
#
# Usage (from the repository root, after scripts\ulak_setup.ps1):
#   powershell -ExecutionPolicy Bypass -File scripts\ulak_run_sudd.ps1            # pair + 10-date series
#   powershell -ExecutionPolicy Bypass -File scripts\ulak_run_sudd.ps1 -PairOnly  # only 2026-06-20 vs 2026-10-18
#
# Authentication: an Earthdata Login bearer token is requested at a hidden prompt only if a cache miss
#   requires an HTTPS read. Fully cached runs do not need a token.
#   Create it at https://urs.earthdata.nasa.gov  ->  Generate Token  (free account).
#   The token stays in this PowerShell process memory only; it is never written to disk or to the repo.
#   Do NOT paste the token into chat or commit it anywhere.
# Data volume: only the AOI window is read over HTTPS (range requests), not the ~1.8 GB granules.
param(
    [switch]$PairOnly,
    [switch]$FullDownload,   # fallback if HTTPS range reads are refused: downloads full .h5 (~1.8 GB each) to data\raw
    [string]$Before = "2026-06-20",
    [string]$After = "2026-10-18",
    [double[]]$Aoi = @(30.55, 7.00, 30.95, 7.40)
)
# Native tools (pip, python) may write warnings to stderr; PowerShell 5.1 would abort on those
# under "Stop", so we use "Continue" and check $LASTEXITCODE explicitly after each step.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run scripts\ulak_setup.ps1 first." }

$log = "data\derived\run_$(Get-Date -Format yyyyMMdd_HHmmss).log"
New-Item -ItemType Directory -Force -Path data\derived | Out-Null
$argsList = @("analysis\run_sudd.py", "--before", $Before, "--after", $After, "--log-file", $log, "--aoi") + ($Aoi | ForEach-Object { [string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $_) })
if ($PairOnly) { $argsList += "--no-series" }
if ($FullDownload) { $argsList += @("--source", "download") }
Write-Host "Running: python $($argsList -join ' ')" -ForegroundColor Cyan
try {
    # Python writes its own UTF-8 log (credentials scrubbed). No Tee-Object: PowerShell 5.1 would write UTF-16
    # and wrap Python's stderr lines as NativeCommandError records.
    & $py @argsList
    $code = $LASTEXITCODE
} finally {
    Remove-Item Env:\EARTHDATA_TOKEN -ErrorAction SilentlyContinue   # drop token from the session
}
if ($code -ne 0) { Write-Host "Workflow stopped with exit code $code. See $log (credentials are scrubbed). Windows already read are cached in data\derived\cache and will be reused on rerun." -ForegroundColor Red; exit $code }

Write-Host "`nResults: web\data\sudd_report.json + overlays; GeoTIFFs + provenance sidecars in data\derived" -ForegroundColor Green
Write-Host "View locally:  py -m http.server 8000 --directory web   then open http://localhost:8000"
