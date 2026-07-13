param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create the Python environment first: scripts/bootstrap-windows.ps1" }
& $python (Join-Path $PSScriptRoot "content_pack.py") build --version $Version
if ($LASTEXITCODE -ne 0) { throw "Content pack build failed." }
$publishCheckout = Join-Path $root "github-upload"
if (Test-Path (Join-Path $publishCheckout ".git")) {
    Copy-Item (Join-Path $root "remote-content\*") (Join-Path $publishCheckout "remote-content") -Recurse -Force
    Write-Host "Content pack copied to github-upload. Commit and push only remote-content for an instant content update." -ForegroundColor Green
} else {
    Write-Host "Content pack files are ready under remote-content. Commit and push only those files for an instant content update." -ForegroundColor Green
}
