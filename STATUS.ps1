$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose ps
if ($LASTEXITCODE -ne 0) { throw 'Unable to read Docker Compose status.' }
& docker compose exec -T app python -m rmr_platform.cli status
if ($LASTEXITCODE -ne 0) { throw 'Unable to read RMR Platform application status.' }
