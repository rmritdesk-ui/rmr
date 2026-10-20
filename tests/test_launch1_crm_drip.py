"""Launch 1 CRM editing and sender ownership; disposable DB, no delivery."""
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from test_prospectiq_federation import federation_engine, fx
from test_prospectiq_crm import transfer
from rmr_platform import cb1_models as m, cb1_router, cb1_worker, v53_experience
from rmr_platform import client_admin_corrections, v531_final_corrections
from rmr_platform.cb1_services import sha, utcnow
from rmr_platform.db import get_db
from rmr_platform.migrations import apply_crm_prospect_outcome_restore_schema
from rmr_platform.models import Account, Activity, CrmProspect, Lead, Opportunity
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
                   v531_final_corrections.router,
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


def test_prospect_activity_is_visible_after_opportunity_conversion(app_client, fx):
    created = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Activity Carryover Co', 'contact_name': 'Casey Example',
        'email': 'casey@example.invalid'})
    assert created.status_code == 200, created.text
    lead_id = created.json()['lead']['id']
    converted = app_client.post(f'/api/leads/{lead_id}/convert-to-prospect')
    assert converted.status_code == 200, converted.text
    prospect = converted.json()['prospect']
    account_id = converted.json()['account']['id']

    activity = app_client.post(f'/api/tenants/{fx.a.id}/activities', json={
        'account_id': account_id, 'activity_type': 'Call',
        'subject': 'Prospect discovery call', 'body': 'Discussed timeline.'})
    assert activity.status_code == 200, activity.text

    opportunity = app_client.post(
        f'/api/prospects/{prospect["id"]}/convert-to-opportunity', json={
            'name': 'Activity Carryover Co opportunity'})
    assert opportunity.status_code == 200, opportunity.text
    opportunity_id = opportunity.json()['opportunity']['id']
    detail = app_client.get(
        f'/api/v53/tenants/{fx.a.id}/crm/records/opportunity/{opportunity_id}')
    assert detail.status_code == 200, detail.text
    assert any(row['subject'] == 'Prospect discovery call'
               for row in detail.json()['activities'])


def test_my_work_combines_open_activities_and_prospect_followups(app_client, fx):
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'MyWork Co', 'contact_name': 'Morgan Example',
        'email': 'morgan@example.invalid'})
    assert lead.status_code == 200, lead.text
    converted = app_client.post(f'/api/leads/{lead.json()["lead"]["id"]}/convert-to-prospect')
    assert converted.status_code == 200, converted.text
    prospect_id = converted.json()['prospect']['id']
    account_id = converted.json()['account']['id']
    now = utcnow()
    with Session(fx.engine) as db:
        prospect = db.get(CrmProspect, prospect_id)
        prospect.follow_up_date = date.today()
        due_activity = Activity(
            tenant_id=fx.a.id, account_id=account_id, user_id=fx.user.id,
            activity_type='Task', subject='Prepare discovery agenda',
            due_at=now + timedelta(hours=1),
        )
        db.add(due_activity)
        db.add(Activity(
            tenant_id=fx.a.id, account_id=account_id, user_id=fx.user.id,
            activity_type='Task', subject='Completed task', due_at=now - timedelta(days=1),
            completed_at=now,
        ))
        db.commit()
        due_activity_id = due_activity.id

    response = app_client.get(f'/api/tenants/{fx.a.id}/crm/my-work')
    assert response.status_code == 200, response.text
    result = response.json()
    assert [row['subject'] for row in result['activities']] == ['Prepare discovery agenda']
    assert [row['id'] for row in result['prospects']] == [prospect_id]
    assert result['activities'][0]['account_name'] == 'MyWork Co'
    assert result['activities'][0]['due_at'].endswith('+00:00')
    completed = app_client.patch(f'/api/activities/{due_activity_id}/complete', json={})
    assert completed.status_code == 200, completed.text
    assert completed.json()['activity']['completed_at']
    repeated = app_client.patch(f'/api/activities/{due_activity_id}/complete', json={})
    assert repeated.status_code == 200, repeated.text
    refreshed = app_client.get(f'/api/tenants/{fx.a.id}/crm/my-work')
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()['activities'] == []
    assert [row['id'] for row in refreshed.json()['prospects']] == [prospect_id]
    overview = app_client.get(f'/api/v53/tenants/{fx.a.id}/crm/overview')
    assert overview.status_code == 200, overview.text
    activity_row = next(row for row in overview.json()['activities']
                        if row['subject'] == 'Prepare discovery agenda')
    assert activity_row['created_at'].endswith('+00:00')
    assert result['prospects'][0]['follow_up_date'] == date.today().isoformat()


def test_prospect_conversion_reuses_same_tenant_account(app_client, fx):
    created_account = app_client.post(f'/api/tenants/{fx.a.id}/accounts', json={
        'name': 'Acme Widgets', 'status': 'Active', 'annual_value_cents': 2500})
    assert created_account.status_code == 200, created_account.text
    existing_account = created_account.json()['account']

    created_lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'acme widgets', 'contact_name': 'Jordan Example',
        'email': 'jordan@example.invalid'})
    assert created_lead.status_code == 200, created_lead.text
    converted = app_client.post(
        f'/api/v53/leads/{created_lead.json()["lead"]["id"]}/convert-to-prospect',
        json={'account_name': ' Acme   Widgets '})
    assert converted.status_code == 200, converted.text
    assert converted.json()['account']['id'] == existing_account['id']
    assert converted.json()['account']['status'] == 'Active'
    prospect_id = converted.json()['prospect']['id']
    opportunity = app_client.post(
        f'/api/prospects/{prospect_id}/convert-to-opportunity', json={
            'name': 'Acme Widgets opportunity'})
    assert opportunity.status_code == 200, opportunity.text
    closed = app_client.patch(
        f'/api/opportunities/{opportunity.json()["opportunity"]["id"]}',
        json={'stage': 'Closed Won'})
    assert closed.status_code == 200, closed.text
    with Session(fx.engine) as db:
        assert db.query(Account).filter_by(tenant_id=fx.a.id).count() == 1
        assert db.get(Account, existing_account['id']).customer_since == date.today()


def test_direct_opportunity_creation_remains_supported(app_client, fx):
    response = app_client.post(f'/api/tenants/{fx.a.id}/opportunities',
        json={'name': 'Legacy opportunity', 'stage': 'Prospecting'})
    assert response.status_code == 200, response.text
    assert response.json()['opportunity']['stage'] == 'Prospecting'
    assert response.json()['opportunity']['prospect_id'] is None


def test_opportunity_stage_move_rejects_stale_expected_stage(app_client, fx):
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Concurrent Stage Co', 'contact_name': 'Morgan Example',
    }).json()['lead']
    prospect = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()['prospect']
    opportunity = app_client.post(
        f'/api/prospects/{prospect["id"]}/convert-to-opportunity',
        json={'name': 'Concurrent stage opportunity'},
    ).json()['opportunity']

    moved = app_client.patch(f'/api/opportunities/{opportunity["id"]}', json={
        'stage': 'Proposal', 'expected_stage': 'Qualified',
    })
    assert moved.status_code == 200, moved.text
    stale = app_client.patch(f'/api/opportunities/{opportunity["id"]}', json={
        'stage': 'Verbal Commitment', 'expected_stage': 'Qualified',
    })
    assert stale.status_code == 409
    assert 'refresh and try again' in stale.json()['detail']
    stale_close = app_client.post(
        f'/api/v531/opportunities/{opportunity["id"]}/quick-close',
        json={
            'stage': 'Closed Won', 'expected_stage': 'Qualified',
            'close_date': date.today().isoformat(),
        },
    )
    assert stale_close.status_code == 409
    with Session(fx.engine) as db:
        assert db.get(Opportunity, opportunity['id']).stage == 'Proposal'


def test_prospect_outcome_restore_migration_is_additive_and_idempotent():
    migration_engine = create_engine('sqlite://')
    with migration_engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE crm_prospects (id VARCHAR(36) PRIMARY KEY, stage VARCHAR(40))'
        ))
        connection.execute(text(
            "INSERT INTO crm_prospects (id, stage) VALUES ('existing', 'Nurture')"
        ))
    apply_crm_prospect_outcome_restore_schema(bind=migration_engine)
    apply_crm_prospect_outcome_restore_schema(bind=migration_engine)
    assert 'stage_before_opportunity_outcome' in {
        column['name'] for column in inspect(migration_engine).get_columns('crm_prospects')
    }
    with migration_engine.connect() as connection:
        row = connection.execute(text(
            "SELECT stage, stage_before_opportunity_outcome FROM crm_prospects WHERE id = 'existing'"
        )).one()
    assert row == ('Nurture', None)


def test_prospect_editor_persists_followup_notes_and_requires_not_pursuing_reason(app_client, fx):
    created = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Prospect Editor Co', 'contact_name': 'Avery Example',
        'email': 'avery@example.invalid'})
    assert created.status_code == 200, created.text
    converted = app_client.post(f'/api/leads/{created.json()["lead"]["id"]}/convert-to-prospect')
    assert converted.status_code == 200, converted.text
    prospect = converted.json()['prospect']

    updated = app_client.patch(f'/api/prospects/{prospect["id"]}', json={
        'stage': 'Nurture', 'next_action': 'Check back after budget review',
        'follow_up_date': '2026-11-15', 'stage_note': 'Asked us to reconnect next month',
        'not_pursuing_reason': ''})
    assert updated.status_code == 200, updated.text
    assert updated.json()['prospect']['stage'] == 'Nurture'
    assert updated.json()['prospect']['next_action'] == 'Check back after budget review'
    assert updated.json()['prospect']['follow_up_date'] == '2026-11-15'
    assert updated.json()['prospect']['stage_note'] == 'Asked us to reconnect next month'
    prospect_activity = app_client.get(
        f'/api/v53/tenants/{fx.a.id}/crm/overview'
    ).json()['activities']
    prospect_event = next(row for row in prospect_activity if row.get('activity_type') == 'Prospect Updated')
    assert 'Check back after budget review' in prospect_event['body']
    assert 'Follow-up date: 2026-11-15' in prospect_event['body']
    assert 'Asked us to reconnect next month' in prospect_event['body']

    promoted = app_client.post(f'/api/prospects/{prospect["id"]}/convert-to-opportunity', json={
        'name': 'Prospect Editor Co opportunity', 'expected_close_date': '2026-12-10',
        'next_action': 'Prepare discovery agenda'})
    assert promoted.status_code == 200, promoted.text
    opportunity_id = promoted.json()['opportunity']['id']
    opportunity_update = app_client.patch(f'/api/opportunities/{opportunity_id}', json={
        'stage': 'Proposal', 'expected_close_date': '2027-01-15',
        'next_action': 'Send proposal'})
    assert opportunity_update.status_code == 200, opportunity_update.text
    opportunity_activity = app_client.get(
        f'/api/v53/tenants/{fx.a.id}/crm/overview'
    ).json()['activities']
    edit_event = next(row for row in opportunity_activity if row.get('opportunity_id') == opportunity_id)
    assert 'Expected close: 2027-01-15' in edit_event['body']
    assert 'Next action: Send proposal' in edit_event['body']
    closed = app_client.patch(f'/api/opportunities/{opportunity_id}', json={
        'stage': 'Closed Lost', 'loss_reason': 'No current budget'})
    assert closed.status_code == 200, closed.text
    with Session(fx.engine) as db:
        stored_prospect = db.get(CrmProspect, prospect['id'])
        assert stored_prospect.stage == 'Not Pursuing'
        assert stored_prospect.stage_before_opportunity_outcome == 'Nurture'
        assert stored_prospect.not_pursuing_reason == (
            'Opportunity was closed as lost. Reason: No current budget'
        )

    missing_reason = app_client.patch(f'/api/prospects/{prospect["id"]}', json={
        'stage': 'Not Pursuing', 'next_action': '', 'follow_up_date': None,
        'stage_note': '', 'not_pursuing_reason': ''})
    assert missing_reason.status_code == 422

    not_pursuing = app_client.patch(f'/api/prospects/{prospect["id"]}', json={
        'stage': 'Not Pursuing', 'next_action': '', 'follow_up_date': None,
        'stage_note': '', 'not_pursuing_reason': 'No current need'})
    assert not_pursuing.status_code == 200, not_pursuing.text
    assert not_pursuing.json()['prospect']['not_pursuing_reason'] == 'No current need'
    refreshed = app_client.get(f'/api/tenants/{fx.a.id}/prospects').json()['prospects']
    reloaded_prospect = next(row for row in refreshed if row['id'] == prospect['id'])
    assert reloaded_prospect['not_pursuing_reason'] == 'No current need'
    assert reloaded_prospect['stage_note'] == ''
    timeline = app_client.get(f'/api/accounts/{converted.json()["account"]["id"]}/360').json()['activities']
    assert any('No current need' in (activity.get('body') or '') for activity in timeline)
    account_detail = app_client.get(
        f'/api/v53/tenants/{fx.a.id}/crm/records/account/{converted.json()["account"]["id"]}'
    )
    assert account_detail.status_code == 200, account_detail.text
    assert account_detail.json()['related']['prospects'][0]['not_pursuing_reason'] == 'No current need'


@pytest.mark.parametrize(
    ('terminal_stage', 'expected_prospect_stage'),
    [('Closed Won', 'Customer'), ('Closed Lost', 'Not Pursuing')],
)
def test_opportunity_outcome_and_reopen_restore_last_prospect_stage(
    app_client, fx, terminal_stage, expected_prospect_stage
):
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': f'{terminal_stage} Restore Co',
        'contact_name': 'Taylor Example',
    }).json()['lead']
    converted = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()
    prospect_id = converted['prospect']['id']
    updated = app_client.patch(f'/api/prospects/{prospect_id}', json={
        'stage': 'Nurture', 'next_action': '', 'follow_up_date': None,
        'stage_note': '', 'not_pursuing_reason': '',
    })
    assert updated.status_code == 200, updated.text
    promoted = app_client.post(
        f'/api/prospects/{prospect_id}/convert-to-opportunity',
        json={'name': f'{terminal_stage} restore opportunity'},
    )
    assert promoted.status_code == 200, promoted.text
    opportunity_id = promoted.json()['opportunity']['id']
    duplicate = app_client.post(
        f'/api/prospects/{prospect_id}/convert-to-opportunity',
        json={'name': 'Second opportunity must not be created'},
    )
    assert duplicate.status_code == 409
    with Session(fx.engine) as db:
        assert db.get(CrmProspect, prospect_id).stage == 'Nurture'

    closed = app_client.post(
        f'/api/v531/opportunities/{opportunity_id}/quick-close',
        json={
            'stage': terminal_stage,
            'close_date': date.today().isoformat(),
            'loss_reason': 'Budget redirected' if terminal_stage == 'Closed Lost' else '',
        },
    )
    assert closed.status_code == 200, closed.text
    with Session(fx.engine) as db:
        prospect = db.get(CrmProspect, prospect_id)
        assert prospect.stage == expected_prospect_stage
        assert prospect.stage_before_opportunity_outcome == 'Nurture'
        if terminal_stage == 'Closed Lost':
            assert prospect.not_pursuing_reason == (
                'Opportunity was closed as lost. Reason: Budget redirected'
            )
        else:
            assert prospect.not_pursuing_reason == ''

    reopened = app_client.patch(
        f'/api/opportunities/{opportunity_id}', json={'stage': 'Qualified'}
    )
    assert reopened.status_code == 200, reopened.text
    with Session(fx.engine) as db:
        prospect = db.get(CrmProspect, prospect_id)
        assert prospect.stage == 'Nurture'
        assert prospect.stage_before_opportunity_outcome is None
        assert prospect.not_pursuing_reason == ''


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
