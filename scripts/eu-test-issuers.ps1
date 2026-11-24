<#
Trust the EU's official TEST age-verification issuers (never a real one) in this verifier.

  powershell -ExecutionPolicy Bypass -File .\scripts\eu-test-issuers.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\eu-test-issuers.ps1 -DryRun

Runs scripts/eu_test_issuers.py inside the verifier's image: it checks the signatures of the
EU's acceptance (test) and production (real) Age Verification Trusted Lists, keeps the test
issuers that are not also on the production list, and writes them as eu-av-test-*.pem into
the certs folder of the verifier config this Compose project uses. Then it restarts the
verifier, if it is running. No other file in that folder is touched.
#>
param([switch]$DryRun)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $config = docker compose config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "docker compose config failed. Is Docker Desktop running?" }
    $mount = $config.services.verifier.volumes | Where-Object { $_.target -eq "/config" }
    if (-not $mount) { throw "The verifier has no /config folder in this Compose project." }
    $certs = Join-Path $mount.source "certs"
    if (-not (Test-Path $certs)) { New-Item -ItemType Directory -Path $certs | Out-Null }
    Write-Host "Certs folder: $certs"

    $extra = @()
    if ($DryRun) { $extra = @("--dry-run") }
    docker compose run --rm --no-deps `
        -v "${certs}:/out" -v "${repo}\scripts:/scripts:ro" `
        --entrypoint /app/.venv/bin/python verifier /scripts/eu_test_issuers.py /out @extra
    if ($LASTEXITCODE -ne 0) { throw "The EU list check refused or failed (exit $LASTEXITCODE); nothing was changed." }

    if (-not $DryRun) {
        $running = @(docker compose ps --services --status running)
        if ($running -contains "verifier") {
            docker compose restart verifier
            Write-Host "Verifier restarted with the new certificates."
        }
    }
} finally {
    Pop-Location
}
