$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Results = Join-Path $Root "data\qc-results"
New-Item -ItemType Directory -Force -Path $Results | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Log = Join-Path $Results "RMR-GLOBAL-UNIFIED-PRODUCT-QC-$Stamp.txt"
$checks = @(
    @{ Name = "Cumulative product preservation"; Script = "qa/cumulative_product_preservation.py" },
    @{ Name = "Unified customer workspace integration"; Script = "qa/unified_product_integration.py" },
    @{ Name = "CB1 preflight regression"; Script = "qa/cb1_preflight.py" },
    @{ Name = "CB1 acceptance regression"; Script = "qa/cb1_acceptance.py" },
    @{ Name = "v5.1 acceptance regression"; Script = "qa/v51_acceptance.py" }
)
$pass=0; $fail=0
"RMR GLOBAL v5.2 UNIFIED PRODUCT QC" | Tee-Object -FilePath $Log
foreach($c in $checks){
    $path=Join-Path $Root $c.Script
    if(-not (Test-Path $path)){ "[FAIL] $($c.Name) - missing $($c.Script)" | Tee-Object -FilePath $Log -Append; $fail++; continue }
    & python $path 2>&1 | Tee-Object -FilePath $Log -Append
    if($LASTEXITCODE -eq 0){ "[PASS] $($c.Name)" | Tee-Object -FilePath $Log -Append; $pass++ } else { "[FAIL] $($c.Name)" | Tee-Object -FilePath $Log -Append; $fail++ }
}
"SUMMARY: $pass PASS / $fail FAIL" | Tee-Object -FilePath $Log -Append
"Evidence: $Log" | Tee-Object -FilePath $Log -Append
if($fail -gt 0){ exit 1 }
