$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = "rmr-global-v5412c-product-owner"
$Release = "5.4.1.2-interaction-regression-correction-po1"
$Port = 8089
$BaseUrl = "http://127.0.0.1:$Port"
$EnvFile = Join-Path $Root ".env.product-owner-v5412c"
$DataDir = Join-Path $Root "product-owner-data-v5412c"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ConsoleLog = Join-Path $DataDir "qc-results\PRODUCT-OWNER-START-$Stamp.txt"
$ResultFile = Join-Path $DataDir "LAST-PRODUCT-OWNER-START.json"

function Stage([string]$Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
    "[$((Get-Date).ToString('s'))] $Text" | Out-File -FilePath $ConsoleLog -Append -Encoding utf8
}

function New-Secret([int]$Bytes = 48) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer)
}

function Invoke-Docker([string[]]$Arguments, [string]$Label, [switch]$AllowFailure) {
    $stdout = Join-Path $env:TEMP ("rmr-po-out-" + [guid]::NewGuid().ToString("N") + ".txt")
    $stderr = Join-Path $env:TEMP ("rmr-po-err-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
        $process = Start-Process -FilePath "docker.exe" -ArgumentList $Arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $out = if (Test-Path $stdout) { Get-Content $stdout -Raw } else { "" }
        $err = if (Test-Path $stderr) { Get-Content $stderr -Raw } else { "" }
        if ($out) { Write-Host $out.TrimEnd(); $out | Out-File -FilePath $ConsoleLog -Append -Encoding utf8 }
        if ($err) { Write-Host $err.TrimEnd(); $err | Out-File -FilePath $ConsoleLog -Append -Encoding utf8 }
        if ($process.ExitCode -ne 0 -and -not $AllowFailure) { throw "$Label failed with Docker exit code $($process.ExitCode)." }
        return $process.ExitCode
    } finally {
        Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue
    }
}

function ComposeArgs([string[]]$Tail) {
    return @("compose","--env-file",".env.product-owner-v5412c","-f","docker-compose.product-owner.yml","-p",$Project) + $Tail
}

function Write-Result([string]$Status, [string]$Message) {
    $payload = [ordered]@{
        release = $Release
        status = $Status
        message = $Message
        completed_utc = (Get-Date).ToUniversalTime().ToString("o")
        base_url = $BaseUrl
        project = $Project
        console_log = $ConsoleLog
        qc_result = (Join-Path $DataDir "qc-results\PRODUCT-OWNER-QC-LATEST.json")
        persistence_qc_result = (Join-Path $DataDir "qc-results\PRODUCT-OWNER-PERSISTENCE-QC-LATEST.json")
        interaction_regression_result = (Join-Path $DataDir "qc-results\V5412-INTERACTION-REGRESSION-LATEST.json")
        theme_preservation_result = (Join-Path $DataDir "qc-results\V5412-THEME-PRESERVATION-LATEST.json")
    }
    $payload | ConvertTo-Json -Depth 8 | Out-File -FilePath $ResultFile -Encoding utf8
}

function Collect-Failure([string]$Reason) {
    try { & (Join-Path $Root "COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1") -Reason $Reason | Out-Host } catch {}
}

function Verify-Manifest {
    $manifestPath = Join-Path $Root "PACKAGE-MANIFEST.json"
    if (-not (Test-Path $manifestPath)) { throw "PACKAGE-MANIFEST.json is missing." }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $checked = 0
    foreach ($item in $manifest.files) {
        $local = Join-Path $Root ($item.path -replace '/', '\')
        if (-not (Test-Path $local -PathType Leaf)) { throw "Packaged file is missing: $($item.path)" }
        $hash = (Get-FileHash -Algorithm SHA256 -Path $local).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$item.sha256).ToLowerInvariant()) { throw "Packaged file checksum mismatch: $($item.path)" }
        $checked++
    }
    Write-Host "Package integrity verified: $checked files." -ForegroundColor Green
}

function Test-Port([int]$PortNumber) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $PortNumber, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(400)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false } finally { $client.Close() }
}

New-Item -ItemType Directory -Force -Path $DataDir,(Join-Path $DataDir "qc-results"),(Join-Path $DataDir "diagnostics"),(Join-Path $DataDir "backups"),(Join-Path $DataDir "training") | Out-Null
"RMR Global $Release Product Owner startup" | Out-File -FilePath $ConsoleLog -Encoding utf8

Push-Location $Root
try {
    Stage "Verifying the packaged application"
    Verify-Manifest
    $sealPath = Join-Path $Root "control\V531-PRODUCTION-BASELINE-SEAL.json"
    if (-not (Test-Path $sealPath)) { throw "The v5.3.1 sealed-baseline record is missing." }
    $seal = Get-Content $sealPath -Raw | ConvertFrom-Json
    if ($seal.canonical_sha256 -ne "d188a52eab6494cb61bcecd828616d4bc17a1fa30cd5ddd2ff54e28555b5f1bf" -or $seal.status -ne "sealed_unchanged") {
        throw "The v5.3.1 sealed-baseline identity does not match the Product Owner-approved artifact."
    }
    Write-Host "Sealed v5.3.1 baseline identity verified." -ForegroundColor Green

    Stage "Checking Docker Desktop"
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) { throw "Docker Desktop is required and docker.exe was not found." }
    Invoke-Docker @("version") "Docker engine check" | Out-Null
    Invoke-Docker @("compose","version") "Docker Compose check" | Out-Null

    Stage "Preparing the isolated Product Owner environment"
    if (-not (Test-Path $EnvFile)) {
        @(
            "RMR_APP_VERSION=$Release",
            "RMR_IMAGE_TAG=$Release-v5412c",
            "RMR_IMAGE_REPOSITORY=rmr-global",
            "RMR_PUBLIC_PORT=$Port",
            "RMR_ENVIRONMENT=pilot",
            "RMR_BASE_URL=http://localhost:$Port",
            "RMR_INSTALL_PROFILE=demo",
            "RMR_AUTO_MIGRATE=true",
            "RMR_AUTO_SEED=true",
            "RMR_ALLOW_DEMO_CREDENTIALS=true",
            "RMR_PAYMENT_PROVIDER=mock",
            "RMR_PROVIDER_MODE=mock",
            "RMR_AI_MODE=safe-template",
            "RMR_AI_PROVIDER=demonstration",
            "RMR_PIQ_DISCOVERY_PROVIDER=demonstration",
            "RMR_PIQ_RESEARCH_PROVIDER=demonstration",
            "RMR_SYSTEM_EMAIL_PROVIDER=local",
            "RMR_EXTERNAL_SITE_LIVE_TEST=false",
            "RMR_COOKIE_SECURE=false",
            "RMR_LOCAL_RECOVERY_MODE=true",
            "RMR_SECRET_KEY=$(New-Secret 48)",
            "RMR_CREDENTIAL_ENCRYPTION_KEY=$(New-Secret 32)",
            "RMR_INTEGRATION_ENCRYPTION_KEY=$(New-Secret 32)",
            "RMR_CONTAINER_UID=10001",
            "RMR_CONTAINER_GID=10001"
        ) | Out-File -FilePath $EnvFile -Encoding ascii
        Write-Host "Created protected local Product Owner configuration." -ForegroundColor Green
    } else {
        Write-Host "Reusing the existing Product Owner configuration and demo data." -ForegroundColor Yellow
    }

    Invoke-Docker (ComposeArgs @("down","--remove-orphans")) "Product Owner cleanup" -AllowFailure | Out-Null
    if (Test-Port $Port) { throw "Port $Port is already in use by another application. Stop that application and run this launcher again." }

    Stage "Building a fresh Product Owner image and starting the actual RMR Global application"
    Invoke-Docker (ComposeArgs @("build","--no-cache","app")) "RMR Global clean image build" | Out-Null
    Invoke-Docker (ComposeArgs @("up","-d","--no-build","--force-recreate")) "RMR Global start" | Out-Null

    Stage "Waiting for application health and the exact release"
    $healthy = $false
    $health = $null
    for ($attempt = 1; $attempt -le 100; $attempt++) {
        try {
            $health = Invoke-RestMethod "$BaseUrl/api/health" -TimeoutSec 5
            if ($health.status -eq "healthy" -and $health.version -eq $Release -and $health.checks.database.ok -and $health.checks.storage.ok -and $health.checks.migrations.current -eq "005.006.100-four-workspace-themes") {
                $healthy = $true
                break
            }
        } catch {}
        if (($attempt % 10) -eq 0) { Write-Host "Still starting... $($attempt * 3) seconds" }
        Start-Sleep -Seconds 3
    }
    if (-not $healthy) { throw "RMR Global did not pass health, database, storage, migration, and version checks within the readiness window." }
    Write-Host "Application health passed: $($health.version)" -ForegroundColor Green

    Stage "Auditing every launcher-required file inside the built Docker application"
    $dependencyAuditArgs = ComposeArgs @("exec","-T","app","python","qa/v5412c_container_dependency_audit.py","--root","/app","--entrypoint","/usr/local/bin/rmr-entrypoint","--output","/data/qc-results/V5412C-CONTAINER-DEPENDENCY-AUDIT-LATEST.json")
    Invoke-Docker $dependencyAuditArgs "Packaged launcher dependency audit" | Out-Null
    $dependencyAuditPath = Join-Path $DataDir "qc-results\V5412C-CONTAINER-DEPENDENCY-AUDIT-LATEST.json"
    if (-not (Test-Path $dependencyAuditPath)) { throw "Packaged launcher dependency audit result file was not created." }
    $dependencyAudit = Get-Content $dependencyAuditPath -Raw | ConvertFrom-Json
    if ($dependencyAudit.status -ne "passed") { throw "Packaged launcher dependency audit did not pass." }
    Write-Host "Packaged launcher dependency audit passed: $($dependencyAudit.passed) files, $($dependencyAudit.failed) missing." -ForegroundColor Green

    Stage "Running comprehensive functional QC inside the packaged application"
    $qcArgs = ComposeArgs @("exec","-T","app","python","-m","rmr_platform.product_owner_qc","--base-url","http://127.0.0.1:8000","--output","/data/qc-results/PRODUCT-OWNER-QC-LATEST.json")
    Invoke-Docker $qcArgs "Product Owner functional QC" | Out-Null

    $qcPath = Join-Path $DataDir "qc-results\PRODUCT-OWNER-QC-LATEST.json"
    if (-not (Test-Path $qcPath)) { throw "Functional QC result file was not created." }
    $qc = Get-Content $qcPath -Raw | ConvertFrom-Json
    if ($qc.status -ne "passed") { throw "Functional QC did not pass. Review the automatically captured evidence." }
    Write-Host "Functional and tenant-theme isolation QC passed: $($qc.passed) checks, $($qc.failed) failures." -ForegroundColor Green
    $markerId = [string]$qc.persistence_marker_id
    if ([string]::IsNullOrWhiteSpace($markerId)) { throw "Functional QC did not produce the restart-persistence marker." }

    Stage "Verifying restored tile navigation and operational route rendering"
    $interactionArgs = ComposeArgs @("exec","-T","app","python","qa/v5412_interaction_regression_gate.py","--root","/app","--output","/data/qc-results/V5412-INTERACTION-REGRESSION-LATEST.json")
    Invoke-Docker $interactionArgs "Interaction regression gate" | Out-Null
    $interactionPath = Join-Path $DataDir "qc-results\V5412-INTERACTION-REGRESSION-LATEST.json"
    if (-not (Test-Path $interactionPath)) { throw "Interaction regression result file was not created." }
    $interaction = Get-Content $interactionPath -Raw | ConvertFrom-Json
    if ($interaction.status -ne "passed") { throw "Tile navigation and operational route regression gate did not pass." }
    Write-Host "Tile navigation and Forecasting route gate passed: $($interaction.passed) checks, $($interaction.failed) failures." -ForegroundColor Green

    Stage "Proving the four approved workspace themes remain unchanged"
    $themeArgs = ComposeArgs @("exec","-T","app","python","qa/v5412_theme_preservation_gate.py","--root","/app","--output","/data/qc-results/V5412-THEME-PRESERVATION-LATEST.json")
    Invoke-Docker $themeArgs "Four-theme preservation gate" | Out-Null
    $themePath = Join-Path $DataDir "qc-results\V5412-THEME-PRESERVATION-LATEST.json"
    if (-not (Test-Path $themePath)) { throw "Four-theme preservation result file was not created." }
    $theme = Get-Content $themePath -Raw | ConvertFrom-Json
    if ($theme.status -ne "passed") { throw "Four-theme preservation gate did not pass." }
    Write-Host "Four approved workspace themes preserved: $($theme.passed) checks, $($theme.failed) failures." -ForegroundColor Green

    Stage "Restarting the application and proving database persistence"
    Invoke-Docker (ComposeArgs @("restart","app")) "Product Owner application restart" | Out-Null
    $restartHealthy = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $restartHealth = Invoke-RestMethod "$BaseUrl/api/health" -TimeoutSec 5
            if ($restartHealth.status -eq "healthy" -and $restartHealth.version -eq $Release -and $restartHealth.checks.database.ok -and $restartHealth.checks.storage.ok -and $restartHealth.checks.migrations.current -eq "005.006.100-four-workspace-themes") {
                $restartHealthy = $true
                break
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $restartHealthy) { throw "RMR Global did not return to healthy status after the controlled restart." }
    $persistenceArgs = ComposeArgs @("exec","-T","app","python","-m","rmr_platform.product_owner_qc","--base-url","http://127.0.0.1:8000","--verify-persistence",$markerId,"--output","/data/qc-results/PRODUCT-OWNER-PERSISTENCE-QC-LATEST.json")
    Invoke-Docker $persistenceArgs "Product Owner restart-persistence QC" | Out-Null
    $persistencePath = Join-Path $DataDir "qc-results\PRODUCT-OWNER-PERSISTENCE-QC-LATEST.json"
    if (-not (Test-Path $persistencePath)) { throw "Restart-persistence QC result file was not created." }
    $persistence = Get-Content $persistencePath -Raw | ConvertFrom-Json
    if ($persistence.status -ne "passed") { throw "Restart-persistence QC did not pass." }
    Write-Host "CRM and tenant-theme restart persistence passed: $($persistence.passed) checks, $($persistence.failed) failures." -ForegroundColor Green

    Write-Result "passed" "Application built, started, passed functional, four-theme-preservation, tile-navigation, Forecasting-route, and restart-persistence gates."
    Stage "Ready for Product Owner use"
    Write-Host "RMR Global: http://localhost:$Port" -ForegroundColor Green
    Write-Host "Kerry website: http://localhost:$Port/sites/kerry-real-estate" -ForegroundColor Green
    Write-Host ""
    Write-Host "RMR Owner: dave@rmr.local / RMR-Owner-2026!"
    Write-Host "Kerry Client Admin: admin@kerry-real-estate.demo / Client-Admin-2026!"
    Write-Host "Kerry Marketing: marketing@kerry-real-estate.demo / Marketing-2026!"
    Write-Host "CAF Client Admin: admin@cactus-air-filters.demo / Client-Admin-2026!"
    Start-Process "http://localhost:$Port"
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-Host ""; Write-Host "PRODUCT OWNER STARTUP FAILED" -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    $message | Out-File -FilePath $ConsoleLog -Append -Encoding utf8
    Write-Result "failed" $message
    Collect-Failure $message
    exit 1
} finally {
    Pop-Location
}
