"""Same provisioning cases on the guarded disposable PostgreSQL 16 database."""
import os
import sys
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_prospectiq_provisioning import *  # noqa


@pytest.fixture
def federation_engine():
    url=make_url(os.environ['RMR_PHASE41_POSTGRES_TEST_URL'])
    assert url.drivername=='postgresql+psycopg' and url.host=='phase41-postgres'
    assert url.database==url.username=='phase41_test'
    schema='provision_'+uuid4().hex
    control=create_engine(url)
    with control.begin() as conn:
        assert str(conn.execute(text('SHOW server_version')).scalar()).startswith('16.')
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    control.dispose()
    engine=create_engine(url.update_query_dict({'options':f'-csearch_path={schema}'}))
    yield engine
    engine.dispose()
