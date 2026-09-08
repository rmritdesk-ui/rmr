"""Phase 4 integrity gate. Temporary SQLite only; provider network forbidden.

Known safety failures deliberately remain normal failing tests, never xfail.
HTTP tests use real cookie authentication and a fresh Session per request.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from rmr_platform.db import get_db
from rmr_platform.models import AuditEvent, Lead, PiqOpportunity, ServiceCatalog, TenantService, User
from rmr_platform.piq_models import PiqProfileMatch
from rmr_platform.piq_engine.discovery import persist_candidates
from rmr_platform.routes import crm, piq, unified
from rmr_platform.security import COOKIE_NAME, create_token
from rmr_platform.unified_models import ManagedTenantSession, PiqEvidence
from rmr_platform.utils import model_dict
from test_piq_phase1_discovery import (
    db, no_real_provider_network, seed_tenant, discovery_run, live_settings,
)
from test_piq_phase2_matching import result_for
from qa.piq_phase4_fixture import canonical_candidate, canonical_profile, browser_payload


def qualified(db, suffix):
    tenant, user, profile = seed_tenant(db, suffix)
    user.team_name = 'Phase 4 team'
    if not db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == 'piq_enhancement')):
        db.add(ServiceCatalog(code='piq_enhancement', name='Enhancement'))
    db.add(TenantService(tenant_id=tenant.id, service_code='piq_enhancement', status='active'))
    db.commit()
    run = discovery_run(db, tenant, user, profile, suffix)
    run.profile_snapshot_json = canonical_profile(profile.id)
    assert persist_candidates(db, run, result_for(run.profile_snapshot_json, [canonical_candidate()])) == (1, 0)
    run.status = 'completed'
    db.commit()
    opportunity = db.scalar(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant.id))
    return SimpleNamespace(tenant=tenant, user=user, profile=profile, run=run, opportunity=opportunity)


@pytest.fixture
def live(db):
    return qualified(db, 'phase4-live')


@pytest.fixture
def api(db, monkeypatch):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    def isolated_db():
        with factory() as session:
            yield session
    app = FastAPI()
    for router in (piq.router, unified.router, crm.router):
        app.include_router(router)
    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(unified, 'settings', live_settings())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def login(api, user, managed=None):
    api.cookies.set(COOKIE_NAME, create_token(user))
    api.headers['X-RMR-Request'] = '1'
    api.headers.pop('X-RMR-Managed-Session', None)
    if managed:
        api.headers['X-RMR-Managed-Session'] = managed


def move(api, live, **kwargs):
    return api.post(f'/api/piq/{live.opportunity.id}/move-to-crm', **kwargs)


def count(db, model=Lead, tenant=None):
    db.expire_all()
    query = select(func.count()).select_from(model)
    if tenant:
        query = query.where(model.tenant_id == tenant)
    return db.scalar(query)


def history(db, live):
    db.expire_all()
    row = model_dict(db.get(PiqOpportunity, live.opportunity.id))
    row.pop('moved_to_crm')
    return (
        row,
        [model_dict(x) for x in db.scalars(select(PiqEvidence).where(
            PiqEvidence.opportunity_id == live.opportunity.id).order_by(PiqEvidence.id))],
        [model_dict(x) for x in db.scalars(select(PiqProfileMatch).where(
            PiqProfileMatch.opportunity_id == live.opportunity.id).order_by(PiqProfileMatch.id))],
    )


def test_mapping_history_audit_and_sequential_idempotency(db, live, api):
    other = qualified(db, 'phase4-other')
    before, other_before = history(db, live), history(db, other)
    assert before[0]['provider'] == 'google_places'
    assert before[0]['estimated_value_cents'] == 0
    assert before[1] and len(before[2]) == 1
    browser_row, browser_evidence = browser_payload()
    for field in ('company_name', 'provider', 'source_external_id', 'source_url', 'phone', 'website',
                  'score', 'base_match_score', 'confidence_score', 'evidence_completeness_pct', 'evidence_count', 'signal'):
        assert before[0][field] == browser_row[field]
    assert sorted(row['fact'] for row in before[1]) == sorted(row['fact'] for row in browser_evidence)
    login(api, live.user)
    first = move(api, live)
    assert first.status_code == 200
    lead = first.json()['lead']
    opportunity = before[0]
    assert lead['tenant_id'] == live.tenant.id
    assert lead['company_name'] == opportunity['company_name']
    assert lead['source'] == 'ProspectIQ' and lead['status'] == 'New'
    assert lead['assigned_user_id'] == live.user.id
    assert lead['email'] == lead['contact_name'] == ''
    assert lead['phone'] == opportunity['phone']
    assert lead['notes'] == (f"Signal: {opportunity['signal']}. Score: {opportunity['score']}. "
                             f"Evidence items: {opportunity['evidence_count']}.")
    assert not {'revenue', 'revenue_cents', 'employees', 'employee_count', 'estimated_value_cents'} & lead.keys()
    assert count(db) == 1
    # Sequential replay, lost-response retry, and already-moved replay.
    for _ in range(3):
        response = move(api, live)
        assert response.status_code == 200 and response.json()['created'] is False
        assert count(db) == 1
    assert db.get(PiqOpportunity, live.opportunity.id).moved_to_crm
    assert history(db, live) == before and history(db, other) == other_before
    assert count(db, tenant=other.tenant.id) == 0
    rows = list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == 'piq.moved_to_crm')))
    assert len(rows) == 1
    audit = rows[0]
    assert (audit.actor_user_id, audit.tenant_id, audit.entity_type, audit.entity_id) == (
        live.user.id, live.tenant.id, 'piq_opportunity', live.opportunity.id)
    assert audit.event_data == {'lead_id': lead['id']} and audit.created_at is not None


@pytest.mark.parametrize('role,writes', [
    ('CLIENT_ADMIN', True), ('VP_SALES', True), ('SALES_MANAGER', True),
    ('SALES_REP', True), ('EXECUTIVE_VIEWER', False), ('MARKETING_USER', False),
])
def test_authenticated_client_role_matrix(db, live, api, role, writes):
    live.user.tenant_role = role
    db.commit()
    login(api, live.user)
    tid = live.tenant.id
    assert api.get(f'/api/tenants/{tid}/piq').status_code == 200
    assert api.get(f'/api/piq/{live.opportunity.id}/profile').status_code == 200
    assert api.post(f'/api/tenants/{tid}/piq/discover', json={'count': 1}).status_code == (202 if writes else 403)
    assert move(api, live).status_code == (200 if writes else 403)
    assert count(db) == int(writes)
    if not writes:
        # Populate through the authorized admin, then restore the reader role.
        live.user.tenant_role = 'CLIENT_ADMIN'; db.commit()
        assert move(api, live).status_code == 200
        live.user.tenant_role = role; db.commit()
    response = api.get(f'/api/tenants/{tid}/leads')
    assert response.status_code == 200 and len(response.json()['leads']) == 1


@pytest.mark.parametrize('mode', ['valid', 'read_only', 'wrong_tenant', 'expired', 'ended', 'missing', 'invalid', 'wrong_actor'])
@pytest.mark.parametrize('global_role', ['RMR_OWNER', 'STEP2_ADMIN'])
def test_managed_session_matrix(db, live, api, mode, global_role):
    other = qualified(db, 'phase4-managed-other')
    admin = User(email='phase4-global@example.test', password_hash='test', full_name='Global', global_role=global_role)
    db.add(admin); db.commit()
    managed = ManagedTenantSession(
        admin_user_id=other.user.id if mode == 'wrong_actor' else admin.id,
        tenant_id=other.tenant.id if mode == 'wrong_tenant' else live.tenant.id,
        reason='Phase 4 isolated verification', access_type='read_only' if mode == 'read_only' else 'managed_write',
        status='ended' if mode == 'ended' else 'active',
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=-1 if mode == 'expired' else 10),
    )
    db.add(managed); db.commit()
    login(api, admin, None if mode == 'missing' else 'invalid-session' if mode == 'invalid' else managed.id)
    tid = live.tenant.id
    # Global read access is intentional and does not require a managed session.
    assert api.get(f'/api/tenants/{tid}/piq').status_code == 200
    assert api.get(f'/api/tenants/{tid}/leads').status_code == 200
    assert api.post(f'/api/tenants/{tid}/piq/discover', json={'count': 1}).status_code == (202 if mode == 'valid' else 403)
    result = move(api, live)
    assert result.status_code == (200 if mode == 'valid' else 403)
    assert count(db, tenant=tid) == int(mode == 'valid')
    if mode == 'valid':
        assert len(api.get(f'/api/tenants/{tid}/leads').json()['leads']) == 1
        audit = db.scalar(select(AuditEvent).where(AuditEvent.event_type == 'piq.moved_to_crm'))
        assert audit.actor_user_id == admin.id and audit.tenant_id == tid
        # Characterize existing limitation: Move audit has lead_id, no session ID.
        assert audit.event_data == {'lead_id': result.json()['lead']['id']}
        assert move(api, other).status_code == 403
        managed.status = 'ended'; db.commit()
        assert move(api, live).status_code == 403
    assert count(db, tenant=other.tenant.id) == 0


def test_foreign_ids_forged_paths_and_bodies(db, live, api):
    other = qualified(db, 'phase4-isolation')
    login(api, live.user)
    a, b = live.tenant.id, other.tenant.id
    oid, rid = other.opportunity.id, other.run.id
    eid = db.scalar(select(PiqEvidence.id).where(PiqEvidence.opportunity_id == oid))
    for url, expected in [
        (f'/api/tenants/{b}/piq', 403), (f'/api/piq/{oid}/profile', 403),
        (f'/api/tenants/{b}/piq/discovery-runs/{rid}', 403),
        (f'/api/tenants/{a}/piq/discovery-runs/{rid}', 404),
        (f'/api/piq/{eid}/profile', 404),
    ]:
        assert api.get(url).status_code == expected
    # Evidence is accessible only through the opportunity profile; no evidence-ID API exists.
    own = api.get(f'/api/piq/{live.opportunity.id}/profile').json()
    assert eid not in {row['id'] for row in own['evidence']}
    assert move(api, other, json={'tenant_id': a, 'opportunity_id': live.opportunity.id}).status_code == 403
    assert api.post(f'/api/tenants/{a}/piq/{oid}/move-to-crm', json={'tenant_id': a}).status_code == 404
    assert api.post(f'/api/tenants/{b}/piq/discover', json={'count': 1, 'tenant_id': a}).status_code == 403
    assert count(db) == 0
    response = move(api, live, json={'tenant_id': b, 'company_name': 'Forged', 'email': 'fake@example.test'})
    assert response.status_code == 200
    assert response.json()['lead']['tenant_id'] == a and response.json()['lead']['email'] == ''
    assert count(db, tenant=b) == 0


@pytest.mark.parametrize('service', ['piq_access', 'piq_enhancement'])
def test_removed_entitlement_blocks_move_and_list(db, live, api, service):
    row = db.scalar(select(TenantService).where(TenantService.tenant_id == live.tenant.id, TenantService.service_code == service))
    row.status = 'inactive'; db.commit()
    login(api, live.user)
    assert move(api, live).status_code == 403
    assert api.get(f'/api/tenants/{live.tenant.id}/piq').status_code == 403
    if service == 'piq_access':
        assert api.post(f'/api/tenants/{live.tenant.id}/piq/discover', json={'count': 1}).status_code == 403
        assert api.get(f'/api/tenants/{live.tenant.id}/piq/discovery-runs/{live.run.id}').status_code == 403
    # PIQ detail now enforces the read entitlement; paid enhancement is separate.
    assert api.get(f'/api/piq/{live.opportunity.id}/profile').status_code == (403 if service == 'piq_access' else 200)
    assert count(db) == 0 and not db.get(PiqOpportunity, live.opportunity.id).moved_to_crm


@pytest.mark.parametrize('opportunity_id', ['missing', 'not-a-uuid', "' OR 1=1 --"])
def test_missing_and_malformed_opportunity_ids(db, live, api, opportunity_id):
    login(api, live.user)
    assert api.post(f'/api/piq/{opportunity_id}/move-to-crm').status_code == 404
    assert count(db) == 0


def test_authentication_and_origin_header_required(db, live, api):
    assert move(api, live).status_code == 401
    login(api, live.user); api.headers.pop('X-RMR-Request')
    assert move(api, live).status_code == 400
    assert count(db) == 0


@pytest.mark.parametrize('provider,status', [(None, 'Priority'), ('demonstration', 'Priority'), (None, 'Imported'), ('google_places', 'Priority')])
def test_legacy_demo_import_live_mapping(db, live, api, provider, status):
    if provider != 'google_places':
        # Historical rows genuinely lack the additive live provenance fields.
        live.opportunity = PiqOpportunity(tenant_id=live.tenant.id,
            company_name='Historical fixture', provider=provider, status=status,
            signal='Existing historical signal', score=60, evidence_count=0)
        db.add(live.opportunity); db.commit()
    before = history(db, live)
    login(api, live.user)
    assert move(api, live).status_code == 200
    assert move(api, live).json()['created'] is False
    assert count(db) == 1 and history(db, live) == before
    assert db.scalar(select(Lead)).source == 'ProspectIQ'


def test_actual_import_path_remains_movable(db, live, api):
    login(api, live.user)
    response = api.post(f'/api/tenants/{live.tenant.id}/piq/import', json={
        'filename': 'phase4-fixture.csv', 'rows': [{'company_name': 'Imported fixture', 'signal': 'User supplied', 'score': 62}]})
    assert response.status_code == 200 and response.json()['count'] == 1
    row = response.json()['created'][0]
    assert row['provider'] is None and row['status'] == 'Imported'
    live.opportunity = db.get(PiqOpportunity, row['id'])
    before = history(db, live)
    assert before[1][0]['evidence_type'] == 'client_import'
    assert move(api, live).json()['created'] is True
    assert move(api, live).json()['created'] is False
    assert count(db) == 1 and history(db, live) == before


def test_retry_after_committed_response_is_lost(db, live, api):
    from fastapi.responses import JSONResponse
    # ASGI middleware discards a successful response after the route commits.
    # No exception inside the route or counterfeit database result is used.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    def isolated_db():
        with factory() as session:
            yield session
    app = FastAPI(); app.include_router(piq.router)
    app.dependency_overrides[get_db] = isolated_db
    lose_next = True
    @app.middleware('http')
    async def drop_first_response(request, call_next):
        nonlocal lose_next
        response = await call_next(request)
        if lose_next:
            lose_next = False
            return JSONResponse({'detail': 'Simulated response lost after commit'}, status_code=503)
        return response
    with TestClient(app) as client:
        login(client, live.user)
        assert move(client, live).status_code == 503
        assert count(db) == 1
        assert move(client, live).json()['created'] is False
        assert count(db) == count(db, AuditEvent) == 1


@pytest.mark.parametrize('terminal', ['Closed Won', 'Closed Lost'])
def test_downstream_conversion_followup_pipeline_reporting(db, live, api, terminal):
    login(api, live.user)
    before = history(db, live)
    lead = move(api, live).json()['lead']
    tid = live.tenant.id
    # Existing activity schema has no lead_id; pre-conversion follow-up is a tenant note.
    note = api.post(f'/api/tenants/{tid}/activities', json={'activity_type': 'Call', 'subject': lead['company_name'], 'body': 'Fixture follow-up'})
    assert note.status_code == 200
    converted = api.post(f"/api/leads/{lead['id']}/convert").json()
    account, contact, opp = (converted[key] for key in ('account', 'contact', 'opportunity'))
    assert account['source'] == opp['source'] == 'ProspectIQ'
    assert account['annual_value_cents'] == opp['value_cents'] == 0
    assert contact['email'] == contact['first_name'] == contact['last_name'] == ''
    assert opp['stage'] == 'Qualified'
    assert db.get(Lead, lead['id']).status == 'Converted'
    followup = api.post(f'/api/tenants/{tid}/activities', json={'account_id': account['id'], 'opportunity_id': opp['id'], 'subject': 'Next conversation'})
    assert followup.status_code == 200
    assert len(api.get(f'/api/tenants/{tid}/activities').json()['activities']) == 2
    assert len(api.get(f"/api/accounts/{account['id']}/360").json()['activities']) == 1
    # Explicit test-user-entered CRM value, NOT a fabricated PIQ estimate.
    for stage in ('Discovery', 'Proposal', 'Negotiation'):
        response = api.patch(f"/api/opportunities/{opp['id']}", json={'stage': stage, 'value_cents': 120000, 'probability_pct': 50})
        assert response.status_code == 200 and response.json()['opportunity']['stage'] == stage
    summary = api.get(f'/api/tenants/{tid}/crm/summary').json()
    assert (summary['accounts'], summary['leads'], summary['opportunities'], summary['weighted_pipeline_cents']) == (1, 1, 1, 60000)
    report = api.get(f'/api/tenants/{tid}/growth-report').json()
    assert report['summary']['pipeline_cents'] == 120000
    assert report['funnel']['piq_to_crm'] == report['funnel']['open_opportunities'] == 1
    assert api.patch(f"/api/opportunities/{opp['id']}", json={'stage': terminal, 'loss_reason': 'Fixture only' if terminal == 'Closed Lost' else ''}).status_code == 200
    report = api.get(f'/api/tenants/{tid}/growth-report').json()
    won = terminal == 'Closed Won'
    assert report['won_revenue_cents'] == (120000 if won else 0)
    assert report['funnel']['won_opportunities'] == int(won)
    assert report['funnel']['open_opportunities'] == 0
    assert report['attribution'] == [{'source': 'ProspectIQ', 'opportunities': 1, 'won_revenue_cents': 120000 if won else 0}]
    assert api.get(f'/api/tenants/{tid}/crm/summary').json()['weighted_pipeline_cents'] == 0
    assert api.get(f'/api/tenants/{tid}/opportunities').json()['opportunities'][0]['stage'] == terminal
    assert count(db) == 1 and history(db, live) == before


@pytest.mark.parametrize('boundary', ['lead_insert', 'audit_call', 'audit_insert', 'before_commit'])
def test_failure_rolls_back_and_retry_creates_once(db, live, api, monkeypatch, boundary):
    login(api, live.user)
    before = history(db, live)
    def fail(*args, **kwargs):
        raise RuntimeError('Phase 4 injected persistence failure')
    target = None
    with monkeypatch.context() as patch:
        if boundary == 'audit_call':
            patch.setattr(piq, 'audit', fail)
        else:
            target, name = ((Lead, 'before_insert') if boundary == 'lead_insert' else
                            (AuditEvent, 'before_insert') if boundary == 'audit_insert' else (Session, 'before_commit'))
            event.listen(target, name, fail)
        try:
            assert move(api, live).status_code == 500
        finally:
            if target:
                event.remove(target, name, fail)
    assert count(db) == count(db, AuditEvent) == 0
    assert not db.get(PiqOpportunity, live.opportunity.id).moved_to_crm
    assert history(db, live) == before
    assert move(api, live).json()['created'] is True
    assert move(api, live).json()['created'] is False
    assert count(db) == count(db, AuditEvent) == 1


def concurrent_moves(db, live, monkeypatch, requests=2, failures=0):
    """All requests load moved=False before racing their real database claims.

    Phase 4's old barrier was at Lead flush. With a correct claim there is only
    ONE inserter, so waiting for two there would deadlock the test itself. Move
    the scheduler barrier to immediately after the unchanged entitlement check;
    keep real auth/SQL/commit and strengthen the original one-Lead invariant.
    """
    both_passed_guard = Barrier(requests)
    arrivals = []
    original_access = piq._require_piq_access
    oid, tenant_id = live.opportunity.id, live.tenant.id
    def synchronize(session, target_tenant):
        result = original_access(session, target_tenant)
        assert target_tenant == tenant_id
        assert session.get(PiqOpportunity, oid).moved_to_crm is False
        arrivals.append(target_tenant)
        both_passed_guard.wait(timeout=20)
        return result
    monkeypatch.setattr(piq, '_require_piq_access', synchronize)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    def isolated_db():
        with factory() as session:
            yield session
    app = FastAPI(); app.include_router(piq.router)
    app.dependency_overrides[get_db] = isolated_db
    token, oid = create_token(live.user), live.opportunity.id
    db.rollback()  # Release fixture reads before worker requests.
    def invoke():
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set(COOKIE_NAME, token)
            response = client.post(f'/api/piq/{oid}/move-to-crm', headers={'X-RMR-Request': '1'})
            return response.status_code, response.json() if response.status_code == 200 else {}
    with ThreadPoolExecutor(max_workers=requests) as pool:
        futures = [pool.submit(invoke) for _ in range(requests)]
        results = [future.result(timeout=40) for future in futures]
    assert len(arrivals) == requests
    assert sorted(status for status, _ in results) == [200] * (requests - failures) + [500] * failures, results
    return results


def test_concurrent_move_maximum_one_lead(db, live, monkeypatch):
    results = concurrent_moves(db, live, monkeypatch)
    leads, audits = count(db), count(db, AuditEvent)
    assert leads == 1, f'CONCURRENCY DEFECT CONFIRMED: {leads} Leads, {audits} audits; created={[body["created"] for _, body in results]}'
    assert audits == 1
    assert sorted(body['created'] for _, body in results) == [False, True]
    assert all(body['opportunity']['moved_to_crm'] is True for _, body in results)
    assert db.get(PiqOpportunity, live.opportunity.id).moved_to_crm is True
