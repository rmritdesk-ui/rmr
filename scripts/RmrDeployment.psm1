Set-StrictMode -Version Latest

function Get-RmrEnvValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [Parameter(Mandatory=$true)][string]$Name,
        [string]$DefaultValue = ''
    )
    $envPath = Join-Path $InstallPath '.env'
    if (-not (Test-Path $envPath)) { return $DefaultValue }
    $line = Get-Content $envPath | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) { return $DefaultValue }
    return $line.Split('=', 2)[1].Trim()
}

function Invoke-RmrDocker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    $output = ''
    $exitCode = 1
    Push-Location $InstallPath
    try {
        $output = (& docker @Arguments 2>&1 | Out-String).TrimEnd()
        $exitCode = $LASTEXITCODE
    }
    catch {
        $output = $_.Exception.ToString()
        $exitCode = 1
    }
    finally {
        Pop-Location
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
        Arguments = ($Arguments -join ' ')
    }
}


function Invoke-RmrCapturedMigration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [Parameter(Mandatory=$true)][string]$DiagnosticsDirectory,
        [Parameter(Mandatory=$true)][string]$RunId
    )

    New-Item -ItemType Directory -Force -Path $DiagnosticsDirectory | Out-Null
    $safeRunId = ($RunId -replace '[^A-Za-z0-9._-]','-')
    $evidenceDirectory = Join-Path $DiagnosticsDirectory "migration-evidence-$safeRunId"
    New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
    $containerName = ("rmr-cb1-r2-migration-$safeRunId").ToLowerInvariant()
    $stdoutPath = Join-Path $evidenceDirectory 'migration.stdout.txt'
    $stderrPath = Join-Path $evidenceDirectory 'migration.stderr.txt'
    $statePath = Join-Path $evidenceDirectory 'container-state.json'
    $commandPath = Join-Path $evidenceDirectory 'container-command.txt'
    $logsPath = Join-Path $evidenceDirectory 'container-logs.txt'
    $containerPsPath = Join-Path $evidenceDirectory 'container-ps.txt'
    $composePsPath = Join-Path $evidenceDirectory 'compose-ps.txt'
    $manifestPath = Join-Path $evidenceDirectory 'evidence-manifest.json'
    $summaryPath = Join-Path $evidenceDirectory 'migration-evidence-summary.txt'

    $arguments = @(
        'compose','run','--name',$containerName,'--no-deps',
        '--entrypoint','python','app','-m','rmr_platform.cli','migrate'
    )
    $startedUtc = (Get-Date).ToUniversalTime().ToString('o')
    $exitCode = 1
    Push-Location $InstallPath
    try {
        # Windows PowerShell 5.1 can promote ordinary native-process stderr
        # records to terminating PowerShell errors when the caller uses
        # ErrorActionPreference=Stop. Start-Process keeps stdout/stderr as raw
        # diagnostic files and makes the Docker process exit code authoritative.
        $process = Start-Process -FilePath 'docker' -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $exitCode = [int]$process.ExitCode
    }
    catch {
        $_.Exception.ToString() | Set-Content -Path $stderrPath -Encoding utf8
        if (-not (Test-Path $stdoutPath)) { '' | Set-Content -Path $stdoutPath -Encoding utf8 }
        $exitCode = 1
    }
    finally {
        Pop-Location
    }

    # Capture only safe, relevant container evidence. Full inspect output is
    # intentionally avoided because it can include environment secrets.
    $state = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('inspect','--format','{{json .State}}',$containerName)
    $command = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('inspect','--format','Image={{.Config.Image}} Path={{json .Path}} Args={{json .Args}}',$containerName)
    $logs = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('logs','--timestamps',$containerName)
    $containerPs = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('ps','-a','--no-trunc','--filter',"name=^/$containerName$",'--format','table {{.ID}}\t{{.Image}}\t{{.Command}}\t{{.Status}}\t{{.Names}}')
    $composePs = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','ps','-a')
    $state.Output | Set-Content -Path $statePath -Encoding utf8
    $command.Output | Set-Content -Path $commandPath -Encoding utf8
    $logs.Output | Set-Content -Path $logsPath -Encoding utf8
    $containerPs.Output | Set-Content -Path $containerPsPath -Encoding utf8
    $composePs.Output | Set-Content -Path $composePsPath -Encoding utf8

    $completedUtc = (Get-Date).ToUniversalTime().ToString('o')
    $manifest = [ordered]@{
        release = '5.1.0-commercial-cb1-r2'
        purpose = 'Controlled additive migration evidence captured before cleanup'
        started_utc = $startedUtc
        completed_utc = $completedUtc
        install_path = $InstallPath
        command = ('docker ' + ($arguments -join ' '))
        exit_code = $exitCode
        container_name = $containerName
        stdout_file = $stdoutPath
        stderr_file = $stderrPath
        container_state_file = $statePath
        container_command_file = $commandPath
        container_logs_file = $logsPath
        container_ps_file = $containerPsPath
        compose_ps_file = $composePsPath
        captured_before_cleanup = $true
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding utf8

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.AppendLine('RMR SOFTWARE CB1-R2 ADDITIVE MIGRATION EVIDENCE')
    [void]$builder.AppendLine("Generated UTC: $completedUtc")
    [void]$builder.AppendLine("Command: docker $($arguments -join ' ')")
    [void]$builder.AppendLine("Exit code: $exitCode")
    [void]$builder.AppendLine("Container: $containerName")
    [void]$builder.AppendLine('Captured before cleanup: true')
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('MIGRATION STDOUT')
    [void]$builder.AppendLine((Get-Content -Path $stdoutPath -Raw -ErrorAction SilentlyContinue))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('MIGRATION STDERR')
    [void]$builder.AppendLine((Get-Content -Path $stderrPath -Raw -ErrorAction SilentlyContinue))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('SAFE CONTAINER STATE')
    [void]$builder.AppendLine($state.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('SAFE CONTAINER COMMAND')
    [void]$builder.AppendLine($command.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('CONTAINER LOGS')
    [void]$builder.AppendLine($logs.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('CONTAINER PS')
    [void]$builder.AppendLine($containerPs.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('COMPOSE PS -A')
    [void]$builder.AppendLine($composePs.Output)
    $utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($summaryPath, $builder.ToString(), $utf8)

    return [pscustomobject]@{
        ExitCode = $exitCode
        EvidenceDirectory = $evidenceDirectory
        EvidenceFiles = @($stdoutPath,$stderrPath,$statePath,$commandPath,$logsPath,$containerPsPath,$composePsPath,$manifestPath,$summaryPath)
        SummaryPath = $summaryPath
        StdoutPath = $stdoutPath
        StderrPath = $stderrPath
        ContainerName = $containerName
        Command = ('docker ' + ($arguments -join ' '))
    }
}

function Get-RmrContainerState {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][string]$InstallPath)

    $psResult = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','ps','-a','-q','app')
    if ($psResult.ExitCode -ne 0) {
        return [pscustomobject]@{
            Exists = $false
            Id = ''
            Status = 'compose-error'
            Running = $false
            Restarting = $false
            ExitCode = $null
            Error = $psResult.Output
            StartedAt = ''
            FinishedAt = ''
            Health = 'unknown'
            RestartCount = $null
        }
    }

    # Compose can write non-fatal warnings to stderr. Because Invoke-RmrDocker
    # intentionally captures stdout and stderr together for diagnostics, select
    # only a valid hexadecimal container ID instead of trusting the first line.
    $id = ($psResult.Output -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^[0-9a-fA-F]{12,64}$' } | Select-Object -First 1)
    if (-not $id) {
        return [pscustomobject]@{
            Exists = $false
            Id = ''
            Status = 'not-created'
            Running = $false
            Restarting = $false
            ExitCode = $null
            Error = ''
            StartedAt = ''
            FinishedAt = ''
            Health = 'none'
            RestartCount = $null
        }
    }

    $stateResult = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('inspect','--format','{{json .State}}',$id)
    $restartResult = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('inspect','--format','{{.RestartCount}}',$id)
    if ($stateResult.ExitCode -ne 0) {
        return [pscustomobject]@{
            Exists = $true
            Id = $id
            Status = 'inspect-error'
            Running = $false
            Restarting = $false
            ExitCode = $null
            Error = $stateResult.Output
            StartedAt = ''
            FinishedAt = ''
            Health = 'unknown'
            RestartCount = $null
        }
    }

    try {
        $state = $stateResult.Output | ConvertFrom-Json
        $healthStatus = 'none'
        if ($state.PSObject.Properties.Name -contains 'Health') {
            if ($null -ne $state.Health -and $state.Health.PSObject.Properties.Name -contains 'Status') {
                $healthStatus = [string]$state.Health.Status
            }
        }
        $restartCount = $null
        if ($restartResult.ExitCode -eq 0 -and $restartResult.Output -match '^\d+$') {
            $restartCount = [int]$restartResult.Output
        }
        return [pscustomobject]@{
            Exists = $true
            Id = $id
            Status = [string]$state.Status
            Running = [bool]$state.Running
            Restarting = [bool]$state.Restarting
            ExitCode = $state.ExitCode
            Error = [string]$state.Error
            StartedAt = [string]$state.StartedAt
            FinishedAt = [string]$state.FinishedAt
            Health = $healthStatus
            RestartCount = $restartCount
        }
    }
    catch {
        return [pscustomobject]@{
            Exists = $true
            Id = $id
            Status = 'inspect-parse-error'
            Running = $false
            Restarting = $false
            ExitCode = $null
            Error = $_.Exception.Message
            StartedAt = ''
            FinishedAt = ''
            Health = 'unknown'
            RestartCount = $null
        }
    }
}

function Test-RmrHostHealth {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [int]$TimeoutSeconds = 5
    )

    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $handler = $null
    $client = $null
    try {
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.UseProxy = $false
        $client = New-Object -TypeName System.Net.Http.HttpClient -ArgumentList (, $handler)
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
        $client.DefaultRequestHeaders.ConnectionClose = $true
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $payload = $null
        try { $payload = $body | ConvertFrom-Json } catch {}
        $statusValue = ''
        $versionValue = ''
        if ($null -ne $payload) {
            $statusValue = [string]$payload.status
            $versionValue = [string]$payload.version
        }
        $errorValue = ''
        if (-not $response.IsSuccessStatusCode) { $errorValue = "HTTP $([int]$response.StatusCode)" }
        return [pscustomobject]@{
            Ok = ($response.IsSuccessStatusCode -and $null -ne $payload -and $payload.status -eq 'healthy')
            StatusCode = [int]$response.StatusCode
            Status = $statusValue
            Version = $versionValue
            Error = $errorValue
            Body = $body
        }
    }
    catch {
        $message = $_.Exception.Message
        if ($null -ne $_.Exception.InnerException) {
            $message = "$message | $($_.Exception.InnerException.Message)"
        }
        return [pscustomobject]@{
            Ok = $false
            StatusCode = 0
            Status = ''
            Version = ''
            Error = $message
            Body = ''
        }
    }
    finally {
        if ($null -ne $client) { $client.Dispose() }
        if ($null -ne $handler) { $handler.Dispose() }
    }
}

function Test-RmrInternalHealth {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][string]$InstallPath)

    $python = "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)); print(json.dumps(d)); raise SystemExit(0 if d.get('status')=='healthy' else 1)"
    $result = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','exec','-T','app','python','-c',$python)
    if ($result.ExitCode -ne 0) {
        return [pscustomobject]@{ Ok=$false; Status=''; Version=''; Error=$result.Output; Body='' }
    }
    try {
        $lines = $result.Output -split "`r?`n" | Where-Object { $_.Trim() }
        $body = $lines | Select-Object -Last 1
        $payload = $body | ConvertFrom-Json
        return [pscustomobject]@{
            Ok = ($payload.status -eq 'healthy')
            Status = [string]$payload.status
            Version = [string]$payload.version
            Error = ''
            Body = $body
        }
    }
    catch {
        return [pscustomobject]@{ Ok=$false; Status=''; Version=''; Error=$_.Exception.Message; Body=$result.Output }
    }
}

function Get-RmrSafeEnvironmentSummary {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][string]$InstallPath)
    $keys = @(
        'RMR_APP_VERSION','RMR_IMAGE_REPOSITORY','RMR_PUBLIC_PORT','RMR_ENVIRONMENT',
        'RMR_BASE_URL','RMR_INSTALL_PROFILE','RMR_AUTO_MIGRATE','RMR_AUTO_SEED',
        'RMR_PAYMENT_PROVIDER','RMR_CONTAINER_UID','RMR_CONTAINER_GID'
    )
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($key in $keys) {
        $value = Get-RmrEnvValue -InstallPath $InstallPath -Name $key -DefaultValue '(not set)'
        $lines.Add("$key=$value")
    }
    return ($lines -join "`r`n")
}

function Write-RmrDiagnostics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [Parameter(Mandatory=$true)][string]$Reason,
        [string]$DiagnosticsDirectory = '',
        [string]$Label = 'health-check',
        [object[]]$Attempts = @(),
        [string[]]$EvidencePaths = @()
    )

    if (-not $DiagnosticsDirectory) {
        $DiagnosticsDirectory = Join-Path $InstallPath 'data\diagnostics'
    }
    New-Item -ItemType Directory -Force -Path $DiagnosticsDirectory | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $safeLabel = ($Label -replace '[^A-Za-z0-9._-]','-')
    $path = Join-Path $DiagnosticsDirectory "$safeLabel-$stamp.txt"
    $port = Get-RmrEnvValue -InstallPath $InstallPath -Name 'RMR_PUBLIC_PORT' -DefaultValue '8080'
    $uri = "http://127.0.0.1:$port/api/health"
    $state = Get-RmrContainerState -InstallPath $InstallPath
    $hostHealth = Test-RmrHostHealth -Uri $uri -TimeoutSeconds 5
    $internalHealth = Test-RmrInternalHealth -InstallPath $InstallPath
    $dockerVersion = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('version')
    $composeVersion = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','version')
    $composePs = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','ps','-a')
    $logs = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','logs','--no-color','--timestamps','--tail=400','app')
    $appStatus = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','status')

    if ($EvidencePaths.Count -eq 0) {
        $latestEvidence = Get-ChildItem -Path $DiagnosticsDirectory -Directory -Filter 'migration-evidence-*' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if ($latestEvidence) {
            $EvidencePaths = @(Get-ChildItem -Path $latestEvidence.FullName -File -ErrorAction SilentlyContinue |
                Sort-Object Name | ForEach-Object { $_.FullName })
        }
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.AppendLine('RMR PLATFORM DEPLOYMENT DIAGNOSTIC')
    [void]$builder.AppendLine("Generated UTC: $((Get-Date).ToUniversalTime().ToString('o'))")
    [void]$builder.AppendLine("Label: $Label")
    [void]$builder.AppendLine("Reason: $Reason")
    [void]$builder.AppendLine("Install path: $InstallPath")
    [void]$builder.AppendLine("PowerShell: $($PSVersionTable.PSVersion)")
    [void]$builder.AppendLine("OS: $([Environment]::OSVersion.VersionString)")
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('SAFE ENVIRONMENT SUMMARY (secrets omitted)')
    [void]$builder.AppendLine((Get-RmrSafeEnvironmentSummary -InstallPath $InstallPath))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('FINAL CONTAINER STATE')
    [void]$builder.AppendLine(($state | ConvertTo-Json -Depth 8))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('FINAL HOST HEALTH')
    [void]$builder.AppendLine(($hostHealth | ConvertTo-Json -Depth 8))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('FINAL INTERNAL HEALTH')
    [void]$builder.AppendLine(($internalHealth | ConvertTo-Json -Depth 8))
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('READINESS ATTEMPTS')
    if ($Attempts.Count -gt 0) {
        foreach ($attempt in $Attempts) { [void]$builder.AppendLine(($attempt | ConvertTo-Json -Compress -Depth 8)) }
    } else {
        [void]$builder.AppendLine('(none recorded)')
    }
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('DOCKER VERSION')
    [void]$builder.AppendLine($dockerVersion.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('DOCKER COMPOSE VERSION')
    [void]$builder.AppendLine($composeVersion.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('DOCKER COMPOSE PS -A')
    [void]$builder.AppendLine($composePs.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('APPLICATION STATUS COMMAND')
    [void]$builder.AppendLine("Exit code: $($appStatus.ExitCode)")
    [void]$builder.AppendLine($appStatus.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('APPLICATION CONTAINER LOGS (last 400 lines)')
    [void]$builder.AppendLine($logs.Output)
    [void]$builder.AppendLine('')
    [void]$builder.AppendLine('PRESERVED MIGRATION EVIDENCE CAPTURED BEFORE CLEANUP')
    if ($EvidencePaths.Count -gt 0) {
        foreach ($evidencePath in $EvidencePaths) {
            [void]$builder.AppendLine("--- $evidencePath ---")
            if (Test-Path $evidencePath -PathType Leaf) {
                try {
                    $content = Get-Content -Path $evidencePath -Raw -ErrorAction Stop
                    [void]$builder.AppendLine($content)
                }
                catch {
                    [void]$builder.AppendLine("Unable to read evidence file: $($_.Exception.Message)")
                }
            }
            else {
                [void]$builder.AppendLine('(evidence file not found)')
            }
            [void]$builder.AppendLine('')
        }
    }
    else {
        [void]$builder.AppendLine('(no preserved migration evidence found)')
    }
    [void]$builder.AppendLine('END OF DIAGNOSTIC')

    $utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($path, $builder.ToString(), $utf8)
    return $path
}


function ConvertTo-RmrComparableVersion {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$Version)

    $value = if ($null -eq $Version) { '' } else { $Version.Trim() }
    # v5.0 shipped with a metadata inconsistency: the installed .env used
    # 5.0.0-rc1 while the running application health endpoint reported
    # 5.0.0-rc.1. Treat only that known baseline pair as equivalent.
    if ($value -in @('5.0.0-rc1','5.0.0-rc.1')) {
        return '5.0.0-rc1'
    }
    return $value
}

function Test-RmrVersionCompatible {
    [CmdletBinding()]
    param(
        [AllowEmptyString()][string]$ActualVersion,
        [AllowEmptyString()][string]$ExpectedVersion
    )
    if (-not $ExpectedVersion) { return $true }
    return ((ConvertTo-RmrComparableVersion -Version $ActualVersion) -ceq (ConvertTo-RmrComparableVersion -Version $ExpectedVersion))
}

function Wait-RmrPlatformReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$InstallPath,
        [int]$MaxWaitSeconds = 240,
        [int]$PollSeconds = 2,
        [string]$DiagnosticsDirectory = '',
        [string]$DiagnosticLabel = 'health-check',
        [switch]$SkipDiagnostics
    )

    $expectedVersion = Get-RmrEnvValue -InstallPath $InstallPath -Name 'RMR_APP_VERSION' -DefaultValue ''
    $port = Get-RmrEnvValue -InstallPath $InstallPath -Name 'RMR_PUBLIC_PORT' -DefaultValue '8080'
    $uri = "http://127.0.0.1:$port/api/health"
    $started = Get-Date
    $attempts = New-Object System.Collections.Generic.List[object]
    $lastProgressSecond = -10
    $failureReason = 'The readiness deadline expired before the application became healthy.'

    Write-Host "Waiting for RMR Platform $expectedVersion to become ready at $uri ..."

    while (((Get-Date) - $started).TotalSeconds -lt $MaxWaitSeconds) {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        $state = Get-RmrContainerState -InstallPath $InstallPath
        $hostHealth = [pscustomobject]@{ Ok=$false; Status=''; Version=''; Error='Container is not running.'; StatusCode=0; Body='' }
        $internalHealth = [pscustomobject]@{ Ok=$false; Status=''; Version=''; Error='Container is not running.'; Body='' }

        if ($state.Exists -and $state.Running -and -not $state.Restarting) {
            $hostHealth = Test-RmrHostHealth -Uri $uri -TimeoutSeconds 5
            $internalHealth = Test-RmrInternalHealth -InstallPath $InstallPath
        }

        $versionOk = $true
        if ($expectedVersion) {
            $hostVersionOk = Test-RmrVersionCompatible -ActualVersion $hostHealth.Version -ExpectedVersion $expectedVersion
            $internalVersionOk = Test-RmrVersionCompatible -ActualVersion $internalHealth.Version -ExpectedVersion $expectedVersion
            $healthVersionsAgree = ((ConvertTo-RmrComparableVersion -Version $hostHealth.Version) -ceq (ConvertTo-RmrComparableVersion -Version $internalHealth.Version))
            $versionOk = ($hostVersionOk -and $internalVersionOk -and $healthVersionsAgree)
        }
        $dockerHealthOk = ($state.Health -eq 'healthy' -or $state.Health -eq 'none')
        $ready = ($state.Running -and -not $state.Restarting -and $hostHealth.Ok -and $internalHealth.Ok -and $versionOk -and $dockerHealthOk)

        $attempt = [pscustomobject]@{
            elapsed_seconds = $elapsed
            container_status = $state.Status
            container_running = $state.Running
            container_restarting = $state.Restarting
            docker_health = $state.Health
            restart_count = $state.RestartCount
            host_ok = $hostHealth.Ok
            host_status = $hostHealth.Status
            host_version = $hostHealth.Version
            host_error = $hostHealth.Error
            internal_ok = $internalHealth.Ok
            internal_status = $internalHealth.Status
            internal_version = $internalHealth.Version
            internal_error = $internalHealth.Error
            expected_version = $expectedVersion
            comparable_host_version = (ConvertTo-RmrComparableVersion -Version $hostHealth.Version)
            comparable_internal_version = (ConvertTo-RmrComparableVersion -Version $internalHealth.Version)
            comparable_expected_version = (ConvertTo-RmrComparableVersion -Version $expectedVersion)
            version_compatible = $versionOk
        }
        $attempts.Add($attempt)

        if ($ready) {
            Write-Host "RMR Platform is ready. Container, internal API, host API, Docker health, and version checks passed."
            return [pscustomobject]@{
                Success = $true
                ElapsedSeconds = $elapsed
                Health = $hostHealth
                Container = $state
                Attempts = $attempts.ToArray()
                DiagnosticPath = ''
            }
        }

        if ($state.Exists -and $state.Status -in @('exited','dead')) {
            $failureReason = "The application container stopped before becoming ready (status: $($state.Status), exit code: $($state.ExitCode))."
            break
        }
        if ($state.Restarting) {
            $failureReason = 'The application container is repeatedly restarting before becoming ready.'
        }
        if ($state.RestartCount -ne $null -and $state.RestartCount -ge 3) {
            $failureReason = "The application container restarted $($state.RestartCount) times before becoming ready."
            break
        }

        if (($elapsed - $lastProgressSecond) -ge 10) {
            $lastProgressSecond = $elapsed
            $hostSummary = if ($hostHealth.Ok) { 'ready' } elseif ($hostHealth.Error) { $hostHealth.Error } else { 'not ready' }
            Write-Host "  $elapsed/$MaxWaitSeconds sec - container=$($state.Status), docker-health=$($state.Health), host=$hostSummary"
        }
        Start-Sleep -Seconds $PollSeconds
    }

    $diagnosticPath = ''
    if (-not $SkipDiagnostics) {
        $diagnosticPath = Write-RmrDiagnostics -InstallPath $InstallPath -Reason $failureReason -DiagnosticsDirectory $DiagnosticsDirectory -Label $DiagnosticLabel -Attempts $attempts.ToArray()
    }
    return [pscustomobject]@{
        Success = $false
        ElapsedSeconds = [int]((Get-Date) - $started).TotalSeconds
        Health = $null
        Container = (Get-RmrContainerState -InstallPath $InstallPath)
        Attempts = $attempts.ToArray()
        DiagnosticPath = $diagnosticPath
        Reason = $failureReason
    }
}

Export-ModuleMember -Function Get-RmrEnvValue,Invoke-RmrDocker,Invoke-RmrCapturedMigration,Get-RmrContainerState,Test-RmrHostHealth,Test-RmrInternalHealth,Write-RmrDiagnostics,ConvertTo-RmrComparableVersion,Test-RmrVersionCompatible,Wait-RmrPlatformReady
