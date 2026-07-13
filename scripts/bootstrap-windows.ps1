[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$DesktopBuild
)

$ErrorActionPreference = "Stop"
$pythonVersion = "3.12.10"
$nodeVersion  = "22.14.0"
$pythonRoot   = Join-Path $env:LocalAppData "Programs\Python\Python312"
$python       = Join-Path $pythonRoot "python.exe"
$downloads    = Join-Path $env:TEMP "egx-intelligence-bootstrap"
New-Item -ItemType Directory -Path $downloads -Force | Out-Null

# ── helpers ──────────────────────────────────────────────────────────────────

function Write-Step([string]$text) { Write-Host "  → $text" -ForegroundColor Cyan }
function Write-OK([string]$text)   { Write-Host "  ✓ $text" -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host "  ⚠ $text" -ForegroundColor Yellow }
function Write-Err([string]$text)  { Write-Host "  ✗ $text" -ForegroundColor Red }

function Get-SafeDownload([string]$url, [string]$dest, [string]$label) {
    Write-Step "Downloading $label from $url"
    try {
        Invoke-WebRequest $url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Err "Download failed: $($_.Exception.Message)"
        Write-Err "DNS or network failure. Check your internet connection and try again."
        throw
    }
}

# ── Python ────────────────────────────────────────────────────────────────────

Write-Host "`nChecking Python $pythonVersion..." -ForegroundColor White
if (Test-Path $python) {
    Write-OK "Python found at $python"
} else {
    Write-Step "Installing Python $pythonVersion (this may take a minute)"
    $pythonInstaller = Join-Path $downloads "python-$pythonVersion-amd64.exe"
    Get-SafeDownload "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe" $pythonInstaller "Python $pythonVersion"
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
    if (-not (Test-Path $python)) { throw "Python installation failed. Run the installer manually: $pythonInstaller" }
    Write-OK "Python $pythonVersion installed"
}

# ── Git ───────────────────────────────────────────────────────────────────────

Write-Host "`nChecking Git..." -ForegroundColor White
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-OK "Git $(git --version)"
} else {
    Write-Warn "Git is not installed."
    Write-Warn "Install Git for Windows from https://git-scm.com/download/win then re-run this script."
    Write-Warn "Git is required for Tauri builds and version tracking."
    # Not a hard stop for non-desktop builds; desktop builds need it.
    if ($DesktopBuild) { throw "Git is required for desktop builds." }
}

# ── Docker (optional) ─────────────────────────────────────────────────────────

if (-not $SkipDocker) {
    Write-Host "`nChecking Docker Desktop..." -ForegroundColor White
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-OK "Docker $(docker --version)"
    } else {
        Write-Step "Installing Docker Desktop (large download, may take several minutes)"
        $dockerInstaller = Join-Path $downloads "DockerDesktopInstaller.exe"
        Get-SafeDownload "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" $dockerInstaller "Docker Desktop"
        Start-Process -FilePath $dockerInstaller -ArgumentList "install --quiet --accept-license" -Wait
        Write-OK "Docker Desktop installed. You may need to restart before using it."
    }
}

# ── Desktop-only prerequisites ────────────────────────────────────────────────

if ($DesktopBuild) {

    # Node.js
    Write-Host "`nChecking Node.js..." -ForegroundColor White
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCmd) {
        $nodeActual = & node --version
        Write-OK "Node.js $nodeActual"
    } else {
        Write-Step "Installing Node.js v$nodeVersion"
        $nodeInstaller = Join-Path $downloads "node-v$nodeVersion-x64.msi"
        Get-SafeDownload "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-x64.msi" $nodeInstaller "Node.js $nodeVersion"
        Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$nodeInstaller`" /quiet /norestart" -Wait
        Write-OK "Node.js $nodeVersion installed. Restart your terminal to use it."
    }

    # Rust / rustup
    Write-Host "`nChecking Rust..." -ForegroundColor White
    if (Get-Command rustup -ErrorAction SilentlyContinue) {
        Write-OK "Rust $(rustc --version 2>$null)"
    } else {
        Write-Step "Installing Rust stable-msvc via rustup-init.exe (from https://win.rustup.rs/x86_64)"
        $rustInstaller = Join-Path $downloads "rustup-init.exe"
        Get-SafeDownload "https://win.rustup.rs/x86_64" $rustInstaller "rustup-init"
        Start-Process -FilePath $rustInstaller -ArgumentList "-y --default-toolchain stable-msvc --no-modify-path" -Wait
        $cargoEnv = Join-Path $env:USERPROFILE ".cargo\env"
        if (Test-Path $cargoEnv) { . $cargoEnv }
        if (Get-Command rustc -ErrorAction SilentlyContinue) {
            Write-OK "Rust installed: $(rustc --version)"
        } else {
            Write-Warn "Rust was installed but rustc is not yet on PATH."
            Write-Warn "Close and reopen your terminal, then re-run this script to verify."
        }
    }

    # Visual Studio Build Tools (C++ desktop workload)
    Write-Host "`nChecking Visual Studio Build Tools..." -ForegroundColor White
    $vsInstalls = @(
        "${env:ProgramFiles}\Microsoft Visual Studio",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022"
    )
    $vsFound = $vsInstalls | Where-Object { Test-Path $_ }
    # Also check for standalone Build Tools via vswhere
    $vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $hasCppWorkload = $false
    if (Test-Path $vsWhere) {
        $vsInfo = & $vsWhere -products * -requires Microsoft.VisualCpp.Tools.HostX64.TargetX64 -format json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
        $hasCppWorkload = ($vsInfo -and $vsInfo.Count -gt 0)
    }
    if ($vsFound -or $hasCppWorkload) {
        Write-OK "Visual Studio / Build Tools with C++ workload found"
    } else {
        Write-Warn "Visual Studio Build Tools with the C++ Desktop workload were not detected."
        Write-Warn "Tauri requires the MSVC C++ toolchain."
        Write-Warn "ACTION REQUIRED: Run this installer manually (it requires UAC elevation):"
        Write-Warn "  https://aka.ms/vs/17/release/vs_BuildTools.exe"
        Write-Warn "Select 'Desktop development with C++' and click Install."
        Write-Warn "After installing, re-run this script with -DesktopBuild."
    }

    # WebView2 Runtime
    Write-Host "`nChecking WebView2 Runtime..." -ForegroundColor White
    $webView2Paths = @(
        "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application",
        "${env:ProgramFiles}\Microsoft\EdgeWebView\Application",
        "${env:LOCALAPPDATA}\Microsoft\EdgeWebView\Application"
    )
    $webView2Reg = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
    $webView2Found = ($webView2Reg -ne $null) -or ($webView2Paths | Where-Object { Test-Path $_ })
    if ($webView2Found) {
        Write-OK "WebView2 Runtime found"
    } else {
        Write-Warn "WebView2 Runtime was not detected."
        Write-Warn "Tauri apps require WebView2. The NSIS installer bundles a bootstrapper that"
        Write-Warn "downloads it automatically for end users. For development you can install it from:"
        Write-Warn "  https://developer.microsoft.com/microsoft-edge/webview2/#download-section"
        Write-Warn "(Choose 'Evergreen Standalone Installer' → x64)"
    }

    # NSIS
    Write-Host "`nChecking NSIS..." -ForegroundColor White
    $nsisPaths = @(
        "${env:ProgramFiles}\NSIS\makensis.exe",
        "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
    )
    $nsisFound = $nsisPaths | Where-Object { Test-Path $_ }
    if ($nsisFound) {
        Write-OK "NSIS found at $($nsisFound | Select-Object -First 1)"
    } else {
        Write-Warn "NSIS was not detected. NSIS is required to build the Windows installer."
        Write-Warn "ACTION REQUIRED: Download and install NSIS from https://nsis.sourceforge.io/Download"
        Write-Warn "Use the default installation directory. After installing, re-run this script."
    }

}   # end $DesktopBuild

# ── Python virtual environment ────────────────────────────────────────────────

Write-Host "`nSetting up Python virtual environment..." -ForegroundColor White

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path ".\.venv")) {
    Write-Step "Creating .venv"
    & $python -m venv .venv
} else {
    Write-OK ".venv already exists"
}

Write-Step "Upgrading pip"
& $venvPython -m pip install --upgrade pip --quiet

Write-Step "Installing project dependencies (including dev extras)"
& $venvPython -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed. Check the output above for missing system libraries." }
Write-OK "Python dependencies installed"

# ── Validate secrets are not overwritten ─────────────────────────────────────

$configDir = Join-Path $env:LOCALAPPDATA "EGX Intelligence"
$envFile    = Join-Path $configDir ".env"
$secretFile = Join-Path $configDir "secrets.json"
if (Test-Path $envFile) {
    Write-OK "Existing .env preserved at $envFile (not overwritten)"
}
if (Test-Path $secretFile) {
    Write-OK "Existing secrets.json preserved at $secretFile (not overwritten)"
}

# ── Frontend dependencies (desktop only) ─────────────────────────────────────

if ($DesktopBuild -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "`nInstalling frontend dependencies..." -ForegroundColor White
    Push-Location "desktop"
    try {
        npm install --silent
        if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
        Write-OK "Frontend dependencies installed"
    } finally { Pop-Location }
}

# ── Run tests ─────────────────────────────────────────────────────────────────

Write-Host "`nRunning tests..." -ForegroundColor White
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Err "Tests failed. Fix the failures above before building."
    throw "pytest failed"
}
Write-OK "All tests passed"

# ── Verify CLI tools ──────────────────────────────────────────────────────────

Write-Host "`nVerifying installed tools..." -ForegroundColor White
foreach ($cmd in @("python", "node", "npm", "cargo", "rustc")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { Write-OK "$cmd → $($found.Source)" }
    else { Write-Warn "$cmd not found on PATH (may need terminal restart)" }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
if ($DesktopBuild) {
    Write-Host "Build the desktop installer: scripts\build-desktop.ps1" -ForegroundColor Green
} else {
    Write-Host "Start the web stack: docker compose up --build" -ForegroundColor Green
    Write-Host "Or run the desktop installer build: scripts\bootstrap-windows.ps1 -DesktopBuild" -ForegroundColor Green
}
