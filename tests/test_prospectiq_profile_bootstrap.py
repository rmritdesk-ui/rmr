"""Runtime coordinator security and active-only selection; no real providers."""
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_prospectiq_federation import federation_engine, fx
from rmr_platform.models import TenantService
from rmr_platform.unified_models import PiqTargetProfile
from rmr_platform.prospectiq_bridge import profile_bootstrap as p
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from rmr_platform.db import get_db
from rmr_platform.prospectiq_bridge.config import bridge_config
from rmr_platform.prospectiq_bridge.routes import router
from rmr_platform.security import COOKIE_NAME
import secrets
import time


@pytest.mark.parametrize('count', [0, 1, 3])
def test_runtime_active_only_and_completion_short_circuit(fx, count):
    for n in range(count):
        fx.db.add(PiqTargetProfile(tenant_id=fx.a.id, name=f'Active {n}', active=True))
    fx.db.add(PiqTargetProfile(tenant_id=fx.a.id, name='Archived', active=False))
    fx.db.add(PiqTargetProfile(tenant_id=fx.b.id, name='Foreign', active=True))
    fx.db.commit()
    complete = False
    calls = []
    def send(req):
        nonlocal complete
        assert str(req.url) == fx.cfg.piq_origin + p.BOOTSTRAP_PATH
        canonical = '\n'.join([fx.cfg.instance, fx.cfg.hmac_key_id, 'POST', p.BOOTSTRAP_PATH,
            req.headers['X-Bridge-Timestamp'], req.headers['X-Bridge-Nonce'], hashlib.sha256(req.content).hexdigest()])
        assert hmac.compare_digest(req.headers['X-Bridge-Signature'], hmac.new(fx.cfg.hmac_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest())
        data = json.loads(req.content); calls.append(data)
        assert data['mapping_id'] == fx.mapping.id and data['piq_client_id'] == fx.mapping.piq_client_id
        if data['operation'] == 'import':
            assert len(data['export']['profiles']) == count
            assert all(row['active'] and row['tenant_id'] == fx.a.id for row in data['export']['profiles'])
            complete = True
        return httpx.Response(200, json={'version':'1', 'status':'completed' if complete else 'never_attempted',
            'mapping_id':fx.mapping.id, 'piq_client_id':fx.mapping.piq_client_id})
    transport = httpx.MockTransport(send)
    assert p.ensure_bootstrap(fx.db, fx.user, fx.a.id, fx.request, fx.cfg, transport)['status'] == 'completed'
    assert len(calls) == 2
    fx.db.add(PiqTargetProfile(tenant_id=fx.a.id, name='Later change', active=True)); fx.db.commit()
    p.ensure_bootstrap(fx.db, fx.user, fx.a.id, fx.request, fx.cfg, transport)
    assert len(calls) == 3 and calls[-1]['operation'] == 'status' and 'export' not in calls[-1]


@pytest.mark.parametrize('change', ['foreign', 'inactive', 'suspended', 'entitlement'])
def test_no_signed_call_before_authorization(fx, change):
    if change == 'foreign': fx.user.tenant_id = fx.b.id
    if change == 'inactive': fx.user.active = False
    if change == 'suspended': fx.mapping.status = 'suspended'
    if change == 'entitlement': fx.db.scalar(select(TenantService)).status = 'inactive'
    fx.db.commit()
    def forbidden(req): pytest.fail('Unauthorized partner request')
    with pytest.raises(HTTPException):
        p.ensure_bootstrap(fx.db, fx.user, fx.a.id, fx.request, fx.cfg, httpx.MockTransport(forbidden))


def test_read_only_can_reenter_completed_but_not_initialize(fx):
    fx.user.tenant_role = 'EXECUTIVE_VIEWER'; fx.db.commit()
    state = 'never_attempted'
    def send(req):
        assert json.loads(req.content)['operation'] == 'status'
        return httpx.Response(200,json={'version':'1','status':state,'mapping_id':fx.mapping.id,'piq_client_id':fx.mapping.piq_client_id})
    with pytest.raises(HTTPException) as error:
        p.ensure_bootstrap(fx.db,fx.user,fx.a.id,fx.request,fx.cfg,httpx.MockTransport(send))
    assert error.value.status_code == 403
    state = 'completed'
    assert p.ensure_bootstrap(fx.db,fx.user,fx.a.id,fx.request,fx.cfg,httpx.MockTransport(send))['status']=='completed'


@pytest.mark.parametrize('mode', ['lost', 'binding', 'failed', 'oversized'])
def test_remote_failure_is_safe_and_retryable(fx, mode):
    def send(req):
        if mode=='lost': raise httpx.ReadTimeout('PRIVATE DSN')
        if mode=='oversized': return httpx.Response(200,content=b'x'*33000)
        return httpx.Response(200,json={'version':'1','status':'failed',
          'mapping_id':str(uuid4()) if mode=='binding' else fx.mapping.id,'piq_client_id':fx.mapping.piq_client_id})
    with pytest.raises(HTTPException) as error:
        p.ensure_bootstrap(fx.db,fx.user,fx.a.id,fx.request,fx.cfg,httpx.MockTransport(send))
    assert 'PRIVATE' not in str(error.value.detail)


def test_mapping_check_auth_replay_and_binding(fx):
    app=FastAPI();app.include_router(router)
    def database():
        with Session(fx.engine) as db: yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[bridge_config]=lambda:fx.cfg
    client=TestClient(app,base_url='https://rmr.test')
    path='/api/integrations/prospectiq/v1/mappings/check'
    payload={'version':'1','mapping_id':fx.mapping.id,'mapping_version':1,
             'rmr_tenant_id':fx.a.id,'piq_client_id':fx.mapping.piq_client_id,'integration_instance_id':fx.cfg.instance}
    def signed(data):
        body=json.dumps(data).encode();stamp=str(int(time.time()));nonce=secrets.token_hex(32)
        canonical='\n'.join([fx.cfg.instance,fx.cfg.hmac_key_id,'POST',path,stamp,nonce,hashlib.sha256(body).hexdigest()])
        headers={'Content-Type':'application/json','X-Bridge-Instance':fx.cfg.instance,'X-Bridge-Key':fx.cfg.hmac_key_id,
          'X-Bridge-Timestamp':stamp,'X-Bridge-Nonce':nonce,
          'X-Bridge-Signature':hmac.new(fx.cfg.hmac_secret.encode(),canonical.encode(),hashlib.sha256).hexdigest()}
        return body,headers
    assert client.post(path,json=payload).status_code==401
    body,headers=signed(payload)
    assert client.post(path,content=body,headers=headers).json()=={'active':True}
    assert client.post(path,content=body,headers=headers).status_code==409
    for key,value in [('rmr_tenant_id',fx.b.id),('piq_client_id',str(uuid4())),('mapping_version',2),('integration_instance_id','wrong')]:
        body,headers=signed({**payload,key:value})
        assert client.post(path,content=body,headers=headers).json()=={'active':False}
    fx.mapping.status='suspended';fx.db.commit()
    body,headers=signed(payload)
    assert client.post(path,content=body,headers=headers).json()=={'active':False}


def test_bootstrap_route_auth_origin_and_strict_tenant_only_contract(fx,monkeypatch):
    app=FastAPI();app.include_router(router)
    def database():
        with Session(fx.engine) as db: yield db
    app.dependency_overrides[get_db]=database
    client=TestClient(app,base_url='https://rmr.test')
    path='/api/integrations/prospectiq/v1/profiles/bootstrap'
    assert client.post(path,json={'tenant_id':fx.a.id}).status_code in (401,404)
    client.cookies.set(COOKIE_NAME,fx.cookie)
    assert client.post(path,json={'tenant_id':fx.a.id}).status_code==404
    app.dependency_overrides[bridge_config]=lambda:fx.cfg
    assert client.post(path,json={'tenant_id':fx.a.id}).status_code==403
    headers={'Origin':'https://rmr.test','X-RMR-Request':'1'}
    assert client.post(path,headers=headers,json={'tenant_id':fx.a.id,'piq_client_id':str(uuid4())}).status_code==422
    monkeypatch.setattr(p,'remote',lambda cfg,data,transport=None:{'version':'1','status':'completed',
      'mapping_id':fx.mapping.id,'piq_client_id':fx.mapping.piq_client_id})
    assert client.post(path,headers=headers,json={'tenant_id':fx.b.id}).status_code==409
    assert client.post(path,headers=headers,json={'tenant_id':fx.a.id}).status_code==200
