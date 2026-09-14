"""Synthetic tenants ONLY in the disposable Prompt 3 browser-proof database."""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
assert os.environ.get('PROFILE_BROWSER_FIXTURE')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text())
os.environ.update(RMR_DATABASE_URL='postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test?options=-csearch_path%3Drmr_operations_proof',
                  RMR_AUTO_MIGRATE='false',RMR_AUTO_SEED='false')
from rmr_platform.db import db_session
from rmr_platform.models import Tenant,User,TenantService
from rmr_platform.unified_models import PiqTargetProfile
from rmr_platform.security import hash_password
actors=[]
with db_session() as db:
    for count in [1,0]:
        tenant=str(uuid4());email='new-'+tenant+'@example.invalid'
        db.add(Tenant(id=tenant,name='Synthetic first use '+str(count),slug='new-'+tenant));db.flush()
        db.add(User(tenant_id=tenant,tenant_role='CLIENT_ADMIN',full_name='Synthetic new administrator',email=email,password_hash=hash_password(f['password'])))
        for code in ['piq_access','piq_enhancement']:db.add(TenantService(tenant_id=tenant,service_code=code,status='active'))
        if count:db.add(PiqTargetProfile(tenant_id=tenant,name='Automatic initial profile',industries_json=['Mortgage'],locations_json=['Phoenix, Arizona']))
        db.add(PiqTargetProfile(tenant_id=tenant,name='Archived must not import',active=False))
        actors.append({'tenant':tenant,'email':email,'count':count})
(root/'new-onboarding.json').write_text(json.dumps(actors))
print('Two synthetic RMR tenants prepared; no PIQ mapping/client/profile created by fixture')
