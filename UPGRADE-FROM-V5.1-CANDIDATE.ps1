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
        [int]$ReadinessAttempts = 0,
        [string]$MigrationEvidenceDirectory = '',
        [string]$MigrationStdout = '',
        [string]$MigrationStderr = '',
        [string]$MigrationContainerEvidence = ''
    )
    $result = [ordered]@{
        release = '5.4.1.2-interaction-regression-correction-po1'
        run_id = $RunId
        completed_utc = (Get-Date).ToUniversalTime().ToString('o')
        status = $Status
        message = $Message
        existing_v5_path = $ExistingInstall
        rc3_path = $NewInstall
        cb1_r2_path = $NewInstall
        diagnostic_file = $DiagnosticPath
        rollback_status = $RollbackStatus
        safety_backup = $SafetyBackup
        readiness_seconds = $ReadinessSeconds
        readiness_attempts = $ReadinessAttempts
        migration_evidence_directory = $MigrationEvidenceDirectory
        migration_stdout = $MigrationStdout
        migration_stderr = $MigrationStderr
        migration_container_evidence = $MigrationContainerEvidence
        console_transcript = $transcriptPath
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $UpgradeResultPath) | Out-Null
    $result | ConvertTo-Json -Depth 8 | Set-Content -Path $UpgradeResultPath -Encoding utf8
}

if ($ExistingInstall -eq $NewInstall) {
    throw 'ExistingInstall must point to the v5.1 Commercial Candidate installation folder, not this v5.1 Commercial Candidate folder.'
}
if (-not (Test-Path (Join-Path $ExistingInstall '.env'))) { throw 'The v5.1 Commercial Candidate .env file was not found.' }
if (-not (Test-Path (Join-Path $ExistingInstall 'data'))) { throw 'The v5.1 Commercial Candidate data folder was not found.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker was not found.' }
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose was not found.' }
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed, but the Docker engine is not running.' }

$oldStopped = $false
$safetyBackup = ''
$primaryDiagnostic = ''
$migrationEvidenceDirectory = ''
$migrationStdout = ''
$migrationStderr = ''
$migrationContainerEvidence = ''
$migrationEvidenceFiles = @()
$transcriptPath = Join-Path $DiagnosticsDir "upgrade-console-$RunId.txt"
try { Start-Transcript -Path $transcriptPath -Force | Out-Null } catch {}

try {
    Write-Host ''
    Write-Host 'RMR Software v5.1 Correction Build 1 Revision 2 upgrade preflight' -ForegroundColor Cyan
    Write-Host 'The existing v5.1 Commercial Candidate installation will remain untouched and will be restarted automatically if Correction Build 1 Revision 2 does not become healthy.'

    $oldHealth = Wait-RmrPlatformReady -InstallPath $ExistingInstall -MaxWaitSeconds 90 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "preflight-v51-candidate-$RunId"
    if (-not $oldHealth.Success) {
        $primaryDiagnostic = $oldHealth.DiagnosticPath
        throw "The existing v5.1 Commercial Candidate installation is not healthy enough to upgrade safely. Diagnostic file: $primaryDiagnostic"
    }

    Write-Host 'Creating a v5.1 Commercial Candidate safety backup...'
    $backupResult = Invoke-RmrDocker -InstallPath $ExistingInstall -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','backup')
    if ($backupResult.ExitCode -ne 0) { throw "The v5.1 Commercial Candidate safety backup failed. $($backupResult.Output)" }
    $safetyBackup = ($backupResult.Output -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    Write-Host "Safety backup created: $safetyBackup"

    Invoke-ComposeStep -InstallPath $ExistingInstall -Description 'Stopping the v5.1 Commercial Candidate application cleanly...' -Arguments @('compose','down')
    $oldStopped = $true

    Write-Host 'Copying the v5.1 Commercial Candidate environment and persistent data into the separate Correction Build 1 Revision 2 folder...'
    Copy-Item (Join-Path $ExistingInstall '.env') (Join-Path $NewInstall '.env') -Force
    $targetData = Join-Path $NewInstall 'data'
    New-Item -ItemType Directory -Force -Path $targetData | Out-Null
    Get-ChildItem -Path $targetData -Force | Where-Object { $_.Name -ne 'diagnostics' } | Remove-Item -Recurse -Force
    & robocopy (Join-Path $ExistingInstall 'data') $targetData /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Persistent data copy failed with robocopy exit code $LASTEXITCODE." }
    New-Item -ItemType Directory -Force -Path $DiagnosticsDir | Out-Null

    Set-EnvValue -Key 'RMR_APP_VERSION' -Value '5.4.1.2-interaction-regression-correction-po1'

    Invoke-ComposeStep -InstallPath $NewInstall -Description 'Building RMR Software v5.1 Correction Build 1 Revision 2...' -Arguments @('compose','build')
    Write-Host 'Applying additive database migrations with pre-cleanup evidence capture...'
    $migrationResult = Invoke-RmrCapturedMigration -InstallPath $NewInstall -DiagnosticsDirectory $DiagnosticsDir -RunId $RunId
    $migrationEvidenceDirectory = $migrationResult.EvidenceDirectory
    $migrationStdout = $migrationResult.StdoutPath
    $migrationStderr = $migrationResult.StderrPath
    $migrationContainerEvidence = $migrationResult.SummaryPath
    $migrationEvidenceFiles = $migrationResult.EvidenceFiles
    if ($migrationResult.ExitCode -ne 0) {
        $primaryDiagnostic = Write-RmrDiagnostics -InstallPath $NewInstall -Reason "Applying additive database migrations failed with Docker exit code $($migrationResult.ExitCode)." -DiagnosticsDirectory $DiagnosticsDir -Label "upgrade-cb1-r2-migration-$RunId" -EvidencePaths $migrationEvidenceFiles
        $migrationCleanup = Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('rm','-f',$migrationResult.ContainerName)
        $migrationCleanup.Output | Set-Content -Path (Join-Path $migrationEvidenceDirectory 'cleanup-after-evidence.txt') -Encoding utf8
        throw "Applying additive database migrations failed with Docker exit code $($migrationResult.ExitCode). Migration evidence: $migrationContainerEvidence. Deployment diagnostic: $primaryDiagnostic"
    }
    $migrationCleanup = Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('rm','-f',$migrationResult.ContainerName)
    $migrationCleanup.Output | Set-Content -Path (Join-Path $migrationEvidenceDirectory 'cleanup-after-evidence.txt') -Encoding utf8
    if ($migrationCleanup.ExitCode -ne 0) {
        throw "The additive migration succeeded, but the one-off migration container could not be cleaned up after evidence capture. Evidence: $migrationContainerEvidence"
    }
    Invoke-ComposeStep -InstallPath $NewInstall -Description 'Starting RMR Software v5.1 Correction Build 1 Revision 2...' -Arguments @('compose','up','-d')

    $rc3Health = Wait-RmrPlatformReady -InstallPath $NewInstall -MaxWaitSeconds 240 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "upgrade-cb1-r2-$RunId"
    if (-not $rc3Health.Success) {
        $primaryDiagnostic = $rc3Health.DiagnosticPath
        throw "RMR Software v5.1 Correction Build 1 Revision 2 did not become ready. $($rc3Health.Reason) Diagnostic file: $primaryDiagnostic"
    }

    $statusResult = Invoke-RmrDocker -InstallPath $NewInstall -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','status')
    if ($statusResult.ExitCode -ne 0) {
        $primaryDiagnostic = Write-RmrDiagnostics -InstallPath $NewInstall -Reason 'Correction Build 1 Revision 2 passed HTTP readiness but failed the post-upgrade application status command.' -DiagnosticsDirectory $DiagnosticsDir -Label "upgrade-cb1-r2-status-$RunId" -Attempts $rc3Health.Attempts -EvidencePaths $migrationEvidenceFiles
        throw "Post-upgrade application validation failed. Diagnostic file: $primaryDiagnostic"
    }

    Write-UpgradeResult -Status 'success' -Message 'RMR Software v5.1 Correction Build 1 Revision 2 is healthy and ready. Existing v5.1 Commercial Candidate data was preserved in the Correction Build 1 Revision 2 folder.' -SafetyBackup $safetyBackup -ReadinessSeconds $rc3Health.ElapsedSeconds -ReadinessAttempts $rc3Health.Attempts.Count -MigrationEvidenceDirectory $migrationEvidenceDirectory -MigrationStdout $migrationStdout -MigrationStderr $migrationStderr -MigrationContainerEvidence $migrationContainerEvidence
    Write-Host ''
    Write-Host 'UPGRADE COMPLETED SUCCESSFULLY' -ForegroundColor Green
    Write-Host 'RMR Software v5.1 Correction Build 1 Revision 2 is healthy and ready.' -ForegroundColor Green
    Write-Host 'Your original v5.1 Commercial Candidate folder remains available and was not overwritten.'
    Write-Host "Upgrade result: $UpgradeResultPath"
    $port = Get-RmrEnvValue -InstallPath $NewInstall -Name 'RMR_PUBLIC_PORT' -DefaultValue '8080'
    try { Start-Process "http://localhost:$port" } catch {}
}
catch {
    $failureMessage = $_.Exception.Message
    Write-Host ''
    Write-Host 'RMR Software v5.1 Correction Build 1 Revision 2 did not pass the upgrade gate.' -ForegroundColor Red
    Write-Host $failureMessage -ForegroundColor Red

    if (-not $primaryDiagnostic) {
        try {
            $primaryDiagnostic = Write-RmrDiagnostics -InstallPath $NewInstall -Reason $failureMessage -DiagnosticsDirectory $DiagnosticsDir -Label "upgrade-cb1-r2-$RunId" -EvidencePaths $migrationEvidenceFiles
        }
        catch {}
    }

    $rollbackStatus = 'not-required'
    if ($oldStopped) {
        Write-Host 'Stopping the unsuccessful Correction Build 1 Revision 2 attempt and restarting the untouched v5.1 Commercial Candidate installation...'
        try {
            Invoke-ComposeStep -InstallPath $NewInstall -Description 'Removing the unsuccessful Correction Build 1 Revision 2 container...' -Arguments @('compose','down')
        }
        catch {
            Write-Warning "Correction Build 1 Revision 2 cleanup reported: $($_.Exception.Message)"
        }

        try {
            Invoke-ComposeStep -InstallPath $ExistingInstall -Description 'Starting the previous v5.1 Commercial Candidate installation...' -Arguments @('compose','up','-d')
            $rollbackHealth = Wait-RmrPlatformReady -InstallPath $ExistingInstall -MaxWaitSeconds 180 -PollSeconds 2 -DiagnosticsDirectory $DiagnosticsDir -DiagnosticLabel "rollback-v51-candidate-$RunId"
            if ($rollbackHealth.Success) {
                $rollbackStatus = 'v5.1 Commercial Candidate-restored-and-healthy'
                Write-Host 'The previous v5.1 Commercial Candidate installation is running and healthy.' -ForegroundColor Green
            }
            else {
                $rollbackStatus = 'v5.1 Commercial Candidate-restart-failed-health-gate'
                if (-not $primaryDiagnostic) { $primaryDiagnostic = $rollbackHealth.DiagnosticPath }
                Write-Host 'The previous v5.1 Commercial Candidate installation restarted but did not pass its health gate.' -ForegroundColor Red
                Write-Host "Rollback diagnostic: $($rollbackHealth.DiagnosticPath)"
            }
        }
        catch {
            $rollbackStatus = 'v5.1 Commercial Candidate-restart-command-failed'
            Write-Host 'The previous v5.1 Commercial Candidate installation could not be restarted automatically.' -ForegroundColor Red
            Write-Host $_.Exception.Message -ForegroundColor Red
        }
    }

    Write-UpgradeResult -Status 'failed' -Message $failureMessage -DiagnosticPath $primaryDiagnostic -RollbackStatus $rollbackStatus -SafetyBackup $safetyBackup -MigrationEvidenceDirectory $migrationEvidenceDirectory -MigrationStdout $migrationStdout -MigrationStderr $migrationStderr -MigrationContainerEvidence $migrationContainerEvidence
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
