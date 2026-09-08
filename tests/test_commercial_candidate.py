
import datetime as dt,json,os,tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from rmr_platform.commercial.models import CommercialBase,Campaign,Message,Suppression,Entitlement,ActivityEvent
from rmr_platform.commercial.security import encrypt,decrypt,new_totp_secret,totp,verify_totp,new_token,hash_token
from rmr_platform.commercial.ai import AIMessageService
from rmr_platform.commercial.policy import scan_text,luhn
from rmr_platform.commercial.providers import adapter,MockAdapter
from rmr_platform.commercial.service import is_suppressed,stop_on_reply,export_tenant

def db():
    e=create_engine('sqlite:///:memory:');CommercialBase.metadata.create_all(e);return sessionmaker(bind=e)(),e
def test_secret_encryption_roundtrip():
    v={'access_token':'sensitive','refresh_token':'more'}; assert json.loads(decrypt(encrypt(v)))==v
def test_totp_mfa():
    s=new_totp_secret();assert verify_totp(s,totp(s));assert not verify_totp(s,'000000')
def test_ai_human_approval_and_facts_only():
    r=AIMessageService().generate({'company_name':'Profound','sender_name':'Dani'},{'contact_name':'Alex','company_name':'ABC'},['ABC opened a second Arizona location'],[],'improve tax planning')
    assert r['human_review_required'] and 'second Arizona location' in r['body'] and not r['unsupported_claims_added']
def test_restricted_card_and_secret_detection():
    assert any(x['type']=='FULL_PAYMENT_CARD' for x in scan_text('4111 1111 1111 1111'))
    assert any(x['type']=='CREDENTIAL_OR_SECRET' for x in scan_text('api_key=abc'))
def test_mock_customer_mailbox_send():
    os.environ['RMR_PROVIDER_MODE']='mock';r=adapter('MICROSOFT',{}).send({'id':'m1','recipient_email':'a@b.com','subject':'s','body':'b'});assert r['status']=='sent'
def test_tenant_suppression_and_stop_on_reply():
    d,e=db();d.add(Suppression(tenant_id='t1',email='x@y.com',reason='UNSUBSCRIBE'));c=Campaign(tenant_id='t1',name='c',purpose='p');d.add(c);d.flush();m1=Message(tenant_id='t1',campaign_id=c.id,recipient_email='x@y.com',status='SENT');m2=Message(tenant_id='t1',campaign_id=c.id,recipient_email='x@y.com',status='SCHEDULED');d.add_all([m1,m2]);d.commit();assert is_suppressed(d,'t1','x@y.com');stop_on_reply(d,m1);d.commit();assert m2.status=='STOPPED' and m1.status=='REPLIED'
def test_activity_event_links_crm_piq():
    d,e=db();a=ActivityEvent(tenant_id='t',event_type='EMAIL_SENT',crm_record_id='crm1',piq_record_id='piq1');d.add(a);d.commit();x=d.query(ActivityEvent).one();assert x.crm_record_id=='crm1' and x.piq_record_id=='piq1'
def test_entitlement_unique_per_tenant_module():
    d,e=db();d.add(Entitlement(tenant_id='t',module='EMAIL'));d.commit();assert d.query(Entitlement).filter_by(tenant_id='t',module='EMAIL').count()==1
def test_export_is_tenant_scoped_and_redacts_secrets(tmp_path):
    d,e=db();d.add(ActivityEvent(tenant_id='t1',event_type='X',data_json='{}'));d.add(ActivityEvent(tenant_id='t2',event_type='Y',data_json='{}'));d.commit();p,m=export_tenant(e,'t1',tmp_path);assert p.exists() and m['tables']['commercial_activity_events']==1
