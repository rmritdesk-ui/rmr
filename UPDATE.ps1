$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path .env)) { throw 'Run INSTALL.ps1 before UPDATE.ps1.' }
& docker compose exec -T app python -m rmr_platform.cli backup
if ($LASTEXITCODE -ne 0) { Write-Warning 'Pre-update backup failed; update stopped.'; exit 1 }
& docker compose build
if ($LASTEXITCODE -ne 0) { throw 'Application image build failed.' }
& docker compose run --rm app python -m rmr_platform.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'Application restart failed.' }
& (Join-Path $PSScriptRoot 'HEALTH-CHECK.ps1')
Write-Host 'Update completed and health validation passed.'
