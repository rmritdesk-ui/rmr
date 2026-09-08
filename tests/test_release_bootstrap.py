"""Fresh-process bootstrap regressions; isolated SQLite by default, no providers."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def release_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RMR_", "DATABASE_URL", "PGOPTIONS"))}
    env.update(RMR_DATA_DIR=str(tmp_path), RMR_DATABASE_URL=f"sqlite:///{tmp_path / 'bootstrap.db'}",
               RMR_ENVIRONMENT="production", RMR_AUTO_MIGRATE="false", RMR_AUTO_SEED="false",
               RMR_INSTALL_PROFILE="empty", RMR_ALLOW_DEMO_CREDENTIALS="false",
               RMR_LOCAL_RECOVERY_MODE="false", RMR_PIQ_WORKER_ENABLED="false",
               RMR_CB1_WORKER_ENABLED="false", RMR_PIQ_LIVE_DISCOVERY_ENABLED="false",
               RMR_PIQ_LIVE_RESEARCH_ENABLED="false", PYTHONDONTWRITEBYTECODE="1")
    return env


def run(env, code):
    result = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_import_status_health_and_failed_startup_do_not_create_schema(release_env):
    run(release_env, '''
from sqlalchemy import inspect, event
from rmr_platform.db import engine, SessionLocal
statements=[]
event.listen(engine, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: statements.append(sql))
from rmr_platform.main import app
from rmr_platform.migrations import migration_status
from rmr_platform.routes.system import health
from fastapi.testclient import TestClient
assert migration_status()["current"] is None
with SessionLocal() as db:
    assert health(db)["status"] == "degraded"
try:
    with TestClient(app): pass
except RuntimeError as exc:
    assert "cli migrate" in str(exc)
else:
    raise AssertionError("Unmigrated startup must fail closed")
assert inspect(engine).get_table_names() == []
assert not any(s.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for s in statements)
''')


def test_explicit_complete_bootstrap_idempotency_and_foreign_keys(release_env):
    run(release_env, '''
import subprocess, sys, os
for _ in range(2):
    subprocess.run([sys.executable,"-m","rmr_platform.cli","migrate"], check=True, capture_output=True)
from sqlalchemy import inspect, select, func, event
from sqlalchemy.exc import IntegrityError
from rmr_platform.db import engine, Base, SessionLocal
from rmr_platform.migrations import MIGRATION_VERSION, migration_status, require_current_schema
from rmr_platform.commercial.models import CommercialBase
from rmr_platform.models import User, Tenant, ServiceCatalog, TenantService, SchemaMigration
from rmr_platform.cb1_models import CB1SchemaMigration
require_current_schema()
assert migration_status()["current"] == MIGRATION_VERSION
assert set(Base.metadata.tables) | set(CommercialBase.metadata.tables) <= set(inspect(engine).get_table_names())
with SessionLocal() as db:
    for model in [User,Tenant]: assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.scalar(select(func.count()).select_from(ServiceCatalog)) > 0
    assert db.scalar(select(func.count()).select_from(CB1SchemaMigration)) == 1
    assert db.scalar(select(func.count()).select_from(SchemaMigration)) == 9
    service=db.scalar(select(ServiceCatalog.code))
    db.add(TenantService(tenant_id="nonexistent-release-tenant",service_code=service))
    try: db.commit()
    except IntegrityError as exc:
        db.rollback()
        assert getattr(exc.orig,"sqlstate",None) == "23503" or "FOREIGN KEY" in str(exc.orig)
    else: raise AssertionError("Foreign key accepted an orphan tenant")
statements=[]
event.listen(engine,"before_cursor_execute",lambda c,cu,sql,p,ctx,many:statements.append(sql))
from rmr_platform.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    assert client.get("/api/health").json()["status"] == "healthy"
    assert client.get("/api/auth/demo-users").json() == {"users": []}
assert not any(s.lstrip().upper().startswith(("CREATE ","ALTER ","DROP ","INSERT ","UPDATE ","DELETE ")) for s in statements)
''')


def test_auto_migrate_true_bootstraps_all_families_without_demo(release_env):
    release_env["RMR_AUTO_MIGRATE"] = "true"
    run(release_env, '''
from fastapi.testclient import TestClient
from rmr_platform.main import app
from rmr_platform.migrations import require_current_schema
from sqlalchemy import select, func
from rmr_platform.db import SessionLocal
from rmr_platform.models import User, Tenant, ServiceCatalog
with TestClient(app) as client:
    assert client.get("/api/health").json()["status"] == "healthy"
    require_current_schema()
with SessionLocal() as db:
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(Tenant)) == 0
    assert db.scalar(select(func.count()).select_from(ServiceCatalog)) > 0
''')


@pytest.mark.parametrize("key,value", [("RMR_AUTO_SEED","true"),("RMR_ALLOW_DEMO_CREDENTIALS","true"),
                                      ("RMR_LOCAL_RECOVERY_MODE","true"),("RMR_INSTALL_PROFILE","demo")])
def test_production_rejects_demo_overrides(release_env, key, value):
    release_env[key] = value
    run(release_env, '''
try: from rmr_platform.config import settings
except ValueError as exc: assert "Production requires" in str(exc)
else: raise AssertionError("Unsafe production configuration accepted")
''')


@pytest.mark.parametrize("command", ["seed", "reset-demo"])
def test_production_rejects_demo_cli(release_env, command):
    result = subprocess.run([sys.executable,"-B","-m","rmr_platform.cli",command],
                            env=release_env,capture_output=True,text=True,timeout=30)
    assert result.returncode != 0 and "Demo seeding is disabled" in result.stderr


def test_local_demo_setup_remains_supported(release_env):
    release_env.update(RMR_ENVIRONMENT="development", RMR_INSTALL_PROFILE="demo",
                       RMR_AUTO_MIGRATE="true", RMR_AUTO_SEED="true", RMR_ALLOW_DEMO_CREDENTIALS="true")
    run(release_env, '''
from fastapi.testclient import TestClient
from rmr_platform.main import app
from sqlalchemy import select
from rmr_platform.db import SessionLocal
from rmr_platform.models import User
with TestClient(app) as client:
    assert client.get("/api/health").json()["status"] == "healthy"
with SessionLocal() as db:
    user=db.scalar(select(User).where(User.email=="admin@kerry-real-estate.demo"))
    assert user and user.tenant_role == "CLIENT_ADMIN"
''')
