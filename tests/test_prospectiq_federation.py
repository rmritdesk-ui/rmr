"""Real RMR handlers/services; ephemeral keys and databases; no providers."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from starlette.requests import Request

from rmr_platform.db import Base, get_db
from rmr_platform.models import Tenant, User, TenantService, ServiceCatalog, utcnow
from rmr_platform.migrations import apply_prospectiq_federation_schema
from rmr_platform.security import COOKIE_NAME, create_token
from rmr_platform.unified_models import ManagedTenantSession
from rmr_platform.prospectiq_bridge import service as s, contracts as c
from rmr_platform.prospectiq_bridge.config import BridgeConfig, bridge_config
from rmr_platform.prospectiq_bridge.models import ProspectiqAuthorizationGrant as Grant, ProspectiqClientMapping as Mapping
from rmr_platform.prospectiq_bridge.routes import router


@pytest.fixture
def federation_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'federation.db'}", connect_args={"check_same_thread":False})
    yield engine
    engine.dispose()


@pytest.fixture
def fx(federation_engine):
    Base.metadata.create_all(federation_engine)
    apply_prospectiq_federation_schema(bind=federation_engine)
    apply_prospectiq_federation_schema(bind=federation_engine)
    db = Session(federation_engine, expire_on_commit=False)
    a,b = Tenant(name="Synthetic A",slug="federation-a"),Tenant(name="Synthetic B",slug="federation-b")
    db.add_all([a,b]); db.commit()
    user = User(tenant_id=a.id,tenant_role="CLIENT_ADMIN",email="federation@example.invalid",
                full_name="Synthetic User",password_hash="not-a-login-hash")
    db.add(user); db.commit()
    for code in ["piq_access","piq_enhancement"]:
        db.add(ServiceCatalog(code=code,name=code))
    db.commit()
    for code in ["piq_access","piq_enhancement"]:
        db.add(TenantService(tenant_id=a.id,service_code=code,status="active"))
    mapping = Mapping(tenant_id=a.id,piq_client_id=str(uuid4()),integration_instance_id="piq-test",status="active")
    db.add(mapping); db.commit()
    cfg = BridgeConfig("https://rmr.test","https://piq.test","https://piq.test/","piq-test",
                       "https://rmr.test","piq-test-audience","ephemeral",
                       rsa.generate_private_key(public_exponent=65537,key_size=2048),
                       "ephemeral-partner",secrets.token_hex(32),60)
    cookie = create_token(user)
    request = Request({"type":"http","method":"POST","path":"/",
        "headers":[(b"cookie",f"{COOKIE_NAME}={cookie}".encode()),(b"origin",b"https://rmr.test"),(b"x-rmr-request",b"1")]})
    f=SimpleNamespace(db=db,engine=federation_engine,user=user,a=a,b=b,mapping=mapping,cfg=cfg,cookie=cookie,request=request)
    yield f
    db.close()


def issue(f):
    launch=s.create_launch(f.db,f.user,c.LaunchRequest(mapping_id=f.mapping.id,destination="prospects"),f.request,f.cfg)
    verifier=secrets.token_urlsafe(32)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    payload=c.AuthorizeRequest(transaction_id=launch["transaction_id"],callback_id="piq-web",
                              state=secrets.token_urlsafe(32),nonce=secrets.token_urlsafe(32),
                              code_challenge=challenge,code_challenge_method="S256")
    auth=s.authorize_launch(f.db,f.user,payload,f.request,f.cfg)
    exchange=c.ExchangeRequest(integration_instance_id="piq-test",callback_id="piq-web",
                               code=auth["code"],code_verifier=verifier,binding_reference=launch["transaction_id"],
                               state=payload.state,nonce=payload.nonce)
    return launch,payload,auth,exchange


def test_real_http_launch_requires_auth_and_disabled_flag(fx):
    app=FastAPI(); app.include_router(router)
    def database():
        with Session(fx.engine) as db: yield db
    app.dependency_overrides[get_db]=database
    client=TestClient(app,base_url="https://rmr.test")
    assert client.post("/api/integrations/prospectiq/v1/launch",json={"mapping_id":fx.mapping.id,"destination":"prospects"}).status_code in (401,404)
    client.cookies.set(COOKIE_NAME,fx.cookie)
    assert client.post("/api/integrations/prospectiq/v1/launch",json={"mapping_id":fx.mapping.id,"destination":"prospects"}).status_code == 404
    app.dependency_overrides[bridge_config]=lambda:fx.cfg
    assert client.post("/api/integrations/prospectiq/v1/launch",json={"mapping_id":fx.mapping.id,"destination":"prospects"}).status_code == 403
    result=client.post("/api/integrations/prospectiq/v1/launch",headers={"Origin":"https://rmr.test","X-RMR-Request":"1"},
                       json={"mapping_id":fx.mapping.id,"destination":"prospects"})
    assert result.status_code == 200
    assert result.json()["launch_url"].startswith("https://piq.test/#rmr-start=")


@pytest.mark.parametrize("change",["missing","pending","suspended","tenant","inactive","entitlement"])
def test_launch_authorization_guards(fx,change):
    if change=="missing": pass
    elif change in ("pending","suspended"): fx.mapping.status=change
    elif change=="tenant": fx.user.tenant_id=fx.b.id
    elif change=="inactive": fx.user.active=False
    elif change=="entitlement":
        fx.db.scalar(select(TenantService).where(TenantService.service_code=="piq_access")).status="inactive"
    if change!="missing": fx.db.commit()
    with pytest.raises(HTTPException):
        s.create_launch(fx.db,fx.user,c.LaunchRequest(mapping_id=str(uuid4()) if change=="missing" else fx.mapping.id,destination="prospects"),fx.request,fx.cfg)


def test_global_managed_session_bound_and_rechecked(fx):
    fx.user.global_role="RMR_OWNER"
    managed=ManagedTenantSession(admin_user_id=fx.user.id,tenant_id=fx.a.id,reason="Synthetic",
                                 access_type="managed_write",status="active",expires_at=utcnow()+timedelta(minutes=2))
    fx.db.add(managed);fx.db.commit()
    fx.user._managed_session_id=managed.id
    launch,_,_,exchange=issue(fx)
    grant=fx.db.get(Grant,launch["transaction_id"])
    assert s.aware(grant.absolute_expires_at)<=s.aware(managed.expires_at)
    managed.status="ended";fx.db.commit()
    with pytest.raises(HTTPException): s.exchange_code(fx.db,exchange,fx.cfg)


def test_one_time_hash_pkce_assertion_and_logout(fx):
    launch,payload,auth,exchange=issue(fx)
    grant=fx.db.get(Grant,launch["transaction_id"])
    assert grant.code_hash==s.digest(auth["code"]) and grant.code_hash!=auth["code"]
    assert len(auth["code"])>=43 and s.aware(grant.code_expires_at)<=utcnow()+timedelta(seconds=60)
    assert "code=" in auth["callback_url"] and "token=" not in auth["callback_url"]
    with pytest.raises(HTTPException): s.authorize_launch(fx.db,fx.user,payload,fx.request,fx.cfg)
    result=s.exchange_code(fx.db,exchange,fx.cfg)
    claims=jwt.decode(result["assertion"],fx.cfg.private_key.public_key(),algorithms=["RS256"],audience=fx.cfg.audience,issuer=fx.cfg.issuer)
    assert claims["sub"]==fx.user.id and claims["rmr_tenant_id"]==fx.a.id
    assert claims["capabilities"]==grant.capabilities_json and claims["exp"]-claims["iat"]<=30
    with pytest.raises(HTTPException): s.exchange_code(fx.db,exchange,fx.cfg)
    s.revoke_browser_grants(fx.db,fx.user.id,fx.cookie);fx.db.commit()
    fx.db.expire_all()
    with pytest.raises(HTTPException): s.check_grant(fx.db,fx.db.get(Grant,grant.id),fx.cfg)


@pytest.mark.parametrize("change",["pkce","instance","callback","state","nonce","expired","revoked","mapping_version","suspended"])
def test_exchange_rejects_invalid_context(fx,change):
    launch,_,_,exchange=issue(fx)
    grant=fx.db.get(Grant,launch["transaction_id"])
    if change=="pkce": exchange=exchange.model_copy(update={"code_verifier":"z"*43})
    elif change=="instance": exchange=exchange.model_copy(update={"integration_instance_id":"wrong"})
    elif change=="callback": exchange=exchange.model_copy(update={"callback_id":"evil"})
    elif change in ("state","nonce"): exchange=exchange.model_copy(update={change:"z"*43})
    elif change=="expired": grant.code_expires_at=utcnow()-timedelta(seconds=1)
    elif change=="revoked": grant.revoked_at=utcnow()
    elif change=="mapping_version": fx.mapping.mapping_version=2
    elif change=="suspended": fx.mapping.status="suspended"
    fx.db.commit()
    with pytest.raises(HTTPException): s.exchange_code(fx.db,exchange,fx.cfg)


def test_launch_owner_and_browser_session_binding(fx):
    launch=s.create_launch(fx.db,fx.user,c.LaunchRequest(mapping_id=fx.mapping.id,destination="prospects"),fx.request,fx.cfg)
    other=User(tenant_id=fx.a.id,tenant_role="CLIENT_ADMIN",email="other@example.invalid",full_name="Other",password_hash="not-a-login-hash")
    fx.db.add(other);fx.db.commit()
    payload=c.AuthorizeRequest(transaction_id=launch["transaction_id"],callback_id="piq-web",state="s"*43,nonce="n"*43,
                               code_challenge="c"*43,code_challenge_method="S256")
    with pytest.raises(HTTPException): s.authorize_launch(fx.db,other,payload,fx.request,fx.cfg)
    wrong=Request({"type":"http","method":"POST","path":"/","headers":[(b"origin",b"https://rmr.test"),(b"x-rmr-request",b"1")]})
    with pytest.raises(HTTPException): s.authorize_launch(fx.db,fx.user,payload,wrong,fx.cfg)


def test_concurrent_exchange_exactly_one_winner(fx):
    _,_,_,payload=issue(fx)
    def consume(_):
        with Session(fx.engine) as db:
            try: return bool(s.exchange_code(db,payload,fx.cfg))
            except HTTPException: return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(consume,range(2)))==1


def test_partner_signature_binds_body_path_and_nonce(fx):
    body=b'{"synthetic":true}';path="/api/integrations/prospectiq/v1/exchange"
    stamp=str(int(time.time()));nonce=secrets.token_hex(32)
    headers={"X-Bridge-Instance":fx.cfg.instance,"X-Bridge-Key":fx.cfg.hmac_key_id,
             "X-Bridge-Timestamp":stamp,"X-Bridge-Nonce":nonce}
    canonical="\n".join([fx.cfg.instance,fx.cfg.hmac_key_id,"POST",path,stamp,nonce,hashlib.sha256(body).hexdigest()])
    headers["X-Bridge-Signature"]=hmac.new(fx.cfg.hmac_secret.encode(),canonical.encode(),hashlib.sha256).hexdigest()
    with pytest.raises(HTTPException): s.authenticate_service(fx.db,headers,b"changed","POST",path,fx.cfg)
    s.authenticate_service(fx.db,headers,body,"POST",path,fx.cfg)
    with pytest.raises(HTTPException): s.authenticate_service(fx.db,headers,body,"POST",path,fx.cfg)


def test_upgrade_from_phase0_preserves_existing_schema(federation_engine):
    from sqlalchemy import MetaData, inspect
    legacy=MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(legacy)
    old=legacy.tables[Grant.__tablename__]
    added={"browser_session_hash","state_hash","nonce_hash","authorized_at","absolute_expires_at","destination"}
    for name in added:
        old._columns.remove(old.c[name])
    legacy.create_all(federation_engine)
    assert not added & {column["name"] for column in inspect(federation_engine).get_columns(Grant.__tablename__)}
    apply_prospectiq_federation_schema(bind=federation_engine)
    apply_prospectiq_federation_schema(bind=federation_engine)
    assert added <= {column["name"] for column in inspect(federation_engine).get_columns(Grant.__tablename__)}
