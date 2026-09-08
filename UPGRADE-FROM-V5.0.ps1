param(
    [Parameter(Mandatory=$true)]
    [string]$ExistingInstall
)
$ErrorActionPreference = 'Stop'
$NewInstall = (Resolve-Path $PSScriptRoot).Path
$ExistingInstall = $ExistingInstall.Trim().Trim('"')
$ExistingInstall = (Resolve-Path $ExistingInstall).Path
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$DiagnosticsDir = Join-Path $NewInstall 'data\diagnostics'
$UpgradeResultPath = Join-Path $NewInstall 'data\LAST-UPGRADE-RESULT.json'
New-Item -ItemType Directory -Force -Path $DiagnosticsDir | Out-Null
Import-Module (Join-Path $NewInstall 'scripts\RmrDeployment.psm1') -Force

function Set-EnvValue {
    param([Parameter(Mandatory=$true)][string]$Key,[Parameter(Mandatory=$true)][string]$Value)
    $path = Join-Path $NewInstall '.env'
    $lines = Get-Content $path
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $updated += "$Key=$Value" }
    Set-Content -Path $path -Value $updated -Encoding ascii
}

function Invoke-ComposeStep {
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [Parameter(Mandatory=$true)][string]$Description,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    Write-Host $Description
    Push-Location $InstallPath
    try {
        & docker @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Description failed with Docker exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

function Write-UpgradeResult {
    param(
        [Parameter(Mandatory=$true)][string]$Status,
        [Parameter(Mandatory=$true)][string]$Message,
        [string]$DiagnosticPath = '',
        [string]$RollbackStatus = '',
        [string]$SafetyBackup = '',
        [int]$ReadinessSeconds = 0,
        [int]$ReadinessAttempts = 0
    )
    $result = [ordered]@{
        release = '5.4.1.2-interaction-regression-correction-po1'
        run_id = $RunId
        completed_utc = (Get-Date).ToUniversalTime().ToString('o')
        status = $Status
        message = $Message
        existing_v5_path = $ExistingInstall
        rc3_path = $NewInstall
        diagnostic_file = $DiagnosticPath
        rollback_status = $RollbackStatus
        safety_backup = $SafetyBackup
        readiness_seconds = $ReadinessSeconds
        readiness_attempts = $ReadinessAttempts
        console_transcript = $transcriptPath
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $UpgradeResultPath) | Out-Null
    $result | ConvertTo-Json -Depth 8 | Set-Content -Path $UpgradeResultPath -Encoding utf8
}

if ($ExistingInstall -eq $NewInstall) {
    throw 'ExistingInstall must point to the v5.0 installation folder, not this v5.1 Commercial Candidate folder.'
}
if (-not (Test-Path (Join-Path $ExistingInstall '.env'))) { throw 'The v5.0 .env file was not found.' }
if (-not (Test-Path (Join-Path $ExistingInstall 'data'))) { throw 'The v5.0 data folder was not found.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker was not found.' }
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose was not found.' }
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed, but the Docker engine is not running.' }

$oldStopped = $false
$safetyBackup = ''
$primaryDiagnostic = ''
$transcriptPath = Join-Path $DiagnosticsDir "upgrade-console-$RunId.txt"
try { Start-Transcript -Path $transcriptPath -Force | Out-Null } catch {}

try {
    Write-Host ''
    Write-Host 'RMR Platform v5.1 Commercial Candidate upgrade preflight' -ForegroundColor Cyan
    Write-Host 'The existing v5.0 installation will remain untouched and will be restarted automatically if RC3 does not become healthy.'

    $oldHealth = Wait-RmrPlatformReady -InstallPath $ExistingInstall -MaxWaitSeconds 90 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "preflight-v50-$RunId"
    if (-not $oldHealth.Success) {
        $primaryDiagnostic = $oldHealth.DiagnosticPath
        throw "The existing v5.0 installation is not healthy enough to upgrade safely. Diagnostic file: $primaryDiagnostic"
    }

    Write-Host 'Creating a v5.0 safety backup...'
    $backupResult = Invoke-RmrDocker -InstallPath $ExistingInstall -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','backup')
    if ($backupResult.ExitCode -ne 0) { throw "The v5.0 safety backup failed. $($backupResult.Output)" }
    $safetyBackup = ($backupResult.Output -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    Write-Host "Safety backup created: $safetyBackup"

    Invoke-ComposeStep -InstallPath $ExistingInstall -Description 'Stopping the v5.0 application cleanly...' -Arguments @('compose','down')
    $oldStopped = $true

    Write-Host 'Copying the v5.0 environment and persistent data into the separate RC3 folder...'
    Copy-Item (Join-Path $ExistingInstall '.env') (Join-Path $NewInstall '.env') -Force
    $targetData = Join-Path $NewInstall 'data'
    New-Item -ItemType Directory -Force -Path $targetData | Out-Null
    Get-ChildItem -Path $targetData -Force | Where-Object { $_.Name -ne 'diagnostics' } | Remove-Item -Recurse -Force
    & robocopy (Join-Path $ExistingInstall 'data') $targetData /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Persistent data copy failed with robocopy exit code $LASTEXITCODE." }
    New-Item -ItemType Directory -Force -Path $DiagnosticsDir | Out-Null

    Set-EnvValue -Key 'RMR_APP_VERSION' -Value '5.4.1.2-interaction-regression-correction-po1'

    Invoke-ComposeStep -InstallPath $NewInstall -Description 'Building RMR Platform v5.1 Commercial Candidate...' -Arguments @('compose','build')
    Invoke-ComposeStep -InstallPath $NewInstall -Description 'Applying additive database migrations...' -Arguments @('compose','run','--rm','--entrypoint','python','app','-m','rmr_platform.cli','migrate')
    Invoke-ComposeStep -InstallPath $NewInstall -Description 'Starting RMR Platform v5.1 Commercial Candidate...' -Arguments @('compose','up','-d')

    $rc3Health = Wait-RmrPlatformReady -InstallPath $NewInstall -MaxWaitSeconds 240 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "upgrade-v51rc3-$RunId"
    if (-not $rc3Health.Success) {
        $primaryDiagnostic = $rc3Health.DiagnosticPath
        throw "RMR Platform v5.1 Commercial Candidate did not become ready. $($rc3Health.Reason) Diagnostic file: $primaryDiagnostic"
    }

    $statusResult = Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','status')
    if ($statusResult.ExitCode -ne 0) {
        $primaryDiagnostic = Write-RmrDiagnostics -InstallPath $NewInstall -Reason 'RC3 passed HTTP readiness but failed the post-upgrade application status command.' -DiagnosticsDirectory $DiagnosticsDir -Label "upgrade-v51rc3-status-$RunId" -Attempts $rc3Health.Attempts
        throw "Post-upgrade application validation failed. Diagnostic file: $primaryDiagnostic"
    }

    Write-UpgradeResult -Status 'success' -Message 'RMR Platform v5.1 Commercial Candidate is healthy and ready. Existing v5.0 data was preserved in the RC3 folder.' -SafetyBackup $safetyBackup -ReadinessSeconds $rc3Health.ElapsedSeconds -ReadinessAttempts $rc3Health.Attempts.Count
    Write-Host ''
    Write-Host 'UPGRADE COMPLETED SUCCESSFULLY' -ForegroundColor Green
    Write-Host 'RMR Platform v5.1 Commercial Candidate is healthy and ready.' -ForegroundColor Green
    Write-Host 'Your original v5.0 folder remains available and was not overwritten.'
    Write-Host "Upgrade result: $UpgradeResultPath"
    $port = Get-RmrEnvValue -InstallPath $NewInstall -Name 'RMR_PUBLIC_PORT' -DefaultValue '8080'
    try { Start-Process "http://localhost:$port" } catch {}
}
catch {
    $failureMessage = $_.Exception.Message
    Write-Host ''
    Write-Host 'RMR Platform v5.1 Commercial Candidate did not pass the upgrade gate.' -ForegroundColor Red
    Write-Host $failureMessage -ForegroundColor Red

    if (-not $primaryDiagnostic) {
        try {
            $primaryDiagnostic = Write-RmrDiagnostics -InstallPath $NewInstall -Reason $failureMessage -DiagnosticsDirectory $DiagnosticsDir -Label "upgrade-v51rc3-$RunId"
        }
        catch {}
    }

    $rollbackStatus = 'not-required'
    if ($oldStopped) {
        Write-Host 'Stopping the unsuccessful RC3 attempt and restarting the untouched v5.0 installation...'
        try {
            Invoke-ComposeStep -InstallPath $NewInstall -Description 'Removing the unsuccessful RC3 container...' -Arguments @('compose','down')
        }
        catch {
            Write-Warning "RC3 cleanup reported: $($_.Exception.Message)"
        }

        try {
            Invoke-ComposeStep -InstallPath $ExistingInstall -Description 'Starting the previous v5.0 installation...' -Arguments @('compose','up','-d')
            $rollbackHealth = Wait-RmrPlatformReady -InstallPath $ExistingInstall -MaxWaitSeconds 180 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "rollback-v50-$RunId"
            if ($rollbackHealth.Success) {
                $rollbackStatus = 'v5.0-restored-and-healthy'
                Write-Host 'The previous v5.0 installation is running and healthy.' -ForegroundColor Green
            }
            else {
                $rollbackStatus = 'v5.0-restart-failed-health-gate'
                if (-not $primaryDiagnostic) { $primaryDiagnostic = $rollbackHealth.DiagnosticPath }
                Write-Host 'The previous v5.0 installation restarted but did not pass its health gate.' -ForegroundColor Red
                Write-Host "Rollback diagnostic: $($rollbackHealth.DiagnosticPath)"
            }
        }
        catch {
            $rollbackStatus = 'v5.0-restart-command-failed'
            Write-Host 'The previous v5.0 installation could not be restarted automatically.' -ForegroundColor Red
            Write-Host $_.Exception.Message -ForegroundColor Red
        }
    }

    Write-UpgradeResult -Status 'failed' -Message $failureMessage -DiagnosticPath $primaryDiagnostic -RollbackStatus $rollbackStatus -SafetyBackup $safetyBackup
    Write-Host ''
    if ($primaryDiagnostic) {
        Write-Host "Diagnostic file to send to RMR/ChatGPT: $primaryDiagnostic" -ForegroundColor Yellow
    }
    Write-Host "Upgrade result: $UpgradeResultPath"
    throw
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
