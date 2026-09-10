"""Phase 4 RMR authority, rotation, receipt recovery and maintenance; no providers."""
import copy, hashlib, hmac, json, secrets, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from test_prospectiq_federation import federation_engine, fx, issue
from test_prospectiq_crm import transfer, counts
from rmr_platform.models import utcnow,TenantService,Lead
from rmr_platform.unified_models import ManagedTenantSession
from rmr_platform.prospectiq_bridge import service as s, crm
from rmr_platform.prospectiq_bridge.models import ProspectiqAuthorizationGrant as Grant,ProspectiqClientMapping as Mapping,ProspectiqReplayNonce as Replay,ProspectiqCrmReceipt as Receipt
from rmr_platform.prospectiq_bridge.keys import verification_keys
from rmr_platform.prospectiq_bridge.operations import cleanup,lookup_receipt,readiness
from rmr_platform.prospectiq_bridge.contracts import ReceiptLookupRequest

def test_bounded_lifetime_downgrade_and_no_resurrection(fx):
    launch,_,_,exchange=issue(fx);s.exchange_code(fx.db,exchange,fx.cfg)
    grant=fx.db.get(Grant,launch["transaction_id"])
    assert s.aware(grant.absolute_expires_at)>utcnow()+timedelta(hours=7)
    fx.user.tenant_role="SALES_REP";fx.db.commit()
    s.check_grant(fx.db,grant,fx.cfg);fx.db.commit()
    assert "discovery.run" in grant.capabilities_json and "crm.move_to_rmr" in grant.capabilities_json
    assert "research.run" not in grant.capabilities_json
    fx.user.tenant_role="CLIENT_ADMIN";fx.db.commit();s.check_grant(fx.db,grant,fx.cfg)
    assert "research.run" not in grant.capabilities_json
    s.revoke_browser_grants(fx.db,fx.user.id,fx.cookie);fx.db.commit()
    with pytest.raises(HTTPException):s.check_grant(fx.db,grant,fx.cfg)

def test_two_existing_global_managed_tenants_independent(fx):
    fx.user.global_role="RMR_OWNER"
    other=Mapping(tenant_id=fx.b.id,piq_client_id=str(uuid4()),integration_instance_id=fx.cfg.instance,status="active")
    fx.db.add(other)
    for code in ["piq_access","piq_enhancement"]:fx.db.add(TenantService(tenant_id=fx.b.id,service_code=code,status="active"))
    a=ManagedTenantSession(admin_user_id=fx.user.id,tenant_id=fx.a.id,reason="Synthetic A",access_type="managed_write",status="active",expires_at=utcnow()+timedelta(hours=1))
    b=ManagedTenantSession(admin_user_id=fx.user.id,tenant_id=fx.b.id,reason="Synthetic B",access_type="managed_write",status="active",expires_at=utcnow()+timedelta(hours=1))
    fx.db.add_all([a,b]);fx.db.commit()
    fx.user._managed_session_id=a.id
    la,_,_,ea=issue(fx);s.exchange_code(fx.db,ea,fx.cfg)
    fx.mapping=other;fx.user._managed_session_id=b.id
    lb,_,_,eb=issue(fx);s.exchange_code(fx.db,eb,fx.cfg)
    a.status="ended";fx.db.commit()
    with pytest.raises(HTTPException):s.check_grant(fx.db,fx.db.get(Grant,la["transaction_id"]),fx.cfg)
    s.check_grant(fx.db,fx.db.get(Grant,lb["transaction_id"]),fx.cfg)

def lookup_input(t):
    return ReceiptLookupRequest(integration_instance_id=t.cfg.bridge.instance,mapping_id=t.f.mapping.id,
      mapping_version=1,piq_client_id=t.f.mapping.piq_client_id,actor_grant_id=t.payload["actor_grant_id"],
      integration_event_id=t.payload["integration_event_id"],
      payload_hash=crm.payload_hash(__import__("rmr_platform.prospectiq_bridge.contracts",fromlist=["CrmLeadRequest"]).CrmLeadRequest(**t.payload)))

def test_signed_receipt_lookup_and_expired_grant_reconciliation(transfer):
    t=transfer;created=t.call();assert created.status_code==201
    data=lookup_input(t)
    from urllib.parse import urlencode
    path="/api/integrations/prospectiq/v1/crm/handoffs/"+t.payload["prospect_public_id"]
    query=urlencode(data.model_dump(mode="json"));canonical_path=path+"?"+query
    stamp=str(int(time.time()));nonce=secrets.token_hex(32);key="crm-test"
    canonical="\n".join([crm.SERVICE,t.cfg.bridge.instance,key,"GET",canonical_path,stamp,nonce,hashlib.sha256(b"").hexdigest()])
    headers={"X-Bridge-Service":crm.SERVICE,"X-Bridge-Instance":t.cfg.bridge.instance,"X-Bridge-Key":key,
      "X-Bridge-Timestamp":stamp,"X-Bridge-Nonce":nonce,"X-Bridge-Signature":hmac.new(t.cfg.keys[key].encode(),canonical.encode(),hashlib.sha256).hexdigest()}
    g=t.f.db.get(Grant,t.payload["actor_grant_id"]);g.absolute_expires_at=utcnow()-timedelta(seconds=1);t.f.db.commit()
    r=t.client.get(canonical_path,headers=headers)
    assert r.status_code==200,r.text
    assert r.json()["status"]=="accepted" and r.json()["rmr_lead_id"]==created.json()["rmr_lead_id"]
    assert t.client.get(canonical_path,headers=headers).status_code==409
    assert counts(t)["Lead"]==1 and counts(t)["Opportunity"]==0

@pytest.mark.parametrize("kind",["absent","hash","event","mapping","client","grant","tombstone"])
def test_receipt_lookup_conflicts_and_no_creation(transfer,kind):
    t=transfer;data=lookup_input(t)
    if kind!="absent":assert t.call().status_code==201
    if kind in ["hash","event","mapping","client","grant"]:
        field={"hash":"payload_hash","event":"integration_event_id","mapping":"mapping_id","client":"piq_client_id","grant":"actor_grant_id"}[kind]
        data=data.model_copy(update={field:"0"*64 if kind=="hash" else str(uuid4())})
    with Session(t.f.engine) as db:
        if kind=="tombstone":
            receipt=db.scalar(select(Receipt));db.delete(db.get(Lead,receipt.lead_id));db.commit()
        if kind in ["mapping","client"]:
            with pytest.raises(HTTPException):lookup_receipt(db,t.payload["prospect_public_id"],data,t.cfg)
        else:
            r=lookup_receipt(db,t.payload["prospect_public_id"],data,t.cfg)
            assert r["status"]==("not_found" if kind=="absent" else "tombstoned" if kind=="tombstone" else "conflict")
    assert counts(t)["Lead"]==(0 if kind in ["absent","tombstone"] else 1)

def test_retention_preserves_receipt_identity(transfer):
    t=transfer;assert t.call().status_code==201
    g=t.f.db.get(Grant,t.payload["actor_grant_id"]);g.absolute_expires_at=utcnow()-timedelta(days=31)
    pending=Grant(user_id=t.f.user.id,tenant_id=t.f.a.id,mapping_id=t.f.mapping.id,mapping_version=1,
      integration_instance_id=t.cfg.bridge.instance,piq_client_id=t.f.mapping.piq_client_id,
      code_hash=secrets.token_hex(32),code_expires_at=utcnow()-timedelta(days=2),pkce_challenge="",binding_reference=str(uuid4()),authorization_checked_at=utcnow())
    t.f.db.add(pending)
    for n in t.f.db.scalars(select(Replay)):n.expires_at=utcnow()-timedelta(minutes=2);n.request_timestamp=utcnow()-timedelta(minutes=3)
    t.f.db.commit();result=cleanup(t.f.db)
    assert result["nonces_deleted"]>=1 and result["expired_pending_grants_deleted"]==1
    assert result["expired_grants_compacted"]==1 and counts(t)["ProspectiqCrmReceipt"]==1
    assert t.f.db.get(Grant,g.id).state_hash is None

def test_bounded_key_rotation_and_retirement():
    old,new=secrets.token_hex(32),secrets.token_hex(32);now=time.time()
    keys=verification_keys(json.dumps({"old":{"secret":old,"not_after":now+60}}),{"new":new})
    assert set(keys)=={"old","new"}
    retired=verification_keys(json.dumps({"old":{"secret":old,"not_after":now-1}}),{"new":new})
    assert set(retired)=={"new"}
    for raw in [{"a":old,"b":new},{"a":{"secret":old,"not_after":now+90000}},
                {"a":{"secret":old,"not_after":float("nan")}}]:
        with pytest.raises(ValueError):verification_keys(json.dumps(raw))
    with pytest.raises(ValueError):verification_keys(json.dumps({"a":old}),forbidden=[old])

def test_hmac_overlap_concurrent_and_retired_rejected(transfer):
    t=transfer;first=t.call();assert first.status_code==201
    def call(key):
        body=json.dumps(t.payload,separators=(",",":")).encode();stamp=str(int(time.time()));nonce=secrets.token_hex(32)
        value="\n".join([crm.SERVICE,t.cfg.bridge.instance,key,"POST",crm.PATH,stamp,nonce,hashlib.sha256(body).hexdigest()])
        headers={"X-Bridge-Service":crm.SERVICE,"X-Bridge-Instance":t.cfg.bridge.instance,"X-Bridge-Key":key,
          "X-Bridge-Timestamp":stamp,"X-Bridge-Nonce":nonce,"X-Bridge-Signature":hmac.new(t.cfg.keys.get(key,"retired").encode(),value.encode(),hashlib.sha256).hexdigest()}
        return t.client.post(crm.PATH,content=body,headers=headers)
    keys=["crm-test","rotation"]*5
    if t.f.engine.dialect.name=="postgresql":
        with ThreadPoolExecutor(max_workers=10) as executor:responses=list(executor.map(call,keys))
    else:responses=[call(key) for key in keys]
    assert all(r.status_code==200 for r in responses)
    t.cfg.keys.pop("crm-test")
    assert call("crm-test").status_code==401 and call("rotation").status_code==200
    assert counts(t)["Lead"]==1

def test_partner_hmac_overlap_rotation_and_retirement(fx):
    keys={"old":secrets.token_hex(32),"new":secrets.token_hex(32)}
    cfg=replace(fx.cfg,hmac_keys=keys)
    def headers(kid):
        stamp=str(int(time.time()));nonce=secrets.token_hex(32);path="/api/integrations/prospectiq/v1/grants/check"
        message="\n".join([cfg.instance,kid,"POST",path,stamp,nonce,hashlib.sha256(b"{}").hexdigest()])
        return {"X-Bridge-Timestamp":stamp,"X-Bridge-Nonce":nonce,"X-Bridge-Instance":cfg.instance,"X-Bridge-Key":kid,
            "X-Bridge-Signature":hmac.new(keys[kid].encode(),message.encode(),hashlib.sha256).hexdigest()}
    path="/api/integrations/prospectiq/v1/grants/check"
    for kid in ("old","new"):
        s.authenticate_service(fx.db,headers(kid),b"{}","POST",path,cfg)
        assert fx.db.info["bridge_key_id"]==kid
    old_headers=headers("old")
    retired=replace(cfg,hmac_keys={"new":keys["new"]})
    with pytest.raises(HTTPException) as error:s.authenticate_service(fx.db,old_headers,b"{}","POST",path,retired)
    assert error.value.status_code==401
    s.authenticate_service(fx.db,headers("new"),b"{}","POST",path,retired)

def test_enabled_startup_readiness_disabled_and_failure(fx,monkeypatch):
    from rmr_platform.prospectiq_bridge import operations as op
    from types import SimpleNamespace
    monkeypatch.setattr(op,"settings",SimpleNamespace(prospectiq_bridge_enabled=False))
    monkeypatch.setattr(op,"bridge_config",lambda:(_ for _ in ()).throw(ValueError("synthetic unsafe config")))
    op.validate_startup()
    assert op.readiness(fx.db)["status"]=="disabled"
    monkeypatch.setattr(op,"settings",SimpleNamespace(prospectiq_bridge_enabled=True))
    with pytest.raises(RuntimeError,match="unsafe or incomplete"):op.validate_startup()
    assert op.readiness(fx.db)["status"]=="not_ready"
    monkeypatch.setattr(op,"bridge_config",lambda:fx.cfg)
    monkeypatch.setattr(op,"crm_config",lambda:object())
    op.validate_startup();ready=op.readiness(fx.db)
    assert ready["status"]=="ready" and ready["federation_signing"] and ready["service_hmac"]
    from sqlalchemy import inspect
    indexes={i["name"] for i in inspect(fx.engine).get_indexes("prospectiq_authorization_grants")}
    assert "ix_prospectiq_authorization_grants_code_hash" in indexes or any("code" in name for name in indexes)
