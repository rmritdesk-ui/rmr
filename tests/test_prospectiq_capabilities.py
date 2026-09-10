"""Phase 2 capability snapshot and revocation policy; no providers."""
import jwt
import pytest
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from rmr_platform.models import TenantService, utcnow
from rmr_platform.unified_models import ManagedTenantSession
from rmr_platform.prospectiq_bridge import service as s
from rmr_platform.prospectiq_bridge.capabilities import READ, OPERATE, ADMIN
from rmr_platform.prospectiq_bridge.models import ProspectiqAuthorizationGrant as Grant
from test_prospectiq_federation import federation_engine, fx, issue


@pytest.mark.parametrize("role",["CLIENT_ADMIN","VP_SALES","SALES_MANAGER","SALES_REP","MARKETING_USER","EXECUTIVE_VIEWER"])
def test_tenant_role_capability_snapshot(fx,role):
    fx.user.tenant_role=role;fx.db.commit()
    launch,_,_,exchange=issue(fx)
    expected=READ + (OPERATE if role in {"CLIENT_ADMIN","VP_SALES","SALES_MANAGER","SALES_REP"} else []) + (ADMIN if role=="CLIENT_ADMIN" else [])
    grant=fx.db.get(Grant,launch["transaction_id"])
    assert grant.capabilities_json==expected
    result=s.exchange_code(fx.db,exchange,fx.cfg)
    claims=jwt.decode(result["assertion"],fx.cfg.private_key.public_key(),algorithms=["RS256"],audience=fx.cfg.audience,issuer=fx.cfg.issuer)
    assert claims["capabilities"]==expected
    assert "crm.transfer" not in claims["capabilities"]


@pytest.mark.parametrize("role",["RMR_OWNER","STEP2_ADMIN"])
@pytest.mark.parametrize("managed",[False,True])
def test_global_capabilities_require_tenant_managed_write_for_spend(fx,role,managed):
    fx.user.global_role=role
    if managed:
        session=ManagedTenantSession(admin_user_id=fx.user.id,tenant_id=fx.a.id,reason="Synthetic phase 2",
            access_type="managed_write",status="active",expires_at=utcnow()+timedelta(minutes=2))
        fx.db.add(session);fx.db.commit();fx.user._managed_session_id=session.id
    fx.db.commit()
    launch,_,_,exchange=issue(fx)
    grant=fx.db.get(Grant,launch["transaction_id"])
    assert grant.capabilities_json==(READ+OPERATE+ADMIN if managed else READ)
    s.exchange_code(fx.db,exchange,fx.cfg)
    if managed:
        session.status="ended";fx.db.commit()
        with pytest.raises(HTTPException):s.check_grant(fx.db,grant,fx.cfg)


@pytest.mark.parametrize("change",["role","user","entitlement","mapping","expired","revoked"])
def test_current_authority_loss_invalidates_existing_grant(fx,change):
    launch,_,_,exchange=issue(fx)
    s.exchange_code(fx.db,exchange,fx.cfg)
    grant=fx.db.get(Grant,launch["transaction_id"])
    if change=="role":fx.user.tenant_role="MARKETING_USER"
    elif change=="user":fx.user.active=False
    elif change=="entitlement":fx.db.scalar(select(TenantService).where(TenantService.service_code=="piq_access")).status="inactive"
    elif change=="mapping":fx.mapping.status="suspended"
    elif change=="expired":grant.absolute_expires_at=utcnow()-timedelta(seconds=1)
    else:grant.revoked_at=utcnow()
    fx.db.commit()
    with pytest.raises(HTTPException):s.check_grant(fx.db,grant,fx.cfg)


def test_role_upgrade_never_elevates_existing_snapshot(fx):
    fx.user.tenant_role="MARKETING_USER";fx.db.commit()
    launch,_,_,exchange=issue(fx)
    fx.user.tenant_role="CLIENT_ADMIN";fx.db.commit()
    s.exchange_code(fx.db,exchange,fx.cfg)
    grant=fx.db.get(Grant,launch["transaction_id"])
    s.check_grant(fx.db,grant,fx.cfg)
    assert s.context(grant).capabilities==READ
