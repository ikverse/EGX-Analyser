[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$DesktopBuild
)

$ErrorActionPreference = "Stop"
$pythonVersion = "3.12.10"
$pythonRoot = Join-Path $env:LocalAppData "Programs\Python\Python312"
$python = Join-Path $pythonRoot "python.exe"
$downloads = Join-Path $env:TEMP "egx-intelligence-bootstrap"
New-Item -ItemType Directory -Path $downloads -Force | Out-Null

if (-not (Test-Path $python)) {
    $pythonInstaller = Join-Path $downloads "python-$pythonVersion-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe" -OutFile $pythonInstaller
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
}

if (-not $SkipDocker -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerInstaller = Join-Path $downloads "DockerDesktopInstaller.exe"
    Invoke-WebRequest "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" -OutFile $dockerInstaller
    Start-Process -FilePath $dockerInstaller -ArgumentList "install --quiet --accept-license" -Wait
}

if ($DesktopBuild -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    $nodeInstaller = Join-Path $downloads "node-v22.14.0-x64.msi"
    Invoke-WebRequest "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi" -OutFile $nodeInstaller
    Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$nodeInstaller`" /quiet /norestart" -Wait
}

if ($DesktopBuild -and -not (Get-Command rustup -ErrorAction SilentlyContinue)) {
    $rustInstaller = Join-Path $downloads "rustup-init.exe"
    Invoke-WebRequest "https://win.rustup.rs/x86_64" -OutFile $rustInstaller
    Start-Process -FilePath $rustInstaller -ArgumentList "-y --default-toolchain stable-msvc" -Wait
}

& $python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -m pytest -q

Write-Host "Setup complete. Restart your terminal. Run docker compose up --build for the web app, or scripts/build-desktop.ps1 for a desktop installer." -ForegroundColor Green
