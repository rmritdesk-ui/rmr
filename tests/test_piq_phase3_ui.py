from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from rmr_platform.db import get_db
from rmr_platform.models import Lead, PiqOpportunity, ServiceCatalog, TenantService
from rmr_platform.security import current_user
from rmr_platform.routes import unified
from rmr_platform.routes.piq import move_piq_to_crm, list_piq
from rmr_platform.piq_engine.discovery import persist_candidates
from rmr_platform.unified_services import cross_channel_report
from test_piq_phase1_discovery import db, no_real_provider_network, seed_tenant, discovery_run, request
from test_piq_phase2_matching import strong, result_for


@pytest.mark.parametrize('status', ['queued','running','retry_wait','completed','partial','failed','cancelled'])
def test_active_run_returns_only_nonterminal_google_run(db, status):
    tenant,user,profile=seed_tenant(db,'phase3-active')
    run=discovery_run(db,tenant,user,profile,'active')
    run.status=status
    db.commit()
    result=unified.active_discovery_run(tenant.id,user,db)['run']
    assert bool(result) == (status in {'queued','running','retry_wait'})
    if result:
        assert result['run_id']==run.id and result['status']==status
        assert 'profile_snapshot_json' not in result


def test_active_run_is_tenant_safe_recent_and_entitled(db):
    a,user_a,profile_a=seed_tenant(db,'phase3-a')
    b,user_b,profile_b=seed_tenant(db,'phase3-b')
    first=discovery_run(db,a,user_a,profile_a,'first')
    second=discovery_run(db,a,user_a,profile_a,'second')
    second.created_at=first.created_at+timedelta(seconds=1)
    other=discovery_run(db,b,user_b,profile_b,'other')
    db.commit()
    assert unified.active_discovery_run(a.id,user_a,db)['run']['run_id']==second.id
    assert unified.active_discovery_run(b.id,user_b,db)['run']['run_id']==other.id
    with pytest.raises(HTTPException) as denied:
        unified.active_discovery_run(a.id,user_b,db)
    assert denied.value.status_code==403
    service=db.scalar(select(TenantService).where(TenantService.tenant_id==a.id))
    service.status='inactive';db.commit()
    with pytest.raises(HTTPException) as denied:
        unified.active_discovery_run(a.id,user_a,db)
    assert denied.value.status_code==403


def test_active_literal_route_precedes_run_id_route(db):
    tenant,user,profile=seed_tenant(db,'phase3-http')
    run=discovery_run(db,tenant,user,profile,'http')
    app=FastAPI();app.include_router(unified.router)
    app.dependency_overrides[current_user]=lambda:user
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app) as client:
        response=client.get(f'/api/tenants/{tenant.id}/piq/discovery-runs/active')
    assert response.status_code==200 and response.json()['run']['run_id']==run.id


def test_qualified_google_opportunity_moves_once_without_fabricated_data(db):
    tenant,user,profile=seed_tenant(db,'phase3-crm')
    db.add(ServiceCatalog(code='piq_enhancement',name='Enhancement'))
    db.add(TenantService(tenant_id=tenant.id,service_code='piq_enhancement',status='active'))
    db.commit()
    run=discovery_run(db,tenant,user,profile,'crm')
    assert persist_candidates(db,run,result_for(run.profile_snapshot_json,[strong()]))==(1,0)
    db.commit()
    opportunity=db.scalar(select(PiqOpportunity).where(PiqOpportunity.tenant_id==tenant.id))
    before=(opportunity.score,opportunity.confidence_score,opportunity.evidence_completeness_pct)
    first=move_piq_to_crm(opportunity.id,request('POST'),user,db)
    second=move_piq_to_crm(opportunity.id,request('POST'),user,db)
    leads=list(db.scalars(select(Lead).where(Lead.tenant_id==tenant.id)))
    assert first['created'] is True and second['created'] is False and len(leads)==1
    assert leads[0].source=='ProspectIQ' and leads[0].email=='' and leads[0].contact_name==''
    assert opportunity.estimated_value_cents==0
    assert (opportunity.score,opportunity.confidence_score,opportunity.evidence_completeness_pct)==before
    assert list_piq(tenant.id,user,db)['opportunities'][0]['provider']=='google_places'
    assert 'revenue' not in first['lead'] and 'employee_count' not in first['lead']
    report=cross_channel_report(db,tenant.id)
    assert report['funnel']['piq_to_crm']==1
