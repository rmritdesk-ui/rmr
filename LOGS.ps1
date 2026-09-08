$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose logs --tail=200 -f app
