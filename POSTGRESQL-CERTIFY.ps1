$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Project="rmr-cb1-postgres-certification"
Write-Host "RMR Software v5.1 CB1-R2 PostgreSQL Certification" -ForegroundColor Cyan
if(-not $env:RMR_POSTGRES_PASSWORD){
  $env:RMR_POSTGRES_PASSWORD = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
}
$files=@("-f","docker-compose.yml","-f","docker-compose.postgres.yml","--project-name",$Project)
try {
  docker compose @files up -d --build | Out-Host
  $deadline=(Get-Date).AddMinutes(6); $ready=$false
  while((Get-Date)-lt $deadline){
    Start-Sleep 5
    try { $h=Invoke-RestMethod "http://127.0.0.1:8080/api/health" -TimeoutSec 10; if($h.status -eq "healthy" -and $h.version -match "commercial-cb1"){$ready=$true;break} } catch {}
  }
  if(-not $ready){ throw "CB1-R2 did not become healthy on PostgreSQL." }
  docker compose @files exec -T app python qa/cb1_postgres_certification.py | Out-Host
  if($LASTEXITCODE -ne 0){ throw "PostgreSQL application certification failed." }
  New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\postgres-certification") | Out-Null
  $dump=Join-Path $Root ("data\postgres-certification\cb1-postgres-"+(Get-Date -Format yyyyMMdd-HHmmss)+".sql")
  docker compose @files exec -T postgres pg_dump -U rmr -d rmr | Set-Content -Encoding utf8 $dump
  if(-not (Test-Path $dump) -or (Get-Item $dump).Length -lt 100){ throw "PostgreSQL backup file was not created correctly." }
  Write-Host "POSTGRESQL CERTIFICATION PASSED" -ForegroundColor Green
  Write-Host "Backup evidence: $dump" -ForegroundColor Green
} catch {
  Write-Host $_ -ForegroundColor Red
  & (Join-Path $Root "COLLECT-DIAGNOSTICS-CB1.ps1")
  throw
}
