#!/usr/bin/env python3
"""Static packaging/startup audit for the complete v5.4.1.2C PO launcher chain."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1.2-interaction-regression-correction-po1"
EXPECTED_PROJECT = "rmr-global-v5412c-product-owner"
EXPECTED_PORT = 8089
EXPECTED_ENV = ".env.product-owner-v5412c"
EXPECTED_DATA = "product-owner-data-v5412c"
EXPECTED_IMAGE_TAG = f"{RELEASE}-v5412c"

checks=[]
def check(name: str, ok: bool, evidence=None):
    checks.append({"name": name, "passed": bool(ok), "evidence": evidence})

start=(ROOT/'START-PRODUCT-OWNER-TEST.ps1').read_text(encoding='utf-8',errors='replace')
compose=(ROOT/'docker-compose.product-owner.yml').read_text(encoding='utf-8',errors='replace')
dockerfile=(ROOT/'Dockerfile').read_text(encoding='utf-8',errors='replace')
dockerignore=(ROOT/'.dockerignore').read_text(encoding='utf-8',errors='replace')
readme=(ROOT/'README-FIRST.txt').read_text(encoding='utf-8',errors='replace')

# Enumerate every Python program/module executed by the successful launcher path.
module_invocations=sorted(set(re.findall(r'"-m","([^"]+)"', start)))
script_invocations=sorted(set(re.findall(r'"python","([^"]+\.py)"', start)))
expected_modules=['rmr_platform.product_owner_qc']
expected_scripts=[
    'qa/v5412c_container_dependency_audit.py',
    'qa/v5412_interaction_regression_gate.py',
    'qa/v5412_theme_preservation_gate.py',
]
check('Launcher release identity unchanged', f'$Release = "{RELEASE}"' in start, RELEASE)
check('2C Docker project is isolated', EXPECTED_PROJECT in start, EXPECTED_PROJECT)
check('2C port is isolated', f'$Port = {EXPECTED_PORT}' in start and f'${{RMR_PUBLIC_PORT:-{EXPECTED_PORT}}}:8000' in compose, EXPECTED_PORT)
check('2C environment file is isolated', EXPECTED_ENV in start and EXPECTED_ENV in compose, EXPECTED_ENV)
check('2C data directory is isolated', EXPECTED_DATA in start and EXPECTED_DATA in compose, EXPECTED_DATA)
check('Unique 2C image tag prevents stale-image reuse', 'RMR_IMAGE_TAG=$Release-v5412c' in start and EXPECTED_IMAGE_TAG in compose, EXPECTED_IMAGE_TAG)
check('Docker image is rebuilt without cache', '@("build","--no-cache","app")' in start)
check('Container is force-recreated from the new image', '@("up","-d","--no-build","--force-recreate")' in start)
check('Launcher verifies package manifest', 'Verify-Manifest' in start)
check('Launcher verifies sealed v5.3.1 identity', 'V531-PRODUCTION-BASELINE-SEAL.json' in start)
check('Launcher checks exact release and migration health', '$health.version -eq $Release' in start and '005.006.100-four-workspace-themes' in start)
check('Launcher Python module chain is complete', module_invocations == expected_modules, {'actual':module_invocations,'expected':expected_modules})
check('Launcher QA script chain is complete', set(script_invocations) == set(expected_scripts), {'actual':script_invocations,'expected':expected_scripts})
for rel in expected_scripts:
    check(f'Launcher script exists in source: {rel}', (ROOT/rel).is_file(), rel)
check('Functional QC module exists in source', (ROOT/'rmr_platform/product_owner_qc.py').is_file())
check('Application server exists in source', (ROOT/'rmr_platform/server.py').is_file())
check('Container entrypoint exists in source', (ROOT/'scripts/container-entrypoint.sh').is_file())
check('Docker context includes all direct QA Python scripts', 'qa/*' not in [line.strip() for line in dockerignore.splitlines()] and 'qa/*.txt' in dockerignore)
check('Dockerfile copies the complete included QA set', 'COPY qa ./qa' in dockerfile)
for rel in expected_scripts:
    check(f'Docker build executes or validates {rel}', rel in dockerfile, rel)
check('Docker build executes interaction gate', 'python /app/qa/v5412_interaction_regression_gate.py' in dockerfile)
check('Docker build executes theme preservation gate', 'python /app/qa/v5412_theme_preservation_gate.py' in dockerfile)
check('Docker build executes container dependency audit', 'python /app/qa/v5412c_container_dependency_audit.py' in dockerfile)
check('Launcher runs container dependency audit before functional QC', start.index('v5412c_container_dependency_audit.py') < start.index('rmr_platform.product_owner_qc'))
check('Launcher runs interaction gate before theme preservation gate', start.index('v5412_interaction_regression_gate.py') < start.index('v5412_theme_preservation_gate.py'))
check('Launcher performs controlled restart', '@("restart","app")' in start)
check('Launcher verifies persistence after restart', '--verify-persistence' in start)
check('Launcher opens the isolated application URL', 'Start-Process "http://localhost:$Port"' in start)
check('Manual PO instructions cover tiles and Forecasting', 'Your growth tools tile' in readme and 'Forecasting fully loads' in readme)

chain=[
    'verify package manifest',
    'verify sealed v5.3.1 baseline identity',
    'check Docker engine and Compose',
    'create/reuse isolated 2C environment',
    'clean prior 2C project',
    'build unique image with --no-cache',
    'execute dependency, interaction and theme gates during Docker build',
    'start/force-recreate isolated container',
    'verify health, release and migration',
    'audit every required container file',
    'run functional Product Owner QC',
    'run interaction regression gate',
    'run four-theme preservation gate',
    'restart application',
    'verify health after restart',
    'run persistence QC',
    'open browser at isolated port',
]
failed=[c for c in checks if not c['passed']]
payload={
    'release':RELEASE,
    'packaging_correction':'C',
    'status':'passed' if not failed else 'failed',
    'passed':len(checks)-len(failed),
    'failed':len(failed),
    'launcher_chain':chain,
    'python_modules':module_invocations,
    'python_scripts':script_invocations,
    'checks':checks,
}
out=ROOT/'qa/V5412C-COMPLETE-LAUNCHER-CHAIN-AUDIT.json'
out.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
print(json.dumps(payload,indent=2))
raise SystemExit(1 if failed else 0)
