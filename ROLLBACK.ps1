param(
  [Parameter(Mandatory=$true)][string]$PriorVersion,
  [string]$BackupPath = ''
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$imageRepoLine = (Get-Content .env | Where-Object { $_ -match '^RMR_IMAGE_REPOSITORY=' } | Select-Object -First 1)
$imageRepo = if ($imageRepoLine) { $imageRepoLine.Split('=',2)[1] } else { 'rmr-platform' }
& docker image inspect "$imageRepo`:$PriorVersion" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Prior image $imageRepo`:$PriorVersion is not available locally." }
$lines = Get-Content .env
$found = $false
$updated = foreach ($line in $lines) {
  if ($line -match '^RMR_APP_VERSION=') { $found = $true; "RMR_APP_VERSION=$PriorVersion" } else { $line }
}
if (-not $found) { $updated += "RMR_APP_VERSION=$PriorVersion" }
Set-Content .env -Value $updated -Encoding ascii
if ($BackupPath) {
  & (Join-Path $PSScriptRoot 'RESTORE.ps1') -BackupPath $BackupPath
} else {
  & docker compose up -d --no-build
  if ($LASTEXITCODE -ne 0) { throw 'Rollback restart failed.' }
  & (Join-Path $PSScriptRoot 'HEALTH-CHECK.ps1')
}
Write-Host 'Rollback completed and health validation passed.'
