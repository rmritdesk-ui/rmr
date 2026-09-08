"""Complete bootstrap on isolated PostgreSQL 16, never any installed database."""
import os
from pathlib import Path
import sys
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import test_release_bootstrap as bootstrap
from test_release_bootstrap import (
    test_import_status_health_and_failed_startup_do_not_create_schema,
    test_explicit_complete_bootstrap_idempotency_and_foreign_keys,
    test_auto_migrate_true_bootstraps_all_families_without_demo,
)


@pytest.fixture
def release_env(tmp_path):
    url = make_url(os.environ["RMR_PHASE41_POSTGRES_TEST_URL"])
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "phase41-postgres" and url.database == url.username == "phase41_test"
    schema = "release_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        assert str(connection.execute(text("SHOW server_version")).scalar()).startswith("16.")
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine.dispose()
    env = bootstrap.release_env.__wrapped__(tmp_path)
    env["RMR_DATABASE_URL"] = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    return env
