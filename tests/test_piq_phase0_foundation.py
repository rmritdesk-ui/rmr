from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from rmr_platform.config import get_settings
from rmr_platform.migrations import apply_piq_phase0_schema
from rmr_platform.models import Lead, PiqOpportunity, ServiceCatalog, Tenant, TenantService, User
from rmr_platform.piq_models import PiqDiscoveryRun, PiqProfileMatch, PiqResearchRun
from rmr_platform import piq_worker
from rmr_platform.routes.piq import list_piq, move_piq_to_crm
from rmr_platform.routes.unified import (
    DiscoverIn,
    TargetProfileIn,
    adaptive_research,
    discover,
    piq_profile,
    save_target,
)
from rmr_platform.unified_models import ManagedTenantSession, PiqEvidence, PiqTargetProfile
from rmr_platform.unified_services import cross_channel_report


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase0.db'}", future=True)
    apply_piq_phase0_schema(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session
    engine.dispose()


def _seed_tenant(db: Session, suffix: str) -> tuple[Tenant, User, PiqTargetProfile, PiqOpportunity]:
    tenant = Tenant(name=f"Tenant {suffix}", slug=f"tenant-{suffix}")
    db.add(tenant)
    db.flush()
    user = User(
        email=f"admin-{suffix}@example.test",
        password_hash="test-only",
        full_name=f"Admin {suffix}",
        tenant_id=tenant.id,
        tenant_role="CLIENT_ADMIN",
    )
    db.add(user)
    db.flush()
    profile = PiqTargetProfile(tenant_id=tenant.id, created_by=user.id, name=f"Profile {suffix}")
    db.add(profile)
    db.flush()
    opportunity = PiqOpportunity(
        tenant_id=tenant.id,
        company_name=f"Company {suffix}",
        score=70,
        fingerprint=f"initial-{suffix}",
    )
    db.add(opportunity)
    db.commit()
    return tenant, user, profile, opportunity


def _discovery(
    tenant: Tenant,
    user: User,
    profile: PiqTargetProfile,
    key: str,
    **values,
) -> PiqDiscoveryRun:
    return PiqDiscoveryRun(
        tenant_id=tenant.id,
        target_profile_id=profile.id,
        requested_by=user.id,
        idempotency_key=key,
        **values,
    )


def _research(
    tenant: Tenant,
    user: User,
    opportunity: PiqOpportunity,
    key: str,
    **values,
) -> PiqResearchRun:
    return PiqResearchRun(
        tenant_id=tenant.id,
        opportunity_id=opportunity.id,
        requested_by=user.id,
        idempotency_key=key,
        **values,
    )


def _write_request(method: str) -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/phase0-test",
        "raw_path": b"/phase0-test",
        "query_string": b"",
        "headers": [(b"x-rmr-request", b"1")],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    })


def test_feature_flags_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in (
        "RMR_PIQ_LIVE_DISCOVERY_ENABLED",
        "RMR_PIQ_LIVE_RESEARCH_ENABLED",
        "RMR_PIQ_RESEARCH_WEB_SEARCH_ENABLED",
        "RMR_PIQ_WORKER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RMR_DATA_DIR", str(tmp_path / "config-data"))

    configured = get_settings()

    assert configured.piq_live_discovery_enabled is False
    assert configured.piq_live_research_enabled is False
    assert configured.piq_research_web_search_enabled is False
    assert configured.piq_worker_enabled is False
    assert configured.piq_discovery_provider == "demonstration"
    assert configured.piq_research_provider == "demonstration"
    assert configured.google_places_api_key == ""


def test_fresh_sqlite_schema_contains_phase0_tables_and_columns(db: Session):
    schema = inspect(db.get_bind())
    assert {"piq_discovery_runs", "piq_profile_matches", "piq_research_runs"}.issubset(schema.get_table_names())
    opportunity_columns = {column["name"] for column in schema.get_columns("piq_opportunities")}
    evidence_columns = {column["name"] for column in schema.get_columns("piq_evidence")}
    assert {"target_profile_id", "provider", "fingerprint", "adaptive_score_delta"}.issubset(opportunity_columns)
    assert {"tenant_id", "provider", "evidence_state", "research_run_id", "raw_json"}.issubset(evidence_columns)


def test_additive_upgrade_keeps_legacy_rows_readable(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-upgrade.db'}", future=True)
    legacy_ddl = (
        "CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY)",
        "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
        "CREATE TABLE managed_tenant_sessions (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36))",
        "CREATE TABLE piq_target_profiles (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36))",
        """CREATE TABLE piq_opportunities (
            id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), company_name VARCHAR(200) NOT NULL,
            score INTEGER, signal VARCHAR(300), evidence_count INTEGER, estimated_value_cents INTEGER,
            status VARCHAR(40), enhanced BOOLEAN, enhancement_price_cents INTEGER,
            moved_to_crm BOOLEAN, created_at DATETIME
        )""",
        """CREATE TABLE piq_evidence (
            id VARCHAR(36) PRIMARY KEY, opportunity_id VARCHAR(36), evidence_type VARCHAR(60),
            source_name VARCHAR(180), source_url VARCHAR(1000), fact TEXT, confidence_pct INTEGER,
            verified BOOLEAN, observed_at DATETIME
        )""",
    )
    with engine.begin() as connection:
        for statement in legacy_ddl:
            connection.execute(text(statement))
        connection.execute(text("INSERT INTO tenants (id) VALUES ('tenant-legacy')"))
        connection.execute(text(
            "INSERT INTO piq_opportunities "
            "(id, tenant_id, company_name, score, signal, evidence_count, estimated_value_cents, status, enhanced, "
            "enhancement_price_cents, moved_to_crm, created_at) VALUES "
            "('opp-legacy', 'tenant-legacy', 'Legacy Co', 81, 'Legacy signal', 1, 5000, 'Priority', 0, 400, 0, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT INTO piq_evidence "
            "(id, opportunity_id, evidence_type, source_name, source_url, fact, confidence_pct, verified, observed_at) "
            "VALUES ('evidence-legacy', 'opp-legacy', 'growth_signal', 'Legacy Provider', '', 'Legacy fact', 80, 1, CURRENT_TIMESTAMP)"
        ))

    apply_piq_phase0_schema(bind=engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        opportunity = session.get(PiqOpportunity, "opp-legacy")
        evidence = session.get(PiqEvidence, "evidence-legacy")
        assert opportunity is not None
        assert opportunity.company_name == "Legacy Co"
        assert opportunity.score == 81
        assert opportunity.provider is None
        assert opportunity.adaptive_score_delta is None
        assert evidence is not None
        assert evidence.fact == "Legacy fact"
        assert evidence.tenant_id is None
        assert evidence.evidence_state == "unknown"
        assert evidence.raw_json == {}
    engine.dispose()


def test_idempotency_and_fingerprint_uniqueness_are_tenant_scoped(db: Session):
    tenant_a, user_a, profile_a, opportunity_a = _seed_tenant(db, "a")
    tenant_b, user_b, profile_b, opportunity_b = _seed_tenant(db, "b")
    opportunity_a.fingerprint = "shared-provider-id"
    opportunity_b.fingerprint = "shared-provider-id"
    discovery_a = _discovery(tenant_a, user_a, profile_a, "same-key")
    discovery_b = _discovery(tenant_b, user_b, profile_b, "same-key")
    research_a = _research(tenant_a, user_a, opportunity_a, "research-key")
    research_b = _research(tenant_b, user_b, opportunity_b, "research-key")
    db.add_all([opportunity_a, opportunity_b, discovery_a, discovery_b, research_a, research_b])
    db.commit()

    db.add(_discovery(tenant_a, user_a, profile_a, "same-key"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(_research(tenant_a, user_a, opportunity_a, "research-key"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    duplicate_fingerprint = PiqOpportunity(
        tenant_id=tenant_a.id,
        company_name="Duplicate A",
        fingerprint="shared-provider-id",
    )
    db.add(duplicate_fingerprint)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_claim_is_atomic_retains_tenant_and_separates_run_types(db: Session):
    tenant, user, profile, opportunity = _seed_tenant(db, "claim")
    discovery = _discovery(tenant, user, profile, "discovery-claim")
    research = _research(tenant, user, opportunity, "research-claim", status="queued")
    db.add_all([discovery, research])
    db.commit()

    claimed_discovery = piq_worker.claim_next_discovery_run(db, worker_id="worker-a")
    assert isinstance(claimed_discovery, PiqDiscoveryRun)
    assert claimed_discovery.tenant_id == tenant.id
    assert claimed_discovery.status == "running"
    assert claimed_discovery.attempt_count == 1
    assert piq_worker.claim_next_discovery_run(db, worker_id="worker-b") is None

    claimed_research = piq_worker.claim_next_research_run(db, worker_id="worker-a")
    assert isinstance(claimed_research, PiqResearchRun)
    assert claimed_research.id == research.id
    assert claimed_research.tenant_id == tenant.id


def test_expired_lease_recovers_then_fails_at_max_attempts(db: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(piq_worker, "settings", SimpleNamespace(piq_job_max_attempts=2))
    tenant, user, profile, opportunity = _seed_tenant(db, "leases")
    now = datetime.now(timezone.utc)
    recoverable = _discovery(
        tenant,
        user,
        profile,
        "recoverable",
        status="running",
        attempt_count=1,
        lease_owner="dead-worker",
        lease_expires_at=now - timedelta(seconds=1),
    )
    exhausted = _research(
        tenant,
        user,
        opportunity,
        "exhausted",
        status="running",
        attempt_count=2,
        lease_owner="dead-worker",
        lease_expires_at=now - timedelta(seconds=1),
    )
    db.add_all([recoverable, exhausted])
    db.commit()

    recovered = piq_worker.recover_expired_leases(db, now=now)

    assert recovered == {"discovery": 1, "research": 1}
    assert recoverable.status == "retry_wait"
    assert recoverable.next_attempt_at == now
    assert recoverable.lease_owner is None
    assert exhausted.status == "failed"
    assert exhausted.completed_at == now


def test_failure_uses_retry_wait_then_enforces_max_attempts_and_redacts_secrets(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(piq_worker, "settings", SimpleNamespace(piq_job_max_attempts=2))
    tenant, user, profile, _ = _seed_tenant(db, "retry")
    now = datetime.now(timezone.utc)
    run = _discovery(tenant, user, profile, "retry", status="running", attempt_count=1)
    db.add(run)
    db.commit()

    piq_worker.mark_run_failure(
        db,
        run,
        error_code="provider_error",
        error_message="Authorization: Bearer super-secret",
        retryable=True,
        now=now,
    )
    assert run.status == "retry_wait"
    assert run.next_attempt_at == now + timedelta(seconds=5)
    assert "super-secret" not in (run.error_message or "")

    run.status = "running"
    run.attempt_count = 2
    piq_worker.mark_run_failure(
        db,
        run,
        error_code="provider_error",
        error_message="still unavailable",
        retryable=True,
        now=now,
    )
    assert run.status == "failed"
    assert run.next_attempt_at is None
    assert run.completed_at == now


def test_tenant_scoped_helpers_and_managed_session_binding(db: Session):
    tenant_a, user_a, profile_a, _ = _seed_tenant(db, "security-a")
    tenant_b, user_b, _, _ = _seed_tenant(db, "security-b")
    run = _discovery(
        tenant_a,
        user_a,
        profile_a,
        "security-run",
        provider="untrusted-provider-label",
        diagnostics_json={"provider_tenant_id": tenant_b.id},
    )
    managed_session = ManagedTenantSession(
        admin_user_id=user_b.id,
        tenant_id=tenant_b.id,
        reason="Phase 0 test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add_all([run, managed_session])
    db.commit()

    assert piq_worker.get_discovery_run_for_tenant(db, tenant_a.id, run.id) is run
    assert piq_worker.get_discovery_run_for_tenant(db, tenant_b.id, run.id) is None
    assert piq_worker.claim_next_discovery_run(db, worker_id="tenant-b-worker", tenant_id=tenant_b.id) is None
    claimed = piq_worker.claim_next_discovery_run(db, worker_id="tenant-a-worker", tenant_id=tenant_a.id)
    assert claimed is not None
    assert claimed.tenant_id == tenant_a.id
    assert piq_worker.managed_session_matches_tenant(db, managed_session.id, tenant_b.id) is True
    assert piq_worker.managed_session_matches_tenant(db, managed_session.id, tenant_a.id) is False
    assert claimed.diagnostics_json["provider_tenant_id"] != claimed.tenant_id


def test_worker_start_stop_is_safe_and_disabled_worker_does_not_start(monkeypatch: pytest.MonkeyPatch):
    piq_worker.stop(timeout=0.1)
    monkeypatch.setattr(
        piq_worker,
        "settings",
        SimpleNamespace(piq_worker_enabled=False, piq_worker_poll_seconds=1),
    )
    assert piq_worker.start() is False
    assert piq_worker.is_running() is False

    monkeypatch.setattr(
        piq_worker,
        "settings",
        SimpleNamespace(piq_worker_enabled=True, piq_worker_poll_seconds=1),
    )
    monkeypatch.setattr(piq_worker, "tick", lambda: {"recovered": {}, "claimed": 0})
    assert piq_worker.start() is True
    piq_worker.stop(timeout=1.0)
    assert piq_worker.is_running() is False


def test_worker_contains_no_http_provider_implementation():
    source = Path(piq_worker.__file__).read_text(encoding="utf-8")
    assert "import httpx" not in source
    assert "import requests" not in source
    assert "urllib.request" not in source
    assert "googleapis.com" not in source
    assert "api.openai.com" not in source


def test_profile_match_foundation_preserves_unscored_state(db: Session):
    tenant, user, profile, opportunity = _seed_tenant(db, "match")
    run = _discovery(tenant, user, profile, "match-run")
    db.add(run)
    db.flush()
    match = PiqProfileMatch(
        tenant_id=tenant.id,
        discovery_run_id=run.id,
        opportunity_id=opportunity.id,
        target_profile_id=profile.id,
    )
    db.add(match)
    db.commit()

    assert match.scoring_version == "unscored"
    assert match.base_match_score is None
    assert match.confidence_score is None
    assert match.evidence_completeness_pct is None


def test_existing_demo_piq_and_move_to_crm_regression(db: Session):
    tenant = Tenant(name="Regression Tenant", slug="phase0-regression")
    db.add(tenant)
    db.flush()
    user = User(
        email="phase0-regression@example.test",
        password_hash="test-only",
        full_name="Regression Admin",
        tenant_id=tenant.id,
        tenant_role="CLIENT_ADMIN",
    )
    db.add(user)
    for code in ("piq_access", "piq_enhancement"):
        db.add(ServiceCatalog(code=code, name=code.replace("_", " ").title()))
        db.add(TenantService(tenant_id=tenant.id, service_code=code, status="active"))
    db.commit()

    saved = save_target(
        tenant.id,
        TargetProfileIn(
            name="Regression Profile",
            industries=["Professional Services"],
            locations=["Arizona"],
        ),
        _write_request("PUT"),
        user,
        db,
    )
    assert saved["profile"]["name"] == "Regression Profile"

    discovery = discover(tenant.id, DiscoverIn(count=1), _write_request("POST"), user, db)
    assert discovery["provider_mode"] == "demonstration"
    assert len(discovery["created"]) == 1
    opportunity_id = discovery["created"][0]["id"]

    listing = list_piq(tenant.id, user, db)
    assert [row["id"] for row in listing["opportunities"]] == [opportunity_id]
    profile = piq_profile(opportunity_id, user, db)
    assert len(profile["evidence"]) == 2

    previous_score = profile["opportunity"]["score"]
    research = adaptive_research(opportunity_id, _write_request("POST"), user, db)
    assert research["provider_mode"] == "demonstration"
    assert research["opportunity"]["score"] == min(100, previous_score + 5)
    assert len(research["facts"]) == 3

    first_move = move_piq_to_crm(opportunity_id, _write_request("POST"), user, db)
    second_move = move_piq_to_crm(opportunity_id, _write_request("POST"), user, db)
    leads = list(db.scalars(select(Lead).where(Lead.tenant_id == tenant.id)))
    assert first_move["created"] is True
    assert second_move["created"] is False
    assert len(leads) == 1
    assert leads[0].source == "ProspectIQ"

    report = cross_channel_report(db, tenant.id)
    assert report["funnel"]["piq_records"] == 1
    assert report["funnel"]["piq_to_crm"] == 1
