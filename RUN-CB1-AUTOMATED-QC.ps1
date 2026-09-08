param()
$ErrorActionPreference="Continue"
$ScriptRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
function Test-AppRoot($p){ return (Test-Path (Join-Path $p "docker-compose.yml")) -and (Test-Path (Join-Path $p "rmr_platform")) -and (Test-Path (Join-Path $p "qa")) }
$Root=$ScriptRoot
if(-not (Test-AppRoot $Root)){
  $cur=Get-Item $ScriptRoot
  for($i=0;$i -lt 5 -and $cur;$i++){
    if($cur.Parent -and (Test-AppRoot $cur.Parent.FullName)){ $Root=$cur.Parent.FullName; break }
    $cur=$cur.Parent
  }
}
if(-not (Test-AppRoot $Root)){ Write-Host "Unable to locate the CB1 application root. No tests were run." -ForegroundColor Red; exit 2 }
Set-Location $Root
$stamp=Get-Date -Format yyyyMMdd-HHmmss
$outDir=Join-Path $Root "data\qc-results"; New-Item -Force -ItemType Directory $outDir|Out-Null
$report=Join-Path $outDir ("RMR-CB1-AUTOMATED-QC-"+$stamp+".txt")
"RMR SOFTWARE v5.1 CORRECTION BUILD 1 AUTOMATED QC"|Set-Content $report
("Generated: "+(Get-Date).ToString("o"))|Add-Content $report
("Application root: "+$Root)|Add-Content $report
$pass=0;$fail=0
function Result($name,$ok,$detail){ if($ok){$script:pass++;$s="PASS";$c="Green"}else{$script:fail++;$s="FAIL";$c="Red"}; Write-Host "[$s] $name" -ForegroundColor $c; "[$s] $name | $detail"|Add-Content $report }
try { $dv=docker version --format "{{.Server.Version}}" 2>&1; Result "Docker engine" ($LASTEXITCODE -eq 0) $dv } catch { Result "Docker engine" $false $_ }
try { $h=Invoke-RestMethod "http://127.0.0.1:8080/api/health" -TimeoutSec 15; Result "Application health" ($h.status -eq "healthy") ($h|ConvertTo-Json -Depth 8); Result "CB1 version" ([string]$h.version -match "5.4.1.2-interaction-regression-correction-po1") ([string]$h.version) } catch { Result "Application health" $false $_ }
$tests=@("qa/v51-acceptance.py","qa/cb1_preflight.py","qa/cb1_acceptance.py","qa/cb1_release_audit.py")
foreach($test in $tests){
  "`r`n===== $test ====="|Add-Content $report
  $output = docker compose run --rm --no-deps -v "${Root}:/work" -w /work --entrypoint python app $test 2>&1 | Out-String
  $ok=($LASTEXITCODE -eq 0)
  $output|Add-Content $report
  Result $test $ok ($output.Substring(0,[Math]::Min(400,$output.Length)))
}
"`r`nDOCKER COMPOSE PS -A"|Add-Content $report
docker compose ps -a 2>&1|Add-Content $report
"`r`nRECENT APP LOGS"|Add-Content $report
docker compose logs --tail 300 app 2>&1|Add-Content $report
"`r`nSUMMARY: $pass PASS / $fail FAIL"|Add-Content $report
Write-Host "QC COMPLETE: $pass PASS / $fail FAIL" -ForegroundColor Cyan
Write-Host "Upload this report to ChatGPT/RMR: $report" -ForegroundColor Yellow
if($fail -gt 0){exit 1}else{exit 0}

# RMR Global v5.2 cumulative preservation and unified product gates
& python (Join-Path $Root "qa/cumulative_product_preservation.py")
if($LASTEXITCODE -ne 0){ Write-Host "[FAIL] qa/cumulative_product_preservation.py" -ForegroundColor Red; exit 1 }
Write-Host "[PASS] qa/cumulative_product_preservation.py" -ForegroundColor Green
& python (Join-Path $Root "qa/unified_product_integration.py")
if($LASTEXITCODE -ne 0){ Write-Host "[FAIL] qa/unified_product_integration.py" -ForegroundColor Red; exit 1 }
Write-Host "[PASS] qa/unified_product_integration.py" -ForegroundColor Green
