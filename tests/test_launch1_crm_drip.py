"""Launch 1 CRM editing and sender ownership; disposable DB, no delivery."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from test_prospectiq_federation import federation_engine, fx
from test_prospectiq_crm import transfer
from rmr_platform import cb1_models as m, cb1_router, cb1_worker, v53_experience
from rmr_platform import client_admin_corrections
from rmr_platform.cb1_services import sha, utcnow
from rmr_platform.db import get_db
from rmr_platform.models import Lead
from rmr_platform.routes import crm, unified
from rmr_platform.security import current_user


@pytest.fixture
def app_client(fx):
    app = FastAPI()
    # CB1 supports owner-managed setup. Exercise sender ownership even for that
    # privileged actor; CRM below still uses the ordinary CLIENT_ADMIN identity.
    def cb1_actor():
        return SimpleNamespace(id=fx.user.id, tenant_id=fx.a.id, global_role='RMR_OWNER', email=fx.user.email)
    for router in (crm.router, unified.router, v53_experience.router,
                   client_admin_corrections.router, cb1_router.build_router(cb1_actor)):
        app.include_router(router)
    def database():
        with Session(fx.engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[cb1_router.db_dep] = database
    app.dependency_overrides[current_user] = lambda: fx.user
    with TestClient(app, headers={'X-RMR-Request': '1'}) as client:
        yield client


def edit_and_reload(client, fx, lead_id):
    fields = dict(company_name='Edited Company', contact_name='Edited Contact',
                  email='edited@example.invalid', phone='+1 555 0123')
    response = client.patch(f'/api/v53/leads/{lead_id}', json={
        **fields, 'status': 'Qualified', 'notes': 'Updated note', 'assigned_user_id': fx.user.id})
    assert response.status_code == 200, response.text
    response = client.get(f'/api/v53/tenants/{fx.a.id}/crm/records/lead/{lead_id}')
    assert response.status_code == 200, response.text
    row = response.json()['record']
    for key, value in fields.items():
        assert row[key] == value
    with Session(fx.engine) as db:
        lead = db.get(Lead, lead_id)
        assert (lead.status, lead.notes, lead.assigned_user_id) == ('Qualified', 'Updated note', fx.user.id)


@pytest.mark.parametrize('entry', ['manual', 'import'])
def test_lead_entry_edit_reload(app_client, fx, entry):
    fields = dict(company_name='Original', contact_name='Original Contact', email='old@example.invalid')
    if entry == 'manual':
        result = app_client.post(f'/api/tenants/{fx.a.id}/leads', json=fields)
    else:
        result = app_client.post(f'/api/tenants/{fx.a.id}/crm/import', json={'rows': [fields]})
    assert result.status_code == 200, result.text
    with Session(fx.engine) as db:
        lead_id = db.query(Lead).one().id
    edit_and_reload(app_client, fx, lead_id)


def test_piq_lead_edit_keeps_idempotency(app_client, transfer):
    response = transfer.call()
    assert response.status_code == 201, response.text
    lead_id = response.json()['rmr_lead_id']
    edit_and_reload(app_client, transfer.f, lead_id)
    again = transfer.call()
    assert again.status_code == 200
    assert again.json()['rmr_lead_id'] == lead_id
    with Session(transfer.f.engine) as db:
        assert db.get(Lead, lead_id).company_name == 'Edited Company'
        assert db.query(Lead).count() == 1


@pytest.mark.parametrize('mode', ['foreign', 'read_only', 'marketing'])
def test_lead_edit_authorization(app_client, fx, mode):
    row = Lead(tenant_id=fx.b.id if mode == 'foreign' else fx.a.id, company_name='Unchanged')
    fx.db.add(row); fx.db.commit()
    if mode != 'foreign':
        fx.user.tenant_role = 'EXECUTIVE_VIEWER' if mode == 'read_only' else 'MARKETING_USER'
    response = app_client.patch(f'/api/v53/leads/{row.id}', json={'company_name': 'Forbidden'})
    assert response.status_code == 403
    fx.db.refresh(row)
    assert row.company_name == 'Unchanged'


def connection(fx, provider='SMTP', foreign=False):
    row = m.CB1ProviderConnection(tenant_id=fx.b.id if foreign else fx.a.id,
        provider=provider, sender_email='sender@example.invalid', physical_address='Test address',
        status='ACTIVE', created_by=fx.user.id)
    fx.db.add(row); fx.db.commit()
    return row


def scheduled(fx, conn):
    campaign = m.CB1Campaign(tenant_id=fx.a.id, name='Test', status='ACTIVE',
        provider_connection_id=conn.id if conn else None, created_by=fx.user.id)
    fx.db.add(campaign); fx.db.flush()
    message = m.CB1Message(tenant_id=fx.a.id, campaign_id=campaign.id,
        recipient_email='recipient@example.invalid', subject='Test', body_draft='Hello',
        body_approved='Hello', approved_hash=sha('Hello'), status='APPROVED',
        idempotency_key=str(uuid4()), created_by=fx.user.id)
    fx.db.add(message); fx.db.flush()
    job = m.CB1DripJob(tenant_id=fx.a.id, campaign_id=campaign.id, message_id=message.id,
        status='QUEUED', due_at=utcnow()-timedelta(minutes=1))
    fx.db.add(job); fx.db.commit()
    return campaign, message, job


@pytest.mark.parametrize('provider', ['SMTP', 'GMAIL', 'MICROSOFT'])
def test_same_tenant_create_schedule_send(app_client, fx, monkeypatch, provider):
    conn = connection(fx, provider)
    response = app_client.post(f'/api/cb1/tenants/{fx.a.id}/campaigns',
        json={'name': 'Test', 'provider_connection_id': conn.id})
    assert response.status_code == 200, response.text
    campaign, message, job = scheduled(fx, conn)
    fx.db.delete(job); fx.db.commit()
    response = app_client.post(f'/api/cb1/messages/{message.id}/schedule',
        json={'scheduled_at': (utcnow()-timedelta(seconds=1)).isoformat()})
    assert response.status_code == 200, response.text
    calls = []
    monkeypatch.setattr(cb1_worker, 'SessionLocal', lambda: Session(fx.engine))
    monkeypatch.setattr(cb1_worker, '_send', lambda c, m: calls.append(c.id) or 'mock-delivery')
    cb1_worker.tick()
    assert calls == [conn.id]
    fx.db.refresh(message)
    assert message.status == 'SENT'


@pytest.mark.parametrize('kind', ['foreign', 'missing', 'deleted'])
def test_invalid_sender_rejected_create_schedule_worker(app_client, fx, monkeypatch, kind):
    conn = None if kind == 'missing' else connection(fx, foreign=kind == 'foreign')
    campaign, message, job = scheduled(fx, conn)
    conn_id = conn.id if conn else None
    if kind == 'deleted':
        fx.db.delete(conn); fx.db.commit()
    response = app_client.post(f'/api/cb1/tenants/{fx.a.id}/campaigns',
        json={'name': 'Rejected', 'provider_connection_id': conn_id})
    assert response.status_code == 400, response.text
    response = app_client.post(f'/api/cb1/messages/{message.id}/schedule',
        json={'scheduled_at': utcnow().isoformat()})
    assert response.status_code == 400, response.text
    monkeypatch.setattr(cb1_worker, 'SessionLocal', lambda: Session(fx.engine))
    monkeypatch.setattr(cb1_worker, '_send', lambda *a: pytest.fail('Must not send'))
    cb1_worker.tick()
    fx.db.refresh(job); fx.db.refresh(message)
    assert job.status == 'FAILED'
    assert message.sent_at is None


@pytest.mark.parametrize('mismatch', ['campaign', 'message', 'job', 'message_campaign'])
def test_worker_rechecks_all_tenant_links(fx, monkeypatch, mismatch):
    campaign, message, job = scheduled(fx, connection(fx))
    if mismatch == 'message_campaign': message.campaign_id = 'different-campaign'
    else: setattr({'campaign': campaign, 'message': message, 'job': job}[mismatch], 'tenant_id', fx.b.id)
    fx.db.commit()
    monkeypatch.setattr(cb1_worker, 'SessionLocal', lambda: Session(fx.engine))
    monkeypatch.setattr(cb1_worker, '_send', lambda *a: pytest.fail('Must not send'))
    cb1_worker.tick(); fx.db.refresh(job)
    assert job.status == 'FAILED'


@pytest.mark.parametrize('case', ['suppression', 'frequency', 'retry', 'final_failure', 'inactive'])
def test_worker_existing_controls_persist(fx, monkeypatch, case):
    conn = connection(fx)
    campaign, message, job = scheduled(fx, conn)
    if case == 'suppression':
        fx.db.add(m.CB1Suppression(tenant_id=fx.a.id, email=message.recipient_email, reason='unsubscribed'))
    if case == 'frequency':
        fx.db.add(m.CB1Message(tenant_id=fx.a.id, recipient_email=message.recipient_email,
            subject='Earlier', body_draft='Earlier', status='SENT', sent_at=utcnow(),
            idempotency_key=str(uuid4()), created_by=fx.user.id))
    if case == 'final_failure': job.attempts = 4
    if case == 'inactive': conn.status = 'DISCONNECTED'
    fx.db.commit()
    monkeypatch.setattr(cb1_worker, 'SessionLocal', lambda: Session(fx.engine))
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError('Synthetic delivery failure')
    monkeypatch.setattr(cb1_worker, '_send', fail)
    cb1_worker.tick(); fx.db.refresh(job); fx.db.refresh(message)
    assert job.status == ('STOPPED' if case == 'suppression' else 'FAILED' if case == 'final_failure' else 'QUEUED')
    assert len(calls) == (1 if case in {'retry', 'final_failure'} else 0)
    if case == 'suppression': assert message.status == 'SUPPRESSED'
    if case in {'frequency', 'retry', 'inactive'}: assert job.due_at.replace(tzinfo=None) > utcnow().replace(tzinfo=None)


def test_one_to_one_flow_unchanged(app_client, fx, monkeypatch):
    conn = connection(fx)
    calls = []
    monkeypatch.setattr(client_admin_corrections, '_send_smtp', lambda c, p: calls.append(c.id) or 'mock-delivery')
    payload = dict(connection_id=conn.id, recipient_email='recipient@example.invalid', subject='Hello', body='Test')
    response = app_client.post(f'/api/v521/tenants/{fx.a.id}/one-to-one-email', json=payload)
    assert response.status_code == 200, response.text
    payload['connection_id'] = connection(fx, foreign=True).id
    response = app_client.post(f'/api/v521/tenants/{fx.a.id}/one-to-one-email', json=payload)
    assert response.status_code == 404
    assert calls == [conn.id]
