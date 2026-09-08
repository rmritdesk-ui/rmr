$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose exec -T app python -m rmr_platform.cli backup
if ($LASTEXITCODE -ne 0) { throw 'Backup failed.' }
