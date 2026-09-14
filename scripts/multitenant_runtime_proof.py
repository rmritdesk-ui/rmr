"""Prompt 4 synthetic fixture controls; never installed databases or provider access."""
import json,os,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text())
os.environ.update(RMR_DATABASE_URL='postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test?options=-csearch_path%3Drmr_operations_proof',RMR_AUTO_MIGRATE='false',RMR_AUTO_SEED='false')
from rmr_platform.db import db_session
from rmr_platform.models import Tenant,User,TenantService,Lead
from rmr_platform.unified_models import PiqTargetProfile
from rmr_platform.security import hash_password
from sqlalchemy import select,func
from rmr_platform.prospectiq_bridge.models import ProspectiqClientMapping as Mapping
action=sys.argv[1]
if action=='ready':
 try:
  with db_session() as db:assert db.get(Tenant,f['tenant'])
 except Exception:raise SystemExit(1)
elif action=='seed':
 actors=[{'name':'Kerry Laughlin Real Estate','tenant':f['tenant'],'email':f['actors']['CLIENT_ADMIN']['email'],'user':f['user'],'profile':True}]
 with db_session() as db:
  db.get(Tenant,f['tenant']).name=actors[0]['name']
  for name,profile in [('Profound',True),('Synthetic Dynamic Tenant',False)]:
   tenant=str(uuid4());user=str(uuid4());email='dynamic-'+user+'@example.invalid'
   db.add(Tenant(id=tenant,name=name,slug='dynamic-'+tenant));db.flush()
   db.add(User(id=user,tenant_id=tenant,tenant_role='CLIENT_ADMIN',full_name=name+' Administrator',email=email,password_hash=hash_password(f['password'])))
   for code in ['piq_access','piq_enhancement']:db.add(TenantService(tenant_id=tenant,service_code=code,status='active'))
   if profile:db.add(PiqTargetProfile(tenant_id=tenant,name=name+' Partners',industries_json=['Mortgage'],locations_json=['Phoenix, Arizona']))
   actors.append({'name':name,'tenant':tenant,'email':email,'user':user,'profile':profile})
 (root/'multitenant-actors.json').write_text(json.dumps(actors))
 print('Three synthetic tenant identities ready; new tenants have no manual PIQ mappings')
elif action in ('disable','enable','user-disable','user-enable','access-disable','enhancement-disable','restore-services','downgrade','restore-role','membership-remove','membership-restore','mapping-suspend','mapping-restore'):
 actor=json.loads((root/'multitenant-actors.json').read_text())[int(sys.argv[2])]
 with db_session() as db:
  user=db.get(User,actor['user']);tenant=db.get(Tenant,actor['tenant'])
  if action in ('disable','enable'):tenant.status='inactive' if action=='disable' else 'live'
  elif action in ('user-disable','user-enable'):user.active=action=='user-enable'
  elif action in ('downgrade','restore-role'):user.tenant_role='EXECUTIVE_VIEWER' if action=='downgrade' else 'CLIENT_ADMIN'
  elif action in ('membership-remove','membership-restore'):user.tenant_id=None if action=='membership-remove' else tenant.id
  elif action.startswith('mapping-'):db.scalar(select(Mapping).where(Mapping.tenant_id==tenant.id)).status='suspended' if action=='mapping-suspend' else 'active'
  else:
   for row in db.scalars(select(TenantService).where(TenantService.tenant_id==tenant.id)):
    if action=='restore-services':row.status='active'
    elif row.service_code==('piq_access' if action=='access-disable' else 'piq_enhancement'):row.status='inactive'
 print('Disposable authorization state updated:',action)
elif action=='restarted':
 (root/'multitenant-restarted').write_text('ready')
elif action=='inspect':
 results=json.loads((root/'multitenant-results.json').read_text())
 with db_session() as db:
  for row in results:
   assert db.scalar(select(func.count(Lead.id)).where(Lead.tenant_id==row['tenant']))==1
   lead=db.get(Lead,row['rmr_lead_id']);assert lead.tenant_id==row['tenant'] and lead.source=='ProspectIQ'
 print('PASS: exactly one correct RMR CRM lead per tenant')
else:raise SystemExit('Unknown disposable fixture action')
