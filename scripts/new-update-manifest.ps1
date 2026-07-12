[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    [string]$Repository,
    [Parameter(Mandatory)]
    [ValidatePattern("^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$")]
    [string]$Version,
    [string]$ReleaseNotes = "",
    [string]$InstallerPath,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $InstallerPath) {
    $nsisDir = Join-Path $root "desktop\src-tauri\target\release\bundle\nsis"
    $InstallerPath = Get-ChildItem $nsisDir -Filter "*.exe" | Where-Object { $_.Name -notlike "*.sig" } | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $InstallerPath -or -not (Test-Path $InstallerPath)) { throw "Could not find the signed NSIS installer. Build the release first." }
$signaturePath = "$InstallerPath.sig"
if (-not (Test-Path $signaturePath)) { throw "Could not find $signaturePath. Ensure TAURI_SIGNING_PRIVATE_KEY is set before the release build." }
if (-not $OutputPath) { $OutputPath = Join-Path $root "release\latest.json" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
$installerName = Split-Path -Leaf $InstallerPath
$manifest = [ordered]@{
    version = $Version
    notes = $ReleaseNotes
    pub_date = (Get-Date).ToUniversalTime().ToString("o")
    platforms = [ordered]@{
        "windows-x86_64" = [ordered]@{
            url = "https://github.com/$Repository/releases/download/v$Version/$installerName"
            signature = (Get-Content $signaturePath -Raw).Trim()
        }
    }
}
$manifestJson = $manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($OutputPath, $manifestJson, [System.Text.UTF8Encoding]::new($false))
Write-Host "Update manifest written to $OutputPath" -ForegroundColor Green
