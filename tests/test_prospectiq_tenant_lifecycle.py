"""Bridge lifecycle policy inherited from existing operational tenant statuses."""
import pytest
from fastapi import HTTPException
from test_prospectiq_federation import federation_engine, fx, issue
from rmr_platform.prospectiq_bridge import service, provisioning, profile_bootstrap, contracts

@pytest.mark.parametrize('status',['onboarding','private','live'])
def test_operational_states_work(fx,status):
    fx.a.status=status;fx.db.commit()
    _,_,_,exchange=issue(fx)
    assert service.exchange_code(fx.db,exchange,fx.cfg)['assertion']

@pytest.mark.parametrize('status',['inactive','disabled','suspended','archived','unknown',''])
def test_unavailable_tenant_denied_at_every_bridge_boundary(fx,status):
    launch,_,_,exchange=issue(fx)
    from rmr_platform.prospectiq_bridge.models import ProspectiqAuthorizationGrant as Grant
    grant=fx.db.get(Grant,launch['transaction_id'])
    fx.a.status=status;fx.db.commit()
    for call in [
        lambda: service.authorized_tenant(fx.db,fx.user,fx.a.id),
        lambda: service.create_launch(fx.db,fx.user,contracts.LaunchRequest(mapping_id=fx.mapping.id,destination='prospects'),fx.request,fx.cfg),
        lambda: provisioning.provision(fx.db,fx.user,fx.a.id,fx.request,fx.cfg),
        lambda: profile_bootstrap.ensure_bootstrap(fx.db,fx.user,fx.a.id,fx.request,fx.cfg),
        lambda: service.check_grant(fx.db,grant,fx.cfg),
        lambda: service.exchange_code(fx.db,exchange,fx.cfg),
    ]:
        with pytest.raises(HTTPException) as error:call()
        assert error.value.status_code==403
    fx.a.status='live';fx.db.commit()
    assert service.authorized(fx.db,fx.user,fx.mapping,fx.cfg) is None

def test_revoked_grant_does_not_revive_when_tenant_reenabled(fx):
    launch,_,_,exchange=issue(fx)
    from rmr_platform.prospectiq_bridge.models import ProspectiqAuthorizationGrant as Grant
    grant=fx.db.get(Grant,launch['transaction_id'])
    fx.a.status='inactive';grant.status='revoked';grant.revoked_at=service.utcnow();fx.db.commit()
    fx.a.status='live';fx.db.commit()
    with pytest.raises(HTTPException):service.exchange_code(fx.db,exchange,fx.cfg)
    assert issue(fx)[0]['transaction_id']!=launch['transaction_id']
