$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = "rmr-global-v5412c-product-owner"
$Compose = Join-Path $Root "docker-compose.product-owner.yml"
Push-Location $Root
try {
    Write-Host "Stopping only the isolated RMR Global v5.4.1.2C Packaging Correction Product Owner environment..." -ForegroundColor Yellow
    & docker compose --env-file .env.product-owner-v5412c -f $Compose -p $Project stop
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose stop returned exit code $LASTEXITCODE." }
    Write-Host "Product Owner environment stopped. Demo data was preserved." -ForegroundColor Green
} finally { Pop-Location }
