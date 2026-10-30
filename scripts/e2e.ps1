# One-command end-to-end check of the passport route, with MOCK passports (test only).
# Starts the stack if needed, then runs scripts/test-phone/e2e.ts in a container: an adult gets
# in, a minor cannot, and a captured proof is refused on replay. Exit code 0 means all passed.
# The site must use SITE_ORIGIN=http://localhost:5000 (the default) and PASSPORT_DEV_MODE=1.
# The payment step needs a real testnet wallet, so it is not covered here.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e.ps1            (the age-gate site)
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e.ps1 -Example   (the reusable
#       PassportGate, through examples/passport_site.py on port 5001)
param([switch]$Example)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

docker compose --profile passport up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Example) {
    # The example site, in the site's image, on the stack's network so it reaches the
    # passport service by name. Removed again at the end.
    $port = 5001
    $pagePath = "/passport-check/verify"
    $env:PASSPORT_PAGE = $pagePath
    $env:PASSPORT_START = "/passport-check/start"
    $env:PASSPORT_FINISH = "/passport-check/finish"
    $key = -join ((1..32) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })
    docker rm -f age-gate-example 2>$null | Out-Null
    docker run -d --name age-gate-example --network age-gate_default -p "127.0.0.1:${port}:5000" `
        -v "${PWD}:/src:ro" -e PYTHONPATH=/src/src -e SECRET_KEY=$key `
        -e PASSPORT_URL=http://passport:8100 -e SITE_DOMAIN=localhost `
        age-gate-site gunicorn --bind 0.0.0.0:5000 --chdir /src/examples passport_site:app | Out-Null
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    $port = 5000
    $pagePath = "/passport"
    $env:PASSPORT_PAGE = $pagePath
    $env:PASSPORT_START = "/api/passport/start"
    $env:PASSPORT_FINISH = "/api/passport/finish"
}

$ready = $false
foreach ($try in 1..30) {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:${port}${pagePath}"
        if ($page.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Error "Nothing answered on http://localhost:${port}${pagePath}"; exit 1 }

docker run --rm -e SITE_URL=http://host.docker.internal:$port `
    -e PASSPORT_PAGE -e PASSPORT_START -e PASSPORT_FINISH `
    -v "${PWD}\scripts\test-phone:/phone:ro" `
    oven/bun:1.3.8@sha256:371d30538b69303ced927bb5915697ac7e2fa8cb409ee332c66009de64de5aa3 `
    bash /phone/test-phone.sh e2e.ts
$result = $LASTEXITCODE
if ($Example) { docker rm -f age-gate-example | Out-Null }
exit $result
