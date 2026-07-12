[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    [string]$Repository,
    [Parameter(Mandatory)]
    [ValidatePattern("^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$")]
    [string]$Version,
    [string]$ReleaseNotes = "",
    [string]$SigningKeyPath = (Join-Path $HOME ".tauri\egx-intelligence.key"),
    [string]$SigningKeyPassword = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $SigningKeyPath)) { throw "Signing key not found: $SigningKeyPath. Run scripts\enable-updater.ps1 first." }
$packageVersion = (Get-Content (Join-Path $root "desktop\package.json") -Raw | ConvertFrom-Json).version
$tauriVersion = (Get-Content (Join-Path $root "desktop\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
$cargoVersion = ((Get-Content (Join-Path $root "desktop\src-tauri\Cargo.toml") | Where-Object { $_ -match '^version\s*=\s*"' } | Select-Object -First 1) -replace '^version\s*=\s*"|"$')
if (@($packageVersion, $tauriVersion, $cargoVersion) | Where-Object { $_ -ne $Version }) {
    throw "Release version $Version must match desktop/package.json ($packageVersion), tauri.conf.json ($tauriVersion), and Cargo.toml ($cargoVersion)."
}
$env:TAURI_SIGNING_PRIVATE_KEY = $SigningKeyPath
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = $SigningKeyPassword
try {
    & (Join-Path $PSScriptRoot "build-desktop.ps1") -Release
    if ($LASTEXITCODE -ne 0) { throw "Desktop release build failed." }
    & (Join-Path $PSScriptRoot "new-update-manifest.ps1") -Repository $Repository -Version $Version -ReleaseNotes $ReleaseNotes
    if ($LASTEXITCODE -ne 0) { throw "Could not create the update manifest." }
} finally {
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD -ErrorAction SilentlyContinue
}
