from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import cb1_models
from .models import (
    Account,
    Activity,
    AuditEvent,
    Campaign,
    Lead,
    Opportunity,
    PiqOpportunity,
    Tenant,
    TenantService,
    TrainingProgress,
    User,
    WebsitePage,
    WebsiteSite,
)
from .unified_models import (
    AppointmentRequest,
    PiqEvidence,
    SeoWorkItem,
    WebsiteBlogPost,
    WebsiteMedia,
    WebsiteResource,
    WebsiteTeamProfile,
)
from .utils import model_dict

RELEASE = "5.4.1.2-interaction-regression-correction-po1"

MODULE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "home": {"label": "Dashboard", "icon": "⌂", "services": [], "always": True},
    "website": {"label": "Website", "icon": "◫", "services": ["managed_website", "custom_website_connection", "external_website_connection"]},
    "crm": {"label": "CRM", "icon": "▤", "services": ["crm"]},
    "piq": {"label": "ProspectIQ", "icon": "◇", "services": ["piq_access"]},
    "campaigns": {"label": "Campaigns & Social", "icon": "◐", "services": ["campaigns"]},
    "email": {"label": "Email & Activities", "icon": "✉", "services": ["crm", "campaigns"]},
    "forecast": {"label": "Forecasting", "icon": "↗", "services": ["forecasting", "forecasting_management"]},
    "reports": {"label": "Reporting", "icon": "▥", "services": ["management_intelligence", "forecasting_management", "crm"]},
    "training": {"label": "Training", "icon": "▶", "services": ["training", "platform_core"]},
    "organization": {"label": "Team & Settings", "icon": "♙", "services": ["crm", "platform_core"]},
    "solutions": {"label": "Solutions", "icon": "✦", "services": [], "always": True},
}


def active_service_codes(db: Session, tenant_id: str) -> set[str]:
    return set(db.scalars(select(TenantService.service_code).where(
        TenantService.tenant_id == tenant_id,
        TenantService.status == "active",
    )))


def module_access(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    codes = active_service_codes(db, tenant_id)
    result: list[dict[str, Any]] = []
    for key, definition in MODULE_DEFINITIONS.items():
        enabled = bool(definition.get("always")) or any(code in codes for code in definition.get("services", []))
        result.append({
            "key": key,
            "label": definition["label"],
            "icon": definition["icon"],
            "enabled": enabled,
            "required_services": definition.get("services", []),
        })
    return result


def workspace_summary(db: Session, tenant_id: str) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("Tenant not found")
    modules = module_access(db, tenant_id)
    counts = {
        "accounts": db.scalar(select(func.count(Account.id)).where(Account.tenant_id == tenant_id)) or 0,
        "leads": db.scalar(select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id)) or 0,
        "open_opportunities": db.scalar(select(func.count(Opportunity.id)).where(
            Opportunity.tenant_id == tenant_id,
            ~Opportunity.stage.in_(["Closed Won", "Closed Lost"]),
        )) or 0,
        "won_opportunities": db.scalar(select(func.count(Opportunity.id)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage == "Closed Won",
        )) or 0,
        "pipeline_cents": db.scalar(select(func.coalesce(func.sum(Opportunity.value_cents), 0)).where(
            Opportunity.tenant_id == tenant_id,
            ~Opportunity.stage.in_(["Closed Won", "Closed Lost"]),
        )) or 0,
        "piq_records": db.scalar(select(func.count(PiqOpportunity.id)).where(PiqOpportunity.tenant_id == tenant_id)) or 0,
        "piq_in_crm": db.scalar(select(func.count(PiqOpportunity.id)).where(PiqOpportunity.tenant_id == tenant_id, PiqOpportunity.moved_to_crm.is_(True))) or 0,
        "campaigns": db.scalar(select(func.count(Campaign.id)).where(Campaign.tenant_id == tenant_id)) or 0,
        "social_drafts": db.scalar(select(func.count(cb1_models.CB1SocialContent.id)).where(cb1_models.CB1SocialContent.tenant_id == tenant_id)) or 0,
        "emails": db.scalar(select(func.count(cb1_models.CB1Message.id)).where(cb1_models.CB1Message.tenant_id == tenant_id)) or 0,
        "website_pages": db.scalar(select(func.count(WebsitePage.id)).join(WebsiteSite, WebsitePage.site_id == WebsiteSite.id).where(WebsiteSite.tenant_id == tenant_id)) or 0,
        "blog_posts": db.scalar(select(func.count(WebsiteBlogPost.id)).where(WebsiteBlogPost.tenant_id == tenant_id)) or 0,
        "media_assets": db.scalar(select(func.count(WebsiteMedia.id)).where(WebsiteMedia.tenant_id == tenant_id)) or 0,
        "resources": db.scalar(select(func.count(WebsiteResource.id)).where(WebsiteResource.tenant_id == tenant_id)) or 0,
        "appointments": db.scalar(select(func.count(AppointmentRequest.id)).where(AppointmentRequest.tenant_id == tenant_id)) or 0,
        "seo_open": db.scalar(select(func.count(SeoWorkItem.id)).where(SeoWorkItem.tenant_id == tenant_id, SeoWorkItem.status != "complete")) or 0,
    }
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant_id))
    recent = unified_timeline(db, tenant_id, limit=8)
    return {
        "release": RELEASE,
        "tenant": model_dict(tenant),
        "modules": modules,
        "counts": counts,
        "website": model_dict(site) if site else None,
        "recent_activity": recent,
    }


def unified_timeline(db: Session, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    users = {u.id: u.full_name for u in db.scalars(select(User).where(User.tenant_id == tenant_id))}

    for row in db.scalars(select(Activity).where(Activity.tenant_id == tenant_id).order_by(Activity.created_at.desc()).limit(limit)):
        events.append({
            "id": row.id,
            "source": "CRM",
            "type": row.activity_type,
            "title": row.subject or row.activity_type,
            "detail": row.body,
            "actor": users.get(row.user_id or "", "Client user"),
            "created_at": row.created_at.isoformat(),
            "entity_type": "activity",
            "entity_id": row.id,
        })
    for row in db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.desc()).limit(limit)):
        actor = db.get(User, row.actor_user_id) if row.actor_user_id else None
        events.append({
            "id": row.id,
            "source": "Audit",
            "type": row.event_type,
            "title": row.event_type.replace(".", " ").replace("_", " ").title(),
            "detail": "",
            "actor": actor.full_name if actor else "System",
            "created_at": row.created_at.isoformat(),
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
        })
    for row in db.scalars(select(cb1_models.CB1AuditEvent).where(cb1_models.CB1AuditEvent.tenant_id == tenant_id).order_by(cb1_models.CB1AuditEvent.created_at.desc()).limit(limit)):
        events.append({
            "id": row.id,
            "source": "Marketing",
            "type": row.event_type,
            "title": row.event_type.replace("_", " ").title(),
            "detail": "",
            "actor": row.actor_email or "System",
            "created_at": row.created_at.isoformat(),
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
        })
    events.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return events[:limit]


def cross_channel_report(db: Session, tenant_id: str) -> dict[str, Any]:
    summary = workspace_summary(db, tenant_id)
    opportunities = list(db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id)))
    won_cents = sum(o.value_cents for o in opportunities if o.stage == "Closed Won")
    source_counts: dict[str, int] = defaultdict(int)
    source_values: dict[str, int] = defaultdict(int)
    for opportunity in opportunities:
        source = opportunity.source or "Unknown"
        source_counts[source] += 1
        if opportunity.stage == "Closed Won":
            source_values[source] += opportunity.value_cents
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary["counts"],
        "won_revenue_cents": won_cents,
        "attribution": [
            {"source": source, "opportunities": source_counts[source], "won_revenue_cents": source_values[source]}
            for source in sorted(source_counts)
        ],
        "funnel": {
            "website_leads": db.scalar(select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id, Lead.source.like("Website%"))) or 0,
            "piq_records": summary["counts"]["piq_records"],
            "piq_to_crm": summary["counts"]["piq_in_crm"],
            "open_opportunities": summary["counts"]["open_opportunities"],
            "won_opportunities": summary["counts"]["won_opportunities"],
            "social_drafts": summary["counts"]["social_drafts"],
            "emails": summary["counts"]["emails"],
        },
    }
