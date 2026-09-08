param(
    [string]$PreviousInstall = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host "RMR Software v5.1 Correction Build 1 Revision 2 - Verified Rollback" -ForegroundColor Cyan
if([string]::IsNullOrWhiteSpace($PreviousInstall)){
    $resultFile = Join-Path $Root "data\LAST-UPGRADE-RESULT.json"
    if(Test-Path $resultFile){
        try {
            $j = Get-Content $resultFile -Raw | ConvertFrom-Json
            foreach($candidate in @($j.source_install,$j.previous_install,$j.existing_install)){
                if($candidate -and (Test-Path $candidate)){ $PreviousInstall=$candidate; break }
            }
        } catch {}
    }
}
if([string]::IsNullOrWhiteSpace($PreviousInstall)){
    $PreviousInstall = Read-Host "Enter the full path to the previous v5.1 Commercial Candidate folder"
}
$PreviousInstall = (Resolve-Path $PreviousInstall).Path
if(-not (Test-Path (Join-Path $PreviousInstall "docker-compose.yml"))){ throw "Previous installation folder is invalid." }
Write-Host "Stopping Correction Build 1 Revision 2..." -ForegroundColor Yellow
try { docker compose down | Out-Host } catch {}
Write-Host "Restarting previous v5.1 candidate..." -ForegroundColor Yellow
Push-Location $PreviousInstall
try { docker compose up -d | Out-Host } finally { Pop-Location }
$deadline=(Get-Date).AddMinutes(4)
$healthy=$false
while((Get-Date) -lt $deadline){
    Start-Sleep -Seconds 4
    try {
        $r=Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 10
        if($r.status -eq "healthy" -and [string]$r.version -match "5\.1\.0-commercial-rc1"){$healthy=$true;break}
    } catch {}
}
if(-not $healthy){
    Write-Host "Rollback restart did not pass the health gate. Collecting diagnostics." -ForegroundColor Red
    & (Join-Path $Root "COLLECT-DIAGNOSTICS-CB1.ps1")
    throw "Previous v5.1 candidate could not be verified healthy."
}
Write-Host "ROLLBACK COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "The previous v5.1 Commercial Candidate is healthy at http://localhost:8080" -ForegroundColor Green
