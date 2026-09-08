$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = "rmr-global-v5412c-product-owner"
$Compose = Join-Path $Root "docker-compose.product-owner.yml"
$Data = Join-Path $Root "product-owner-data-v5412c"
$ArchiveRoot = Join-Path $Root "product-owner-data-v5412c-archive"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Write-Host "This resets only the isolated Product Owner demo data." -ForegroundColor Yellow
$answer = Read-Host "Type RESET to continue"
if ($answer -ne "RESET") { Write-Host "Reset cancelled."; exit 0 }
Push-Location $Root
try {
    & docker compose --env-file .env.product-owner-v5412c -f $Compose -p $Project down --remove-orphans 2>$null | Out-Host
    if (Test-Path $Data) {
        New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null
        $archive = Join-Path $ArchiveRoot "product-owner-data-$Stamp"
        Move-Item -Path $Data -Destination $archive
        Write-Host "Previous demo data archived to: $archive" -ForegroundColor Cyan
    }
    New-Item -ItemType Directory -Force -Path $Data | Out-Null
    Write-Host "Demo data reset. Double-click START-PRODUCT-OWNER-TEST.bat to rebuild and start." -ForegroundColor Green
} finally { Pop-Location }
