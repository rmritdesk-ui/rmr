"""Focused provisioning tests; no live provider or application databases."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from test_prospectiq_federation import federation_engine, fx, issue
from rmr_platform.db import get_db
from rmr_platform.models import Tenant, User, TenantService
from rmr_platform.security import COOKIE_NAME
from rmr_platform.prospectiq_bridge import provisioning as p, contracts as c, service
from rmr_platform.prospectiq_bridge.config import bridge_config
from rmr_platform.prospectiq_bridge.models import ProspectiqClientMapping as Mapping
from rmr_platform.prospectiq_bridge.routes import router


@pytest.fixture
def fresh(fx):
    fx.db.delete(fx.mapping);fx.db.commit()
    fx.tenant_id,fx.user_id=fx.a.id,fx.user.id
    return fx


def remote(f, *, lose_first=False):
    """Deterministic local fixture, or the isolated real PIQ provisioning endpoint."""
    clients,lock={},Lock()
    endpoint=os.getenv('RMR_WORKSPACE_FIXTURE_URL')
    if endpoint:
        assert endpoint=='http://workspace-fixture:4000'
    def send(request):
        assert request.url==f.cfg.piq_origin+p.WORKSPACE_PATH
        data=json.loads(request.content)
        assert set(data)=={'version','rmr_tenant_id','tenant_name'}
        if endpoint:
            with httpx.Client(trust_env=False,timeout=15) as client:
                result=client.post(endpoint+p.WORKSPACE_PATH,content=request.content,headers=dict(request.headers))
            payload=result.json()
        else:
            payload={'version':'1','issuer':f.cfg.issuer,'integration_instance_id':f.cfg.instance,
                     'rmr_tenant_id':data['rmr_tenant_id'],
                     'piq_client_id':str(uuid5(NAMESPACE_URL,f.cfg.issuer+data['rmr_tenant_id']))}
            result=None
        with lock:
            first=data['rmr_tenant_id'] not in clients
            clients[data['rmr_tenant_id']]=payload.get('piq_client_id')
        if lose_first and first:
            raise httpx.ReadTimeout('simulated lost response')
        return httpx.Response(result.status_code if result else 200,json=payload)
    return httpx.MockTransport(send),clients


def configured_fixture(f):
    """Only disposable fixture integration uses a public test-only HMAC."""
    if os.getenv('RMR_WORKSPACE_FIXTURE_URL'):
        from dataclasses import replace
        f.cfg=replace(f.cfg,hmac_key_id='workspace-test',hmac_secret='workspace-test-only-not-a-production-secret')
        f.user.email=str(uuid4())+'@example.invalid'
        f.db.commit()
    return f


@pytest.mark.parametrize('concurrency',[2,5,8])
def test_concurrent_first_use_repeat_and_existing_federation(fresh,concurrency):
    f=configured_fixture(fresh);transport,clients=remote(f)
    def provision(_):
        with Session(f.engine,expire_on_commit=False) as db:
            return p.provision(db,db.get(User,f.user_id),f.tenant_id,f.request,f.cfg,transport)
    results=list(ThreadPoolExecutor(max_workers=concurrency).map(provision,range(concurrency)))
    assert len({r['mapping_id'] for r in results})==1
    assert provision(None)==results[0]
    f.db.expire_all()
    rows=list(f.db.scalars(select(Mapping).where(Mapping.tenant_id==f.tenant_id)))
    assert len(rows)==1 and rows[0].piq_client_id==clients[f.tenant_id]
    f.mapping=rows[0]
    launch,_,_,exchange=issue(f)
    assertion=service.exchange_code(f.db,exchange,f.cfg)['assertion']
    import jwt
    claims=jwt.decode(assertion,f.cfg.private_key.public_key(),algorithms=['RS256'],audience=f.cfg.audience)
    assert claims['piq_client_id']==rows[0].piq_client_id and claims['rmr_tenant_id']==f.tenant_id
    if os.getenv('RMR_WORKSPACE_FIXTURE_URL'):
        from cryptography.hazmat.primitives import serialization
        public=f.cfg.private_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        with httpx.Client(trust_env=False) as client:
            stats=client.get(os.environ['RMR_WORKSPACE_FIXTURE_URL']+'/test/counts/'+f.tenant_id).json()
            session=client.post(os.environ['RMR_WORKSPACE_FIXTURE_URL']+'/test/federation',json={
                'assertion':assertion,'nonce':exchange.nonce,'public_key':public}).json()
        assert stats=={'workspaces':1,'clients':1}
        assert session['context']['piq_client_id']==rows[0].piq_client_id
        assert session['user']['bridge'] is True


def test_response_lost_after_piq_creation_is_recoverable(fresh):
    f=configured_fixture(fresh);transport,clients=remote(f,lose_first=True)
    with pytest.raises(HTTPException) as err:
        p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,transport)
    assert err.value.status_code==503
    assert p.mapping_for(f.db,f.tenant_id,f.cfg) is None
    result=p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,transport)
    assert f.db.get(Mapping,result['mapping_id']).piq_client_id==clients[f.tenant_id]


def test_existing_mapping_reused_without_network(fx):
    def forbidden(request):raise AssertionError('Existing mapping must not call PIQ')
    before=(fx.mapping.id,fx.mapping.piq_client_id,fx.mapping.mapping_version,fx.mapping.approved_by_user_id)
    result=p.provision(fx.db,fx.user,fx.a.id,fx.request,fx.cfg,httpx.MockTransport(forbidden))
    assert result['mapping_id']==before[0]
    assert (fx.mapping.id,fx.mapping.piq_client_id,fx.mapping.mapping_version,fx.mapping.approved_by_user_id)==before


@pytest.mark.parametrize('state',['pending','suspended'])
def test_nonactive_mapping_never_rebound(fx,state):
    fx.mapping.status=state;fx.db.commit()
    with pytest.raises(HTTPException) as err:p.provision(fx.db,fx.user,fx.a.id,fx.request,fx.cfg)
    assert err.value.status_code==409


@pytest.mark.parametrize('denial',['foreign_tenant','inactive','password','role','access_entitlement','enhancement_entitlement','origin','global_without_managed'])
def test_unauthorized_cannot_contact_piq(fresh,denial):
    f=fresh;tenant=f.tenant_id;request=f.request
    if denial=='foreign_tenant':tenant=f.b.id
    if denial=='inactive':f.user.active=False
    if denial=='password':f.user.must_change_password=True
    if denial=='role':f.user.tenant_role='MARKETING_USER'
    if denial=='global_without_managed':f.user.global_role='RMR_OWNER'
    if denial.endswith('_entitlement'):
        code='piq_access' if denial.startswith('access') else 'piq_enhancement'
        f.db.scalar(select(TenantService).where(TenantService.tenant_id==tenant,TenantService.service_code==code)).status='inactive'
    if denial=='origin':
        from starlette.requests import Request
        request=Request({'type':'http','headers':[]})
    f.db.commit()
    def forbidden(request):raise AssertionError('Unauthorized request reached PIQ')
    with pytest.raises(HTTPException) as err:p.provision(f.db,f.user,tenant,request,f.cfg,httpx.MockTransport(forbidden))
    assert err.value.status_code==403
    assert f.db.scalar(select(func.count()).select_from(Mapping))==0


def test_same_display_name_distinct_workspaces(fresh):
    f=configured_fixture(fresh);transport,_=remote(f)
    a=p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,transport)
    f.b.name=f.a.name;f.db.add(f.b);f.db.commit()
    other=User(tenant_id=f.b.id,tenant_role='CLIENT_ADMIN',email=str(uuid4())+'@example.invalid',full_name='Other',password_hash='unused')
    f.db.add(other)
    for code in ['piq_access','piq_enhancement']:f.db.add(TenantService(tenant_id=f.b.id,service_code=code,status='active'))
    f.db.commit()
    b=p.provision(f.db,other,f.b.id,f.request,f.cfg,transport)
    assert f.db.get(Mapping,a['mapping_id']).piq_client_id!=f.db.get(Mapping,b['mapping_id']).piq_client_id


def test_local_commit_failure_retries_same_remote_workspace(fresh,monkeypatch):
    f=configured_fixture(fresh);transport,clients=remote(f);original=p.audit
    def failed(*args,**kwargs):raise SQLAlchemyError('fixture commit boundary')
    monkeypatch.setattr(p,'audit',failed)
    with pytest.raises(HTTPException):p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,transport)
    assert p.mapping_for(f.db,f.tenant_id,f.cfg) is None
    first=clients[f.tenant_id];monkeypatch.setattr(p,'audit',original)
    result=p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,transport)
    assert f.db.get(Mapping,result['mapping_id']).piq_client_id==first


def test_client_already_bound_to_other_tenant_is_not_rebound(fresh,monkeypatch):
    f=fresh;client_id=str(uuid4())
    other=Mapping(tenant_id=f.b.id,piq_client_id=client_id,integration_instance_id=f.cfg.instance,status='active')
    f.db.add(other);f.db.commit()
    monkeypatch.setattr(p,'resolve_remote',lambda *args:client_id)
    with pytest.raises(HTTPException) as err:p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg)
    assert err.value.status_code==409
    assert p.mapping_for(f.db,f.tenant_id,f.cfg) is None
    assert f.db.get(Mapping,other.id).tenant_id==f.b.id


def test_authority_revoked_during_remote_call_prevents_mapping(fresh,monkeypatch):
    f=fresh
    def remote_revoke(*args):
        with Session(f.engine) as db:
            db.get(User,f.user_id).active=False;db.commit()
        return str(uuid4())
    monkeypatch.setattr(p,'resolve_remote',remote_revoke)
    with pytest.raises(HTTPException) as err:p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg)
    assert err.value.status_code==403 and p.mapping_for(f.db,f.tenant_id,f.cfg) is None


@pytest.mark.parametrize('field',['issuer','integration_instance_id','rmr_tenant_id'])
def test_wrong_remote_identity_never_persisted(fresh,field):
    f=fresh
    response={'version':'1','issuer':f.cfg.issuer,'integration_instance_id':f.cfg.instance,
              'rmr_tenant_id':f.tenant_id,'piq_client_id':str(uuid4())}
    response[field]=str(uuid4()) if field=='rmr_tenant_id' else 'wrong'
    with pytest.raises(HTTPException) as err:
        p.provision(f.db,f.user,f.tenant_id,f.request,f.cfg,httpx.MockTransport(lambda req:httpx.Response(200,json=response)))
    assert err.value.status_code==503 and p.mapping_for(f.db,f.tenant_id,f.cfg) is None


def test_unknown_revoked_mapping_status_fails_closed():
    from types import SimpleNamespace
    with pytest.raises(HTTPException) as err:p.ready(SimpleNamespace(status='revoked'))
    assert err.value.status_code==409  # Persisted schema uses suspended, not revoked.


def test_http_availability_read_only_provision_flag_and_contract(fresh,monkeypatch):
    from rmr_platform.prospectiq_bridge import routes
    f=fresh;app=FastAPI();app.include_router(router)
    def database():
        with Session(f.engine) as db:yield db
    app.dependency_overrides[get_db]=database
    client=TestClient(app,base_url=f.cfg.rmr_origin)
    body={'tenant_id':f.tenant_id};path='/api/integrations/prospectiq/v1'
    assert client.post(path+'/provision',json=body).status_code in (401,404)
    client.cookies.set(COOKIE_NAME,f.cookie)
    assert client.post(path+'/provision',json=body).status_code==404
    assert client.get(path+'/availability',params=body).json()=={'enabled':False}
    from types import SimpleNamespace
    monkeypatch.setattr(routes,'settings',SimpleNamespace(prospectiq_bridge_enabled=True))
    monkeypatch.setattr(routes,'bridge_config',lambda:f.cfg)
    app.dependency_overrides[bridge_config]=lambda:f.cfg
    available=client.get(path+'/availability',params=body)
    assert available.status_code==200 and available.json()['status']=='unprovisioned'
    assert f.db.scalar(select(func.count()).select_from(Mapping))==0
    assert client.post(path+'/provision',json=body).status_code==403
    headers={'Origin':f.cfg.rmr_origin,'X-RMR-Request':'1'}
    assert client.post(path+'/provision',headers=headers,json={**body,'piq_client_id':str(uuid4())}).status_code==422
    monkeypatch.setattr(p,'resolve_remote',lambda cfg,tenant,transport=None:str(uuid4()))
    result=client.post(path+'/provision',headers=headers,json=body)
    assert result.status_code==200 and set(result.json())=={'version','status','mapping_id'}
    assert result.headers['Cache-Control']=='no-store'
    assert client.get(path+'/availability',params=body).json()['status']=='ready'
