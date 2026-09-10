from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import inspect, select, text

from .db import Base, engine, db_session
from .models import SchemaMigration
from . import unified_models  # noqa: F401 - registers additive v5.2 tables
from . import client_admin_models  # noqa: F401 - registers additive v5.2.1 correction tables
from . import cumulative_product_models  # noqa: F401 - registers additive v5.2.2 repair tables
from . import tenant_theme_models  # noqa: F401 - registers additive v5.4 tenant theme table
from . import piq_models  # noqa: F401 - registers additive PIQ workflow tables
from .prospectiq_bridge import models as prospectiq_bridge_models  # noqa: F401
from . import cb1_models  # noqa: F401 - complete shared metadata before DDL
from .commercial.models import CommercialBase

INITIAL_VERSION = "005.000.000-initial-production-pilot"
FUNCTIONAL_EXPERIENCE_VERSION = "005.001.000-functional-client-experience"
UNIFIED_PRODUCT_VERSION = "005.003.000-unified-product-integration"
CLIENT_ADMIN_VERSION = "005.004.000-client-administrator-correction"
CUMULATIVE_PRODUCT_VERSION = "005.005.000-cumulative-product-repair"
TENANT_THEMES_VERSION = "005.006.000-tenant-themes"
FOUR_WORKSPACE_THEMES_VERSION = "005.006.100-four-workspace-themes"
PIQ_PHASE0_VERSION = "005.007.000-piq-integration-foundation"
PIQ_WORKFLOW_VERSION = "005.008.000-piq-profile-collection"
PROSPECTIQ_BRIDGE_VERSION = "005.009.000-prospectiq-bridge-foundation"
MIGRATION_VERSION = PROSPECTIQ_BRIDGE_VERSION


def _column_names(table_name: str, *, bind=engine) -> set[str]:
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {str(row["name"]) for row in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column_name: str, ddl: str, *, bind=engine) -> None:
    if column_name in _column_names(table_name, bind=bind):
        return
    with bind.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _migration_005_001_000() -> None:
    # New v5.1 tables are created by SQLAlchemy metadata. Existing v5.0
    # tables are upgraded additively so installed pilot data and QC notes are
    # never overwritten or reseeded.
    Base.metadata.create_all(bind=engine)
    _add_column_if_missing("notifications", "action_route", "action_route VARCHAR(160) NOT NULL DEFAULT ''")
    _add_column_if_missing("notifications", "action_label", "action_label VARCHAR(100) NOT NULL DEFAULT 'Open'")
    _add_column_if_missing("notifications", "entity_type", "entity_type VARCHAR(80) NOT NULL DEFAULT ''")
    _add_column_if_missing("notifications", "entity_id", "entity_id VARCHAR(80) NOT NULL DEFAULT ''")
    with engine.begin() as connection:
        # Preserve all v5.0 onboarding notes/data while clarifying that tenant
        # provisioning includes the client access handoff discovered in QC.
        connection.execute(text(
            "UPDATE onboarding_steps SET name = 'Tenant provisioning & client access' "
            "WHERE stage_number = 2 AND name = 'Tenant provisioning'"
        ))


def _migration_005_003_000() -> None:
    # v5.2 adds only new customer-product tables. Existing tenant, CRM,
    # website, pricing, revenue-share, onboarding and audit data are never
    # rewritten or reseeded.
    Base.metadata.create_all(bind=engine)


def _migration_005_004_000() -> None:
    # v5.2.1 is additive. It adds Client Administrator workflow tables only;
    # no existing tenant, CRM, PIQ, website, forecast, pricing or audit data is rewritten.
    Base.metadata.create_all(bind=engine)


def _migration_005_005_000() -> None:
    # v5.2.2 adds per-client commercial terms, commercial history,
    # communication provenance and social revision tables. Existing data is preserved.
    Base.metadata.create_all(bind=engine)


def _migration_005_006_000() -> None:
    # v5.4 adds one tenant-scoped branding table only. Existing tenants, users,
    # CRM, websites, pricing, onboarding, audit records and Product Owner data
    # are never rewritten or reseeded.
    Base.metadata.create_all(bind=engine)


def _migration_005_006_100() -> None:
    # v5.4.1 adds one bounded preset-selection field to the existing tenant theme row.
    # Existing branding, tenants, CRM, websites, pricing, permissions and data remain intact.
    _add_column_if_missing(
        "tenant_themes",
        "workspace_style",
        "workspace_style VARCHAR(40) NOT NULL DEFAULT 'classic-blue'",
    )


def apply_piq_phase0_schema(*, bind=engine) -> None:
    """Create only additive PIQ foundation objects on the supplied database."""
    Base.metadata.create_all(bind=bind)

    opportunity_columns = {
        "target_profile_id": "target_profile_id VARCHAR(36)",
        "provider": "provider VARCHAR(80)",
        "source_external_id": "source_external_id VARCHAR(255)",
        "source_url": "source_url VARCHAR(1000)",
        "fingerprint": "fingerprint VARCHAR(255)",
        "website": "website VARCHAR(1000)",
        "location": "location VARCHAR(300)",
        "industry": "industry VARCHAR(180)",
        "phone": "phone VARCHAR(80)",
        "base_match_score": "base_match_score INTEGER",
        "confidence_score": "confidence_score INTEGER",
        "evidence_completeness_pct": "evidence_completeness_pct INTEGER",
        "adaptive_score_delta": "adaptive_score_delta INTEGER",
    }
    for column_name, ddl in opportunity_columns.items():
        _add_column_if_missing("piq_opportunities", column_name, ddl, bind=bind)

    evidence_columns = {
        "tenant_id": "tenant_id VARCHAR(36)",
        "provider": "provider VARCHAR(80)",
        "source_title": "source_title VARCHAR(500)",
        "source_domain": "source_domain VARCHAR(255)",
        "evidence_state": "evidence_state VARCHAR(40) NOT NULL DEFAULT 'unknown'",
        "profile_criterion": "profile_criterion VARCHAR(300)",
        "discovery_run_id": "discovery_run_id VARCHAR(36)",
        "research_run_id": "research_run_id VARCHAR(36)",
        "evidence_hash": "evidence_hash VARCHAR(64)",
        "is_synthesized": "is_synthesized BOOLEAN NOT NULL DEFAULT FALSE",
        "raw_json": "raw_json JSON NOT NULL DEFAULT '{}'",
    }
    for column_name, ddl in evidence_columns.items():
        _add_column_if_missing("piq_evidence", column_name, ddl, bind=bind)

    with bind.begin() as connection:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_piq_opportunity_tenant_fingerprint "
            "ON piq_opportunities (tenant_id, fingerprint)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_piq_opportunities_target_profile_id "
            "ON piq_opportunities (target_profile_id)"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_piq_evidence_tenant_hash "
            "ON piq_evidence (tenant_id, evidence_hash)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_piq_evidence_tenant_id "
            "ON piq_evidence (tenant_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_piq_evidence_discovery_run "
            "ON piq_evidence (discovery_run_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_piq_evidence_research_run "
            "ON piq_evidence (research_run_id)"
        ))


def _migration_005_007_000() -> None:
    apply_piq_phase0_schema(bind=engine)


def apply_piq_profile_collection(*, bind=engine) -> None:
    """Forward-only: drop only tenant-only uniqueness, preserving rows and FKs."""
    inspector = inspect(bind)
    if "piq_target_profiles" not in inspector.get_table_names():
        Base.metadata.create_all(bind=bind)
        return
    constraints = [c for c in inspector.get_unique_constraints("piq_target_profiles")
                   if c["column_names"] == ["tenant_id"]]
    indexes = [i for i in inspector.get_indexes("piq_target_profiles")
               if i.get("unique") and i["column_names"] == ["tenant_id"] and not i.get("duplicates_constraint")]
    with bind.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote
        # Shipped SQLite schema uses a named unique INDEX (unique=True,index=True),
        # not an inline UNIQUE constraint. PostgreSQL constraints are handled too.
        if constraints and connection.dialect.name == "sqlite":
            raise RuntimeError("Unexpected inline profile uniqueness; migration requires schema review")
        for constraint in constraints:
            connection.execute(text("ALTER TABLE piq_target_profiles DROP CONSTRAINT " + quote(constraint["name"])))
        for index in indexes:
            connection.execute(text("DROP INDEX " + quote(index["name"])))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_piq_target_profiles_tenant_id ON piq_target_profiles (tenant_id)"))

def _migration_005_008_000() -> None:
    apply_piq_profile_collection(bind=engine)

def apply_prospectiq_bridge_schema(*, bind=engine) -> None:
    """Add bridge tables only; existing tenant/user/CRM rows are not changed."""
    tables = [table for table in Base.metadata.sorted_tables
              if table.name.startswith("prospectiq_")]
    Base.metadata.create_all(bind=bind, tables=tables)


def _migration_005_009_000() -> None:
    apply_prospectiq_bridge_schema(bind=engine)


MIGRATIONS: list[tuple[str, Callable[[], None]]] = [
    (FUNCTIONAL_EXPERIENCE_VERSION, _migration_005_001_000),
    (UNIFIED_PRODUCT_VERSION, _migration_005_003_000),
    (CLIENT_ADMIN_VERSION, _migration_005_004_000),
    (CUMULATIVE_PRODUCT_VERSION, _migration_005_005_000),
    (TENANT_THEMES_VERSION, _migration_005_006_000),
    (FOUR_WORKSPACE_THEMES_VERSION, _migration_005_006_100),
    (PIQ_PHASE0_VERSION, _migration_005_007_000),
    (PIQ_WORKFLOW_VERSION, _migration_005_008_000),
    (PROSPECTIQ_BRIDGE_VERSION, _migration_005_009_000),
]


def migrate() -> None:
    """Explicit complete bootstrap: all schema families and governed reference data.

    Never creates demo tenants/users. Call once under deployment control, or
    from application lifespan only when RMR_AUTO_MIGRATE is enabled.
    """
    Base.metadata.create_all(bind=engine)
    with db_session() as db:
        if not db.scalar(select(SchemaMigration).where(SchemaMigration.version == INITIAL_VERSION)):
            db.add(SchemaMigration(version=INITIAL_VERSION))

    for version, function in MIGRATIONS:
        with db_session() as db:
            if db.scalar(select(SchemaMigration).where(SchemaMigration.version == version)):
                continue
        function()
        with db_session() as db:
            if not db.scalar(select(SchemaMigration).where(SchemaMigration.version == version)):
                db.add(SchemaMigration(version=version))

    from .cb1_migration import apply as apply_cb1
    from .seed import seed_reference_data
    apply_cb1()
    CommercialBase.metadata.create_all(bind=engine)
    with db_session() as db:
        seed_reference_data(db)


def migration_status() -> dict[str, object]:
    """Read-only even on an empty database; safe for status/health probes."""
    if not inspect(engine).has_table(SchemaMigration.__tablename__):
        return {"current": None, "required": MIGRATION_VERSION, "applied": []}
    with db_session() as db:
        rows = list(db.scalars(select(SchemaMigration).order_by(SchemaMigration.applied_at)))
        applied = {row.version for row in rows}
        current = None
        for version in [INITIAL_VERSION, *(version for version, _ in MIGRATIONS)]:
            if version not in applied:
                break
            current = version
        return {
            "current": current,
            "required": MIGRATION_VERSION,
            "applied": [row.version for row in rows],
        }


def require_current_schema() -> None:
    """Fail without DDL when explicit bootstrap has not completed."""
    from .cb1_migration import MIGRATION_ID
    tables = set(inspect(engine).get_table_names())
    required = set(Base.metadata.tables) | set(CommercialBase.metadata.tables)
    if required - tables or migration_status()["current"] != MIGRATION_VERSION:
        raise RuntimeError("Database bootstrap is incomplete. Run: python -m rmr_platform.cli migrate")
    with engine.connect() as connection:
        if not connection.execute(text("SELECT migration_id FROM cb1_schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).first():
            raise RuntimeError("CB1 bootstrap is incomplete. Run: python -m rmr_platform.cli migrate")
