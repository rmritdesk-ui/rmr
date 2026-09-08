param(
  [ValidateSet('demo','empty')]
  [string]$Profile = 'empty'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Set-EnvValue([string]$Key, [string]$Value) {
  $lines = if (Test-Path .env) { Get-Content .env } else { @() }
  $found = $false
  $updated = foreach ($line in $lines) {
    if ($line -match "^$([regex]::Escape($Key))=") { $found = $true; "$Key=$Value" } else { $line }
  }
  if (-not $found) { $updated += "$Key=$Value" }
  Set-Content -Path .env -Value $updated -Encoding ascii
}
function New-Secret {
  $bytes = New-Object byte[] 48
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Invoke-Compose([string[]]$Arguments) {
  & docker compose @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Docker Compose command failed: $($Arguments -join ' ')" }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker Desktop/Engine was not found. Install Docker with Compose and retry.'
}
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose was not found.' }
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but the Docker engine is not running. Start Docker Desktop/Engine and retry.' }

New-Item -ItemType Directory -Force -Path data, data/training, data/backups, data/diagnostics | Out-Null
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$content = Get-Content .env -Raw
if ($content -match 'RMR_SECRET_KEY=REPLACE_BY_INSTALLER') { Set-EnvValue 'RMR_SECRET_KEY' (New-Secret) }
if ((Get-Content .env -Raw) -match 'RMR_SETUP_TOKEN=REPLACE_BY_INSTALLER') { Set-EnvValue 'RMR_SETUP_TOKEN' (New-Secret) }
Set-EnvValue 'RMR_CONTAINER_UID' '10001'
Set-EnvValue 'RMR_CONTAINER_GID' '10001'
Set-EnvValue 'RMR_INSTALL_PROFILE' $Profile
Set-EnvValue 'RMR_APP_VERSION' '5.4.1.2-interaction-regression-correction-po1'
Set-EnvValue 'RMR_AUTO_SEED' ($(if ($Profile -eq 'demo') {'true'} else {'false'}))
Set-EnvValue 'RMR_ALLOW_DEMO_CREDENTIALS' ($(if ($Profile -eq 'demo') {'true'} else {'false'}))

Write-Host 'Building the certified RMR Platform application image...'
Invoke-Compose @('build')
Write-Host 'Starting RMR Platform...'
Invoke-Compose @('up','-d')

$portLine = (Get-Content .env | Where-Object { $_ -match '^RMR_PUBLIC_PORT=' } | Select-Object -First 1)
$port = if ($portLine) { $portLine.Split('=',2)[1] } else { '8080' }
& (Join-Path $PSScriptRoot 'HEALTH-CHECK.ps1') -InstallPath $PSScriptRoot -MaxWaitSeconds 240 -PollSeconds 2 -DiagnosticLabel 'install-v51rc3'
if ($LASTEXITCODE -ne 0) { throw 'Installation did not pass the health gate.' }
& docker compose exec -T app python -m rmr_platform.cli status | Set-Content data/INSTALLATION-STATUS.json -Encoding ascii
Write-Host "RMR Platform installation completed successfully. Open http://localhost:$port"
try { Start-Process "http://localhost:$port" } catch {}
if ($Profile -eq 'demo') {
  Write-Host 'Demo RMR Owner: dave@rmr.local / RMR-Owner-2026!'
  Write-Host 'Demo Step2 Admin: hasan@step2.local / Step2-Admin-2026!'
  Write-Host 'Change or disable demo credentials before any real customer use.'
} else {
  $tokenLine = (Get-Content .env | Where-Object { $_ -match '^RMR_SETUP_TOKEN=' } | Select-Object -First 1)
  $token = $tokenLine.Split('=',2)[1]
  @"
RMR Platform initial setup
URL: http://localhost:$port
Setup token: $token
Use this token once in the browser setup screen. The application removes this file after successful setup.
"@ | Set-Content data/INITIAL-SETUP.txt -Encoding ascii
  Write-Host 'Open the URL and complete first-run setup using data/INITIAL-SETUP.txt.'
}
