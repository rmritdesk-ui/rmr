"""Signed real receiver tests; disposable SQLite/PG16, no providers."""
import copy
import hashlib
import hmac
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from test_prospectiq_federation import federation_engine, fx, issue
from rmr_platform.db import get_db
from rmr_platform.models import Lead, Account, Contact, Opportunity, AuditEvent, TenantService, utcnow
from rmr_platform.unified_models import ManagedTenantSession
from rmr_platform.prospectiq_bridge import crm, service
from rmr_platform.prospectiq_bridge.models import ProspectiqCrmReceipt as Receipt, ProspectiqCrmEvent as Event, ProspectiqClientMapping as Mapping, ProspectiqAuthorizationGrant as Grant
from rmr_platform.prospectiq_bridge.routes import router


def signed(cfg,body,**changes):
    stamp=str(int(time.time()));nonce=secrets.token_hex(32);key="crm-test"
    canonical="\n".join([crm.SERVICE,cfg.bridge.instance,key,"POST",crm.PATH,stamp,nonce,hashlib.sha256(body).hexdigest()])
    headers={"Content-Type":"application/json","X-Bridge-Service":crm.SERVICE,"X-Bridge-Instance":cfg.bridge.instance,
             "X-Bridge-Key":key,"X-Bridge-Timestamp":stamp,"X-Bridge-Nonce":nonce,
             "X-Bridge-Signature":hmac.new(cfg.keys[key].encode(),canonical.encode(),hashlib.sha256).hexdigest()}
    headers.update(changes)
    return headers


@pytest.fixture
def transfer(fx):
    launch,_,_,exchange=issue(fx);service.exchange_code(fx.db,exchange,fx.cfg)
    cfg=crm.CrmConfig(fx.cfg,{"crm-test":secrets.token_hex(32),"rotation":secrets.token_hex(32)})
    payload={"version":"1","integration_instance_id":fx.cfg.instance,"mapping_id":fx.mapping.id,
        "mapping_version":1,"piq_client_id":fx.mapping.piq_client_id,"prospect_public_id":str(uuid4()),
        "integration_event_id":str(uuid4()),"actor_grant_id":launch["transaction_id"],
        "prospect":{"company_name":"Synthetic PIQ Company","contact_name":"Named Contact",
          "email":"contact@example.invalid","phone":"+1 555 0100","website":"https://example.invalid/",
          "address":"Synthetic address","industry":"Synthetic industry","piq_score":35,"evidence":[],
          "email_provenance":[{"source_url":"https://example.invalid/contact","claim":"contact@example.invalid",
                               "provider":"website"}],
          "intelligence_snapshot":{"piq_scores":{"confidence_score":42,"fit_score":35},"unresolved":["industry"]}}}
    app=FastAPI();app.include_router(router)
    def database():
        with Session(fx.engine) as db: yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[crm.crm_config]=lambda:cfg
    client=TestClient(app,base_url="https://rmr.test")
    def call(data=None,headers=None):
        body=json.dumps(data or payload,separators=(",",":")).encode()
        return client.post(crm.PATH,content=body,headers=headers or signed(cfg,body))
    yield SimpleNamespace(f=fx,cfg=cfg,payload=payload,client=client,call=call)
    client.close()


def counts(t):
    with Session(t.f.engine) as db:
        return {model.__name__:db.scalar(select(func.count()).select_from(model))
                for model in [Lead,Receipt,Event,Account,Contact,Opportunity]}


def test_creation_mapping_provenance_audit_and_lost_response(transfer):
    t=transfer
    first=t.call();assert first.status_code==201,first.text
    result=first.json();assert result["status"]=="created"
    # The first response is deliberately treated as lost; retry has a fresh HTTP nonce.
    retry=t.call();assert retry.status_code==200,retry.text
    assert retry.json()["rmr_lead_id"]==result["rmr_lead_id"]
    assert retry.json()["status"]=="already_exists"
    assert result["crm_url"]==f"https://rmr.test/#/crm?tenant={t.f.a.id}&lead={result['rmr_lead_id']}"
    with Session(t.f.engine) as db:
        lead=db.get(Lead,result["rmr_lead_id"])
        assert (lead.tenant_id,lead.source,lead.status,lead.assigned_user_id)==(t.f.a.id,"ProspectIQ","New",t.f.user.id)
        assert lead.email=="contact@example.invalid" and "PIQ profile match score: 35" in lead.notes
        receipt=db.scalar(select(Receipt))
        assert receipt.provenance_json["import"]["prospect"]["intelligence_snapshot"]["piq_scores"]["confidence_score"]==42
        audit=list(db.scalars(select(AuditEvent).where(AuditEvent.event_type.like("prospectiq.crm.%"))))
        assert len(audit)==2 and all(x.actor_user_id==t.f.user.id for x in audit)
        assert all(x.event_data["integration_service"]=="ProspectIQ" and x.event_data["payload_hash"] for x in audit)
    assert counts(t)=={"Lead":1,"ProspectiqCrmReceipt":1,"ProspectiqCrmEvent":1,"Account":0,"Contact":0,"Opportunity":0}


@pytest.mark.parametrize("attack",["hmac","key","past","future","service","instance","altered","replay"])
def test_service_authentication(transfer,attack):
    t=transfer;body=json.dumps(t.payload,separators=(",",":")).encode();headers=signed(t.cfg,body)
    if attack=="hmac":headers["X-Bridge-Signature"]="0"*64
    if attack=="key":headers["X-Bridge-Key"]="unknown"
    if attack in ["past","future"]:headers["X-Bridge-Timestamp"]=str(int(time.time())+(-60 if attack=="past" else 60))
    if attack=="service":headers["X-Bridge-Service"]="piq"
    if attack=="instance":headers["X-Bridge-Instance"]="inactive-instance"
    if attack=="altered":body=body.replace(b"Synthetic PIQ Company",b"Altered Company")
    if attack=="replay":assert t.client.post(crm.PATH,content=body,headers=headers).status_code==201
    result=t.client.post(crm.PATH,content=body,headers=headers)
    assert result.status_code==(409 if attack=="replay" else 401),result.text
    assert counts(t)["Lead"]==(1 if attack=="replay" else 0)


@pytest.mark.parametrize("attack",["tenant_field","actor_field","client","mapping","version","grant",
    "suspended","mapping_version","inactive_actor","actor_tenant","capability","expired","revoked","entitlement","global_no_managed"])
def test_tenant_actor_and_payload_attacks(transfer,attack):
    t=transfer;f=t.f;data=copy.deepcopy(t.payload);g=f.db.get(Grant,data["actor_grant_id"])
    if attack=="tenant_field":data["rmr_tenant_id"]=f.b.id
    elif attack=="actor_field":data["actor_user_id"]=str(uuid4())
    elif attack=="client":data["piq_client_id"]=str(uuid4())
    elif attack=="mapping":data["mapping_id"]=str(uuid4())
    elif attack=="version":data["mapping_version"]=2
    elif attack=="grant":data["actor_grant_id"]=str(uuid4())
    elif attack=="suspended":f.mapping.status="suspended"
    elif attack=="mapping_version":f.mapping.mapping_version=2
    elif attack=="inactive_actor":f.user.active=False
    elif attack=="actor_tenant":f.user.tenant_id=f.b.id
    elif attack=="capability":g.capabilities_json=["prospects.read"]
    elif attack=="expired":g.absolute_expires_at=utcnow()-timedelta(seconds=1)
    elif attack=="revoked":g.revoked_at=utcnow()
    elif attack=="entitlement":f.db.scalar(select(TenantService).where(TenantService.service_code=="piq_access")).status="inactive"
    else:f.user.global_role="RMR_OWNER"
    f.db.commit()
    result=t.call(data)
    assert result.status_code in (403,422),result.text
    assert counts(t)["Lead"]==0


def test_valid_hmac_wrong_canonical_client_and_conflicting_identity(transfer):
    t=transfer;f=t.f
    assert t.call().status_code==201
    other=Mapping(tenant_id=f.b.id,piq_client_id=str(uuid4()),integration_instance_id=f.cfg.instance,status="active")
    f.db.add(other);f.db.commit()
    changed=copy.deepcopy(t.payload);changed.update(mapping_id=other.id,piq_client_id=other.piq_client_id)
    assert t.call(changed).status_code==403  # Valid service, but wrong grant/client.
    f.user.tenant_id=f.b.id;f.mapping=other;f.db.add(TenantService(tenant_id=f.b.id,service_code="piq_access",status="active"))
    f.db.add(TenantService(tenant_id=f.b.id,service_code="piq_enhancement",status="active"));f.db.commit()
    launch,_,_,exchange=issue(f);service.exchange_code(f.db,exchange,f.cfg)
    changed.update(actor_grant_id=launch["transaction_id"],integration_event_id=str(uuid4()))
    assert t.call(changed).status_code==409  # A new legitimate client cannot reuse the accepted public identity.
    assert counts(t)["Lead"]==1


@pytest.mark.parametrize("role",["CLIENT_ADMIN","VP_SALES","SALES_MANAGER","SALES_REP","MARKETING_USER","EXECUTIVE_VIEWER","RMR_OWNER","STEP2_ADMIN"])
def test_crm_role_policy(transfer,role):
    t=transfer;f=t.f
    if role in ["RMR_OWNER","STEP2_ADMIN"]:
        f.user.global_role=role
        managed=ManagedTenantSession(admin_user_id=f.user.id,tenant_id=f.a.id,reason="Synthetic CRM",
            access_type="managed_write",status="active",expires_at=utcnow()+timedelta(minutes=2))
        f.db.add(managed);f.db.flush();f.user._managed_session_id=managed.id
    else:f.user.tenant_role=role
    f.db.commit()
    launch,_,_,exchange=issue(f);service.exchange_code(f.db,exchange,f.cfg)
    data=copy.deepcopy(t.payload);data["actor_grant_id"]=launch["transaction_id"]
    assert t.call(data).status_code==(403 if role in ["MARKETING_USER","EXECUTIVE_VIEWER"] else 201)


def test_event_conflicts_and_tombstone(transfer):
    t=transfer
    first=t.call();assert first.status_code==201
    changed=copy.deepcopy(t.payload);changed["prospect"]["company_name"]="Changed body"
    assert t.call(changed).status_code==409
    changed=copy.deepcopy(t.payload);changed["prospect_public_id"]=str(uuid4())
    assert t.call(changed).status_code==409
    second=copy.deepcopy(t.payload);second["integration_event_id"]=str(uuid4())
    assert t.call(second).status_code==200
    second["prospect"]["phone"]="Changed"
    assert t.call(second).status_code==409
    with Session(t.f.engine) as db:
        db.delete(db.get(Lead,first.json()["rmr_lead_id"]));db.commit()
    assert t.call().status_code==410
    assert counts(t)["Lead"]==0 and counts(t)["ProspectiqCrmReceipt"]==1


@pytest.mark.parametrize("events",["same","distinct"])
def test_ten_equivalent_requests_converge(transfer,events):
    t=transfer
    def send(_):
        data=copy.deepcopy(t.payload)
        if events=="distinct":data["integration_event_id"]=str(uuid4())
        return t.call(data)
    # PG is authoritative: ten simultaneous real HTTP receiver requests.
    workers=10 if t.f.engine.dialect.name=="postgresql" else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:responses=list(pool.map(send,range(10)))
    assert all(r.status_code in (200,201) for r in responses),[(r.status_code,r.text) for r in responses]
    assert sum(r.status_code==201 for r in responses)==1
    assert len({r.json()["rmr_lead_id"] for r in responses})==1
    assert counts(t)["Lead"]==counts(t)["ProspectiqCrmReceipt"]==1


def test_email_without_provenance_rejected_and_missing_email_not_fabricated(transfer):
    t=transfer;data=copy.deepcopy(t.payload);data["prospect"]["email_provenance"]=[]
    assert t.call(data).status_code==422
    data["prospect"]["email"]=None
    assert t.call(data).status_code==201
    with Session(t.f.engine) as db:assert db.scalar(select(Lead)).email==""
