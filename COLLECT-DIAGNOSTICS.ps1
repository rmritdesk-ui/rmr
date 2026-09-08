param(
    [string]$InstallPath = $PSScriptRoot,
    [string]$Reason = 'Manual diagnostic collection requested.'
)
$ErrorActionPreference = 'Stop'
$InstallPath = (Resolve-Path $InstallPath).Path
Import-Module (Join-Path $PSScriptRoot 'scripts\RmrDeployment.psm1') -Force
$path = Write-RmrDiagnostics -InstallPath $InstallPath -Reason $Reason -Label 'cb1-r2-manual-diagnostic'
Write-Host ''
Write-Host 'RMR Software CB1-R2 diagnostic collection completed.' -ForegroundColor Green
Write-Host "Send this file to RMR/ChatGPT: $path"
