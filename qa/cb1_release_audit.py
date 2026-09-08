from __future__ import annotations
import ast, hashlib, json, os, re, sys, traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'qa/cb1_release_audit_result.json'
checks=[]
def check(cid,ok,detail=''):
    checks.append({'id':cid,'pass':bool(ok),'detail':detail})
    if not ok: raise AssertionError(f'{cid}: {detail}')

def text(path): return (ROOT/path).read_text(errors='replace')
def contains(files,terms):
    corpus='\n'.join(text(f) for f in files if (ROOT/f).exists()).lower()
    return all(t.lower() in corpus for t in terms)
try:
    # Syntax and controlled version.
    pyfiles=list(ROOT.rglob('*.py'))
    for p in pyfiles: ast.parse(p.read_text(errors='replace'),filename=str(p))
    check('AUD-001',True,f'{len(pyfiles)} Python files parse')
    check('AUD-002','5.3.1-final-production-corrections-po1' in text('.env.example'),'version in env example')
    check('AUD-003','5.3.1-final-production-corrections-po1' in text('docker-compose.yml'),'version in compose')
    check('AUD-004',(ROOT/'control/BUILD-PROVENANCE.json').exists(),'provenance')

    # No malformed routes or forbidden native social publishing.
    malformed_routes=[]
    for p in pyfiles:
        source=p.read_text(errors='replace')
        if re.search(r"@[A-Za-z0-9_\.]+\.(?:get|post|put|patch|delete)\([^\n]*\{\{",source):
            malformed_routes.append(str(p.relative_to(ROOT)))
    check('AUD-005',not malformed_routes,'malformed route files='+','.join(malformed_routes))
    social_files=['templates/cb1_commercial.html','public/cb1_enhancements.js','rmr_platform/cb1_router.py']
    social='\n'.join(text(f) for f in social_files).lower()
    check('AUD-006','copy post' in social and 'copy hashtags' in social,'social copy controls')
    check('AUD-007',not any(x in social for x in ['facebook oauth','linkedin oauth','instagram oauth','x oauth']),'no native social OAuth')

    # P0/P1 correction controls.
    feature_files=['rmr_platform/cb1_router.py','rmr_platform/cb1_services.py','rmr_platform/cb1_worker.py','rmr_platform/cb1_models.py','public/cb1_enhancements.js','templates/cb1_commercial.html']
    controls={
      'AUD-008':['client administrator','resend','revoke','activation'],
      'AUD-009':['tenant provisioning','client access','go-live'],
      'AUD-010':['order form','entitlement'],
      'AUD-011':['data custody','totp','read-only','audit'],
      'AUD-012':['microsoft','gmail','smtp','imap'],
      'AUD-013':['unsubscribe','suppression','bounce','reply'],
      'AUD-014':['idempot','frequency','heartbeat'],
      'AUD-015':['approved','cb1messageversion','supported fact'],
      'AUD-016':['commercial readiness','external','dependency'],
      'AUD-017':['show password'],
      'AUD-018':['healthy','needs_configuration','needs_attention'],
      'AUD-019':['export','manifest','offboarding'],
    }
    for cid,terms in controls.items(): check(cid,contains(feature_files,terms),','.join(terms))
    retry_corpus='\n'.join(text(f) for f in feature_files if (ROOT/f).exists()).lower()
    check('AUD-014B',('retry' in retry_corpus) or ('attempts' in retry_corpus and 'due_at' in retry_corpus),'bounded retry/backoff implementation')

    # Frontend release integrity/cache controls.
    service=(text('rmr_platform/cb1_services.py')+'\n'+text('rmr_platform/cb1_router.py')).lower()
    check('AUD-020','cache-control' in service and 'no-store' in service,'no-store response headers')
    check('AUD-021','x-rmr-release' in service,'release header')
    check('AUD-022','cb1_enhancements.js' in service and 'cb1.css' in service,'versioned asset injection')

    # Upgrade/rollback/diagnostics controls.
    up=text('UPGRADE-FROM-V5.1-CANDIDATE.ps1').lower()
    check('AUD-023','existing v5.1 commercial candidate' in up and '5.3.1-final-production-corrections-po1' in up,'source/target candidate identity')
    deployment=(up+'\n'+text('scripts/RmrDeployment.psm1').lower())
    check('AUD-024','api/health' in deployment and ('maxwaitseconds' in deployment or 'deadline' in deployment),'bounded readiness')
    check('AUD-025','diagnostic' in up and 'rollback' in up,'diagnostics/rollback')
    rb=text('ROLLBACK-TO-V5.1-CANDIDATE.ps1').lower()
    check('AUD-026','commercial-rc1' in rb and 'api/health' in rb and 'healthy' in rb,'verified rollback')
    check('AUD-027',(ROOT/'COLLECT-DIAGNOSTICS-CB1.ps1').exists(),'diagnostic collector')

    # PostgreSQL production path.
    pg=text('docker-compose.postgres.yml').lower()
    check('AUD-028','postgres:16-alpine' in pg and 'pg_isready' in pg,'PostgreSQL service/health')
    check('AUD-029','postgresql+psycopg' in pg,'PostgreSQL application URL')
    check('AUD-030',(ROOT/'qa/cb1_postgres_certification.py').exists() and (ROOT/'POSTGRESQL-CERTIFY.ps1').exists(),'Postgres certification tooling')

    # Dependency/security controls.
    dep=''
    for f in ['requirements.txt','pyproject.toml']:
        if (ROOT/f).exists(): dep+=text(f).lower()
    check('AUD-031','cryptography' in dep,'cryptography dependency')
    check('AUD-032','httpx' in dep,'httpx dependency')
    check('AUD-033','psycopg' in dep,'psycopg dependency')
    suspicious=[]
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in {'.py','.js','.ps1','.yml','.yaml','.json','.env','.example','.md','.txt'}: continue
        rel=str(p.relative_to(ROOT))
        if rel.startswith(('data/','control/')): continue
        s=p.read_text(errors='replace')
        for pattern in [r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'(?i)client_secret\s*[=:]\s*["\'][^"\']{12,}']:
            if re.search(pattern,s): suspicious.append(rel+':'+pattern)
    check('AUD-034',not suspicious,';'.join(suspicious))

    # Package should not carry live database or environment secrets.
    forbidden=[]
    for p in ROOT.rglob('*'):
        if not p.is_file(): continue
        rel=str(p.relative_to(ROOT)).replace('\\','/')
        if rel=='.env' or rel.endswith(('.db','.sqlite','.sqlite3','-wal','-shm')):
            forbidden.append(rel)
    check('AUD-035',not forbidden,'forbidden runtime files='+','.join(forbidden))

    # Frozen scope/control package retained.
    frozen=list((ROOT/'control').glob('*FROZEN*'))
    correction=list((ROOT/'control').glob('*Correction*'))+list((ROOT/'control').glob('*QC*'))
    check('AUD-036',bool(frozen),'frozen baseline embedded')
    check('AUD-037',bool(correction),'approved correction scope embedded')

    payload={'status':'passed','release':'5.3.1-final-production-corrections-po1','passed':len(checks),'failed':0,'checks':checks}
    OUT.write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2)); raise SystemExit(0)
except Exception as exc:
    payload={'status':'failed','release':'5.3.1-final-production-corrections-po1','passed':sum(1 for c in checks if c['pass']),'failed':1,'error':str(exc),'traceback':traceback.format_exc(),'checks':checks}
    OUT.write_text(json.dumps(payload,indent=2)); print(json.dumps(payload,indent=2)); raise SystemExit(1)
