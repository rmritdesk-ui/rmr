from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import hashlib, hmac, json, os, secrets, urllib.parse
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from .db import SessionLocal, engine
from . import cb1_models as m
from .cb1_migration import apply as apply_migration, MIGRATION_ID
from .cb1_services import (active_client_admin_count,audit,content_has_unsupported_facts,create_or_get_client_user,create_token,
    decrypt,dumps,encrypt,ensure_membership,export_tenant,generate_supported_message,loads,readiness,require_owner,role_of,sha,
    totp_code,totp_secret,uid,user_email,user_id,utcnow,verify_totp,model_by_columns)
from . import cb1_worker

VERSION="5.4.1.2-interaction-regression-correction-po1"
BASE_DIR=Path(__file__).resolve().parent.parent
EXPORT_DIR=Path(os.getenv('RMR_DATA_DIR','/data'))/'exports'
if not str(EXPORT_DIR).startswith('/') and os.name=='nt': EXPORT_DIR=BASE_DIR/'data'/'exports'

def db_dep():
    db=SessionLocal()
    try: yield db
    finally: db.close()

def tenant_allowed(db,user,tenant_id):
    if role_of(user) in {'RMR_OWNER','OWNER','SUPER_ADMIN','STEP2_ADMIN','RMR_ADMIN'}: return True
    Membership=model_by_columns({'user_id','tenant_id'},('membership','tenant_user','user_tenant','access'))
    if Membership:
        row=db.scalar(select(Membership).where(getattr(Membership,'user_id')==getattr(user,'id')).where(getattr(Membership,'tenant_id')==str(tenant_id)))
        return bool(row)
    return str(getattr(user,'tenant_id',''))==str(tenant_id)
def require_tenant(db,user,tenant_id):
    if not tenant_allowed(db,user,tenant_id): raise HTTPException(403,'Tenant access denied.')

def public_user(user):
    return {'id':user_id(user),'email':user_email(user),'name':str(getattr(user,'full_name',getattr(user,'name',''))),'role':role_of(user)}

def json_row(row, exclude=()):
    if row is None: return None
    d={}
    for c in row.__table__.columns:
        if c.name in exclude: continue
        v=getattr(row,c.name)
        d[c.name]=v.isoformat() if isinstance(v,datetime) else v
    return d

def aware(dt):
    if dt is None: return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def stepup_from_request(db,user,request):
    raw=request.cookies.get('rmr_cb1_stepup') or request.headers.get('x-rmr-stepup')
    if not raw: return None
    row=db.scalar(select(m.CB1StepUpSession).where(m.CB1StepUpSession.token_hash==sha(raw),m.CB1StepUpSession.user_id==user_id(user)))
    return row if row and aware(row.expires_at)>utcnow() else None

def custody_authorized(db,user):
    row=db.get(m.CB1CustodyAuthority,1)
    return bool(row and str(row.user_id)==user_id(user))

def require_custody(db,user):
    require_owner(user)
    if not custody_authorized(db,user): raise HTTPException(403,'This RMR Owner has not been assigned Data Custody Authority.')

def active_custody(db,user,tenant_id,request):
    sid=request.cookies.get('rmr_cb1_custody_session') or request.headers.get('x-rmr-custody-session')
    if not sid: return None
    row=db.get(m.CB1CustodySession,sid)
    if not row or row.status!='ACTIVE' or row.user_id!=user_id(user) or row.tenant_id!=str(tenant_id) or aware(row.expires_at)<=utcnow(): return None
    return row

class InviteIn(BaseModel):
    email:str; full_name:str; expires_hours:int=72
class ActivateIn(BaseModel):
    token:str; password:str=Field(min_length=10)
class OrderFormIn(BaseModel):
    reference:str; effective_date:str|None=None; signed:bool=True; notes:str|None=None; entitlements:list[dict[str,Any]]=Field(default_factory=list)
class MFAIn(BaseModel): code:str
class CustodyStartIn(BaseModel): reason:str=Field(min_length=5)
class ProviderIn(BaseModel):
    provider:str; sender_email:str; sender_name:str|None=None; physical_address:str; config:dict[str,Any]=Field(default_factory=dict); credentials:dict[str,Any]=Field(default_factory=dict)
class CampaignIn(BaseModel): name:str; provider_connection_id:str|None=None; frequency_hours:int=24
class GenerateIn(BaseModel):
    tenant_id:str; client_name:str; recipient_name:str=''; recipient_email:str; facts:list[str]=Field(default_factory=list); tone:str='professional'; cta:str=''; campaign_id:str|None=None; crm_record_id:str|None=None; piq_record_id:str|None=None
class MessageIn(BaseModel):
    tenant_id:str; recipient_email:str; subject:str; body:str; supported_facts:list[str]=Field(default_factory=list); campaign_id:str|None=None; crm_record_id:str|None=None; piq_record_id:str|None=None
class ApproveIn(BaseModel): subject:str|None=None; body:str|None=None; verified_facts:bool=True
class ScheduleIn(BaseModel): scheduled_at:datetime
class EventIn(BaseModel): event_type:str; detail:str|None=None; positive:bool=False
class SocialIn(BaseModel): tenant_id:str; platform:str; title:str|None=None; post_text:str; hashtags:str=''
class SocialPublishIn(BaseModel): published_url:str
class OffboardIn(BaseModel): notes:str|None=None

HTML_PATH=BASE_DIR/'templates'/'cb1_commercial.html'
JS_PATH=BASE_DIR/'public'/'cb1_enhancements.js'
CSS_PATH=BASE_DIR/'public'/'cb1.css'
ACTIVATE_PATH=BASE_DIR/'templates'/'cb1_activate.html'

def build_router(auth_dependency):
    router=APIRouter()

    @router.get('/commercial',response_class=HTMLResponse)
    async def commercial(user=Depends(auth_dependency)):
        require_owner(user)
        return HTMLResponse(HTML_PATH.read_text(encoding='utf-8'),headers={'Cache-Control':'no-store','X-RMR-Release':VERSION})

    @router.get('/activate-client-admin',response_class=HTMLResponse)
    async def activate_page(token:str=''):
        html=ACTIVATE_PATH.read_text(encoding='utf-8').replace('__TOKEN__',token.replace('"',''))
        return HTMLResponse(html,headers={'Cache-Control':'no-store'})

    @router.get('/cb1/assets/enhancements.js')
    async def enhancement_js(): return FileResponse(JS_PATH,media_type='application/javascript',headers={'Cache-Control':'no-store','X-RMR-Release':VERSION})
    @router.get('/cb1/assets/cb1.css')
    async def cb1_css(): return FileResponse(CSS_PATH,media_type='text/css',headers={'Cache-Control':'no-store','X-RMR-Release':VERSION})

    @router.get('/api/cb1/release')
    async def release():
        manifest=BASE_DIR/'RELEASE-MANIFEST.json'
        data=loads(manifest.read_text(encoding='utf-8'),{}) if manifest.exists() else {}
        return {'version':VERSION,'migration':MIGRATION_ID,'manifest':data}

    @router.get('/api/cb1/me')
    async def me(user=Depends(auth_dependency)):
        return {'user':public_user(user)}

    @router.get('/api/cb1/tenants')
    async def tenants(user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user)
        from .models import Tenant
        rows=db.scalars(select(Tenant)).all()
        return {'tenants':[{'id':str(getattr(x,'id')),'name':str(getattr(x,'name',getattr(x,'legal_name','Tenant'))),'slug':str(getattr(x,'slug',''))} for x in rows]}

    @router.get('/api/cb1/tenants/{tenant_id}/client-admins')
    async def client_admins(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user)
        rows=db.scalars(select(m.CB1ClientAdminInvite).where(m.CB1ClientAdminInvite.tenant_id==tenant_id).order_by(m.CB1ClientAdminInvite.created_at.desc())).all()
        return {'items':[json_row(x,('token_hash',)) for x in rows]}

    @router.post('/api/cb1/tenants/{tenant_id}/client-admins/invite')
    async def invite_admin(tenant_id:str,payload:InviteIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user)
        raw,hashed=create_token(); now=utcnow()
        prior=db.scalar(select(m.CB1ClientAdminInvite).where(m.CB1ClientAdminInvite.tenant_id==tenant_id,m.CB1ClientAdminInvite.email==payload.email.lower(),m.CB1ClientAdminInvite.status.in_(['PENDING','ACTIVATED'])))
        if prior and prior.status=='ACTIVATED': raise HTTPException(409,'This administrator is already activated.')
        if prior:
            prior.token_hash=hashed; prior.expires_at=now+timedelta(hours=max(1,payload.expires_hours)); prior.last_sent_at=now; prior.status='PENDING'; row=prior
        else:
            row=m.CB1ClientAdminInvite(tenant_id=tenant_id,email=payload.email.lower(),full_name=payload.full_name,status='PENDING',token_hash=hashed,
                expires_at=now+timedelta(hours=max(1,payload.expires_hours)),created_by=user_id(user)); db.add(row)
        audit(db,user,'CLIENT_ADMIN_INVITED',tenant_id,'client_admin_invite',row.id,{'email':row.email},request); db.commit()
        base=str(request.base_url).rstrip('/'); url=f'{base}/activate-client-admin?token={urllib.parse.quote(raw)}'
        return {'invite':json_row(row,('token_hash',)),'activation_url':url,'delivery':'LOCAL_LINK' if not os.getenv('RMR_TRANSACTIONAL_EMAIL_CONFIGURED') else 'TRANSACTIONAL_EMAIL_QUEUED'}

    @router.post('/api/cb1/client-admins/{invite_id}/resend')
    async def resend(invite_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); row=db.get(m.CB1ClientAdminInvite,invite_id)
        if not row: raise HTTPException(404,'Invitation not found.')
        raw,hashed=create_token(); row.token_hash=hashed; row.expires_at=utcnow()+timedelta(hours=72); row.last_sent_at=utcnow(); row.status='PENDING'
        audit(db,user,'CLIENT_ADMIN_INVITE_RESENT',row.tenant_id,'client_admin_invite',row.id,{'email':row.email},request); db.commit()
        return {'activation_url':str(request.base_url).rstrip('/')+'/activate-client-admin?token='+urllib.parse.quote(raw),'invite':json_row(row,('token_hash',))}

    @router.post('/api/cb1/client-admins/{invite_id}/revoke')
    async def revoke(invite_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); row=db.get(m.CB1ClientAdminInvite,invite_id)
        if not row: raise HTTPException(404,'Invitation not found.')
        row.status='REVOKED'; row.revoked_at=utcnow(); audit(db,user,'CLIENT_ADMIN_REVOKED',row.tenant_id,'client_admin_invite',row.id,{},request); db.commit(); return {'ok':True}

    @router.post('/api/cb1/client-admins/{invite_id}/reset')
    async def reset_admin(invite_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); row=db.get(m.CB1ClientAdminInvite,invite_id)
        if not row: raise HTTPException(404,'Administrator record not found.')
        raw,hashed=create_token(); row.token_hash=hashed; row.expires_at=utcnow()+timedelta(hours=24); row.last_sent_at=utcnow(); row.status='RESET_PENDING'
        audit(db,user,'CLIENT_ADMIN_RESET_CREATED',row.tenant_id,'client_admin_invite',row.id,{},request); db.commit()
        return {'reset_url':str(request.base_url).rstrip('/')+'/activate-client-admin?token='+urllib.parse.quote(raw)}

    @router.post('/api/cb1/client-admins/activate')
    async def activate(payload:ActivateIn,request:Request,db=Depends(db_dep)):
        row=db.scalar(select(m.CB1ClientAdminInvite).where(m.CB1ClientAdminInvite.token_hash==sha(payload.token)))
        if not row or row.status not in {'PENDING','RESET_PENDING'} or aware(row.expires_at)<=utcnow(): raise HTTPException(400,'Activation link is invalid or expired.')
        user=create_or_get_client_user(db,row.email,row.full_name,payload.password)
        from .security import hash_password
        for attr in ('password_hash','hashed_password'):
            if hasattr(user,attr): setattr(user,attr,hash_password(payload.password))
        ensure_membership(db,user,row.tenant_id); row.status='ACTIVATED'; row.activated_user_id=str(getattr(user,'id')); row.activated_at=utcnow()
        audit(db,user,'CLIENT_ADMIN_ACTIVATED',row.tenant_id,'client_admin_invite',row.id,{'email':row.email},request); db.commit()
        return {'ok':True,'email':row.email,'tenant_id':row.tenant_id}

    @router.get('/api/cb1/tenants/{tenant_id}/readiness')
    async def tenant_readiness(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); return readiness(db,tenant_id)

    @router.get('/api/cb1/tenants/{tenant_id}/order-forms')
    async def order_forms(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); rows=db.scalars(select(m.CB1OrderForm).where(m.CB1OrderForm.tenant_id==tenant_id).order_by(m.CB1OrderForm.created_at.desc())).all()
        result=[]
        for row in rows:
            ents=db.scalars(select(m.CB1Entitlement).where(m.CB1Entitlement.order_form_id==row.id)).all(); d=json_row(row); d['entitlements']=[json_row(e) for e in ents]; result.append(d)
        return {'items':result}

    @router.post('/api/cb1/tenants/{tenant_id}/order-forms')
    async def create_order_form(tenant_id:str,payload:OrderFormIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); row=m.CB1OrderForm(tenant_id=tenant_id,reference=payload.reference,effective_date=payload.effective_date,status='ACTIVE',signed_at=utcnow() if payload.signed else None,notes=payload.notes,created_by=user_id(user)); db.add(row); db.flush()
        for item in payload.entitlements:
            key=str(item.get('module_key','')).strip().lower()
            if not key: continue
            db.add(m.CB1Entitlement(order_form_id=row.id,tenant_id=tenant_id,module_key=key,enabled=bool(item.get('enabled',True)),quantity=item.get('quantity'),usage_limit=item.get('usage_limit')))
        audit(db,user,'ORDER_FORM_RECORDED',tenant_id,'order_form',row.id,{'reference':row.reference},request); db.commit(); return {'order_form':json_row(row)}

    @router.get('/api/cb1/tenants/{tenant_id}/entitlements')
    async def entitlements(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); rows=db.scalars(select(m.CB1Entitlement).where(m.CB1Entitlement.tenant_id==tenant_id,m.CB1Entitlement.enabled.is_(True))).all(); return {'items':[json_row(x) for x in rows]}

    @router.get('/api/cb1/custody/status')
    async def custody_status(user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); authority=db.get(m.CB1CustodyAuthority,1); factor=db.get(m.CB1MFAFactor,user_id(user))
        return {'claimed':bool(authority),'authorized_user':bool(authority and authority.user_id==user_id(user)),'mfa_enrolled':bool(factor and factor.verified)}

    @router.post('/api/cb1/custody/claim')
    async def custody_claim(request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); authority=db.get(m.CB1CustodyAuthority,1)
        if authority and authority.user_id!=user_id(user): raise HTTPException(409,'Data Custody Authority has already been assigned to another RMR Owner.')
        if not authority: db.add(m.CB1CustodyAuthority(id=1,user_id=user_id(user)))
        audit(db,user,'DATA_CUSTODY_AUTHORITY_CLAIMED',None,'user',user_id(user),{},request); db.commit(); return {'ok':True}

    @router.post('/api/cb1/custody/mfa/enroll')
    async def mfa_enroll(request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); secret=totp_secret(); row=db.get(m.CB1MFAFactor,user_id(user))
        if row: row.secret_encrypted=encrypt(secret); row.verified=False; row.verified_at=None
        else: db.add(m.CB1MFAFactor(user_id=user_id(user),secret_encrypted=encrypt(secret),verified=False))
        audit(db,user,'MFA_ENROLLMENT_STARTED',None,'user',user_id(user),{},request); db.commit()
        return {'secret':secret,'otpauth_uri':f'otpauth://totp/RMR%20Software:{urllib.parse.quote(user_email(user))}?secret={secret}&issuer=RMR%20Software'}

    @router.post('/api/cb1/custody/mfa/verify')
    async def mfa_verify(payload:MFAIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); row=db.get(m.CB1MFAFactor,user_id(user))
        if not row or not verify_totp(decrypt(row.secret_encrypted),payload.code): raise HTTPException(400,'Invalid multi-factor authentication code.')
        row.verified=True; row.verified_at=utcnow(); audit(db,user,'MFA_ENROLLMENT_VERIFIED',None,'user',user_id(user),{},request); db.commit(); return {'ok':True}

    @router.post('/api/cb1/custody/step-up')
    async def step_up(payload:MFAIn,response:Response,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); factor=db.get(m.CB1MFAFactor,user_id(user))
        if not factor or not factor.verified or not verify_totp(decrypt(factor.secret_encrypted),payload.code): raise HTTPException(400,'Invalid multi-factor authentication code.')
        raw,hashed=create_token(); row=m.CB1StepUpSession(token_hash=hashed,user_id=user_id(user),expires_at=utcnow()+timedelta(minutes=10)); db.add(row); audit(db,user,'MFA_STEP_UP_COMPLETED',None,'user',user_id(user),{},request); db.commit()
        response.set_cookie('rmr_cb1_stepup',raw,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=600); return {'ok':True,'expires_at':row.expires_at}

    @router.post('/api/cb1/tenants/{tenant_id}/custody/start')
    async def custody_start(tenant_id:str,payload:CustodyStartIn,response:Response,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user)
        if not stepup_from_request(db,user,request): raise HTTPException(403,'Recent multi-factor authentication step-up required.')
        row=m.CB1CustodySession(tenant_id=tenant_id,user_id=user_id(user),reason=payload.reason,read_only=True,expires_at=utcnow()+timedelta(minutes=15),ip_address=request.client.host if request.client else None,user_agent=request.headers.get('user-agent')); db.add(row); audit(db,user,'CUSTODY_SESSION_STARTED',tenant_id,'custody_session',row.id,{'reason':payload.reason},request); db.commit()
        response.set_cookie('rmr_cb1_custody_session',row.id,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=900); return {'session':json_row(row)}

    @router.post('/api/cb1/tenants/{tenant_id}/custody/elevate')
    async def custody_elevate(tenant_id:str,payload:CustodyStartIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); row=active_custody(db,user,tenant_id,request)
        if not row or not stepup_from_request(db,user,request): raise HTTPException(403,'Active custody session and recent MFA step-up required.')
        row.elevated_until=utcnow()+timedelta(minutes=5); audit(db,user,'CUSTODY_SESSION_ELEVATED',tenant_id,'custody_session',row.id,{'reason':payload.reason},request); db.commit(); return {'session':json_row(row)}

    @router.post('/api/cb1/tenants/{tenant_id}/custody/end')
    async def custody_end(tenant_id:str,response:Response,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); row=active_custody(db,user,tenant_id,request)
        if row: row.status='ENDED'; row.ended_at=utcnow(); audit(db,user,'CUSTODY_SESSION_ENDED',tenant_id,'custody_session',row.id,{},request); db.commit()
        response.delete_cookie('rmr_cb1_custody_session'); return {'ok':True}

    @router.get('/api/cb1/tenants/{tenant_id}/custody/active')
    async def custody_active(tenant_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); row=active_custody(db,user,tenant_id,request); return {'active':bool(row),'session':json_row(row) if row else None}

    @router.post('/api/cb1/tenants/{tenant_id}/exports')
    async def create_export(tenant_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); session=active_custody(db,user,tenant_id,request)
        if not session: raise HTTPException(403,'Active RMR Owner Data Custody session required.')
        job=export_tenant(db,tenant_id,user_id(user),'CUSTOMER_DATA_RETURN',EXPORT_DIR); audit(db,user,'CUSTOMER_DATA_EXPORTED',tenant_id,'export_job',job.id,{'sha256':job.sha256},request); db.commit(); return {'job':json_row(job)}

    @router.get('/api/cb1/exports/{job_id}/download')
    async def download_export(job_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); job=db.get(m.CB1ExportJob,job_id)
        if not job or job.status!='COMPLETE' or not active_custody(db,user,job.tenant_id,request): raise HTTPException(404,'Export unavailable or custody session inactive.')
        return FileResponse(job.file_path,filename=Path(job.file_path).name,media_type='application/zip')

    @router.post('/api/cb1/tenants/{tenant_id}/offboarding')
    async def offboard(tenant_id:str,payload:OffboardIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_custody(db,user); session=active_custody(db,user,tenant_id,request)
        if not session: raise HTTPException(403,'Active custody session required.')
        row=m.CB1OffboardingCase(tenant_id=tenant_id,status='OPEN',export_deadline=utcnow()+timedelta(days=30),notes=payload.notes,created_by=user_id(user)); db.add(row); audit(db,user,'OFFBOARDING_OPENED',tenant_id,'offboarding',row.id,{},request); db.commit(); return {'case':json_row(row)}

    @router.get('/api/cb1/tenants/{tenant_id}/providers')
    async def providers(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); rows=db.scalars(select(m.CB1ProviderConnection).where(m.CB1ProviderConnection.tenant_id==tenant_id)).all(); return {'items':[json_row(x,('token_encrypted','refresh_token_encrypted','credential_encrypted')) for x in rows]}

    @router.post('/api/cb1/tenants/{tenant_id}/providers')
    async def provider_create(tenant_id:str,payload:ProviderIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); p=payload.provider.upper(); status='ACTIVE' if p=='MOCK' else 'CONFIGURATION_REQUIRED'
        if p in {'MICROSOFT','OUTLOOK','MICROSOFT365'} and os.getenv('RMR_MICROSOFT_CLIENT_ID'): status='AUTHORIZATION_REQUIRED'
        if p in {'GOOGLE','GMAIL','GOOGLE_WORKSPACE'} and os.getenv('RMR_GOOGLE_CLIENT_ID'): status='AUTHORIZATION_REQUIRED'
        if p in {'SMTP','IMAP','SMTP_IMAP'} and payload.credentials: status='SAVED_UNTESTED'
        row=m.CB1ProviderConnection(tenant_id=tenant_id,provider=p,sender_email=payload.sender_email,sender_name=payload.sender_name,physical_address=payload.physical_address,status=status,config_json=dumps(payload.config),credential_encrypted=encrypt(dumps(payload.credentials)),created_by=user_id(user)); db.add(row); audit(db,user,'EMAIL_PROVIDER_CREATED',tenant_id,'provider_connection',row.id,{'provider':p,'sender':payload.sender_email},request); db.commit(); return {'connection':json_row(row,('token_encrypted','refresh_token_encrypted','credential_encrypted'))}

    @router.post('/api/cb1/provider-connections/{connection_id}/test')
    async def provider_test(connection_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1ProviderConnection,connection_id)
        if not row: raise HTTPException(404,'Connection not found.')
        require_tenant(db,user,row.tenant_id); p=row.provider.upper(); detail=''
        try:
            if p=='MOCK': row.status='ACTIVE'; detail='Mock provider operational.'
            elif p in {'SMTP','IMAP','SMTP_IMAP'}:
                import smtplib
                cfg=loads(row.config_json,{}) or {}; cred=loads(decrypt(row.credential_encrypted),{}) or {}
                host=cfg.get('smtp_host') or cred.get('smtp_host'); port=int(cfg.get('smtp_port') or cred.get('smtp_port') or 587)
                if not host: raise RuntimeError('SMTP host missing.')
                with smtplib.SMTP(host,port,timeout=12) as s:
                    if cfg.get('starttls',True): s.starttls()
                    if cred.get('username'): s.login(cred.get('username'),cred.get('password'))
                row.status='ACTIVE'; detail='SMTP authentication succeeded.'
            else:
                token=decrypt(row.token_encrypted)
                if not token: row.status='AUTHORIZATION_REQUIRED'; detail='OAuth provider credentials/authorization required.'
                else: row.status='ACTIVE'; detail='Stored OAuth authorization is present; live provider call remains provider-dependent.'
        except Exception as exc:
            row.status='FAILED'; detail=str(exc)
        row.updated_at=utcnow(); audit(db,user,'EMAIL_PROVIDER_TESTED',row.tenant_id,'provider_connection',row.id,{'status':row.status,'detail':detail},request); db.commit(); return {'status':row.status,'detail':detail}

    @router.delete('/api/cb1/provider-connections/{connection_id}')
    async def provider_disconnect(connection_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1ProviderConnection,connection_id)
        if not row: raise HTTPException(404,'Connection not found.')
        require_tenant(db,user,row.tenant_id); row.status='DISCONNECTED'; row.token_encrypted=None; row.refresh_token_encrypted=None; row.credential_encrypted=None; audit(db,user,'EMAIL_PROVIDER_DISCONNECTED',row.tenant_id,'provider_connection',row.id,{},request); db.commit(); return {'ok':True}

    @router.get('/api/cb1/provider-connections/{connection_id}/authorize')
    async def provider_authorize(connection_id:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1ProviderConnection,connection_id)
        if not row: raise HTTPException(404,'Connection not found.')
        require_tenant(db,user,row.tenant_id); state=secrets.token_urlsafe(24); cfg=loads(row.config_json,{}) or {}; cfg['oauth_state']=state; row.config_json=dumps(cfg); db.commit(); base=str(request.base_url).rstrip('/')
        if row.provider.upper() in {'MICROSOFT','OUTLOOK','MICROSOFT365'}:
            cid=os.getenv('RMR_MICROSOFT_CLIENT_ID'); tenant=os.getenv('RMR_MICROSOFT_TENANT','common')
            if not cid: raise HTTPException(409,'Microsoft application credentials are an external activation dependency.')
            redirect=base+'/api/cb1/oauth/microsoft/callback'; params={'client_id':cid,'response_type':'code','redirect_uri':redirect,'response_mode':'query','scope':'offline_access User.Read Mail.Send Mail.Read','state':state}
            return {'authorization_url':f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?'+urllib.parse.urlencode(params)}
        if row.provider.upper() in {'GOOGLE','GMAIL','GOOGLE_WORKSPACE'}:
            cid=os.getenv('RMR_GOOGLE_CLIENT_ID')
            if not cid: raise HTTPException(409,'Google application credentials are an external activation dependency.')
            redirect=base+'/api/cb1/oauth/google/callback'; params={'client_id':cid,'response_type':'code','redirect_uri':redirect,'scope':'openid email https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly','access_type':'offline','prompt':'consent','state':state}
            return {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params)}
        raise HTTPException(400,'This provider does not use OAuth authorization.')

    async def oauth_callback(provider,code,state,request,db):
        row=db.scalar(select(m.CB1ProviderConnection).where(m.CB1ProviderConnection.provider.in_([provider,provider.upper(),'MICROSOFT365' if provider=='MICROSOFT' else 'GOOGLE_WORKSPACE'])))
        # Find exact state among provider rows.
        rows=db.scalars(select(m.CB1ProviderConnection)).all(); row=next((x for x in rows if (loads(x.config_json,{}) or {}).get('oauth_state')==state),None)
        if not row: raise HTTPException(400,'Invalid OAuth state.')
        import httpx
        base=str(request.base_url).rstrip('/')
        if provider=='MICROSOFT':
            token_url=f'https://login.microsoftonline.com/{os.getenv("RMR_MICROSOFT_TENANT","common")}/oauth2/v2.0/token'; data={'client_id':os.getenv('RMR_MICROSOFT_CLIENT_ID'),'client_secret':os.getenv('RMR_MICROSOFT_CLIENT_SECRET'),'code':code,'grant_type':'authorization_code','redirect_uri':base+'/api/cb1/oauth/microsoft/callback','scope':'offline_access User.Read Mail.Send Mail.Read'}
        else:
            token_url='https://oauth2.googleapis.com/token'; data={'client_id':os.getenv('RMR_GOOGLE_CLIENT_ID'),'client_secret':os.getenv('RMR_GOOGLE_CLIENT_SECRET'),'code':code,'grant_type':'authorization_code','redirect_uri':base+'/api/cb1/oauth/google/callback'}
        r=httpx.post(token_url,data=data,timeout=30); r.raise_for_status(); tok=r.json(); row.token_encrypted=encrypt(tok.get('access_token')); row.refresh_token_encrypted=encrypt(tok.get('refresh_token')); row.status='ACTIVE'; row.expires_at=utcnow()+timedelta(seconds=int(tok.get('expires_in',3600))); row.updated_at=utcnow(); db.commit(); return RedirectResponse('/commercial#email')

    @router.get('/api/cb1/oauth/microsoft/callback')
    async def ms_callback(code:str,state:str,request:Request,db=Depends(db_dep)): return await oauth_callback('MICROSOFT',code,state,request,db)
    @router.get('/api/cb1/oauth/google/callback')
    async def google_callback(code:str,state:str,request:Request,db=Depends(db_dep)): return await oauth_callback('GOOGLE',code,state,request,db)

    @router.get('/api/cb1/tenants/{tenant_id}/campaigns')
    async def campaigns(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); rows=db.scalars(select(m.CB1Campaign).where(m.CB1Campaign.tenant_id==tenant_id)).all(); return {'items':[json_row(x) for x in rows]}

    @router.post('/api/cb1/tenants/{tenant_id}/campaigns')
    async def campaign_create(tenant_id:str,payload:CampaignIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); row=m.CB1Campaign(tenant_id=tenant_id,name=payload.name,status='ACTIVE',provider_connection_id=payload.provider_connection_id,frequency_hours=max(1,payload.frequency_hours),created_by=user_id(user)); db.add(row); audit(db,user,'CAMPAIGN_CREATED',tenant_id,'campaign',row.id,{},request); db.commit(); return {'campaign':json_row(row)}

    @router.post('/api/cb1/campaigns/{campaign_id}/{action}')
    async def campaign_action(campaign_id:str,action:str,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1Campaign,campaign_id)
        if not row: raise HTTPException(404,'Campaign not found.')
        require_tenant(db,user,row.tenant_id)
        if action not in {'pause','resume'}: raise HTTPException(400,'Unsupported action.')
        row.status='PAUSED' if action=='pause' else 'ACTIVE'; audit(db,user,'CAMPAIGN_'+action.upper(),row.tenant_id,'campaign',row.id,{},request); db.commit(); return {'campaign':json_row(row)}

    @router.post('/api/cb1/messages/generate')
    async def message_generate(payload:GenerateIn,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,payload.tenant_id); return generate_supported_message(payload.client_name,payload.recipient_name,payload.facts,payload.tone,payload.cta)

    @router.post('/api/cb1/messages')
    async def message_create(payload:MessageIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,payload.tenant_id)
        if content_has_unsupported_facts(payload.body,payload.supported_facts): raise HTTPException(400,'Message does not preserve all verified supported facts.')
        key=sha('|'.join([payload.tenant_id,payload.campaign_id or '',payload.recipient_email.lower(),payload.subject,payload.body]))
        existing=db.scalar(select(m.CB1Message).where(m.CB1Message.idempotency_key==key))
        if existing: return {'message':json_row(existing),'duplicate_prevented':True}
        row=m.CB1Message(tenant_id=payload.tenant_id,campaign_id=payload.campaign_id,crm_record_id=payload.crm_record_id,piq_record_id=payload.piq_record_id,recipient_email=payload.recipient_email.lower(),subject=payload.subject,body_draft=payload.body,supported_facts_json=dumps(payload.supported_facts),idempotency_key=key,created_by=user_id(user)); db.add(row); db.flush()
        db.add(m.CB1MessageVersion(message_id=row.id,version_number=1,subject=row.subject,body=row.body_draft,body_hash=sha(row.body_draft),created_by=user_id(user)))
        audit(db,user,'AI_MESSAGE_CREATED',row.tenant_id,'message',row.id,{'crm_record_id':row.crm_record_id,'piq_record_id':row.piq_record_id},request); db.commit(); return {'message':json_row(row)}

    @router.post('/api/cb1/messages/{message_id}/approve')
    async def message_approve(message_id:str,payload:ApproveIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1Message,message_id)
        if not row: raise HTTPException(404,'Message not found.')
        require_tenant(db,user,row.tenant_id); body=payload.body if payload.body is not None else row.body_draft; subject=payload.subject if payload.subject is not None else row.subject
        if not payload.verified_facts: raise HTTPException(400,'Human verification of prospect facts is required before approval.')
        if content_has_unsupported_facts(body,loads(row.supported_facts_json,[]) or []): raise HTTPException(400,'Approved content does not preserve verified supported facts.')
        count=db.query(m.CB1MessageVersion).filter(m.CB1MessageVersion.message_id==row.id).count(); db.add(m.CB1MessageVersion(message_id=row.id,version_number=count+1,subject=subject,body=body,body_hash=sha(body),created_by=user_id(user)))
        row.subject=subject; row.body_approved=body; row.approved_hash=sha(body); row.approved_by=user_id(user); row.approved_at=utcnow(); row.status='APPROVED'; audit(db,user,'MESSAGE_APPROVED',row.tenant_id,'message',row.id,{},request); db.commit(); return {'message':json_row(row)}

    @router.post('/api/cb1/messages/{message_id}/schedule')
    async def message_schedule(message_id:str,payload:ScheduleIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1Message,message_id)
        if not row: raise HTTPException(404,'Message not found.')
        require_tenant(db,user,row.tenant_id)
        if row.status!='APPROVED' or not row.body_approved or row.approved_hash!=sha(row.body_approved): raise HTTPException(409,'Only the exact approved message can be scheduled.')
        when=payload.scheduled_at if payload.scheduled_at.tzinfo else payload.scheduled_at.replace(tzinfo=timezone.utc); row.scheduled_at=when; row.status='SCHEDULED'; job=m.CB1DripJob(tenant_id=row.tenant_id,campaign_id=row.campaign_id,message_id=row.id,status='QUEUED',due_at=when); db.add(job); audit(db,user,'MESSAGE_SCHEDULED',row.tenant_id,'message',row.id,{'scheduled_at':when.isoformat()},request); db.commit(); return {'message':json_row(row),'job':json_row(job)}

    @router.post('/api/cb1/messages/{message_id}/event')
    async def message_event(message_id:str,payload:EventIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1Message,message_id)
        if not row: raise HTTPException(404,'Message not found.')
        require_tenant(db,user,row.tenant_id); event=payload.event_type.upper(); now=utcnow()
        if event=='REPLY':
            row.replied_at=now; row.status='REPLIED'; row.stop_reason='Reply received';
            for job in db.scalars(select(m.CB1DripJob).where(m.CB1DripJob.campaign_id==row.campaign_id,m.CB1DripJob.status=='QUEUED')).all(): job.status='STOPPED'; job.last_error='Sequence stopped after reply.'
            if payload.positive: db.add(m.CB1SalesTask(tenant_id=row.tenant_id,crm_record_id=row.crm_record_id,message_id=row.id,task_type='POSITIVE_REPLY_FOLLOW_UP',detail=payload.detail))
        elif event=='BOUNCE':
            row.bounced_at=now; row.status='BOUNCED'; row.stop_reason='Bounce'; db.merge(m.CB1Suppression(tenant_id=row.tenant_id,email=row.recipient_email,reason='BOUNCE',source_message_id=row.id))
        elif event=='UNSUBSCRIBE':
            row.unsubscribed_at=now; row.status='UNSUBSCRIBED'; row.stop_reason='Unsubscribe'; db.merge(m.CB1Suppression(tenant_id=row.tenant_id,email=row.recipient_email,reason='UNSUBSCRIBE',source_message_id=row.id))
        else: raise HTTPException(400,'Unsupported event.')
        audit(db,user,'MESSAGE_'+event,row.tenant_id,'message',row.id,{'detail':payload.detail,'positive':payload.positive},request); db.commit(); return {'message':json_row(row)}

    @router.get('/api/cb1/worker/health')
    async def worker_health(user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1WorkerState,'drip-worker'); return {'status':row.status if row else 'NOT_STARTED','heartbeat_at':row.heartbeat_at.isoformat() if row else None,'detail':loads(row.detail_json,{}) if row else {}}

    @router.get('/api/cb1/tenants/{tenant_id}/social-content')
    async def social_list(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,tenant_id); rows=db.scalars(select(m.CB1SocialContent).where(m.CB1SocialContent.tenant_id==tenant_id).order_by(m.CB1SocialContent.created_at.desc())).all(); return {'items':[json_row(x) for x in rows]}

    @router.post('/api/cb1/social-content')
    async def social_create(payload:SocialIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_tenant(db,user,payload.tenant_id); platform=payload.platform.upper()
        if platform not in {'FACEBOOK','INSTAGRAM','LINKEDIN','X'}: raise HTTPException(400,'Supported copy/paste platforms are Facebook, Instagram, LinkedIn and X.')
        row=m.CB1SocialContent(tenant_id=payload.tenant_id,platform=platform,title=payload.title,post_text=payload.post_text,hashtags=payload.hashtags,created_by=user_id(user)); db.add(row); audit(db,user,'SOCIAL_CONTENT_CREATED',row.tenant_id,'social_content',row.id,{'platform':platform},request); db.commit(); return {'item':json_row(row)}

    @router.post('/api/cb1/social-content/{content_id}/published')
    async def social_published(content_id:str,payload:SocialPublishIn,request:Request,user=Depends(auth_dependency),db=Depends(db_dep)):
        row=db.get(m.CB1SocialContent,content_id)
        if not row: raise HTTPException(404,'Social content not found.')
        require_tenant(db,user,row.tenant_id); row.status='PUBLISHED_MANUALLY'; row.published_url=payload.published_url; row.published_at=utcnow(); audit(db,user,'SOCIAL_CONTENT_PUBLISHED_MANUALLY',row.tenant_id,'social_content',row.id,{'url':payload.published_url},request); db.commit(); return {'item':json_row(row)}

    @router.get('/api/cb1/business-health')
    async def business_health(user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); backend=engine.url.get_backend_name(); worker=db.get(m.CB1WorkerState,'drip-worker'); provider_count=db.query(m.CB1ProviderConnection).filter(m.CB1ProviderConnection.status=='ACTIVE').count()
        cards=[
          {'label':'Core Platform','state':'HEALTHY','message':'Client records and core application services are available.','action':'No action required.'},
          {'label':'Database','state':'HEALTHY' if backend in {'postgresql','sqlite'} else 'NEEDS_ATTENTION','message':f'{backend} database is responding.','action':'PostgreSQL certification is required before production.' if backend!='postgresql' else 'No action required.'},
          {'label':'Connected Email','state':'HEALTHY' if provider_count else 'NEEDS_CONFIGURATION','message':f'{provider_count} active provider connection(s).','action':'Connect and test a client business mailbox before campaign activation.' if not provider_count else 'Monitor provider status.'},
          {'label':'Drip Worker','state':'HEALTHY' if worker and worker.status=='HEALTHY' else 'NEEDS_ATTENTION','message':worker.status if worker else 'Worker has not reported a heartbeat.','action':'Restart the application or review technical diagnostics.' if not worker else 'No action required.'},
        ]
        return {'headline':'Core platform services are operating normally.' if all(c['state']!='NEEDS_ATTENTION' for c in cards) else 'Some services need attention.','cards':cards,'technical':{'backend':backend,'migration':MIGRATION_ID,'version':VERSION}}

    @router.get('/api/cb1/commercial-readiness')
    async def commercial_readiness(user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); from .models import Tenant
        tenants=db.scalars(select(Tenant)).all(); items=[]
        for t in tenants: items.append({'tenant_id':str(t.id),'name':str(getattr(t,'name','Tenant')),'readiness':readiness(db,str(t.id))})
        return {'release':VERSION,'database_backend':engine.url.get_backend_name(),'tenants':items,'external_dependencies':[
          'Live Microsoft Graph application credentials, customer authorization and provider acceptance',
          'Live Google OAuth application credentials, customer authorization and provider acceptance',
          'Customer-specific SMTP/IMAP credentials and provider permission',
          'Production PostgreSQL host and Windows/Docker certification',
          'Final U.S. counsel approval of MSA/Order Form and production policies']}

    @router.get('/api/cb1/tenants/{tenant_id}/audit')
    async def audit_list(tenant_id:str,user=Depends(auth_dependency),db=Depends(db_dep)):
        require_owner(user); rows=db.scalars(select(m.CB1AuditEvent).where(m.CB1AuditEvent.tenant_id==tenant_id).order_by(m.CB1AuditEvent.created_at.desc()).limit(200)).all(); return {'items':[json_row(x) for x in rows]}

    return router

class CB1Middleware:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        headers=[]; body=[]; start=None
        async def capture(message):
            nonlocal start
            if message['type']=='http.response.start': start=message
            elif message['type']=='http.response.body': body.append(message.get('body',b''))
        await self.app(scope,receive,capture)
        if start is None: return
        hs=[(k.lower(),v) for k,v in start.get('headers',[])]; ctype=next((v.decode(errors='ignore') for k,v in hs if k==b'content-type'),'')
        data=b''.join(body)
        if 'text/html' in ctype:
            try:
                textdata=data.decode('utf-8'); inject=f'<link rel="stylesheet" href="/cb1/assets/cb1.css?v={VERSION}"><script src="/cb1/assets/enhancements.js?v={VERSION}" defer></script>'
                if inject not in textdata: textdata=textdata.replace('</body>',inject+'</body>')
                data=textdata.encode('utf-8')
            except Exception: pass
        filtered=[(k,v) for k,v in start.get('headers',[]) if k.lower() not in {b'content-length',b'cache-control',b'x-rmr-release'}]
        filtered.extend([(b'cache-control',b'no-store, no-cache, must-revalidate'),(b'x-rmr-release',VERSION.encode()),(b'content-length',str(len(data)).encode())])
        start['headers']=filtered; await send(start); await send({'type':'http.response.body','body':data,'more_body':False})

def install_cb1(app):
    # Schema and worker lifecycle are owned by main.lifespan / CLI migration.
    app.add_middleware(CB1Middleware)
