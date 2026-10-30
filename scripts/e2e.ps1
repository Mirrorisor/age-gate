# One-command end-to-end check of the passport route, with MOCK passports (test only).
# Starts the stack if needed, then runs scripts/test-phone/e2e.ts in a container: an adult gets
# in, a minor cannot, and a captured proof is refused on replay. Exit code 0 means all passed.
# The site must use SITE_ORIGIN=http://localhost:5000 (the default) and PASSPORT_DEV_MODE=1.
# The payment step needs a real testnet wallet, so it is not covered here.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

docker compose -f docker-compose.yml -f docker-compose.fork.yml --profile passport up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ready = $false
foreach ($try in 1..30) {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://localhost:5000/passport
        if ($page.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Error "The site did not answer on http://localhost:5000/passport"; exit 1 }

docker run --rm -e SITE_URL=http://host.docker.internal:5000 `
    -v "${PWD}\scripts\test-phone:/phone:ro" `
    oven/bun:1.3.8@sha256:371d30538b69303ced927bb5915697ac7e2fa8cb409ee332c66009de64de5aa3 `
    bash /phone/test-phone.sh e2e.ts
exit $LASTEXITCODE
