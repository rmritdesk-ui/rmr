
from __future__ import annotations
import datetime as dt, json, os, secrets
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse
from pydantic import BaseModel,Field
from rmr_platform.db import SessionLocal
from rmr_platform.security import current_user as current_user
from .models import *
from .security import encrypt,decrypt,new_totp_secret,totp,verify_totp,hash_token,new_token
from .policy import POLICY,scan_text
from .ai import AIMessageService
from .providers import adapter,MicrosoftGraphAdapter,GoogleGmailAdapter
from .service import event,is_suppressed,stop_on_reply,export_tenant
router=APIRouter(prefix='/api/commercial',tags=['commercial'])

def dbs(): return SessionLocal()
def bind():
    d=SessionLocal()
    try: return d.get_bind()
    finally: d.close()
def initialize_commercial_schema(): CommercialBase.metadata.create_all(bind=bind())

def role(u): return str(getattr(u,'global_role',getattr(u,'role','')) or '').upper()
def uid(u): return str(getattr(u,'id',''))
def owner(u): return role(u)=='RMR_OWNER'
def platform_admin(u): return role(u) in ('RMR_OWNER','RMR_ADMIN','STEP2_ADMIN','PLATFORM_ADMIN')
def user_tenant(u,db=None):
    v=getattr(u,'tenant_id',None)
    if v is not None: return str(v)
    # Generic membership lookup across existing schema
    try:
        from sqlalchemy import inspect,text
        b=(db or SessionLocal()).get_bind(); ins=inspect(b)
        for t in ins.get_table_names():
            cs={c['name'] for c in ins.get_columns(t)}
            if {'user_id','tenant_id'}<=cs:
                with b.connect() as c:
                    r=c.execute(text(f'SELECT tenant_id FROM "{t}" WHERE CAST(user_id AS TEXT)=:u LIMIT 1'),{'u':uid(u)}).first()
                    if r: return str(r[0])
    except Exception: pass
    return None
def require_tenant(u,tenant_id=None):
    if platform_admin(u):
        if not tenant_id: raise HTTPException(400,'tenant_id required')
        return str(tenant_id)
    t=user_tenant(u)
    if not t: raise HTTPException(403,'No tenant membership')
    if tenant_id and str(tenant_id)!=t: raise HTTPException(403,'Tenant isolation enforced')
    return t
def require_entitlement(db,tenant,module):
    e=db.query(Entitlement).filter_by(tenant_id=str(tenant),module=module,status='ACTIVE').first()
    if not e: raise HTTPException(403,f'Module not activated: {module}')
    return e
class EntitlementIn(BaseModel): tenant_id:str; module:str; status:str='ACTIVE'; source_order:str|None=None
class OrderIn(BaseModel): tenant_id:str; order_number:str; effective_date:str|None=None; modules:list[str]=[]; pricing:dict={}
class ConnectionIn(BaseModel): tenant_id:str|None=None; provider:str; account_email:str|None=None; display_name:str|None=None; credentials:dict={}; scopes:list[str]=[]
class CampaignIn(BaseModel): tenant_id:str|None=None; name:str; purpose:str; provider_connection_id:str|None=None; sequence:list[dict]=[]
class GenerateIn(BaseModel): client:dict; prospect:dict; verified_facts:list[str]=[]; adaptive_research:list[str]=[]; tone:str='professional'; cta:str='Would you be open to a brief conversation?'; crm_record_type:str|None=None; crm_record_id:str|None=None; piq_record_id:str|None=None; recipient_email:str; recipient_name:str|None=None; scheduled_at:dt.datetime|None=None
class ApproveIn(BaseModel): subject:str|None=None; body:str|None=None; scheduled_at:dt.datetime|None=None
class SuppressIn(BaseModel): tenant_id:str|None=None; email:str; reason:str; source:str='MANUAL'
class SocialIn(BaseModel): tenant_id:str|None=None; campaign_name:str; topic:str; base_copy:str; hashtags:list[str]=[]
class AccessIn(BaseModel): tenant_id:str; reason:str=Field(min_length=8); mode:str='READ_ONLY'; mfa_code:str
class ExportIn(BaseModel): tenant_id:str; reason:str=Field(min_length=8); secure_access_token:str|None=None
class CostIn(BaseModel): tenant_id:str|None=None; category:str; amount:float; period:str; allocation_method:str='DIRECT'; policy_status:str='APPROVED'; notes:str|None=None

# Complete commercial initialization is owned by rmr_platform.migrations.
@router.get('/status')
def status(u=Depends(current_user)):
    return {'version':'5.4.1.2-interaction-regression-correction-po1','role':role(u),'tenant_id':user_tenant(u),'provider_mode':os.getenv('RMR_PROVIDER_MODE','mock'),'social_mode':'GENERATE_COPY_PASTE','email_architecture':['MICROSOFT','GOOGLE','SMTP_IMAP']}
@router.get('/restricted-data/policy')
def restricted_policy(u=Depends(current_user)): return POLICY
@router.get('/entitlements')
def entitlements(tenant_id:str|None=None,u=Depends(current_user)):
    d=dbs(); t=require_tenant(u,tenant_id)
    try: return [{'module':x.module,'status':x.status,'source_order':x.source_order,'effective_at':x.effective_at} for x in d.query(Entitlement).filter_by(tenant_id=t).all()]
    finally: d.close()
@router.post('/entitlements')
def set_entitlement(i:EntitlementIn,u=Depends(current_user)):
    if not owner(u): raise HTTPException(403,'Only RMR Owner may activate commercial entitlements')
    d=dbs()
    try:
        e=d.query(Entitlement).filter_by(tenant_id=i.tenant_id,module=i.module).first() or Entitlement(tenant_id=i.tenant_id,module=i.module)
        e.status=i.status;e.source_order=i.source_order;e.created_by=uid(u);d.add(e);event(d,i.tenant_id,'MODULE_ENTITLEMENT_CHANGED',uid(u),'entitlement',e.id,module=i.module,status=i.status);d.commit();return {'id':e.id,'status':e.status}
    finally:d.close()
@router.post('/orders')
def create_order(i:OrderIn,u=Depends(current_user)):
    if not owner(u): raise HTTPException(403,'Only RMR Owner may record an Order Form')
    d=dbs()
    try:
        o=OrderRecord(tenant_id=i.tenant_id,order_number=i.order_number,effective_date=i.effective_date,modules_json=json.dumps(i.modules),pricing_json=json.dumps(i.pricing),approved_by=uid(u));d.add(o);d.flush()
        for m in i.modules:
            e=d.query(Entitlement).filter_by(tenant_id=i.tenant_id,module=m).first() or Entitlement(tenant_id=i.tenant_id,module=m)
            e.status='ACTIVE';e.source_order=i.order_number;e.created_by=uid(u);d.add(e)
        event(d,i.tenant_id,'ORDER_FORM_RECORDED',uid(u),'order',o.id,order_number=i.order_number,modules=i.modules);d.commit();return {'id':o.id}
    finally:d.close()
@router.get('/provider-connections')
def list_connections(tenant_id:str|None=None,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,tenant_id)
    try:return [{'id':x.id,'provider':x.provider,'account_email':x.account_email,'display_name':x.display_name,'status':x.status,'last_tested_at':x.last_tested_at,'last_sync_at':x.last_sync_at,'error':x.error} for x in d.query(ProviderConnection).filter_by(tenant_id=t).all()]
    finally:d.close()
@router.post('/provider-connections')
def create_connection(i:ConnectionIn,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,i.tenant_id);require_entitlement(d,t,'EMAIL')
    try:
        p=i.provider.upper();
        if p not in ('MICROSOFT','GOOGLE','SMTP_IMAP','MOCK'): raise HTTPException(400,'Unsupported provider')
        c=ProviderConnection(tenant_id=t,provider=p,account_email=i.account_email,display_name=i.display_name,encrypted_credentials=encrypt(i.credentials),scopes=json.dumps(i.scopes),status='CONFIGURED',created_by=uid(u));d.add(c);d.flush();event(d,t,'EMAIL_PROVIDER_CONNECTED',uid(u),'provider_connection',c.id,provider=p,account=i.account_email);d.commit();return {'id':c.id,'status':c.status}
    finally:d.close()
@router.get('/oauth/{provider}/start')
def oauth_start(provider:str,tenant_id:str,u=Depends(current_user)):
    t=require_tenant(u,tenant_id);state=new_token();base=os.getenv('RMR_BASE_URL','http://localhost:8080');redirect=base+f'/api/commercial/oauth/{provider.lower()}/callback'
    if provider.upper()=='MICROSOFT': url=MicrosoftGraphAdapter.auth_url(os.getenv('RMR_MICROSOFT_CLIENT_ID','CONFIGURE_ME'),redirect,state)
    elif provider.upper()=='GOOGLE': url=GoogleGmailAdapter.auth_url(os.getenv('RMR_GOOGLE_CLIENT_ID','CONFIGURE_ME'),redirect,state)
    else: raise HTTPException(400,'OAuth is available for Microsoft or Google')
    return {'authorization_url':url,'state':state,'tenant_id':t,'external_activation_required':True}
@router.post('/provider-connections/{cid}/test')
def test_connection(cid:str,u=Depends(current_user)):
    d=dbs()
    try:
        c=d.get(ProviderConnection,cid)
        if not c: raise HTTPException(404,'Connection not found')
        require_tenant(u,c.tenant_id);creds=json.loads(decrypt(c.encrypted_credentials) or '{}'); a=adapter(c.provider,creds); c.status='ACTIVE';c.last_tested_at=now();c.error=None;event(d,c.tenant_id,'EMAIL_PROVIDER_TESTED',uid(u),'provider_connection',c.id,provider=c.provider);d.commit();return {'status':'ACTIVE','mode':os.getenv('RMR_PROVIDER_MODE','mock')}
    except Exception as e:
        if 'c' in locals() and c: c.status='ERROR';c.error=str(e);d.commit()
        raise
    finally:d.close()
@router.post('/campaigns')
def create_campaign(i:CampaignIn,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,i.tenant_id);require_entitlement(d,t,'EMAIL')
    try:c=Campaign(tenant_id=t,name=i.name,purpose=i.purpose,provider_connection_id=i.provider_connection_id,sequence_json=json.dumps(i.sequence),created_by=uid(u));d.add(c);d.flush();event(d,t,'CAMPAIGN_CREATED',uid(u),'campaign',c.id,campaign_id=c.id);d.commit();return {'id':c.id,'status':c.status}
    finally:d.close()
@router.post('/campaigns/{cid}/generate')
def generate_message(cid:str,i:GenerateIn,u=Depends(current_user)):
    d=dbs()
    try:
        c=d.get(Campaign,cid)
        if not c: raise HTTPException(404,'Campaign not found')
        require_tenant(u,c.tenant_id); result=AIMessageService().generate(i.client,i.prospect,i.verified_facts,i.adaptive_research,c.purpose,i.tone,i.cta)
        findings=scan_text(result['subject']+'\n'+result['body'])
        if any(x['severity']=='BLOCK' for x in findings): raise HTTPException(400,{'message':'Restricted data detected','findings':findings})
        m=Message(tenant_id=c.tenant_id,campaign_id=c.id,crm_record_type=i.crm_record_type,crm_record_id=i.crm_record_id,piq_record_id=i.piq_record_id,recipient_name=i.recipient_name,recipient_email=i.recipient_email.lower(),subject=result['subject'],body=result['body'],scheduled_at=i.scheduled_at,generated_context_json=json.dumps(result['context']),created_by=uid(u));d.add(m);d.flush();event(d,c.tenant_id,'AI_MESSAGE_GENERATED',uid(u),'message',m.id,message_id=m.id,campaign_id=c.id,crm_record_id=i.crm_record_id,piq_record_id=i.piq_record_id,human_review_required=True);d.commit();return {'id':m.id,'subject':m.subject,'body':m.body,'status':m.status,'human_review_required':True}
    finally:d.close()
@router.post('/messages/{mid}/approve')
def approve(mid:str,i:ApproveIn,u=Depends(current_user)):
    d=dbs()
    try:
        m=d.get(Message,mid)
        if not m: raise HTTPException(404,'Message not found')
        require_tenant(u,m.tenant_id)
        if i.subject is not None:m.subject=i.subject
        if i.body is not None:m.body=i.body
        findings=scan_text((m.subject or '')+'\n'+(m.body or ''))
        if any(x['severity']=='BLOCK' for x in findings):raise HTTPException(400,{'message':'Restricted data detected','findings':findings})
        m.status='SCHEDULED' if i.scheduled_at else 'APPROVED';m.scheduled_at=i.scheduled_at;m.approved_at=now();m.approved_by=uid(u);event(d,m.tenant_id,'MESSAGE_APPROVED',uid(u),'message',m.id,message_id=m.id,campaign_id=m.campaign_id);d.commit();return {'status':m.status}
    finally:d.close()
@router.post('/messages/{mid}/send')
def send(mid:str,u=Depends(current_user)):
    d=dbs()
    try:
        m=d.get(Message,mid)
        if not m:raise HTTPException(404,'Message not found')
        require_tenant(u,m.tenant_id);require_entitlement(d,m.tenant_id,'EMAIL')
        if m.status not in ('APPROVED','SCHEDULED'):raise HTTPException(409,'Human approval is required before sending')
        if is_suppressed(d,m.tenant_id,m.recipient_email):raise HTTPException(409,'Recipient is suppressed')
        c=d.get(Campaign,m.campaign_id);pc=d.get(ProviderConnection,c.provider_connection_id) if c and c.provider_connection_id else None
        if not pc:raise HTTPException(409,'Connected customer mailbox required')
        result=adapter(pc.provider,json.loads(decrypt(pc.encrypted_credentials) or '{}')).send({'id':m.id,'recipient_email':m.recipient_email,'subject':m.subject,'body':m.body});m.status='SENT';m.sent_at=now();m.provider_message_id=result.get('provider_message_id');event(d,m.tenant_id,'EMAIL_SENT',uid(u),'message',m.id,message_id=m.id,campaign_id=m.campaign_id,crm_record_id=m.crm_record_id,piq_record_id=m.piq_record_id,provider=pc.provider);d.commit();return {'status':'SENT','provider_message_id':m.provider_message_id}
    finally:d.close()
@router.post('/providers/{provider}/webhook')
def provider_webhook(provider:str,payload:dict,request:Request):
    d=dbs()
    try:
        tenant=str(payload.get('tenant_id',''));mid=payload.get('rmr_message_id');typ=str(payload.get('event_type','')).upper();m=d.get(Message,mid) if mid else None
        if not tenant or not m or m.tenant_id!=tenant:raise HTTPException(404,'Message correlation not found')
        if typ=='REPLY':stop_on_reply(d,m)
        elif typ in ('BOUNCE','FAILED'):m.status='BOUNCED';m.stopped_reason='BOUNCE';d.add(Suppression(tenant_id=tenant,email=m.recipient_email,reason='BOUNCE',source=provider.upper()));event(d,tenant,'EMAIL_BOUNCED',None,'message',m.id,message_id=m.id)
        elif typ=='UNSUBSCRIBE':d.add(Suppression(tenant_id=tenant,email=m.recipient_email,reason='UNSUBSCRIBE',source=provider.upper()));m.status='UNSUBSCRIBED';m.stopped_reason='UNSUBSCRIBE';event(d,tenant,'EMAIL_UNSUBSCRIBED',None,'message',m.id,message_id=m.id)
        else:event(d,tenant,'EMAIL_'+typ,None,'message',m.id,message_id=m.id)
        d.commit();return {'accepted':True}
    finally:d.close()
@router.post('/suppressions')
def suppress(i:SuppressIn,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,i.tenant_id)
    try:
        s=d.query(Suppression).filter_by(tenant_id=t,email=i.email.lower()).first() or Suppression(tenant_id=t,email=i.email.lower(),reason=i.reason)
        s.reason=i.reason;s.source=i.source;s.active=True;s.created_by=uid(u);d.add(s);event(d,t,'RECIPIENT_SUPPRESSED',uid(u),'suppression',s.id,email=i.email,reason=i.reason);d.commit();return {'status':'SUPPRESSED'}
    finally:d.close()
@router.post('/social-drafts')
def social(i:SocialIn,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,i.tenant_id);require_entitlement(d,t,'SOCIAL_CONTENT')
    try:
        tags=' '.join('#'+x.lstrip('#') for x in i.hashtags);base=i.base_copy.strip();x=(base+' '+tags).strip()[:280]
        s=SocialDraft(tenant_id=t,campaign_name=i.campaign_name,topic=i.topic,facebook_text=base,instagram_text=(base+'\n\n'+tags).strip(),linkedin_text=base,x_text=x,hashtags=tags,created_by=uid(u));d.add(s);d.flush();event(d,t,'SOCIAL_CONTENT_GENERATED',uid(u),'social_draft',s.id,mode='COPY_PASTE');d.commit();return {'id':s.id,'facebook':s.facebook_text,'instagram':s.instagram_text,'linkedin':s.linkedin_text,'x':s.x_text,'publishing_mode':'COPY_PASTE'}
    finally:d.close()
@router.post('/mfa/enroll')
def mfa_enroll(u=Depends(current_user)):
    if not owner(u):raise HTTPException(403,'RMR Owner only')
    d=dbs()
    try:
        s=new_totp_secret();r=d.query(MFAState).filter_by(user_id=uid(u)).first() or MFAState(user_id=uid(u),encrypted_secret=encrypt(s));r.encrypted_secret=encrypt(s);r.enabled=False;d.add(r);d.commit();return {'secret':s,'otpauth_uri':f'otpauth://totp/RMR%20Software:{getattr(u,"email",uid(u))}?secret={s}&issuer=RMR%20Software'}
    finally:d.close()
@router.post('/mfa/verify')
def mfa_verify(payload:dict,u=Depends(current_user)):
    if not owner(u):raise HTTPException(403,'RMR Owner only')
    d=dbs()
    try:
        r=d.query(MFAState).filter_by(user_id=uid(u)).first()
        if not r or not verify_totp(decrypt(r.encrypted_secret),payload.get('code')):raise HTTPException(400,'Invalid code')
        r.enabled=True;r.verified_at=now();event(d,'PLATFORM','RMR_OWNER_MFA_VERIFIED',uid(u),'user',uid(u));d.commit();return {'verified':True}
    finally:d.close()
@router.post('/secure-access/start')
def access_start(i:AccessIn,request:Request,u=Depends(current_user)):
    if not owner(u):raise HTTPException(403,'RMR Owner Secure Tenant Access is RMR Owner only')
    d=dbs()
    try:
        m=d.query(MFAState).filter_by(user_id=uid(u),enabled=True).first()
        if not m or not verify_totp(decrypt(m.encrypted_secret),i.mfa_code):raise HTTPException(403,'Current multi-factor authentication required')
        token=new_token();s=SecureAccessSession(token_hash=hash_token(token),owner_user_id=uid(u),tenant_id=i.tenant_id,reason=i.reason,mode='READ_ONLY' if i.mode.upper()!='ELEVATED' else 'ELEVATED',ip_address=request.client.host if request.client else None,user_agent=request.headers.get('user-agent'),expires_at=now()+dt.timedelta(minutes=15));d.add(s);d.flush();event(d,i.tenant_id,'RMR_OWNER_SECURE_TENANT_ACCESS_STARTED',uid(u),'secure_access',s.id,reason=i.reason,mode=s.mode);d.commit();return {'access_token':token,'session_id':s.id,'tenant_id':s.tenant_id,'mode':s.mode,'expires_at':s.expires_at,'banner':'RMR OWNER ACCESS - ALL ACTIVITY IS AUDITED'}
    finally:d.close()
@router.post('/secure-access/{sid}/end')
def access_end(sid:str,u=Depends(current_user)):
    if not owner(u):raise HTTPException(403,'RMR Owner only')
    d=dbs()
    try:s=d.get(SecureAccessSession,sid);s.ended_at=now();event(d,s.tenant_id,'RMR_OWNER_SECURE_TENANT_ACCESS_ENDED',uid(u),'secure_access',s.id);d.commit();return {'ended':True}
    finally:d.close()
@router.post('/exports')
def export(i:ExportIn,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,i.tenant_id)
    try:
        if platform_admin(u):
            if not owner(u):raise HTTPException(403,'Only RMR Owner may export another tenant')
            if not i.secure_access_token:raise HTTPException(403,'Secure tenant access token required')
            s=d.query(SecureAccessSession).filter_by(token_hash=hash_token(i.secure_access_token),owner_user_id=uid(u),tenant_id=t).first()
            if not s or s.ended_at or s.expires_at<now():raise HTTPException(403,'Secure access session expired')
        out=Path(os.getenv('RMR_DATA_DIR','/data' if Path('/data').exists() else str(Path.cwd()/'data')))/'exports';path,manifest=export_tenant(d.get_bind(),t,out);j=ExportJob(tenant_id=t,requested_by=uid(u),reason=i.reason,status='COMPLETED',file_path=str(path),manifest_json=json.dumps(manifest),completed_at=now());d.add(j);d.flush();event(d,t,'CUSTOMER_DATA_EXPORT_CREATED',uid(u),'export',j.id,reason=i.reason,table_counts=manifest['tables']);d.commit();return {'id':j.id,'status':j.status,'download_url':f'/api/commercial/exports/{j.id}/download','manifest':manifest}
    finally:d.close()
@router.get('/exports/{jid}/download')
def download_export(jid:str,u=Depends(current_user)):
    d=dbs()
    try:
        j=d.get(ExportJob,jid)
        if not j:raise HTTPException(404,'Export not found')
        require_tenant(u,j.tenant_id)
        if not owner(u) and user_tenant(u)!=j.tenant_id:raise HTTPException(403,'Tenant isolation enforced')
        return FileResponse(j.file_path,filename=Path(j.file_path).name)
    finally:d.close()
@router.post('/costs')
def add_cost(i:CostIn,u=Depends(current_user)):
    if not owner(u):raise HTTPException(403,'RMR Owner only')
    d=dbs()
    try:c=CostEntry(tenant_id=i.tenant_id,category=i.category,amount=i.amount,period=i.period,allocation_method=i.allocation_method,policy_status=i.policy_status,notes=i.notes,created_by=uid(u));d.add(c);d.flush();event(d,i.tenant_id or 'PLATFORM','PARTNER_ECONOMICS_COST_RECORDED',uid(u),'cost',c.id,category=i.category,amount=i.amount,allocation_method=i.allocation_method,policy_status=i.policy_status);d.commit();return {'id':c.id}
    finally:d.close()
@router.get('/costs/summary')
def costs(tenant_id:str|None=None,period:str|None=None,u=Depends(current_user)):
    if not platform_admin(u):raise HTTPException(403,'Platform administration only')
    d=dbs()
    try:
        q=d.query(CostEntry)
        if tenant_id:q=q.filter_by(tenant_id=tenant_id)
        if period:q=q.filter_by(period=period)
        rows=q.all();return {'total':sum(x.amount for x in rows),'by_category':{k:sum(x.amount for x in rows if x.category==k) for k in sorted({x.category for x in rows})},'policy_pending':[x.id for x in rows if x.policy_status!='APPROVED']}
    finally:d.close()
@router.get('/events')
def events(tenant_id:str|None=None,limit:int=200,u=Depends(current_user)):
    d=dbs();t=require_tenant(u,tenant_id)
    try:return [{'id':x.id,'event_type':x.event_type,'actor_user_id':x.actor_user_id,'entity_type':x.entity_type,'entity_id':x.entity_id,'crm_record_id':x.crm_record_id,'piq_record_id':x.piq_record_id,'data':json.loads(x.data_json or '{}'),'occurred_at':x.occurred_at} for x in d.query(ActivityEvent).filter_by(tenant_id=t).order_by(ActivityEvent.occurred_at.desc()).limit(min(limit,500)).all()]
    finally:d.close()
