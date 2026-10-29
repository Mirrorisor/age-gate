<#
Make the local age gate reachable at a temporary public https address, for TESTING ONLY
(test credentials, Zcash testnet). Uses a Cloudflare quick tunnel: free, no account, and
a new random address every time it starts.

  powershell -ExecutionPolicy Bypass -File .\scripts\go-public.ps1         start
  powershell -ExecutionPolicy Bypass -File .\scripts\go-public.ps1 -Stop   back to local

Starting it:
  1. runs cloudflared and waits for its https://....trycloudflare.com address,
  2. writes that address into the verifier's config.toml (expected_origin),
  3. sets SITE_ORIGIN, SESSION_COOKIE_SECURE=1 and TRUST_PROXY=1 in .env,
  4. recreates the site container and restarts the verifier.
-Stop undoes all four and goes back to http://localhost:5000.

Cloudflare can see visitors' IP addresses and which pages they open. The site keeps the
visitor address only in memory, for one minute, for rate limiting.
#>
param([switch]$Stop)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo ".env"
$logFile = Join-Path $env:TEMP "age-gate-tunnel.log"
$pidFile = Join-Path $env:TEMP "age-gate-tunnel.pid"
$localOrigin = "http://localhost:5000"
$utf8 = New-Object System.Text.UTF8Encoding($false)  # no BOM: compose and TOML dislike it
$compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.fork.yml")

if (-not (Test-Path $envFile)) { throw "No .env file in $repo. Copy .env.example to .env first." }

function Read-EnvValue($name) {
    foreach ($line in [IO.File]::ReadAllLines($envFile)) {
        if ($line -match "^\s*$name\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Set-EnvValues($values) {
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($line in [IO.File]::ReadAllLines($envFile)) { $lines.Add($line) }
    foreach ($key in $values.Keys) {
        $newLine = "$key=$($values[$key])"
        $index = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^\s*$key\s*=") { $index = $i }
        }
        if ($index -ge 0) { $lines[$index] = $newLine } else { $lines.Add($newLine) }
    }
    [IO.File]::WriteAllLines($envFile, $lines, $utf8)
}

function Set-ExpectedOrigin($origin) {
    $dir = Read-EnvValue "VERIFIER_CONFIG_DIR"
    if (-not $dir) { $dir = Join-Path $repo "verifier-config" }
    $file = Join-Path $dir "config.toml"
    $text = [IO.File]::ReadAllText($file)
    if ($text -notmatch '(?m)^\s*expected_origin\s*=') {
        throw "No expected_origin line in $file"
    }
    $text = [regex]::Replace(
        $text, '(?m)^(\s*expected_origin\s*=\s*)[^\r\n]*', ('${1}"' + $origin + '"'))
    [IO.File]::WriteAllText($file, $text, $utf8)
    Write-Host "Verifier now expects $origin  ($file)"
}

function Restart-Stack {
    Push-Location $repo
    try {
        & docker @compose up -d --no-deps site
        if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
        & docker @compose restart verifier
        if ($LASTEXITCODE -ne 0) { throw "docker compose restart failed" }
    } finally {
        Pop-Location
    }
}

function Stop-Tunnel {
    if (Test-Path $pidFile) {
        $id = [int](Get-Content $pidFile)
        Stop-Process -Id $id -ErrorAction SilentlyContinue
        Remove-Item $pidFile
    }
}

function Find-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "cloudflared\cloudflared.exe"),
        (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe")
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    throw ("cloudflared not found. Install it with:  winget install --id Cloudflare.cloudflared -e" +
        "  then open a new PowerShell window and run this again.")
}

if ($Stop) {
    Stop-Tunnel
    Set-ExpectedOrigin $localOrigin
    Set-EnvValues @{ SITE_ORIGIN = $localOrigin; SESSION_COOKIE_SECURE = "0"; TRUST_PROXY = "0" }
    Restart-Stack
    Write-Host "Tunnel stopped. Local only again: $localOrigin" -ForegroundColor Green
    exit 0
}

$exe = Find-Cloudflared
Stop-Tunnel
Remove-Item $logFile, "$logFile.out" -ErrorAction SilentlyContinue
$start = @{
    FilePath = $exe
    ArgumentList = @("tunnel", "--no-autoupdate", "--url", $localOrigin)
    RedirectStandardError = $logFile
    RedirectStandardOutput = "$logFile.out"
    PassThru = $true
}
if ($PSVersionTable.PSEdition -eq "Desktop" -or $IsWindows) { $start.WindowStyle = "Hidden" }
$proc = Start-Process @start
Set-Content -Path $pidFile -Value $proc.Id

Write-Host "Waiting for the tunnel address..."
$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { throw "cloudflared stopped. See $logFile" }
    if (Test-Path $logFile) {
        $text = Get-Content -Raw -Path $logFile -ErrorAction SilentlyContinue
        if ($text) {
            foreach ($m in [regex]::Matches($text, 'https://[a-z0-9-]+\.trycloudflare\.com')) {
                if ($m.Value -ne "https://api.trycloudflare.com") { $url = $m.Value; break }
            }
        }
    }
}
if (-not $url) {
    Stop-Tunnel
    throw "No tunnel address after 60 seconds. See $logFile"
}

Set-ExpectedOrigin $url
Set-EnvValues @{ SITE_ORIGIN = $url; SESSION_COOKIE_SECURE = "1"; TRUST_PROXY = "1" }
Restart-Stack

Write-Host ""
Write-Host "Public TEST address:  $url/verify" -ForegroundColor Green
Write-Host "Test credentials and testnet coins only. The address changes every time."
Write-Host "Stop it with:  powershell -ExecutionPolicy Bypass -File .\scripts\go-public.ps1 -Stop"
