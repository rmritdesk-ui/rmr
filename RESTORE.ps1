param([Parameter(Mandatory=$true)][string]$BackupPath)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$normalizedBackupPath = $BackupPath.Replace('\','/')
if (-not $normalizedBackupPath.StartsWith('data/backups/')) { throw 'Copy the backup into data/backups and pass that path.' }
$containerPath = "/data/backups/$([IO.Path]::GetFileName($BackupPath))"
& docker compose stop app
& docker compose run --rm app python -m rmr_platform.cli restore $containerPath
if ($LASTEXITCODE -ne 0) { throw 'Restore failed.' }
& docker compose up -d
& (Join-Path $PSScriptRoot 'HEALTH-CHECK.ps1')
