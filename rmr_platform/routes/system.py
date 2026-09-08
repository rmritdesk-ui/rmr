from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import __version__
from ..config import settings
from ..db import get_db
from ..migrations import migration_status
from ..models import AuditEvent, Tenant, User
from ..permissions import require_global_admin
from ..security import current_user

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    database_ok = False
    database_error = ""
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - surfaced to deployment health report
        database_error = str(exc)
    storage_ok = os.access(settings.data_dir, os.W_OK)
    migrations = migration_status()
    core_ok = database_ok and storage_ok and migrations["current"] == migrations["required"]
    warnings = []
    if settings.payment_provider == "mock":
        warnings.append("Payment processing is in pilot mode; no live card charges are being processed.")
    warnings.append("Outbound email is not configured; invitation and password-reset links are delivered through the local pilot workflow.")
    if core_ok:
        business_status = {
            "headline": "Core platform services are operating normally.",
            "impact": "Client records, CRM, onboarding, websites, pricing, and reporting are available.",
            "action": "No immediate technical action is required. Review pilot-mode warnings before production use.",
            "tone": "healthy" if not warnings else "attention",
        }
    else:
        business_status = {
            "headline": "One or more core services need attention.",
            "impact": "Some client or administrative functions may be unavailable until the failed check is corrected.",
            "action": "Open the technical checks below and contact platform support before continuing production work.",
            "tone": "degraded",
        }
    return {
        "status": "healthy" if core_ok else "degraded",
        "business_status": business_status,
        "warnings": warnings,
        "version": __version__,
        "time": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": {"ok": database_ok, "error": database_error},
            "storage": {"ok": storage_ok, "path": str(settings.data_dir)},
            "migrations": migrations,
            "payment_provider": {"ok": settings.payment_provider in {"mock", "stripe"}, "mode": settings.payment_provider},
            "email": {"ok": False, "status": "Not configured in pilot package"},
            "backups": {"ok": (settings.data_dir / "backups").exists(), "path": str(settings.data_dir / "backups")},
        },
    }


@router.get("/system/info")
def system_info(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    return {
        "version": __version__,
        "environment": settings.environment,
        "base_url": settings.base_url,
        "database": "SQLite WAL" if settings.database_url.startswith("sqlite") else "External database",
        "tenant_count": db.scalar(select(func.count(Tenant.id))) or 0,
        "user_count": db.scalar(select(func.count(User.id))) or 0,
        "audit_event_count": db.scalar(select(func.count(AuditEvent.id))) or 0,
        "deployment": {
            "containerized": os.path.exists("/.dockerenv"),
            "data_dir": str(settings.data_dir),
            "payment_provider": settings.payment_provider,
        },
    }


@router.get("/audit")
def audit_log(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(300)))
    return {"events": [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "tenant_id": row.tenant_id,
            "event_type": row.event_type,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "event_data": row.event_data,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]}
