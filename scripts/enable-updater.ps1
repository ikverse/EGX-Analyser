[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    [string]$Repository,
    [string]$SigningKeyPath = (Join-Path $HOME ".tauri\egx-analyzer.key"),
    [string]$SigningKeyPassword = "",
    [switch]$RotateSigningKey
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $root "desktop"
$configPath = Join-Path $desktop "src-tauri\tauri.conf.json"

function Read-SigningKeyPassword {
    $securePassword = Read-Host "Create a password for the update signing key" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

if ($RotateSigningKey -and (Test-Path $SigningKeyPath)) {
    Remove-Item $SigningKeyPath -Force
    Remove-Item "$SigningKeyPath.pub" -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $SigningKeyPath)) {
    $npx = Get-Command npx -ErrorAction SilentlyContinue
    if (-not $npx) { throw "Node.js is required to create the signing key. Install Node.js, restart PowerShell, then run this command again." }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SigningKeyPath) | Out-Null
    if (-not $SigningKeyPassword) {
        $SigningKeyPassword = Read-SigningKeyPassword
        if (-not $SigningKeyPassword) { throw "A signing-key password is required. Run the command again and enter a password." }
    }
    Write-Host "Creating the update signing key at $SigningKeyPath" -ForegroundColor Cyan
    Push-Location $desktop
    try {
        $signerArguments = @("tauri", "signer", "generate", "--ci", "--write-keys", $SigningKeyPath)
        $signerArguments += @("--password", $SigningKeyPassword)
        $output = & $npx.Source @signerArguments 2>&1
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the signing key: $($output -join [Environment]::NewLine)" }
}

$publicKeyPath = "$SigningKeyPath.pub"
if (-not (Test-Path $publicKeyPath)) { throw "The public signing key is missing: $publicKeyPath. Do not delete the private key; restore its matching .pub file from backup." }
$publicKey = (Get-Content $publicKeyPath -Raw).Trim()

$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not $config.plugins) { $config | Add-Member -NotePropertyName plugins -NotePropertyValue ([pscustomobject]@{}) }
$config.plugins | Add-Member -Force -NotePropertyName updater -NotePropertyValue ([pscustomobject]@{
    pubkey = $publicKey
    endpoints = @("https://github.com/$Repository/releases/latest/download/latest.json")
    windows = [pscustomobject]@{ installMode = "passive" }
})
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 12), $utf8WithoutBom)

Write-Host "OTA updates are configured for https://github.com/$Repository/releases." -ForegroundColor Green
Write-Host "Back up this private key now: $SigningKeyPath" -ForegroundColor Yellow
Write-Host "Never commit, email, or share the private key or its password." -ForegroundColor Yellow
