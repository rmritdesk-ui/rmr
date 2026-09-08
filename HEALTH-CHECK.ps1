param(
    [string]$InstallPath = $PSScriptRoot,
    [int]$MaxWaitSeconds = 240,
    [int]$PollSeconds = 2,
    [string]$DiagnosticLabel = 'health-check',
    [string]$DiagnosticsDirectory = ''
)
$ErrorActionPreference = 'Stop'
$InstallPath = (Resolve-Path $InstallPath).Path
Import-Module (Join-Path $PSScriptRoot 'scripts\RmrDeployment.psm1') -Force

$result = Wait-RmrPlatformReady `
    -InstallPath $InstallPath `
    -MaxWaitSeconds $MaxWaitSeconds `
    -PollSeconds $PollSeconds `
    -DiagnosticLabel $DiagnosticLabel `
    -DiagnosticsDirectory $DiagnosticsDirectory

if (-not $result.Success) {
    $message = "RMR Platform did not become ready. $($result.Reason)"
    if ($result.DiagnosticPath) {
        $message += " Diagnostic file: $($result.DiagnosticPath)"
    }
    Write-Host ''
    Write-Host 'RMR Platform is not ready.' -ForegroundColor Red
    Write-Host $message -ForegroundColor Red
    throw $message
}

$health = $result.Health
$health | ConvertTo-Json -Depth 8
$statusResult = Invoke-RmrDocker -InstallPath $InstallPath -Arguments @('compose','exec','-T','app','python','-m','rmr_platform.cli','status')
if ($statusResult.ExitCode -ne 0) {
    $diagnosticPath = Write-RmrDiagnostics -InstallPath $InstallPath -Reason 'The application health endpoint passed, but the application status command failed.' -DiagnosticsDirectory $DiagnosticsDirectory -Label $DiagnosticLabel -Attempts $result.Attempts
    throw "Application status validation failed. Diagnostic file: $diagnosticPath"
}
$statusResult.Output
Write-Host "RMR Platform health validation passed in $($result.ElapsedSeconds) seconds." -ForegroundColor Green
