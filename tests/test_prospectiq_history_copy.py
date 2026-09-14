"""Explicit copy security; isolated source data and offline signed transport."""
import json
from uuid import uuid4
import httpx
import pytest
from fastapi import HTTPException,FastAPI
from fastapi.testclient import TestClient
from test_prospectiq_federation import federation_engine,fx
from rmr_platform.unified_models import PiqTargetProfile
from rmr_platform.prospectiq_bridge import history_copy as h
from rmr_platform.prospectiq_bridge.profile_bootstrap import record
from rmr_platform.prospectiq_bridge.routes import router
from rmr_platform.prospectiq_bridge.config import bridge_config
from rmr_platform.security import current_user
from rmr_platform.db import get_db

def source(f):
    p=PiqTargetProfile(tenant_id=f.a.id,name='Historical source',active=False,
      industries_json=['Mortgage','Title & Escrow'],locations_json=['Phoenix, Arizona','Northern Colorado'])
    f.db.add(p);f.db.commit();f.db.refresh(p);return p

def test_explicit_copy_derives_binding_preserves_source_and_request_id(fx):
    p=source(fx);before=record(p).copy();request=h.HistoryCopyRequest(source_profile_id=p.id,request_id=uuid4());calls=[];new=str(uuid4())
    def send(req):
        data=json.loads(req.content);calls.append(data)
        assert str(req.url)==fx.cfg.piq_origin+h.COPY_PATH
        assert req.headers['X-Bridge-Signature']
        assert data['actor_user_id']==fx.user.id and data['piq_client_id']==fx.mapping.piq_client_id
        assert data['export']['profiles'][0]['industries_json']==['Mortgage','Title & Escrow']
        if len(calls)==1:raise httpx.ReadTimeout('private')
        return httpx.Response(200,json={'version':'1','request_id':str(request.request_id),'mapping_id':fx.mapping.id,'piq_client_id':fx.mapping.piq_client_id,'profile_id':new,'status':'draft'})
    with pytest.raises(HTTPException):h.copy_history(fx.db,fx.user,request,fx.request,fx.cfg,httpx.MockTransport(send))
    result=h.copy_history(fx.db,fx.user,request,fx.request,fx.cfg,httpx.MockTransport(send))
    assert result['profile_id']==new and calls[0]==calls[1]
    fx.db.refresh(p);assert record(p)==before

@pytest.mark.parametrize('change',['foreign','inactive_user','inactive_tenant','suspended','role','entitlement','origin'])
def test_copy_denied_before_partner_request(fx,change):
    p=source(fx)
    if change=='foreign':p.tenant_id=fx.b.id
    elif change=='inactive_user':fx.user.active=False
    elif change=='inactive_tenant':fx.a.status='inactive'
    elif change=='suspended':fx.mapping.status='suspended'
    elif change=='role':fx.user.tenant_role='EXECUTIVE_VIEWER'
    elif change=='entitlement':
        from sqlalchemy import select
        from rmr_platform.models import TenantService
        for row in fx.db.scalars(select(TenantService)):row.status='inactive'
    elif change=='origin':
        from starlette.requests import Request
        fx.request=Request({'type':'http','headers':[(b'origin',b'https://foreign.test')]})
    fx.db.commit()
    def forbidden(req):pytest.fail('Unauthorized signed request')
    with pytest.raises(HTTPException):h.copy_history(fx.db,fx.user,h.HistoryCopyRequest(source_profile_id=p.id,request_id=uuid4()),fx.request,fx.cfg,httpx.MockTransport(forbidden))

def test_http_contract_rejects_browser_destination_tenant_and_payload(fx):
    p=source(fx);app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_db]=lambda:fx.db
    app.dependency_overrides[current_user]=lambda:fx.user
    app.dependency_overrides[bridge_config]=lambda:fx.cfg
    client=TestClient(app,base_url='https://rmr.test')
    data={'source_profile_id':p.id,'request_id':str(uuid4())}
    for extra in ['piq_client_id','tenant_id','export','actor_user_id']:
        assert client.post('/api/integrations/prospectiq/v1/profiles/history-copy',json={**data,extra:'untrusted'}).status_code==422
