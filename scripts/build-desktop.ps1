[CmdletBinding()]
param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create the Python environment first: scripts/bootstrap-windows.ps1" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js 20+ is required to build the desktop installer." }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Rust is required to build the desktop installer." }

$tauriConfig = Get-Content (Join-Path $root "desktop\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
$loadedDefaultSigningKey = $false
$loadedDefaultSigningPassword = $false
if ($tauriConfig.plugins.updater.pubkey -and -not $env:TAURI_SIGNING_PRIVATE_KEY) {
    $preferredSigningKey = Join-Path $HOME ".tauri\egx-analyzer.key"
    $legacySigningKey = Join-Path $HOME ".tauri\egx-intelligence.key"
    $defaultSigningKey = if (Test-Path $preferredSigningKey) { $preferredSigningKey } elseif (Test-Path $legacySigningKey) { $legacySigningKey } else { $preferredSigningKey }
    if (-not (Test-Path $defaultSigningKey)) {
        throw "OTA updates are configured but no signing key was found. Restore the original $legacySigningKey (preferred for installed users) or set TAURI_SIGNING_PRIVATE_KEY before building."
    }
    $env:TAURI_SIGNING_PRIVATE_KEY = $defaultSigningKey
    $securePassword = Read-Host "Enter the update signing-key password" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try { $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer) }
    if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) { throw "An update signing-key password is required to build this application." }
    $loadedDefaultSigningKey = $true
    $loadedDefaultSigningPassword = $true
}

if ($Release) {
    $updater = $tauriConfig.plugins.updater
    if (-not $updater -or -not $updater.pubkey -or -not $updater.endpoints) {
        throw "OTA updates are not configured. Run scripts\enable-updater.ps1 with your GitHub owner/repository first."
    }
    if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
        throw "A release build requires TAURI_SIGNING_PRIVATE_KEY. Use scripts\build-release.ps1 so your signing key is loaded safely."
    }
}

Push-Location $root
try {
    & $python -m pip install --no-build-isolation -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "Could not install the local Python project into the existing virtual environment." }
    & $python scripts/generate_desktop_icon.py

    # Build the sidecar as --onedir (avoids %TEMP% self-extraction that triggers
    # Windows Defender ASR "Block executable files" rule).
    & $python -m PyInstaller --noconfirm --clean egx-intelligence-api.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed. Check the output above." }

    # Copy the entire onedir folder into Tauri's resources directory.
    $sidecarsDir = Join-Path $root "desktop\src-tauri\sidecar"
    if (Test-Path $sidecarsDir) { Remove-Item $sidecarsDir -Recurse -Force }
    Copy-Item "dist\egx-intelligence-api" $sidecarsDir -Recurse -Force
    $sidecarExe = Join-Path $sidecarsDir "egx-intelligence-api.exe"
    $pythonDll = Join-Path $sidecarsDir "_internal\python312.dll"
    if (-not (Test-Path $sidecarExe)) { throw "Sidecar executable was not produced: $sidecarExe" }
    if (-not (Test-Path $pythonDll)) { throw "PyInstaller sidecar is missing python312.dll: $pythonDll" }
    Write-Host "Sidecar folder copied to $sidecarsDir" -ForegroundColor Green
    Push-Location "desktop\src-tauri"
    try {
        Write-Host "Running cargo check..." -ForegroundColor Cyan
        cargo check
        if ($LASTEXITCODE -ne 0) { throw "cargo check failed. Fix Rust compilation errors before building the installer." }
        Write-Host "cargo check passed." -ForegroundColor Green
    } finally { Pop-Location }
    Push-Location "desktop"
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "Could not install desktop dependencies." }
        $buildLog = Join-Path $root "desktop-build.log"
        & cmd.exe /d /c "npm run tauri build > `"$buildLog`" 2>&1"
        $buildExitCode = $LASTEXITCODE
        Get-Content $buildLog
        if ($buildExitCode -ne 0) { throw "Desktop build failed. See desktop-build.log for the exact cause." }
    } finally { Pop-Location }
} finally {
    if ($loadedDefaultSigningKey) { Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY -ErrorAction SilentlyContinue }
    if ($loadedDefaultSigningPassword) { Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD -ErrorAction SilentlyContinue }
    Pop-Location
}

Write-Host "Installer created under desktop\src-tauri\target\release\bundle\nsis" -ForegroundColor Green
