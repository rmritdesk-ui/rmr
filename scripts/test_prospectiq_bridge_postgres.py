"""Run the same Phase 0 invariants on guarded, disposable PostgreSQL 16."""
import os
from pathlib import Path
import sys
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_prospectiq_bridge import *  # noqa: F401,F403 - reuse identical assertions


@pytest.fixture
def bridge_engine():
    url = make_url(os.environ["RMR_PHASE41_POSTGRES_TEST_URL"])
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "phase41-postgres" and url.database == url.username == "phase41_test"
    schema = "bridge_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        assert str(connection.execute(text("SHOW server_version")).scalar()).startswith("16.")
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    control.dispose()
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    yield engine
    engine.dispose()
    # Test schemas disappear with the disposable tmpfs PostgreSQL container.
