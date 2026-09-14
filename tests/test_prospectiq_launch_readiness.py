"""Safe final configuration diagnostics and non-destructive installed-state upgrade."""
import json,secrets
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException
from test_prospectiq_federation import federation_engine,fx
from test_prospectiq_crm import transfer,counts
from rmr_platform.prospectiq_bridge import config as c,crm,operations as op

@pytest.fixture
def configured(fx,tmp_path,monkeypatch):
 key=tmp_path/'ephemeral.pem';key.write_bytes(fx.cfg.private_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
 settings=SimpleNamespace(prospectiq_bridge_enabled=True,base_url='https://rmr.test',prospectiq_base_url='https://piq.test',cookie_secure=True,secret_key=secrets.token_hex(32),prospectiq_integration_instance_id='test',prospectiq_assertion_issuer='https://rmr.test',prospectiq_assertion_audience='test',prospectiq_authorization_code_ttl_seconds=60)
 for module in [c,crm,op]:monkeypatch.setattr(module,'settings',settings)
 for name,value in {'SIGNING_KEY_ID':'fed','HMAC_KEY_ID':'grant','HMAC_SECRET':fx.cfg.hmac_secret,'SIGNING_PRIVATE_KEY_FILE':str(key),'CALLBACK_URL':'https://piq.test/','HMAC_KEYS_JSON':'{}','CRM_KEYS_JSON':json.dumps({'crm':secrets.token_hex(32)}),'GRANT_MAX_SECONDS':'28800'}.items():monkeypatch.setenv('RMR_PROSPECTIQ_'+name,value)
 return settings,key

@pytest.mark.parametrize('change,category',[
 ('rmr','invalid_rmr_origin'),('piq','invalid_piq_origin'),('cookie','secure_cookie_or_hostname_requirement'),
 ('samehost','secure_cookie_or_hostname_requirement'),('callback','callback_mismatch'),('grant','grant_hmac_or_identity_configuration'),
 ('missing','signing_key_missing_unreadable_or_invalid'),('invalid','signing_key_missing_unreadable_or_invalid'),
 ('issuer','issuer_or_ttl_mismatch'),('crm','crm_hmac_unavailable')])
def test_categories_are_safe_and_startup_fails_closed(fx,configured,monkeypatch,change,category):
 settings,key=configured
 if change=='rmr':settings.base_url='http://invalid.test'
 elif change=='piq':settings.prospectiq_base_url='http://invalid.test'
 elif change=='cookie':settings.cookie_secure=False
 elif change=='samehost':settings.prospectiq_base_url='https://rmr.test:8443'
 elif change=='callback':monkeypatch.setenv('RMR_PROSPECTIQ_CALLBACK_URL','https://other.test/')
 elif change=='grant':monkeypatch.setenv('RMR_PROSPECTIQ_HMAC_SECRET','invalid')
 elif change=='missing':monkeypatch.setenv('RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE',str(key/'missing'))
 elif change=='invalid':key.write_text('invalid')
 elif change=='issuer':settings.prospectiq_assertion_issuer='https://other.test'
 elif change=='crm':monkeypatch.setenv('RMR_PROSPECTIQ_CRM_KEYS_JSON',json.dumps({'crm':c.bridge_config().hmac_secret}))
 result=op.readiness(fx.db);assert result['status']=='not_ready';assert category in result['failure_categories']
 assert fx.cfg.hmac_secret not in json.dumps(result)
 with pytest.raises(RuntimeError,match=category):op.validate_startup()

def test_valid_readiness_and_db_failure_are_separate(fx,configured):
 assert op.readiness(fx.db)['status']=='ready'
 class Offline:
  def execute(self,*a):raise RuntimeError('private DSN must never leak')
  def scalar(self,*a):raise RuntimeError('private DSN must never leak')
  def rollback(self):pass
 result=op.readiness(Offline());assert result['failure_categories']==['database_unavailable','mapping_subsystem_unavailable']
 assert 'private DSN' not in json.dumps(result)

def test_existing_crm_identity_survives_repeated_additive_upgrade(transfer):
 from rmr_platform.migrations import apply_prospectiq_federation_schema,apply_prospectiq_operations_schema
 t=transfer;first=t.call();assert first.status_code==201;before=counts(t)
 for _ in range(2):
  apply_prospectiq_federation_schema(bind=t.f.engine);apply_prospectiq_operations_schema(bind=t.f.engine)
 assert counts(t)==before
 retry=t.call();assert retry.status_code==200;assert retry.json()['rmr_lead_id']==first.json()['rmr_lead_id'];assert counts(t)==before
