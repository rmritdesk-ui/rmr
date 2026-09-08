"""Explicit-only gate for our disposable PostgreSQL container, never a user DB.

Run with RMR_PHASE41_POSTGRES_TEST_URL pointing to the isolated test container.
No schemas are dropped here; the owning disposable container is removed afterward.
"""
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_piq_phase4_crm_regression as phase4
import test_piq_phase41_atomic_claim as phase41
from rmr_platform.migrations import apply_piq_phase0_schema

api = phase4.api
live = phase4.live
no_real_provider_network = phase4.no_real_provider_network


@pytest.fixture
def db():
    url = make_url(os.environ['RMR_PHASE41_POSTGRES_TEST_URL'])
    assert url.drivername == 'postgresql+psycopg'
    assert url.host == 'phase41-postgres' and url.database == 'phase41_test' and url.username == 'phase41_test'
    schema = 'phase41_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
    admin.dispose()
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    apply_piq_phase0_schema(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as session:
        yield session
    engine.dispose()


def test_two_concurrent_requests(db, live, monkeypatch):
    phase4.test_concurrent_move_maximum_one_lead(db, live, monkeypatch)


@pytest.mark.parametrize('requests', [3, 5, 8])
def test_multiple_concurrent_requests(db, live, monkeypatch, requests):
    phase41.test_many_concurrent_moves(db, live, monkeypatch, requests)


@pytest.mark.parametrize('boundary', ['lead_insert', 'audit_call', 'audit_insert', 'before_commit'])
def test_rollback_retry(db, live, api, monkeypatch, boundary):
    phase4.test_failure_rolls_back_and_retry_creates_once(db, live, api, monkeypatch, boundary)


@pytest.mark.parametrize('boundary', ['lead_insert', 'audit_insert', 'before_commit'])
def test_failed_claimant_and_waiters(db, live, api, monkeypatch, boundary):
    phase41.test_failed_winner_releases_claim_to_waiting_request(db, live, api, monkeypatch, boundary)


def test_stale_orm_loser(db, live, api):
    phase41.test_stale_loaded_loser_is_refreshed(db, live, api)


def test_response_loss(db, live, api):
    phase4.test_retry_after_committed_response_is_lost(db, live, api)


def test_database_commit_failure(db, live, api, monkeypatch):
    phase41.test_database_commit_failure_rolls_back_claim_lead_and_audit(db, live, api, monkeypatch)
