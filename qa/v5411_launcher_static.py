#!/usr/bin/env python3
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
RELEASE='5.4.1.1-four-workspace-themes-rendering-correction-po1'
checks=[]
def text(path): return (ROOT/path).read_text(encoding='utf-8',errors='replace')
def check(name,ok,detail=''):
    checks.append({'name':name,'passed':bool(ok),'detail':detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"+(f' | {detail}' if detail else ''))

start=text('START-PRODUCT-OWNER-TEST.ps1'); compose=text('docker-compose.product-owner.yml'); readme=text('README-FIRST.txt'); diag=text('COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1'); stop=text('STOP-PRODUCT-OWNER-TEST.ps1'); reset=text('RESET-PRODUCT-OWNER-DEMO.ps1')
check('Exact release is used by launcher and Compose', RELEASE in start and RELEASE in compose)
check('Product Owner port is isolated at 8087', '$Port = 8087' in start and '${RMR_PUBLIC_PORT:-8087}:8000' in compose and 'http://localhost:8087' in readme)
check('Docker project is isolated', 'rmr-global-v5411-product-owner' in start and 'rmr-global-v5411-product-owner' in diag and 'rmr-global-v5411-product-owner' in readme)
check('Environment file is isolated', '.env.product-owner-v5411' in start and '.env.product-owner-v5411' in compose and '.env.product-owner-v5411' in stop and '.env.product-owner-v5411' in reset)
check('Data directory is isolated', 'product-owner-data-v5411' in start and 'product-owner-data-v5411' in compose and 'product-owner-data-v5411' in diag and 'product-owner-data-v5411' in reset)
check('Launcher verifies package manifest', 'Verify-Manifest' in start and 'PACKAGE-MANIFEST.json' in start)
check('Launcher verifies exact release and current migration', 'health.version -eq $Release' in start and '005.006.100-four-workspace-themes' in start)
check('Launcher runs functional QC', 'rmr_platform.product_owner_qc' in start and 'PRODUCT-OWNER-QC-LATEST.json' in start)
check('Launcher restarts application and verifies persistence', 'restart","app' in start and '--verify-persistence' in start and 'PRODUCT-OWNER-PERSISTENCE-QC-LATEST.json' in start)
check('Launcher preserves diagnostics on failure', 'Collect-Failure' in start and 'COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1' in start)
check('Launcher opens corrected Product Owner URL', 'Start-Process "http://localhost:$Port"' in start)
check('Prior environments are explicitly protected', 'v5.4.1 on port 8086' in readme and 'v5.4.0 on port 8085' in readme and 'v5.3.1 on port 8084' in readme)
check('First test explicitly targets Client 360 theme rendering', 'Confirm Kerry Client 360 materially changes' in readme and 'Open Client Workspace' in readme)
status='passed' if all(x['passed'] for x in checks) else 'failed'
result={'status':status,'release':RELEASE,'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'checks':checks}
(ROOT/'qa/V5411-LAUNCHER-STATIC-RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('status','passed','failed')},indent=2))
raise SystemExit(0 if status=='passed' else 1)
