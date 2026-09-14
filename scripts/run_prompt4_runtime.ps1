param(
  [string]$PiqRepo = 'F:\hDocs\prospectiqv15\prospectiq-main',
  [string]$ImagePrefix = 'rmr-final-gate-1789061438594',
  [string]$BrowserImage = 'rmr-piq-local-browser:local'
)
# Disposable fixture harness only. No installed .env, data, published ports or providers.
$ErrorActionPreference = 'Stop'
$RmrRepo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.Replace('\','/')
$PiqRepo = (Resolve-Path $PiqRepo).Path.Replace('\','/')
$proofName = 'rmr-prompt4-' + [guid]::NewGuid().ToString('N').Substring(0,10)
function D { & docker @args; if ($LASTEXITCODE -ne 0) { throw "Docker step failed (exit $LASTEXITCODE)" } }
function BrowserProof([string]$Script) {
  D run --rm --network $proofName --entrypoint python -e MULTITENANT_PROOF=disposable -v "${proofName}:/proof" -v "${RmrRepo}/scripts:/tests:ro" $BrowserImage "/tests/$Script"
}
foreach ($testImage in @("${ImagePrefix}-rmr:test","${ImagePrefix}-backend:test","${ImagePrefix}-worker:test","${ImagePrefix}-frontend:build",$BrowserImage,'postgres:16','redis:7','nginx:1.27')) {
  D image inspect --format '{{.Id}}' $testImage
}
D network create --internal --label rmr.task=prompt4 $proofName
D volume create --label rmr.task=prompt4 $proofName
D run --rm --network none --entrypoint python -v "${proofName}:/proof" -v "${RmrRepo}/scripts:/app/scripts:ro" "${ImagePrefix}-rmr:test" scripts/federation_operations_proof.py init
D run --rm --network none --entrypoint sh -v "${proofName}:/proof" -v "${PiqRepo}/frontend/src:/app/src:ro" -v "${PiqRepo}/frontend/public:/app/public:ro" "${ImagePrefix}-frontend:build" -c 'npm run build -- --outDir /proof/piq-dist --emptyOutDir'
D run -d --name "${proofName}-pg" --label rmr.task=prompt4 --network $proofName --network-alias phase41-postgres --tmpfs /var/lib/postgresql/data -e POSTGRES_USER=phase41_test -e POSTGRES_DB=phase41_test -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16
D run -d --name "${proofName}-redis" --label rmr.task=prompt4 --network $proofName --network-alias rmr-federation-phase4-redis redis:7
D run -d --name "${proofName}-rmr" --label rmr.task=prompt4 --network $proofName --network-alias rmr-federation-phase4-rmr --entrypoint sh -v "${proofName}:/proof" -v "${RmrRepo}/rmr_platform:/app/rmr_platform:ro" -v "${RmrRepo}/scripts:/app/scripts:ro" -v "${RmrRepo}/public:/app/public:ro" "${ImagePrefix}-rmr:test" -c 'cp /proof/tls.crt /usr/local/share/ca-certificates/prompt4.crt && update-ca-certificates && cp /etc/ssl/certs/ca-certificates.crt /usr/local/lib/python3.13/site-packages/certifi/cacert.pem && python scripts/federation_operations_proof.py rmr'
D run -d --name "${proofName}-piq" --label rmr.task=prompt4 --network $proofName --network-alias rmr-federation-phase4-piq --entrypoint node -e PROFILE_BROWSER_FIXTURE=disposable -e NODE_EXTRA_CA_CERTS=/proof/tls.crt --mount "type=volume,source=$proofName,target=/proof,volume-subpath=piq" -v "${PiqRepo}/backend/src:/app/src:ro" -v "${PiqRepo}/backend/tests:/app/tests:ro" -v "${PiqRepo}/db:/db:ro" "${ImagePrefix}-backend:test" tests/initialProfiles.browser.fixture.mjs
D run -d --name "${proofName}-provider" --label rmr.task=prompt4 --network $proofName --network-alias rmr-federation-phase4-provider --entrypoint node -e MULTITENANT_PROOF=disposable -v "${PiqRepo}/backend/tests:/app/tests:ro" "${ImagePrefix}-backend:test" tests/multitenant_mock_discovery.mjs
D run -d --name "${proofName}-worker" --label rmr.task=prompt4 --network $proofName --entrypoint node -e NODE_EXTRA_CA_CERTS=/proof/tls.crt --mount "type=volume,source=$proofName,target=/proof,volume-subpath=piq" -v "${PiqRepo}/worker/src:/app/src:ro" -v "${PiqRepo}/backend/tests:/app/tests:ro" "${ImagePrefix}-worker:test" tests/federation_operations_worker.js
D run -d --name "${proofName}-proxy" --label rmr.task=prompt4 --network $proofName --network-alias rmr.test --network-alias piq.test -v "${proofName}:/proof:ro" nginx:1.27 nginx -c /proof/nginx.conf -g 'daemon off;'
D run -d --name "${proofName}-control" --label rmr.task=prompt4 --network $proofName --network-alias control-fixture --entrypoint python -e MULTITENANT_PROOF=disposable -v "${proofName}:/proof" -v "${RmrRepo}/rmr_platform:/app/rmr_platform:ro" -v "${RmrRepo}/scripts:/app/scripts:ro" "${ImagePrefix}-rmr:test" scripts/multitenant_control_fixture.py
try {
  $deadline = (Get-Date).AddSeconds(120)
  do {
    & docker exec -e MULTITENANT_PROOF=disposable "${proofName}-rmr" python scripts/multitenant_runtime_proof.py ready
    if ($LASTEXITCODE -eq 0) { break }
    if ((Get-Date) -gt $deadline) { throw 'Disposable RMR seed readiness timed out' }
    Start-Sleep -Milliseconds 500
  } while ($true)
  do {
    & docker exec "${proofName}-piq" test -f /proof/piq-ready
    if ($LASTEXITCODE -eq 0) { break }
    if ((Get-Date) -gt $deadline) { throw 'Disposable PIQ readiness timed out' }
    Start-Sleep -Milliseconds 500
  } while ($true)
  D exec -e MULTITENANT_PROOF=disposable "${proofName}-rmr" python scripts/multitenant_runtime_proof.py seed
  BrowserProof test_multitenant_runtime_browser.py
  BrowserProof test_multitenant_revocation_browser.py
  D exec -e MULTITENANT_PROOF=disposable "${proofName}-piq" node tests/identityRecovery.browser.fixture.mjs
  BrowserProof test_identity_recovery_browser.py
  BrowserProof test_multitenant_native_browser.py
  D run -d --name "${proofName}-browser" --label rmr.task=prompt4 --network $proofName --entrypoint python -e MULTITENANT_PROOF=disposable -v "${proofName}:/proof" -v "${RmrRepo}/scripts:/tests:ro" $BrowserImage /tests/test_multitenant_restart_browser.py
  $deadline = (Get-Date).AddSeconds(120)
  do {
    $log = & docker logs "${proofName}-browser" 2>&1
    if (($log -join "`n") -match 'READY FOR DISPOSABLE') { break }
    if ((Get-Date) -gt $deadline) { throw 'Browser restart handshake timed out' }
    Start-Sleep -Milliseconds 500
  } while ($true)
  D restart "${proofName}-rmr" "${proofName}-piq" "${proofName}-worker"
  D exec -e MULTITENANT_PROOF=disposable "${proofName}-rmr" python scripts/multitenant_runtime_proof.py restarted
  # Wait for completion without blocking a tool session for an unbounded interval.
  $deadline = (Get-Date).AddSeconds(120)
  while ((& docker inspect --format '{{.State.Running}}' "${proofName}-browser") -eq 'true') {
    if ((Get-Date) -gt $deadline) { throw 'Restart recovery browser timed out' }
    Start-Sleep -Milliseconds 500
  }
  D logs "${proofName}-browser"
  if ((& docker inspect --format '{{.State.ExitCode}}' "${proofName}-browser") -ne '0') { throw 'Restart recovery browser failed' }
  D exec -e MULTITENANT_PROOF=disposable "${proofName}-rmr" python scripts/multitenant_runtime_proof.py inspect
  Write-Output "PASS: Prompt 4 disposable browser acceptance ($proofName)"
} finally {
  Write-Output "Fixture containers/volume retained for inspection: $proofName. No installed/manual services changed."
}
