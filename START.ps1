$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'RMR Platform start failed.' }
& (Join-Path $PSScriptRoot 'HEALTH-CHECK.ps1')
