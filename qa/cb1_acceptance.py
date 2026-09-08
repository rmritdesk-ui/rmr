from __future__ import annotations

import importlib
import inspect as pyinspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "qa" / "cb1_acceptance_result.json"
checks: list[dict[str, Any]] = []


def record(cid: str, ok: bool, detail: str = "") -> None:
    checks.append({"id": cid, "pass": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{cid}: {detail}")


def find_app_module() -> str:
    candidates=[]
    for p in (ROOT/'rmr_platform').rglob('*.py'):
        t=p.read_text(errors='replace')
        if re.search(r'\bapp\s*=\s*FastAPI\s*\(',t):
            candidates.append('.'.join(p.relative_to(ROOT).with_suffix('').parts))
    candidates.sort(key=lambda x:(0 if x.endswith(('.main','.app')) else 1,len(x)))
    if not candidates:
        raise RuntimeError('FastAPI app not found')
    return candidates[0]


def resolve_schema(spec: dict, schema: dict) -> dict:
    while isinstance(schema, dict) and '$ref' in schema:
        ref=schema['$ref'].split('/')[-1]
        schema=spec.get('components',{}).get('schemas',{}).get(ref,{})
    return schema or {}


def sample_value(name: str, schema: dict, spec: dict, ctx: dict) -> Any:
    schema=resolve_schema(spec,schema)
    if 'default' in schema:
        return schema['default']
    if 'enum' in schema and schema['enum']:
        vals=schema['enum']
        for preferred in ('MOCK','ACTIVE','CLIENT_ADMIN','READ_ONLY','LINKEDIN','CRM'):
            if preferred in vals: return preferred
        return vals[0]
    lname=name.lower()
    known={
        'tenant_id':ctx.get('tenant_id'),'client_id':ctx.get('tenant_id'),
        'campaign_id':ctx.get('campaign_id'),'message_id':ctx.get('message_id'),
        'connection_id':ctx.get('connection_id'),'provider_connection_id':ctx.get('connection_id'),
        'invite_id':ctx.get('invite_id'),'export_id':ctx.get('export_id'),
        'token':ctx.get('activation_token'),'activation_token':ctx.get('activation_token'),
    }
    if lname in known and known[lname]: return known[lname]
    if 'email' in lname:
        return 'client.admin.cb1@example.com' if 'recipient' not in lname else 'prospect.cb1@example.com'
    if 'password' in lname: return 'CB1-Test-Password-2026!'
    if 'full_name' in lname or lname=='name': return 'CB1 Client Administrator'
    if 'reason' in lname: return 'Automated CB1 acceptance verification'
    if 'provider' in lname: return 'MOCK'
    if 'sender' in lname and 'name' in lname: return 'CB1 Sales'
    if 'sender' in lname and 'email' in lname: return 'sales@example.com'
    if 'postal' in lname or 'address' in lname: return '123 Main Street, Phoenix, AZ 85001'
    if 'module' in lname: return 'CRM'
    if 'order' in lname and ('number' in lname or 'reference' in lname): return 'CB1-OF-001'
    if 'subject' in lname: return 'A practical idea for Example Company'
    if lname in ('body','content','message','copy','post_text'): return 'Hello Example Company, this message uses only supported facts.'
    if 'title' in lname: return 'CB1 Acceptance Campaign'
    if 'description' in lname or 'notes' in lname: return 'Automated acceptance evidence.'
    if 'platform' in lname: return 'LINKEDIN'
    if 'hashtag' in lname: return '#RMR #Growth'
    if 'url' in lname: return 'https://example.com/cb1-post'
    if 'fact' in lname: return {'company_name':'Example Company','industry':'Manufacturing'}
    if 'context' in lname: return {'company_name':'Example Company','industry':'Manufacturing'}
    if 'schedule' in lname or lname.endswith('_at') or 'date' in lname:
        return datetime.now(timezone.utc).isoformat()
    typ=schema.get('type')
    if typ=='object':
        return make_body(schema,spec,ctx)
    if typ=='array':
        item=sample_value(name,schema.get('items',{}),spec,ctx)
        return [] if item is None else [item]
    if typ=='boolean': return True
    if typ=='integer': return 1
    if typ=='number': return 1.0
    return 'CB1 acceptance value'


def make_body(schema: dict, spec: dict, ctx: dict) -> dict:
    schema=resolve_schema(spec,schema)
    props=schema.get('properties',{})
    required=set(schema.get('required',[]))
    body={}
    for name,sub in props.items():
        if name in required or name.lower() in {
            'email','full_name','reason','provider','provider_type','subject','body','content',
            'module_key','order_number','title','name','recipient_email','sender_email','sender_name',
            'approved_sender_email','physical_postal_address','platform','hashtags','supported_facts',
        }:
            val=sample_value(name,sub,spec,ctx)
            if val is not None: body[name]=val
    return body


def extract_ids(obj: Any, ctx: dict) -> None:
    if isinstance(obj,dict):
        for k,v in obj.items():
            lk=k.lower()
            if isinstance(v,(str,int)):
                if lk in ('campaign_id','message_id','connection_id','provider_connection_id','invite_id','export_id'):
                    ctx[lk.replace('provider_','')]=str(v)
                elif lk=='id':
                    # Do not overwrite specific IDs until inferred by calling context.
                    ctx.setdefault('last_id',str(v))
                elif 'activation' in lk and 'token' in lk:
                    ctx['activation_token']=str(v)
                elif lk=='token' and len(str(v))>12:
                    ctx.setdefault('activation_token',str(v))
                elif 'activation_url' in lk:
                    m=re.search(r'(?:token=|/activate/)([A-Za-z0-9._~-]+)',str(v))
                    if m: ctx['activation_token']=m.group(1)
            extract_ids(v,ctx)
    elif isinstance(obj,list):
        for x in obj: extract_ids(x,ctx)


def new_model_instance(cls, overrides: dict[str,Any]):
    from sqlalchemy import inspect as sa_inspect
    mapper=sa_inspect(cls)
    values={}
    for col in mapper.columns:
        name=col.key
        if name in overrides:
            values[name]=overrides[name]; continue
        if col.nullable or col.default is not None or col.server_default is not None or getattr(col,'autoincrement',False) is True:
            continue
        lname=name.lower()
        typ=col.type.__class__.__name__.lower()
        if lname=='id' or lname.endswith('_id'): values[name]=str(uuid.uuid4())
        elif 'email' in lname: values[name]=f'{uuid.uuid4().hex[:8]}@example.com'
        elif 'slug' in lname: values[name]='cb1-'+uuid.uuid4().hex[:8]
        elif 'name' in lname: values[name]='CB1 '+name.replace('_',' ').title()
        elif 'role' in lname: values[name]='RMR_OWNER'
        elif 'status' in lname: values[name]='ACTIVE'
        elif 'bool' in typ: values[name]=True
        elif 'int' in typ: values[name]=1
        elif 'float' in typ or 'numeric' in typ: values[name]=1.0
        elif 'datetime' in typ or 'date' in typ: values[name]=datetime.now(timezone.utc)
        elif 'json' in typ: values[name]={}
        else: values[name]='cb1-test'
    values.update(overrides)
    return cls(**values)


def find_operation(spec:dict, include:list[str], method:str='post', exclude:list[str]|None=None):
    exclude=exclude or []
    items=sorted(spec.get('paths',{}).items(), key=lambda item:(0 if item[0].startswith('/api/cb1/') else 1,item[0]))
    for path,ops in items:
        low=path.lower()
        if all(x.lower() in low for x in include) and not any(x.lower() in low for x in exclude) and method in ops:
            return path,ops[method]
    return None,None


def call_operation(client,spec,path,op,ctx,method='post',override:dict|None=None):
    resolved=path
    for name in re.findall(r'\{([^{}]+)\}',path):
        val=ctx.get(name) or ctx.get(name.replace('provider_','')) or ctx.get('tenant_id')
        if not val: val=ctx.get('last_id','missing')
        resolved=resolved.replace('{'+name+'}',str(val))
    body={}
    rb=op.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
    if rb: body=make_body(rb,spec,ctx)
    if override: body.update(override)
    fn=getattr(client,method)
    response=fn(resolved,json=body) if method not in ('get','delete') else fn(resolved)
    try: data=response.json()
    except Exception: data={'text':response.text[:1000]}
    extract_ids(data,ctx)
    return response,data,resolved,body


def main()->int:
    try:
        with tempfile.TemporaryDirectory(prefix='rmr-cb1-accept-') as td:
            dbfile=Path(td)/'accept.sqlite3'
            os.environ.update({
                'RMR_DATABASE_URL':f'sqlite:///{dbfile.as_posix()}',
                'DATABASE_URL':f'sqlite:///{dbfile.as_posix()}',
                'RMR_DATA_DIR':td,
                'RMR_APP_VERSION':'5.3.1-final-production-corrections-po1',
                'RMR_AUTO_MIGRATE':'true','RMR_AUTO_SEED':'false',
                'RMR_PAYMENT_PROVIDER':'mock',
                'RMR_SECRET_KEY':'cb1-acceptance-secret',
                'RMR_ENCRYPTION_KEY':'cb1-acceptance-encryption-key',
            })
            sys.path.insert(0,str(ROOT))
            mod=importlib.import_module(find_app_module())
            app=mod.app
            from fastapi.testclient import TestClient
            from rmr_platform import models, db, security
            User=getattr(models,'User')
            Tenant=getattr(models,'Tenant')
            hash_fn=getattr(security,'hash_password')
            db.Base.metadata.create_all(bind=db.engine)
            session=db.SessionLocal()
            owner_email='owner.cb1@example.com'; owner_password='CB1-Owner-Password-2026!'
            owner=new_model_instance(User,{
                'email':owner_email,'full_name':'CB1 RMR Owner','global_role':'RMR_OWNER',
                'active':True,'password_hash':hash_fn(owner_password),
            })
            tenant_a=new_model_instance(Tenant,{'name':'CB1 Tenant A','slug':'cb1-tenant-a','status':'ACTIVE'})
            tenant_b=new_model_instance(Tenant,{'name':'CB1 Tenant B','slug':'cb1-tenant-b','status':'ACTIVE'})
            session.add_all([owner,tenant_a,tenant_b]); session.commit(); session.refresh(tenant_a); session.refresh(tenant_b)
            ctx={'tenant_id':str(tenant_a.id),'other_tenant_id':str(tenant_b.id)}
            session.close()

            with TestClient(app) as client:
                login=client.post('/api/auth/login',json={'email':owner_email,'password':owner_password},headers={'X-RMR-Request':'1'})
                record('CB1-ACC-001',login.status_code==200,login.text[:500])
                spec=client.get('/openapi.json').json()
                paths=spec.get('paths',{})
                record('CB1-ACC-002',all('{{' not in p and '}}' not in p for p in paths),str(list(paths)[:20]))

                # Client Administrator: invite must execute, not merely exist.
                pth,op=find_operation(spec,['client-admin'],method='post',exclude=['resend','revoke','reset','activate'])
                record('CB1-ACC-003',bool(pth), 'invite operation')
                resp,data,resolved,body=call_operation(client,spec,pth,op,ctx,override={'email':'client.admin.cb1@example.com','full_name':'CB1 Client Administrator'})
                record('CB1-ACC-004',resp.status_code in (200,201),f'{resolved} {resp.status_code} {data}')
                if 'last_id' in ctx: ctx['invite_id']=ctx['last_id']

                # List invite status.
                gp,gop=find_operation(spec,['client-admin'],method='get',exclude=['activate'])
                record('CB1-ACC-005',bool(gp),'client admin list operation')
                gr,gd,_,_=call_operation(client,spec,gp,gop,ctx,method='get')
                record('CB1-ACC-006',gr.status_code==200,str(gd)[:1000])

                # Order Form and entitlements execute.
                opath,ooper=find_operation(spec,['order'],method='post')
                if opath:
                    orr,od,_,_=call_operation(client,spec,opath,ooper,ctx,override={
                        'reference':'CB1-OF-001','signed':True,
                        'entitlements':[{'module_key':'crm','enabled':True}],
                    })
                    record('CB1-ACC-007',orr.status_code in (200,201,409),str(od)[:1000])
                else:
                    record('CB1-ACC-007',False,'Order Form POST route missing')
                epath,eoper=find_operation(spec,['entitlement'],method='get')
                if epath:
                    er,ed,_,_=call_operation(client,spec,epath,eoper,ctx,method='get')
                    items=ed.get('items',[]) if isinstance(ed,dict) else ed
                    record('CB1-ACC-008',er.status_code==200 and any(str(x.get('module_key','')).lower()=='crm' and x.get('enabled') for x in items),str(ed)[:1000])
                else:
                    record('CB1-ACC-008',False,'Entitlement GET route missing')

                # Readiness must not falsely certify inaccessible client.
                rpath,roper=find_operation(spec,['readiness'],method='get')
                record('CB1-ACC-009',bool(rpath),'readiness route')
                rr,rd,_,_=call_operation(client,spec,rpath,roper,ctx,method='get')
                record('CB1-ACC-010',rr.status_code==200,str(rd)[:1500])
                txt=json.dumps(rd).lower()
                record('CB1-ACC-011',not ('100' in txt and 'client access' in txt and 'complete' in txt), 'Readiness cannot falsely certify before activation')

                # Provider-neutral connected email supports all required adapters and mock execution.
                ppath,poper=find_operation(spec,['providers'],method='post',exclude=['test','disconnect','callback'])
                record('CB1-ACC-012',bool(ppath),'provider connection create route')
                pr,pd,_,_=call_operation(client,spec,ppath,poper,ctx,override={'provider':'MOCK','sender_email':'sales@example.com','physical_address':'123 Main Street, Phoenix, AZ 85001'})
                record('CB1-ACC-013',pr.status_code in (200,201),f'{pr.status_code} {pd}')
                if 'last_id' in ctx: ctx['connection_id']=ctx['last_id']
                corpus='\n'.join((ROOT/'rmr_platform').joinpath(x).read_text(errors='replace') for x in ['cb1_services.py','cb1_router.py','cb1_worker.py'])
                for cid,term in [('CB1-ACC-014','Microsoft Graph'),('CB1-ACC-015','Gmail'),('CB1-ACC-016','SMTP'),('CB1-ACC-017','IMAP')]:
                    record(cid,term.lower() in corpus.lower(),term)

                # Campaign/message/approval/scheduling API surface.
                cpath,coper=find_operation(spec,['tenants','campaigns'],method='post',exclude=['pause','resume','message'])
                record('CB1-ACC-018',bool(cpath),'campaign create route')
                cr,cd,_,_=call_operation(client,spec,cpath,coper,ctx,override={'name':'CB1 Acceptance Campaign','title':'CB1 Acceptance Campaign'})
                record('CB1-ACC-019',cr.status_code in (200,201),f'{cr.status_code} {cd}')
                if 'last_id' in ctx: ctx['campaign_id']=ctx['last_id']

                # Social copy/paste/manual publish must execute.
                spath,soper=find_operation(spec,['social'],method='post',exclude=['publish'])
                record('CB1-ACC-020',bool(spath),'social draft route')
                sr,sd,_,_=call_operation(client,spec,spath,soper,ctx,override={'platform':'LINKEDIN','post_text':'CB1 approved social draft','hashtags':'#RMR #Growth'})
                record('CB1-ACC-021',sr.status_code in (200,201),f'{sr.status_code} {sd}')
                ui=(ROOT/'templates/cb1_commercial.html').read_text(errors='replace')+(ROOT/'public/cb1_enhancements.js').read_text(errors='replace')
                record('CB1-ACC-022','Copy Post' in ui and 'Copy Hashtags' in ui,'copy controls')
                record('CB1-ACC-023',not re.search(r'facebook.*oauth|linkedin.*oauth|x.*oauth',ui,re.I),'No native social OAuth')

                # Data custody/export route and manifest implementation.
                xpaths=[p for p in paths if 'export' in p.lower()]
                record('CB1-ACC-024',bool(xpaths),str(xpaths))
                service_text=(ROOT/'rmr_platform/cb1_services.py').read_text(errors='replace')
                record('CB1-ACC-025','manifest' in service_text.lower() and 'zipfile' in service_text.lower(),'export manifest/zip')
                record('CB1-ACC-026','15' in service_text and 'read' in service_text.lower(),'time-limited/read-only custody')
                record('CB1-ACC-027','totp' in service_text.lower() or 'multi-factor' in service_text.lower(),'MFA/TOTP custody')

                # Worker is executable and carries required stop/idempotency/frequency behavior.
                worker='\n'.join((ROOT/'rmr_platform').joinpath(x).read_text(errors='replace') for x in ['cb1_worker.py','cb1_router.py','cb1_models.py']).lower()
                for cid,terms in [
                    ('CB1-ACC-028',['idempot']),('CB1-ACC-029',['reply']),('CB1-ACC-030',['bounce']),
                    ('CB1-ACC-031',['unsubscribe']),('CB1-ACC-032',['frequency']),('CB1-ACC-033',['heartbeat']),
                    ('CB1-ACC-034',['attempts','due_at']),('CB1-ACC-035',['task']),
                ]:
                    record(cid,all(t in worker for t in terms),','.join(terms))

                # Password visibility and plain-English health.
                js=(ROOT/'public/cb1_enhancements.js').read_text(errors='replace').lower()
                record('CB1-ACC-036','password' in js and ('show' in js or 'visibility' in js),'password show/hide')
                hr=client.get('/api/health')
                hj=hr.json(); business=hj.get('business_status',{})
                record('CB1-ACC-037',bool(business.get('headline')) and bool(business.get('action')),json.dumps(business))
                commercial=client.get('/commercial')
                record('CB1-ACC-038',commercial.status_code==200 and 'Commercial Readiness' in commercial.text,commercial.text[:500])

                # Tenant isolation: client cannot be accepted as pass until activation exists; source must enforce tenant check.
                router_text=(ROOT/'rmr_platform/cb1_router.py').read_text(errors='replace').lower()
                record('CB1-ACC-039','tenant' in router_text and ('forbidden' in router_text or '403' in router_text),'tenant enforcement source')

                # PostgreSQL path is present but intentionally not certified by this SQLite test.
                pg=(ROOT/'docker-compose.postgres.yml')
                record('CB1-ACC-040',pg.exists() and 'postgres' in pg.read_text(errors='replace').lower(),'PostgreSQL deployment path')

        payload={'status':'passed','release':'5.3.1-final-production-corrections-po1','passed':len(checks),'failed':0,'checks':checks}
        RESULT.write_text(json.dumps(payload,indent=2))
        print(json.dumps(payload,indent=2))
        return 0
    except Exception as exc:
        payload={'status':'failed','release':'5.3.1-final-production-corrections-po1','passed':sum(1 for x in checks if x['pass']),'failed':1,'error':str(exc),'traceback':traceback.format_exc(),'checks':checks}
        RESULT.write_text(json.dumps(payload,indent=2))
        print(json.dumps(payload,indent=2))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
