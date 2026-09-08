from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64, csv, hashlib, hmac, io, json, os, secrets, struct, tempfile, time, zipfile
from sqlalchemy import inspect as sa_inspect, select, text
from cryptography.fernet import Fernet
from .db import SessionLocal, engine
from . import cb1_models as m

def utcnow(): return datetime.now(timezone.utc)
def uid(): return secrets.token_hex(16)
def sha(value:str)->str: return hashlib.sha256(value.encode('utf-8')).hexdigest()
def dumps(value)->str: return json.dumps(value,default=str,separators=(',',':'))
def loads(value, default=None):
    try: return json.loads(value or '')
    except Exception: return default

def _fernet():
    raw=(os.getenv('RMR_CREDENTIAL_ENCRYPTION_KEY') or os.getenv('RMR_SECRET_KEY') or os.getenv('RMR_SESSION_SECRET') or 'local-pilot-change-me').encode()
    key=base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)
def encrypt(value:str|None)->str|None: return _fernet().encrypt(value.encode()).decode() if value else None
def decrypt(value:str|None)->str|None: return _fernet().decrypt(value.encode()).decode() if value else None

def role_of(user)->str:
    for attr in ('global_role','role','user_role'):
        v=getattr(user,attr,None)
        if v is not None:
            return str(getattr(v,'value',v)).upper()
    return ''
def user_id(user)->str: return str(getattr(user,'id',''))
def user_email(user)->str: return str(getattr(user,'email',''))
def require_owner(user):
    if role_of(user) not in {'RMR_OWNER','OWNER','SUPER_ADMIN'}:
        from fastapi import HTTPException
        raise HTTPException(403,'RMR Owner authority required.')

def audit(db, user, event_type, tenant_id=None, object_type=None, object_id=None, detail=None, request=None):
    row=m.CB1AuditEvent(tenant_id=str(tenant_id) if tenant_id else None,user_id=user_id(user) if user else None,event_type=event_type,
        object_type=object_type,object_id=str(object_id) if object_id else None,detail_json=dumps(detail or {}),
        ip_address=(request.client.host if request and request.client else None),user_agent=(request.headers.get('user-agent') if request else None))
    db.add(row); return row

def totp_secret(): return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
def totp_code(secret:str, at:int|None=None, step:int=30)->str:
    at=at or int(time.time()); counter=at//step
    key=base64.b32decode(secret + '='*((8-len(secret)%8)%8))
    msg=struct.pack('>Q',counter); digest=hmac.new(key,msg,hashlib.sha1).digest(); off=digest[-1]&15
    num=(struct.unpack('>I',digest[off:off+4])[0]&0x7fffffff)%1000000
    return f'{num:06d}'
def verify_totp(secret:str, code:str)->bool:
    now=int(time.time())
    return any(hmac.compare_digest(totp_code(secret,now+d),str(code).zfill(6)) for d in (-30,0,30))

def create_token():
    raw=secrets.token_urlsafe(32); return raw,sha(raw)

def model_by_columns(required:set[str], preferred=()):
    try:
        from .db import Base
    except Exception:
        from .models import Base
    scored=[]
    for mapper in list(Base.registry.mappers):
        cls=mapper.class_; cols=set(c.name for c in mapper.local_table.columns)
        if required.issubset(cols):
            name=mapper.local_table.name.lower(); score=sum(3 for p in preferred if p in name)
            scored.append((score,cls))
    return max(scored,key=lambda x:x[0])[1] if scored else None

def enum_value(column, names):
    try:
        ec=column.type.enum_class
        if ec:
            for n in names:
                if hasattr(ec,n): return getattr(ec,n)
                for item in ec:
                    if str(getattr(item,'value',item)).upper()==n: return item
    except Exception: pass
    return names[0]

def create_or_get_client_user(db,email,full_name,password):
    from .models import User
    from .security import hash_password
    cols=User.__table__.columns
    existing=db.scalar(select(User).where(User.email==email))
    if existing: user=existing
    else:
        kw={}
        if 'id' in cols and not cols['id'].default and not cols['id'].server_default: kw['id']=uid()
        if 'email' in cols: kw['email']=email
        if 'full_name' in cols: kw['full_name']=full_name
        elif 'name' in cols: kw['name']=full_name
        if 'password_hash' in cols: kw['password_hash']=hash_password(password)
        elif 'hashed_password' in cols: kw['hashed_password']=hash_password(password)
        if 'global_role' in cols: kw['global_role']=enum_value(cols['global_role'],['CLIENT_ADMIN','CLIENT_USER'])
        elif 'role' in cols: kw['role']=enum_value(cols['role'],['CLIENT_ADMIN','CLIENT_USER'])
        for a in ('is_active','active','enabled'):
            if a in cols: kw[a]=True
        user=User(**kw); db.add(user); db.flush()
    return user

def ensure_membership(db,user,tenant_id):
    Membership=model_by_columns({'user_id','tenant_id'},('membership','tenant_user','user_tenant','access'))
    if not Membership:
        # Some schemas place tenant_id directly on User.
        if hasattr(user,'tenant_id'): setattr(user,'tenant_id',tenant_id); return True
        raise RuntimeError('No tenant membership model was found.')
    cols=Membership.__table__.columns
    stmt=select(Membership).where(getattr(Membership,'user_id')==getattr(user,'id')).where(getattr(Membership,'tenant_id')==tenant_id)
    row=db.scalar(stmt)
    if row: return row
    kw={'user_id':getattr(user,'id'),'tenant_id':tenant_id}
    if 'id' in cols and not cols['id'].default and not cols['id'].server_default: kw['id']=uid()
    for c in ('role','tenant_role','membership_role'):
        if c in cols: kw[c]=enum_value(cols[c],['CLIENT_ADMIN','ADMIN']); break
    for c in ('is_active','active','enabled'):
        if c in cols: kw[c]=True
    if 'status' in cols: kw['status']=enum_value(cols['status'],['ACTIVE'])
    row=Membership(**kw); db.add(row); db.flush(); return row

def active_client_admin_count(db,tenant_id)->int:
    return db.query(m.CB1ClientAdminInvite).filter(m.CB1ClientAdminInvite.tenant_id==str(tenant_id),m.CB1ClientAdminInvite.status=='ACTIVATED').count()

def readiness(db,tenant_id):
    profile=db.get(m.CB1CommercialProfile,str(tenant_id))
    admins=active_client_admin_count(db,tenant_id)
    stage2=admins>0 or bool(profile and profile.managed_no_login)
    order=db.query(m.CB1OrderForm).filter(m.CB1OrderForm.tenant_id==str(tenant_id),m.CB1OrderForm.status=='ACTIVE').first()
    ent=db.query(m.CB1Entitlement).filter(m.CB1Entitlement.tenant_id==str(tenant_id),m.CB1Entitlement.enabled.is_(True)).count()
    worker=db.get(m.CB1WorkerState,'drip-worker')
    provider=db.query(m.CB1ProviderConnection).filter(m.CB1ProviderConnection.tenant_id==str(tenant_id),m.CB1ProviderConnection.status=='ACTIVE').count()
    gates=[
      {'id':'client_access','label':'Tenant Provisioning & Client Access','pass':stage2,'detail':f'{admins} activated administrator(s)' if admins else 'No activated client administrator.'},
      {'id':'order_form','label':'Order Form Recorded','pass':bool(order),'detail':order.reference if order else 'No active Order Form.'},
      {'id':'entitlements','label':'Module Entitlements','pass':ent>0,'detail':f'{ent} active entitlement(s).'},
      {'id':'worker','label':'Drip Worker','pass':bool(worker and worker.status=='HEALTHY'),'detail':worker.status if worker else 'Not started.'},
      {'id':'email','label':'Connected Business Email','pass':provider>0,'external':provider==0,'detail':f'{provider} active connection(s).' if provider else 'Provider credentials/configuration required.'},
    ]
    core=all(g['pass'] for g in gates if g['id'] in {'client_access','order_form','entitlements'})
    return {'tenant_id':str(tenant_id),'stage2_complete':stage2,'go_live_complete':core,'readiness_pct':100 if core else round(100*sum(1 for g in gates[:3] if g['pass'])/3),'gates':gates}

def generate_supported_message(client_name,recipient_name,facts,tone,cta):
    facts=[str(x).strip() for x in facts if str(x).strip()]
    greeting=f'Hello {recipient_name},' if recipient_name else 'Hello,'
    lead=f'I am reaching out on behalf of {client_name}.'
    fact_text=' '.join(facts)
    closing=cta.strip() if cta else 'Would a brief conversation be worthwhile?'
    body='\n\n'.join(x for x in (greeting,lead,fact_text,closing) if x)
    return {'subject':f'A quick note from {client_name}','body':body,'supported_facts':facts,'tone':tone or 'professional'}

def content_has_unsupported_facts(body,facts):
    # Strict commercial safe mode: generated body may only include the fixed template and exact supplied facts.
    normalized=' '.join(body.split()).lower()
    return any(' '.join(str(f).split()).lower() not in normalized for f in facts)

def export_tenant(db,tenant_id,requested_by,purpose,output_dir):
    tenant_id=str(tenant_id); output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    job=m.CB1ExportJob(tenant_id=tenant_id,requested_by=str(requested_by),purpose=purpose,status='RUNNING'); db.add(job); db.flush()
    temp=Path(tempfile.mkdtemp(prefix='rmr-export-')); manifest={'tenant_id':tenant_id,'generated_at':utcnow().isoformat(),'files':[],'exclusions':['credentials','tokens','passwords','secrets','RMR source code','other tenants']}
    excluded_words=('password','token','secret','credential','hash','session','mfa','custody_authority')
    try:
        insp=sa_inspect(engine)
        for table in sorted(insp.get_table_names()):
            cols=[c['name'] for c in insp.get_columns(table)]
            if 'tenant_id' not in cols: continue
            if any(w in table.lower() for w in ('provider_connection','stepup','mfa_factor','custody_session')): continue
            safe=[c for c in cols if not any(w in c.lower() for w in excluded_words)]
            if not safe: continue
            q=text('SELECT '+','.join('"'+c.replace('"','')+'"' for c in safe)+' FROM "'+table.replace('"','')+'" WHERE tenant_id = :tenant_id')
            rows=[dict(r._mapping) for r in db.execute(q,{'tenant_id':tenant_id}).all()]
            if not rows: continue
            f=temp/(table+'.csv')
            with f.open('w',newline='',encoding='utf-8-sig') as h:
                writer=csv.DictWriter(h,fieldnames=safe); writer.writeheader()
                for row in rows: writer.writerow({k:(json.dumps(v,default=str) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
            data=f.read_bytes(); manifest['files'].append({'name':f.name,'rows':len(rows),'sha256':hashlib.sha256(data).hexdigest()})
        (temp/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        target=output_dir/f'RMR-Customer-Data-Export-{tenant_id}-{utcnow().strftime("%Y%m%d-%H%M%S")}.zip'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for f in temp.iterdir(): z.write(f,f.name)
        job.status='COMPLETE'; job.file_path=str(target); job.manifest_json=dumps(manifest); job.sha256=hashlib.sha256(target.read_bytes()).hexdigest(); job.completed_at=utcnow(); db.commit()
        return job
    except Exception as exc:
        job.status='FAILED'; job.error=str(exc); db.commit(); raise
    finally:
        import shutil; shutil.rmtree(temp,ignore_errors=True)
