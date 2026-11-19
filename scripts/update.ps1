<#
Update the age gate on this computer in one step, and restart what is running.

  powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1

It:
  1. remembers which age-gate containers are running now (site, verifier, passport,
     zeccheckout, ...), whatever profiles they were started with,
  2. runs git pull,
  3. pulls every pinned image and builds every image this repository builds, in all
     profiles (plain `docker compose build` skips services in profiles, such as passport),
  4. recreates exactly the containers that were running, so each one is on its new image.

Nothing that was stopped is started. Your .env and config files are not touched.
-NoGitPull skips step 2 (for CI, or to rebuild what you already have).
#>
param([switch]$NoGitPull)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    function Invoke-Checked {
        param([string]$What)
        & $args[0] $args[1..($args.Count - 1)]
        if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)." }
    }

    # Every profile by name (a literal "*" can be expanded as a file pattern on the way to docker).
    $profiles = @(docker compose config --profiles | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0) { throw "docker compose config failed. Is Docker Desktop running?" }
    $all = @("compose") + @($profiles | ForEach-Object { "--profile", $_ })

    $running = @(docker @all ps --services --status running)
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed. Is Docker Desktop running?" }
    $running = @($running | Where-Object { $_ })
    if ($running.Count -gt 0) {
        Write-Host "Running now: $($running -join ', ')"
    } else {
        Write-Host "No age-gate containers are running; images will be updated, nothing restarted."
    }

    if (-not $NoGitPull) {
        Invoke-Checked "git pull" git pull --ff-only
    }
    Invoke-Checked "Pulling images" docker @all pull --ignore-buildable
    Invoke-Checked "Building images" docker @all build

    if ($running.Count -gt 0) {
        Invoke-Checked "Restarting" docker @all up -d --no-deps @running
        Write-Host ""
        Write-Host "Updated and restarted: $($running -join ', ')"
    }
} finally {
    Pop-Location
}
