$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose stop
if ($LASTEXITCODE -ne 0) { throw 'RMR Platform stop failed.' }
Write-Host 'RMR Platform stopped.'
