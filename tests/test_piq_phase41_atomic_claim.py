"""Phase 4.1: strengthen the original gate, with no provider network access."""
from threading import Lock

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from rmr_platform.models import AuditEvent, Lead, PiqOpportunity
from rmr_platform.routes import piq
from test_piq_phase1_discovery import request
from test_piq_phase4_crm_regression import (
    api, db, live, no_real_provider_network, concurrent_moves, count, history, login, move,
)


@pytest.mark.parametrize('requests', [3, 5, 8])
def test_many_concurrent_moves(db, live, monkeypatch, requests):
    before = history(db, live)
    results = concurrent_moves(db, live, monkeypatch, requests=requests)
    assert count(db) == count(db, AuditEvent) == 1
    assert sum(body['created'] for _, body in results) == 1
    assert all(body['opportunity']['moved_to_crm'] for _, body in results)
    for _, body in results:
        assert set(body) == ({'opportunity', 'lead', 'created'} if body['created'] else {'opportunity', 'created'})
    assert history(db, live) == before


def test_stale_loaded_loser_is_refreshed(db, live, api):
    stale = db.get(PiqOpportunity, live.opportunity.id)
    assert not stale.moved_to_crm
    login(api, live.user)
    assert move(api, live).json()['created'] is True
    assert not stale.moved_to_crm  # Deliberately stale Session identity map.
    result = piq.move_piq_to_crm(stale.id, request('POST'), live.user, db)
    assert result['created'] is False and result['opportunity']['moved_to_crm'] is True
    assert stale.moved_to_crm is True
    db.rollback()  # Release the losing request's transaction as get_db.close does.
    assert count(db) == count(db, AuditEvent) == 1


def test_actual_claim_sql_compiles_for_both_databases(db, live, api):
    statements = []
    def capture(state):
        if state.is_update:
            statements.append(state.statement)
    event.listen(Session, 'do_orm_execute', capture)
    try:
        login(api, live.user)
        assert move(api, live).status_code == 200
    finally:
        event.remove(Session, 'do_orm_execute', capture)
    assert len(statements) == 1
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = statements[0].compile(dialect=dialect)
        sql = str(compiled)
        assert 'UPDATE piq_opportunities SET moved_to_crm=' in sql
        assert 'piq_opportunities.id =' in sql and 'piq_opportunities.tenant_id =' in sql
        assert 'piq_opportunities.moved_to_crm IS' in sql
        assert live.tenant.id in compiled.params.values()
        assert live.opportunity.id in compiled.params.values()


@pytest.mark.parametrize('boundary', ['lead_insert', 'audit_insert', 'before_commit'])
def test_failed_winner_releases_claim_to_waiting_request(db, live, api, monkeypatch, boundary):
    lock, failed = Lock(), []
    def fail_once(*args, **kwargs):
        with lock:
            if failed:
                return
            failed.append(True)
        raise RuntimeError('Phase 4.1 injected failure in first claimant')
    target, name = ((Lead, 'before_insert') if boundary == 'lead_insert' else
                    (AuditEvent, 'before_insert') if boundary == 'audit_insert' else (Session, 'before_commit'))
    event.listen(target, name, fail_once)
    try:
        with monkeypatch.context() as patch:
            results = concurrent_moves(db, live, patch, requests=3, failures=1)
    finally:
        event.remove(target, name, fail_once)
    assert len(failed) == 1
    successful = [body for status, body in results if status == 200]
    assert sorted(body['created'] for body in successful) == [False, True]
    assert count(db) == count(db, AuditEvent) == 1
    assert db.get(PiqOpportunity, live.opportunity.id).moved_to_crm
    login(api, live.user)
    assert move(api, live).json()['created'] is False
    assert count(db) == count(db, AuditEvent) == 1


def test_historical_unmoved_flag_with_existing_lead_is_not_repaired(db, live, api):
    # There is no reliable PIQ FK on Lead. Matching a company name is not identity.
    old_lead = Lead(tenant_id=live.tenant.id, company_name=live.opportunity.company_name,
                    source='ProspectIQ', notes='Historical inconsistent fixture')
    db.add(old_lead); db.commit()
    assert not live.opportunity.moved_to_crm
    login(api, live.user)
    assert move(api, live).json()['created'] is True
    assert count(db) == 2  # Existing inconsistency is explicitly not silently repaired.
    assert count(db, AuditEvent) == 1
    assert db.get(Lead, old_lead.id).notes == 'Historical inconsistent fixture'
    assert move(api, live).json()['created'] is False and count(db) == 2


def test_database_commit_failure_rolls_back_claim_lead_and_audit(db, live, api, monkeypatch):
    inserted = []
    def record_insert(mapper, connection, target):
        inserted.append(type(target).__name__)
    def fail_commit(connection):
        raise RuntimeError('Phase 4.1 database commit failure before acknowledgement')
    event.listen(Lead, 'after_insert', record_insert)
    event.listen(AuditEvent, 'after_insert', record_insert)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db.get_bind().dialect, 'do_commit', fail_commit)
            login(api, live.user)
            assert move(api, live).status_code == 500
    finally:
        event.remove(Lead, 'after_insert', record_insert)
        event.remove(AuditEvent, 'after_insert', record_insert)
    assert inserted == ['Lead', 'AuditEvent']  # Both INSERTs ran before COMMIT failed.
    assert count(db) == count(db, AuditEvent) == 0
    assert not db.get(PiqOpportunity, live.opportunity.id).moved_to_crm
    assert move(api, live).json()['created'] is True
    assert move(api, live).json()['created'] is False
    assert count(db) == count(db, AuditEvent) == 1
