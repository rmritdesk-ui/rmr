param([Parameter(Mandatory=$true)][string]$Stack)
# Only an explicitly labelled, isolated final-proof stack may be interrupted.
$ErrorActionPreference='Stop'
if ($Stack -notmatch '^rmr-prompt4-[a-f0-9]{10}$') { throw 'Disposable stack required' }
function D { & docker @args; if ($LASTEXITCODE -ne 0) { throw 'Docker proof failed' } }
foreach ($suffix in @('piq','pg','redis')) {
 $containerInfo = (& docker inspect "$Stack-$suffix" | ConvertFrom-Json)[0]
 if ($containerInfo.Config.Labels.'rmr.task' -ne 'prompt4') { throw 'Fixture label required' }
}
function Probe([string]$Expected) {
 D exec "$Stack-piq" node -e "fetch('http://127.0.0.1:4000/api/integrations/rmr/v1/health').then(async r=>{const b=await r.json();if('$Expected'==='ready'?r.status!==200||b.status!=='ready':r.status!==503||!b.failure_categories.includes('$Expected'))throw Error('Unexpected readiness');console.log('$Expected PASS')}).catch(()=>process.exit(1))"
}
D restart "$Stack-piq"
Start-Sleep -Seconds 5
Probe ready
foreach ($dependency in @(@('redis','redis_unavailable'),@('pg','postgresql_unavailable'))) {
 try { D pause "$Stack-$($dependency[0])"; Probe $dependency[1] }
 finally { D unpause "$Stack-$($dependency[0])" }
 Start-Sleep -Seconds 2
 Probe ready
}
D exec "$Stack-frontend" nginx -t
Write-Output 'PASS: bounded Redis/PostgreSQL failure and recovery; production frontend config valid'
