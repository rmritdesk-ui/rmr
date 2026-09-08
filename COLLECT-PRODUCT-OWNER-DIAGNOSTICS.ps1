param(
    [string]$Reason = "Manual diagnostic collection"
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = "rmr-global-v5412c-product-owner"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Diag = Join-Path $Root "product-owner-data-v5412c\diagnostics\$Stamp"
New-Item -ItemType Directory -Force -Path $Diag | Out-Null

function Capture([string]$Name, [scriptblock]$Action) {
    $path = Join-Path $Diag $Name
    try { & $Action 2>&1 | Out-File -FilePath $path -Encoding utf8 -Width 4096 } catch { $_ | Out-File -FilePath $path -Encoding utf8 -Width 4096 }
}

@(
    "RMR GLOBAL v5.4.1.2C PACKAGING CORRECTION PRODUCT OWNER DIAGNOSTICS",
    "Generated: $((Get-Date).ToUniversalTime().ToString('o'))",
    "Reason: $Reason",
    "Root: $Root",
    "PowerShell: $($PSVersionTable.PSVersion)",
    "OS: $([Environment]::OSVersion.VersionString)"
) | Out-File -FilePath (Join-Path $Diag "SUMMARY.txt") -Encoding utf8

Push-Location $Root
try {
    Capture "docker-version.txt" { docker version }
    Capture "docker-compose-version.txt" { docker compose version }
    Capture "compose-ps.txt" { docker compose --env-file .env.product-owner-v5412c -f docker-compose.product-owner.yml -p $Project ps -a }
    Capture "compose-logs.txt" { docker compose --env-file .env.product-owner-v5412c -f docker-compose.product-owner.yml -p $Project logs --timestamps --tail 800 }
    Capture "container-inspect.txt" {
        $id = docker compose --env-file .env.product-owner-v5412c -f docker-compose.product-owner.yml -p $Project ps -q app
        if ($id) { docker inspect $id } else { "Application container does not exist." }
    }
    Capture "host-health.txt" { Invoke-RestMethod "http://127.0.0.1:8089/api/health" -TimeoutSec 10 | ConvertTo-Json -Depth 12 }
    Capture "application-status.txt" { docker compose --env-file .env.product-owner-v5412c -f docker-compose.product-owner.yml -p $Project exec -T app python -m rmr_platform.cli status }
    Capture "product-owner-qc-latest.txt" {
        $p = Join-Path $Root "product-owner-data-v5412c\qc-results\PRODUCT-OWNER-QC-LATEST.json"
        if (Test-Path $p) { Get-Content $p -Raw } else { "No Product Owner QC result exists." }
    }
} finally { Pop-Location }

Write-Host "Diagnostics captured to:" -ForegroundColor Cyan
Write-Host $Diag
exit 0
