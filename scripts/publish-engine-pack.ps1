param([Parameter(Mandatory = $true)][string]$Version)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
& $python (Join-Path $PSScriptRoot "engine_pack.py") --version $Version
if ($LASTEXITCODE -ne 0) { throw "Engine pack build failed." }
$checkout = Join-Path $root "github-upload"
if (Test-Path (Join-Path $checkout ".git")) { Copy-Item (Join-Path $root "remote-engine\*") (Join-Path $checkout "remote-engine") -Recurse -Force }
Write-Host "Commit and push remote-engine only. Installed apps can download the patch from Settings." -ForegroundColor Green
