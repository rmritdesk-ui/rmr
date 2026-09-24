from __future__ import annotations

import hashlib
import json
import re
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import cb1_models
from ..cb1_services import generate_supported_message
from ..config import settings
from ..db import get_db
from ..models import Account, Activity, Campaign, Contact, Lead, Opportunity, PiqOpportunity, SupportAccess, Tenant, User, WebsitePage, WebsiteSite
from ..piq_engine.contracts import PiqProviderError
from ..piq_engine.profile import plan_profile_queries, snapshot_target_profile
from ..piq_models import PiqDiscoveryRun
from ..permissions import (
    is_global_admin,
    require_global_admin,
    require_client_campaign_write,
    require_client_operational_write,
    require_client_website_write,
    require_tenant_access,
)
from ..security import current_user, require_request_origin
from ..services import audit
from ..unified_models import (
    AppointmentRequest,
    PiqEvidence,
    PiqImportBatch,
    PiqTargetProfile,
    SeoWorkItem,
    WebsiteBlogPost,
    WebsiteMedia,
    WebsiteResource,
    WebsiteTeamProfile,
    ManagedTenantSession,
)
from ..unified_services import active_service_codes, cross_channel_report, module_access, unified_timeline, workspace_summary
from ..utils import model_dict, slugify
from .piq_research import router as research_router, ResearchConfirmation, translate as research_translate
from ..piq_engine.research_service import confirm as confirm_research
from .piq_workflow import router as workflow_router, ProfileInput, profile_for, access as piq_access, update_fields

router = APIRouter(prefix="/api", tags=["unified-product"])
router.include_router(research_router)
router.include_router(workflow_router)


def _cb1_dict(row: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        data[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return data


def _require_service(db: Session, tenant_id: str, *codes: str) -> None:
    active = active_service_codes(db, tenant_id)
    if not any(code in active for code in codes):
        raise HTTPException(status_code=403, detail=f"This module is not active for the client. Required service: {', '.join(codes)}")


def _actor_name(user: User) -> str:
    return user.full_name or user.email


class MediaIn(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    media_type: Literal["image", "video", "document", "logo"] = "image"
    url: str = Field(min_length=3, max_length=1000)
    alt_text: str = Field(default="", max_length=300)
    tags: list[str] = Field(default_factory=list)


class BlogIn(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    slug: str = Field(default="", max_length=140)
    summary: str = Field(default="", max_length=500)
    body: str = ""
    status: Literal["draft", "published"] = "draft"
    seo_title: str = Field(default="", max_length=220)
    seo_description: str = Field(default="", max_length=500)
    featured_image_url: str = Field(default="", max_length=1000)


class ResourceIn(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str = ""
    resource_type: str = "guide"
    url: str = Field(min_length=3, max_length=1000)
    lead_capture_required: bool = True
    status: Literal["draft", "published"] = "draft"


class TeamProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    title: str = ""
    bio: str = ""
    email: str = ""
    phone: str = ""
    photo_url: str = ""
    display_order: int = 0
    visible: bool = True


class SeoIn(BaseModel):
    page_id: str | None = None
    item_type: str = "content"
    title: str = Field(min_length=2, max_length=220)
    status: Literal["open", "in_progress", "complete"] = "open"
    priority: Literal["low", "medium", "high"] = "medium"
    recommendation: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class AppointmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=80)
    preferred_time: str = Field(default="", max_length=180)
    message: str = ""


class TargetProfileIn(ProfileInput):
    pass


class DiscoverIn(BaseModel):
    count: int = Field(default=6, ge=1, le=50, strict=True)
    target_profile_id: str | None = Field(default=None, min_length=1, max_length=36)


class ImportRowsIn(BaseModel):
    filename: str = "pasted-list.csv"
    rows: list[dict[str, Any]] = Field(default_factory=list)
    batch_id: str | None = None

class CrmImportRowsIn(ImportRowsIn):
    filename: str = Field(default="pasted-list.csv", max_length=255)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class MergeIn(BaseModel):
    keep_id: str
    merge_id: str


class CrmEmailIn(BaseModel):
    recipient_email: str = Field(min_length=5, max_length=320)
    recipient_name: str = ""
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    account_id: str | None = None
    opportunity_id: str | None = None
    piq_record_id: str | None = None
    supported_facts: list[str] = Field(default_factory=list)
    send_now: bool = True


class SocialGenerateIn(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    message: str = Field(min_length=2)
    call_to_action: str = "Learn more"
    hashtags: list[str] = Field(default_factory=list)


class SocialPublishIn(BaseModel):
    published_url: str = Field(min_length=3, max_length=1000)


class EmailGenerateIn(BaseModel):
    recipient_name: str = ""
    recipient_email: str = Field(min_length=5, max_length=320)
    facts: list[str] = Field(default_factory=list)
    call_to_action: str = "Would a brief conversation be worthwhile?"
    crm_record_id: str | None = None
    piq_record_id: str | None = None


@router.get("/tenants/{tenant_id}/workspace")
def workspace(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    return workspace_summary(db, tenant_id)


@router.get("/tenants/{tenant_id}/modules")
def modules(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    return {"modules": module_access(db, tenant_id), "services": sorted(active_service_codes(db, tenant_id))}


@router.get("/tenants/{tenant_id}/timeline")
def timeline(tenant_id: str, limit: int = 100, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    return {"events": unified_timeline(db, tenant_id, max(1, min(limit, 250)))}


@router.get("/tenants/{tenant_id}/growth-report")
def growth_report(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    return cross_channel_report(db, tenant_id)


@router.get("/tenants/{tenant_id}/website-content")
def website_content(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    _require_service(db, tenant_id, "managed_website", "custom_website_connection", "external_website_connection")
    return {
        "media": [model_dict(x) for x in db.scalars(select(WebsiteMedia).where(WebsiteMedia.tenant_id == tenant_id).order_by(WebsiteMedia.created_at.desc()))],
        "posts": [model_dict(x) for x in db.scalars(select(WebsiteBlogPost).where(WebsiteBlogPost.tenant_id == tenant_id).order_by(WebsiteBlogPost.created_at.desc()))],
        "resources": [model_dict(x) for x in db.scalars(select(WebsiteResource).where(WebsiteResource.tenant_id == tenant_id).order_by(WebsiteResource.created_at.desc()))],
        "team": [model_dict(x) for x in db.scalars(select(WebsiteTeamProfile).where(WebsiteTeamProfile.tenant_id == tenant_id).order_by(WebsiteTeamProfile.display_order, WebsiteTeamProfile.full_name))],
        "seo": [model_dict(x) for x in db.scalars(select(SeoWorkItem).where(SeoWorkItem.tenant_id == tenant_id).order_by(SeoWorkItem.created_at.desc()))],
        "appointments": [model_dict(x) for x in db.scalars(select(AppointmentRequest).where(AppointmentRequest.tenant_id == tenant_id).order_by(AppointmentRequest.created_at.desc()).limit(100))],
    }


@router.post("/tenants/{tenant_id}/website-media")
def create_media(tenant_id: str, payload: MediaIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_website_write(user, tenant_id); _require_service(db, tenant_id, "managed_website", "custom_website_connection", "external_website_connection")
    row = WebsiteMedia(tenant_id=tenant_id, title=payload.title, media_type=payload.media_type, url=payload.url, alt_text=payload.alt_text, tags_json=payload.tags, created_by=user.id)
    db.add(row); db.flush(); audit(db, user, "website.media.created", tenant_id=tenant_id, entity_type="website_media", entity_id=row.id); db.commit()
    return {"media": model_dict(row)}


@router.post("/tenants/{tenant_id}/blog-posts")
def create_blog(tenant_id: str, payload: BlogIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_website_write(user, tenant_id); _require_service(db, tenant_id, "managed_website")
    slug = slugify(payload.slug or payload.title)
    if db.scalar(select(WebsiteBlogPost).where(WebsiteBlogPost.tenant_id == tenant_id, WebsiteBlogPost.slug == slug)):
        raise HTTPException(status_code=409, detail="A blog post with this URL slug already exists")
    row = WebsiteBlogPost(tenant_id=tenant_id, title=payload.title, slug=slug, summary=payload.summary, body=payload.body, status=payload.status, seo_title=payload.seo_title, seo_description=payload.seo_description, featured_image_url=payload.featured_image_url, published_at=datetime.now(timezone.utc) if payload.status == "published" else None, created_by=user.id)
    db.add(row); db.flush(); audit(db, user, "website.blog.created", tenant_id=tenant_id, entity_type="blog_post", entity_id=row.id, data={"status": row.status}); db.commit()
    return {"post": model_dict(row)}


@router.patch("/blog-posts/{post_id}")
def update_blog(post_id: str, payload: BlogIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = db.get(WebsiteBlogPost, post_id)
    if not row: raise HTTPException(status_code=404, detail="Blog post not found")
    require_client_website_write(user, row.tenant_id)
    for key in ["title", "summary", "body", "status", "seo_title", "seo_description", "featured_image_url"]: setattr(row, key, getattr(payload, key))
    row.slug = slugify(payload.slug or payload.title); row.published_at = datetime.now(timezone.utc) if row.status == "published" and not row.published_at else row.published_at
    audit(db, user, "website.blog.updated", tenant_id=row.tenant_id, entity_type="blog_post", entity_id=row.id, data={"status": row.status}); db.commit()
    return {"post": model_dict(row)}


@router.post("/tenants/{tenant_id}/website-resources")
def create_resource(tenant_id: str, payload: ResourceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_website_write(user, tenant_id)
    row = WebsiteResource(tenant_id=tenant_id, title=payload.title, description=payload.description, resource_type=payload.resource_type, url=payload.url, lead_capture_required=payload.lead_capture_required, status=payload.status, created_by=user.id)
    db.add(row); db.flush(); audit(db, user, "website.resource.created", tenant_id=tenant_id, entity_type="website_resource", entity_id=row.id); db.commit()
    return {"resource": model_dict(row)}


@router.post("/tenants/{tenant_id}/website-team")
def create_team_profile(tenant_id: str, payload: TeamProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_website_write(user, tenant_id)
    row = WebsiteTeamProfile(tenant_id=tenant_id, **payload.model_dump())
    db.add(row); db.flush(); audit(db, user, "website.team.created", tenant_id=tenant_id, entity_type="website_team_profile", entity_id=row.id); db.commit()
    return {"profile": model_dict(row)}


@router.post("/tenants/{tenant_id}/seo-items")
def create_seo(tenant_id: str, payload: SeoIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_website_write(user, tenant_id)
    row = SeoWorkItem(tenant_id=tenant_id, page_id=payload.page_id, item_type=payload.item_type, title=payload.title, status=payload.status, priority=payload.priority, recommendation=payload.recommendation, evidence_json=payload.evidence, created_by=user.id, completed_at=datetime.now(timezone.utc) if payload.status == "complete" else None)
    db.add(row); db.flush(); audit(db, user, "seo.item.created", tenant_id=tenant_id, entity_type="seo_work_item", entity_id=row.id); db.commit()
    return {"item": model_dict(row)}


@router.patch("/seo-items/{item_id}")
def update_seo(item_id: str, payload: SeoIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = db.get(SeoWorkItem, item_id)
    if not row: raise HTTPException(status_code=404, detail="SEO item not found")
    require_client_website_write(user, row.tenant_id)
    for key, value in payload.model_dump().items():
        setattr(row, "evidence_json" if key == "evidence" else key, value)
    row.completed_at = datetime.now(timezone.utc) if row.status == "complete" else None
    audit(db, user, "seo.item.updated", tenant_id=row.tenant_id, entity_type="seo_work_item", entity_id=row.id, data={"status": row.status}); db.commit()
    return {"item": model_dict(row)}


@router.post("/public/sites/{site_slug}/appointments")
def public_appointment(site_slug: str, payload: AppointmentIn, request: Request, db: Session = Depends(get_db)):
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.slug == site_slug))
    if not site: raise HTTPException(status_code=404, detail="Website not found")
    lead = Lead(tenant_id=site.tenant_id, company_name="", contact_name=payload.name, email=payload.email, phone=payload.phone, source="Website Appointment Request", status="New", notes=f"Preferred time: {payload.preferred_time}\n{payload.message}")
    db.add(lead); db.flush()
    row = AppointmentRequest(tenant_id=site.tenant_id, name=payload.name, email=payload.email, phone=payload.phone, preferred_time=payload.preferred_time, message=payload.message, lead_id=lead.id)
    db.add(row); db.flush(); audit(db, None, "website.appointment.created", tenant_id=site.tenant_id, entity_type="appointment_request", entity_id=row.id, data={"source_ip": request.client.host if request.client else ""}); db.commit()
    return {"ok": True, "request_id": row.id, "lead_id": lead.id}


@router.get("/tenants/{tenant_id}/piq/target-profile")
def get_target(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    row = profile_for(db, tenant_id)
    return {"profile": model_dict(row) if row else None}


@router.put("/tenants/{tenant_id}/piq/target-profile")
def save_target(tenant_id: str, payload: TargetProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_operational_write(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    row = profile_for(db, tenant_id)
    if not row:
        row = PiqTargetProfile(tenant_id=tenant_id, created_by=user.id); db.add(row)
    row.name=payload.name; row.industries_json=payload.industries; row.locations_json=payload.locations; row.employee_min=payload.employee_min; row.employee_max=payload.employee_max; row.revenue_min_cents=payload.revenue_min_cents; row.keywords_json=payload.keywords; row.exclusions_json=payload.exclusions
    db.flush(); audit(db, user, "piq.target.saved", tenant_id=tenant_id, entity_type="piq_target_profile", entity_id=row.id); db.commit()
    return {"profile": model_dict(row)}


DEMO_COMPANIES = [
    ("Summit Property Partners", "Expanding into two new Arizona communities", 91, 2400000),
    ("Copper State Home Lending", "Hiring loan officers and increasing regional advertising", 87, 1750000),
    ("Sonoran Title & Escrow", "Opened a new West Valley office", 83, 950000),
    ("Desert Bloom Senior Living", "Announced a multi-site growth initiative", 80, 1200000),
    ("Pinnacle Commercial Realty", "Recently added a property-management division", 78, 2100000),
    ("Canyon Ridge Insurance", "Launching a homeowner acquisition campaign", 75, 825000),
    ("Mesa Valley Builders", "New permits indicate upcoming residential inventory", 73, 3000000),
    ("Arizona Relocation Services", "Partnership announcements show increased referral activity", 70, 600000),
]


@router.post("/tenants/{tenant_id}/piq/discover")
def discover(tenant_id: str, payload: DiscoverIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_operational_write(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    profile = profile_for(db, tenant_id, payload.target_profile_id, active=True)
    if not profile: raise HTTPException(status_code=400, detail="Create a target profile before running discovery")
    if settings.piq_live_discovery_enabled:
        if settings.piq_discovery_provider != "google_places":
            raise HTTPException(status_code=503, detail="Live PIQ discovery provider is not configured")
        if not settings.google_places_api_key:
            raise HTTPException(status_code=503, detail="Google Places is not configured for live discovery")
        profile_snapshot = snapshot_target_profile(profile)
        try:
            plan_profile_queries(profile_snapshot, max_queries=settings.piq_max_queries_per_run)
        except PiqProviderError as exc:
            raise HTTPException(status_code=400, detail=exc.public_message) from exc
        if payload.count > settings.piq_max_results_per_run:
            raise HTTPException(status_code=422, detail="Requested count exceeds the configured discovery limit")
        requested_count = payload.count
        managed_session_id = None
        if is_global_admin(user):
            managed_session_id = db.scalar(select(ManagedTenantSession.id).where(
                ManagedTenantSession.id == getattr(user, "_managed_session_id", None),
                ManagedTenantSession.admin_user_id == user.id,
                ManagedTenantSession.tenant_id == tenant_id,
                ManagedTenantSession.access_type == "managed_write",
                ManagedTenantSession.status == "active",
                ManagedTenantSession.expires_at > datetime.now(timezone.utc),
            ))
            if not managed_session_id:
                raise HTTPException(status_code=403, detail="An active tenant-bound managed write session is required")
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if len(idempotency_key) > 120:
            raise HTTPException(status_code=422, detail="Idempotency-Key must be at most 120 characters")
        if idempotency_key:
            existing_run = db.scalar(select(PiqDiscoveryRun).where(
                PiqDiscoveryRun.tenant_id == tenant_id,
                PiqDiscoveryRun.idempotency_key == idempotency_key,
            ))
            if existing_run:
                if existing_run.requested_count != requested_count or existing_run.profile_snapshot_json != profile_snapshot:
                    raise HTTPException(status_code=409, detail="Idempotency-Key was already used for different discovery inputs")
                return JSONResponse(status_code=202, content={
                    "run_id": existing_run.id,
                    "status": existing_run.status,
                    "provider_mode": existing_run.provider,
                    "requested_count": existing_run.requested_count,
                })
        run = PiqDiscoveryRun(
            tenant_id=tenant_id,
            target_profile_id=profile.id,
            requested_by=user.id,
            managed_session_id=managed_session_id,
            provider="google_places",
            status="queued",
            idempotency_key=idempotency_key or uuid.uuid4().hex,
            requested_count=requested_count,
            profile_snapshot_json=profile_snapshot,
            diagnostics_json={"provider": "google_places", "phase": "candidate_discovery"},
        )
        db.add(run)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            prior = db.scalar(select(PiqDiscoveryRun).where(
                PiqDiscoveryRun.tenant_id == tenant_id,
                PiqDiscoveryRun.idempotency_key == idempotency_key,
            )) if idempotency_key else None
            if prior is None:
                raise
            if prior.requested_count != requested_count or prior.profile_snapshot_json != profile_snapshot:
                raise HTTPException(status_code=409, detail="Idempotency-Key was already used for different discovery inputs")
            return JSONResponse(status_code=202, content={
                "run_id": prior.id, "status": prior.status,
                "provider_mode": prior.provider, "requested_count": prior.requested_count,
            })
        audit(db,user,"piq.discovery.queued",tenant_id=tenant_id,entity_type="piq_discovery_run",entity_id=run.id,data={"provider":"google_places","requested_count":requested_count}); db.commit()
        return JSONResponse(status_code=202, content={
            "run_id": run.id,
            "status": run.status,
            "provider_mode": run.provider,
            "requested_count": run.requested_count,
        })
    existing = {x.lower() for x in db.scalars(select(PiqOpportunity.company_name).where(PiqOpportunity.tenant_id == tenant_id))}
    created=[]
    for company, signal, score, value in DEMO_COMPANIES:
        if len(created) >= payload.count: break
        if company.lower() in existing: continue
        row=PiqOpportunity(tenant_id=tenant_id, target_profile_id=profile.id, provider="demonstration", company_name=company, score=score, signal=signal, evidence_count=2, estimated_value_cents=value, status="Priority", enhancement_price_cents=400)
        db.add(row); db.flush()
        db.add_all([
            PiqEvidence(opportunity_id=row.id, evidence_type="growth_signal", source_name="RMR Demonstration Discovery Provider", source_url="https://example.com/demo-source", fact=signal, confidence_pct=min(score,95), verified=True),
            PiqEvidence(opportunity_id=row.id, evidence_type="profile_match", source_name="RMR Target Profile", fact=f"Matched {', '.join(profile.industries_json or ['target industries'])} in {', '.join(profile.locations_json or ['target geography'])}", confidence_pct=max(score-8,60), verified=True),
        ])
        created.append(row)
    audit(db,user,"piq.discovery.completed",tenant_id=tenant_id,entity_type="piq_target_profile",entity_id=profile.id,data={"created":len(created),"provider":"demo"}); db.commit()
    return {"provider_mode":"demonstration","created":[model_dict(x) for x in created]}


@router.get("/tenants/{tenant_id}/piq/discovery-runs/active")
def active_discovery_run(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db), target_profile_id: str | None = None):
    require_tenant_access(user, tenant_id)
    _require_service(db, tenant_id, "piq_access")
    run = db.scalar(select(PiqDiscoveryRun).where(
        PiqDiscoveryRun.tenant_id == tenant_id,
        PiqDiscoveryRun.provider == "google_places",
        PiqDiscoveryRun.status.in_(("queued", "running", "retry_wait")),
        *([PiqDiscoveryRun.target_profile_id == target_profile_id] if target_profile_id else []),
    ).order_by(PiqDiscoveryRun.created_at.desc(), PiqDiscoveryRun.id.desc()).limit(1))
    return {"run": discovery_run_status(tenant_id, run.id, user, db) if run else None}


@router.get("/tenants/{tenant_id}/piq/discovery-runs/{run_id}")
def discovery_run_status(tenant_id: str, run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    run = db.scalar(select(PiqDiscoveryRun).where(
        PiqDiscoveryRun.id == run_id,
        PiqDiscoveryRun.tenant_id == tenant_id,
    ))
    if not run: raise HTTPException(status_code=404, detail="PIQ discovery run not found")
    return {
        "run_id": run.id,
        "target_profile_id": run.target_profile_id,
        "status": run.status,
        "provider_mode": run.provider,
        "requested_count": run.requested_count,
        "result_count": run.result_count,
        "attempt_count": run.attempt_count,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "diagnostics": {key: value for key, value in (run.diagnostics_json or {}).items() if key in {
            "provider", "api_mode", "planned_query_count", "executed_query_count", "page_count",
            "details_request_count", "provider_candidate_count", "unique_candidate_count",
            "created_count", "duplicate_count", "issues", "employee_revenue_filters_applied",
            "scoring_version", "candidates_received", "duplicates_skipped", "rejected", "qualified", "persisted", "provider_errors",
            "rejection_summary", "evaluated_count", "candidate_budget", "retained_limit",
        }},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.post("/tenants/{tenant_id}/piq/import-preview")
def piq_import_preview(tenant_id: str, payload: ImportRowsIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_operational_write(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    existing={x.lower() for x in db.scalars(select(PiqOpportunity.company_name).where(PiqOpportunity.tenant_id==tenant_id))}
    preview=[]; duplicates=errors=0
    for index,row in enumerate(payload.rows,1):
        name=str(row.get("company_name") or row.get("company") or "").strip()
        if not name: preview.append({"row":index,"status":"error","message":"Company name is required","input":row}); errors+=1; continue
        duplicate=name.lower() in existing
        preview.append({"row":index,"status":"duplicate" if duplicate else "ready","company_name":name,"signal":str(row.get("signal") or "Imported prospect"),"score":int(row.get("score") or 60),"estimated_value_cents":int(row.get("estimated_value_cents") or 0)})
        if duplicate: duplicates+=1
    batch=PiqImportBatch(tenant_id=tenant_id,filename=payload.filename,row_count=len(payload.rows),duplicate_count=duplicates,error_count=errors,accepted_count=0,preview_json=preview,created_by=user.id)
    db.add(batch); db.commit(); return {"batch":model_dict(batch),"preview":preview}


@router.post("/tenants/{tenant_id}/piq/import")
def piq_import_commit(tenant_id: str, payload: ImportRowsIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_operational_write(user, tenant_id); _require_service(db, tenant_id, "piq_access")
    batch=db.get(PiqImportBatch,payload.batch_id) if payload.batch_id else None
    rows=batch.preview_json if batch else payload.rows
    created=[]
    for row in rows:
        if row.get("status") not in {None,"ready"}: continue
        name=str(row.get("company_name") or row.get("company") or "").strip()
        if not name: continue
        if db.scalar(select(PiqOpportunity).where(PiqOpportunity.tenant_id==tenant_id,func.lower(PiqOpportunity.company_name)==name.lower())): continue
        item=PiqOpportunity(tenant_id=tenant_id,company_name=name,score=max(0,min(int(row.get("score") or 60),100)),signal=str(row.get("signal") or "Imported prospect"),evidence_count=1,estimated_value_cents=max(0,int(row.get("estimated_value_cents") or 0)),status="Imported",enhancement_price_cents=400)
        db.add(item);db.flush();db.add(PiqEvidence(opportunity_id=item.id,evidence_type="client_import",source_name=payload.filename,fact=item.signal,confidence_pct=70,verified=False));created.append(item)
    if batch: batch.status="committed";batch.accepted_count=len(created)
    audit(db,user,"piq.import.completed",tenant_id=tenant_id,entity_type="piq_import_batch",entity_id=batch.id if batch else "",data={"created":len(created)});db.commit()
    return {"created":[model_dict(x) for x in created],"count":len(created)}


@router.get("/piq/{opportunity_id}/profile")
def piq_profile(opportunity_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row=db.get(PiqOpportunity,opportunity_id)
    if not row: raise HTTPException(status_code=404,detail="ProspectIQ record not found")
    piq_access(db,user,row.tenant_id)
    evidence=list(db.scalars(select(PiqEvidence).where(PiqEvidence.opportunity_id==row.id).order_by(PiqEvidence.observed_at.desc())))
    from .piq_workflow import research_state
    from ..piq_models import PiqProfileMatch
    match = db.scalar(select(PiqProfileMatch).where(
        PiqProfileMatch.tenant_id == row.tenant_id,
        PiqProfileMatch.opportunity_id == row.id,
        PiqProfileMatch.target_profile_id == row.target_profile_id,
    ).order_by(PiqProfileMatch.created_at.desc(), PiqProfileMatch.id.desc()).limit(1))
    # Present persisted deterministic criteria, never raw model reasoning.
    evidence_rows = []
    for item in evidence:
        value = model_dict(item)
        effect = (item.raw_json or {}).get("effect")
        value["score_effect"] = effect if item.provider == "openai_research" and type(effect) is int else None
        evidence_rows.append(value)
    return {"opportunity":model_dict(row),"evidence":evidence_rows,
            "match":model_dict(match) if match else None,
            "research":research_state(db,user,row)}


@router.post("/piq/{opportunity_id}/adaptive-research")
def adaptive_research(opportunity_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db), payload: dict[str, Any] | None = None):
    require_request_origin(request)
    if getattr(settings, "piq_live_research_enabled", False):
        if payload is None:
            raise HTTPException(422, "A research estimate and confirmation are required")
        try:
            confirmation = ResearchConfirmation.model_validate(payload)
        except ValidationError:
            raise HTTPException(422, "Invalid research confirmation") from None
        result = research_translate(lambda: confirm_research(db, user, opportunity_id, confirmation, settings))
        return JSONResponse(result, status_code=202)
    row=db.get(PiqOpportunity,opportunity_id)
    if not row: raise HTTPException(status_code=404,detail="ProspectIQ record not found")
    require_client_operational_write(user,row.tenant_id); _require_service(db,row.tenant_id,"piq_access")
    facts=[
        f"Recent public signals support the existing opportunity summary for {row.company_name}.",
        "The organization shows evidence of active growth or customer-acquisition investment.",
        "Human review is required before relying on this profile for outreach.",
    ]
    for fact in facts: db.add(PiqEvidence(opportunity_id=row.id,evidence_type="adaptive_research",source_name="RMR Demonstration Research Provider",source_url="https://example.com/demo-research",fact=fact,confidence_pct=82,verified=True))
    row.enhanced=True; row.evidence_count=(row.evidence_count or 0)+len(facts); row.score=min(100,(row.score or 0)+5); row.status="Enhanced"
    audit(db,user,"piq.adaptive_research.completed",tenant_id=row.tenant_id,entity_type="piq_opportunity",entity_id=row.id,data={"provider":"demo","facts":len(facts)});db.commit()
    return {"opportunity":model_dict(row),"facts":facts,"provider_mode":"demonstration"}


@router.get("/tenants/{tenant_id}/crm/search")
def crm_search(tenant_id: str, q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user,tenant_id);needle=f"%{q.strip()}%"
    accounts=list(db.scalars(select(Account).where(Account.tenant_id==tenant_id,Account.name.ilike(needle)).limit(25))) if q.strip() else []
    contacts=list(db.scalars(select(Contact).where(Contact.tenant_id==tenant_id,or_(Contact.first_name.ilike(needle),Contact.last_name.ilike(needle),Contact.email.ilike(needle))).limit(25))) if q.strip() else []
    leads=list(db.scalars(select(Lead).where(Lead.tenant_id==tenant_id,or_(Lead.company_name.ilike(needle),Lead.contact_name.ilike(needle),Lead.email.ilike(needle))).limit(25))) if q.strip() else []
    opportunities=list(db.scalars(select(Opportunity).where(Opportunity.tenant_id==tenant_id,Opportunity.name.ilike(needle)).limit(25))) if q.strip() else []
    return {"accounts":[model_dict(x) for x in accounts],"contacts":[model_dict(x) for x in contacts],"leads":[model_dict(x) for x in leads],"opportunities":[model_dict(x) for x in opportunities]}


@router.get("/tenants/{tenant_id}/crm/duplicates")
def crm_duplicates(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user,tenant_id)
    rows=list(db.execute(select(func.lower(Account.name),func.count(Account.id)).where(Account.tenant_id==tenant_id).group_by(func.lower(Account.name)).having(func.count(Account.id)>1)))
    groups=[]
    for normalized,count in rows:
        items=list(db.scalars(select(Account).where(Account.tenant_id==tenant_id,func.lower(Account.name)==normalized)))
        groups.append({"normalized_name":normalized,"count":count,"accounts":[model_dict(x) for x in items]})
    return {"groups":groups}


@router.post("/tenants/{tenant_id}/crm/merge-accounts")
def merge_accounts(tenant_id: str, payload: MergeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request); require_client_operational_write(user,tenant_id)
    keep=db.get(Account,payload.keep_id);merge=db.get(Account,payload.merge_id)
    if not keep or not merge or keep.tenant_id!=tenant_id or merge.tenant_id!=tenant_id or keep.id==merge.id: raise HTTPException(status_code=400,detail="Select two valid accounts in this tenant")
    for model in (Contact,Opportunity,Activity):
        for row in db.scalars(select(model).where(model.account_id==merge.id)): row.account_id=keep.id
    keep.notes=(keep.notes+"\n" if keep.notes else "")+f"Merged account: {merge.name}"
    db.delete(merge);audit(db,user,"crm.account.merged",tenant_id=tenant_id,entity_type="account",entity_id=keep.id,data={"merged_id":payload.merge_id});db.commit();return {"account":model_dict(keep)}


@router.post("/tenants/{tenant_id}/crm/import-preview")
def crm_import_preview(tenant_id: str,payload:CrmImportRowsIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);require_client_operational_write(user,tenant_id)
    return _crm_import_preview(db, tenant_id, payload.rows)


def _crm_import_preview(db: Session, tenant_id: str, rows: list[dict[str, Any]]) -> dict:
    # Syntax-only validation: import must never need DNS or an external service.
    email_pattern = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
    normalize = lambda value: str(value or "").strip().casefold()
    existing_accounts = {normalize(x) for x in db.scalars(select(Account.name).where(Account.tenant_id == tenant_id))}
    existing_leads = list(db.execute(select(Lead.company_name, Lead.contact_name, Lead.email).where(Lead.tenant_id == tenant_id)))
    existing_emails = {normalize(x.email) for x in existing_leads if x.email}
    existing_emails.update(normalize(x) for x in db.scalars(select(Contact.email).where(Contact.tenant_id == tenant_id, Contact.email != "")))
    existing_names = {(normalize(x.company_name), normalize(x.contact_name)) for x in existing_leads}
    seen_emails, seen_names = set(), set()
    preview=[]
    for i,row in enumerate(rows,1):
        company=str(row.get("company_name") or row.get("company") or "").strip()
        contact=str(row.get("contact_name") or "").strip()
        email=str(row.get("email") or "").strip().lower()
        phone=str(row.get("phone") or "").strip()
        source=str(row.get("source") or "Imported List").strip()
        errors=[]
        if not company:errors.append("Company is required")
        if email and not re.fullmatch(email_pattern,email): errors.append("Enter a valid email address")
        for label,value,limit in [("Company",company,200),("Contact name",contact,160),("Email",email,255),("Phone",phone,80),("Source",source,80)]:
            if len(value)>limit: errors.append(f"{label} exceeds {limit} characters")
        key=(normalize(company),normalize(contact))
        reason=""
        if not errors:
            if normalize(company) in existing_accounts or (email and email in existing_emails) or (not email and key in existing_names):
                reason="Already in this client's CRM"
            elif (email and email in seen_emails) or (not email and key in seen_names):
                reason="Duplicate within this import"
            if not reason:
                if email: seen_emails.add(email)
                seen_names.add(key)
        preview.append({"row":i,"status":"error" if errors else "duplicate" if reason else "ready","type":"lead","company_name":company,"contact_name":contact,"email":email,"phone":phone,"source":source,"errors":errors,"duplicate_reason":reason})
    return {"preview":preview,"ready":sum(1 for x in preview if x["status"]=="ready"),"duplicates":sum(1 for x in preview if x["status"]=="duplicate"),"errors":sum(1 for x in preview if x["status"]=="error")}


@router.post("/tenants/{tenant_id}/crm/import")
def crm_import(tenant_id: str,payload:CrmImportRowsIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);require_client_operational_write(user,tenant_id);created=0
    result = _crm_import_preview(db, tenant_id, payload.rows)
    for row in result["preview"]:
        if row["status"] != "ready": continue
        db.add(Lead(tenant_id=tenant_id,company_name=row["company_name"],contact_name=row["contact_name"],email=row["email"],phone=row["phone"],source=row["source"],status="New",assigned_user_id=user.id));created+=1
    audit(db,user,"crm.import.completed",tenant_id=tenant_id,entity_type="lead",data={"created":created,"filename":payload.filename});db.commit()
    return {"created":created,"duplicates":result["duplicates"],"errors":result["errors"],"skipped":result["duplicates"]+result["errors"]}


@router.get("/tenants/{tenant_id}/email-status")
def email_status(tenant_id: str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_tenant_access(user,tenant_id)
    rows=list(db.scalars(select(cb1_models.CB1ProviderConnection).where(cb1_models.CB1ProviderConnection.tenant_id==tenant_id)))
    return {"provider_mode":settings.payment_provider if False else "mock" if not rows else "configured","connections":[_cb1_dict(x) for x in rows]}


@router.post("/tenants/{tenant_id}/crm/email")
def crm_email(tenant_id: str,payload:CrmEmailIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);require_client_operational_write(user,tenant_id);_require_service(db,tenant_id,"crm")
    if payload.account_id:
        account=db.get(Account,payload.account_id)
        if not account or account.tenant_id!=tenant_id:raise HTTPException(status_code=400,detail="Account is not in this tenant")
    message=cb1_models.CB1Message(tenant_id=tenant_id,campaign_id=None,crm_record_id=payload.opportunity_id or payload.account_id,piq_record_id=payload.piq_record_id,recipient_email=payload.recipient_email.lower(),subject=payload.subject,body_draft=payload.body,body_approved=payload.body,approved_hash=hashlib.sha256((payload.subject+"\n"+payload.body).encode()).hexdigest(),status="SENT" if payload.send_now else "APPROVED",approved_by=user.id,approved_at=datetime.now(timezone.utc),sent_at=datetime.now(timezone.utc) if payload.send_now else None,idempotency_key=hashlib.sha256(f"{tenant_id}:{payload.recipient_email}:{payload.subject}:{uuid.uuid4()}".encode()).hexdigest(),supported_facts_json=json.dumps(payload.supported_facts),created_by=user.id)
    db.add(message);db.flush()
    activity=Activity(tenant_id=tenant_id,account_id=payload.account_id,opportunity_id=payload.opportunity_id,user_id=user.id,activity_type="Email",subject=payload.subject,body=f"To: {payload.recipient_email}\n\n{payload.body}",completed_at=datetime.now(timezone.utc) if payload.send_now else None)
    db.add(activity);db.flush();audit(db,user,"crm.email.sent" if payload.send_now else "crm.email.approved",tenant_id=tenant_id,entity_type="activity",entity_id=activity.id,data={"message_id":message.id,"recipient":payload.recipient_email,"provider_mode":"mock"});db.commit()
    return {"message":_cb1_dict(message),"activity":model_dict(activity),"provider_mode":"mock"}


@router.get("/tenants/{tenant_id}/marketing")
def marketing(tenant_id: str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_tenant_access(user,tenant_id);_require_service(db,tenant_id,"campaigns")
    return {
        "campaigns":[model_dict(x) for x in db.scalars(select(Campaign).where(Campaign.tenant_id==tenant_id).order_by(Campaign.created_at.desc()))],
        "social":[_cb1_dict(x) for x in db.scalars(select(cb1_models.CB1SocialContent).where(cb1_models.CB1SocialContent.tenant_id==tenant_id).order_by(cb1_models.CB1SocialContent.created_at.desc()))],
        "messages":[_cb1_dict(x) for x in db.scalars(select(cb1_models.CB1Message).where(cb1_models.CB1Message.tenant_id==tenant_id).order_by(cb1_models.CB1Message.created_at.desc()).limit(100))],
        "providers":[_cb1_dict(x) for x in db.scalars(select(cb1_models.CB1ProviderConnection).where(cb1_models.CB1ProviderConnection.tenant_id==tenant_id))],
    }


@router.post("/tenants/{tenant_id}/marketing/generate-social")
def generate_social(tenant_id: str,payload:SocialGenerateIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);require_client_campaign_write(user,tenant_id);_require_service(db,tenant_id,"campaigns")
    tags=" ".join("#"+re.sub(r"[^A-Za-z0-9]","",x) for x in payload.hashtags if x.strip())
    variants={
        "FACEBOOK":f"{payload.message}\n\n{payload.call_to_action}",
        "INSTAGRAM":f"{payload.message}\n\n{payload.call_to_action}\n\n{tags}",
        "LINKEDIN":f"{payload.title}\n\n{payload.message}\n\n{payload.call_to_action}",
        "X":(f"{payload.message} {payload.call_to_action} {tags}")[:280],
    }
    rows=[]
    for platform,text in variants.items():
        row=cb1_models.CB1SocialContent(tenant_id=tenant_id,platform=platform,title=payload.title,post_text=text,hashtags=tags,status="DRAFT",created_by=user.id);db.add(row);db.flush();rows.append(row)
    audit(db,user,"marketing.social.generated",tenant_id=tenant_id,entity_type="social_content",data={"platforms":list(variants)});db.commit();return {"items":[_cb1_dict(x) for x in rows]}


@router.post("/social-content/{item_id}/published")
def mark_social_published(item_id: str,payload:SocialPublishIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);row=db.get(cb1_models.CB1SocialContent,item_id)
    if not row:raise HTTPException(status_code=404,detail="Social content not found")
    require_client_campaign_write(user,row.tenant_id);row.status="PUBLISHED_MANUALLY";row.published_url=payload.published_url;row.published_at=datetime.now(timezone.utc);row.updated_at=datetime.now(timezone.utc);audit(db,user,"marketing.social.published",tenant_id=row.tenant_id,entity_type="social_content",entity_id=row.id,data={"url":payload.published_url});db.commit();return {"item":_cb1_dict(row)}


@router.post("/tenants/{tenant_id}/marketing/generate-email")
def generate_email(tenant_id: str,payload:EmailGenerateIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_request_origin(request);require_client_campaign_write(user,tenant_id);_require_service(db,tenant_id,"campaigns")
    tenant=db.get(Tenant,tenant_id);draft=generate_supported_message(tenant.name if tenant else "Client",payload.recipient_name,payload.facts,"professional",payload.call_to_action)
    return {"draft":draft,"recipient_email":payload.recipient_email,"crm_record_id":payload.crm_record_id,"piq_record_id":payload.piq_record_id}


def _owned_row(db: Session, model, row_id: str, tenant_id: str | None = None):
    row = db.get(model, row_id)
    if not row or (tenant_id and str(getattr(row, "tenant_id", "")) != str(tenant_id)):
        raise HTTPException(status_code=404, detail="Record not found")
    return row


@router.post("/tenants/{tenant_id}/website-media/upload")
async def upload_media(
    tenant_id: str,
    request: Request,
    title: str = Form(...),
    alt_text: str = Form(""),
    tags: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_client_website_write(user, tenant_id)
    _require_service(db, tenant_id, "managed_website", "custom_website_connection", "external_website_connection")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", Path(file.filename or "upload").name).strip(".-") or "upload"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf", ".mp4", ".mov"}:
        raise HTTPException(status_code=400, detail="Unsupported media type")
    media_dir = settings.data_dir / "media" / tenant_id
    media_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:12]}-{safe_name}"
    destination = media_dir / stored_name
    with destination.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    content_type = (file.content_type or "").lower()
    media_type = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else "document"
    row = WebsiteMedia(
        tenant_id=tenant_id,
        title=title.strip() or safe_name,
        media_type=media_type,
        url=f"/sites/media/{tenant_id}/{stored_name}",
        alt_text=alt_text.strip(),
        tags_json=[x.strip() for x in tags.split(",") if x.strip()],
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    audit(db, user, "website.media.uploaded", tenant_id=tenant_id, entity_type="website_media", entity_id=row.id, data={"filename": safe_name, "media_type": media_type})
    db.commit()
    return {"media": model_dict(row)}


@router.get("/sites/media/{tenant_id}/{filename}", include_in_schema=False)
def public_media(tenant_id: str, filename: str):
    safe_name = Path(filename).name
    path = settings.data_dir / "media" / tenant_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path)


@router.delete("/website-media/{media_id}")
def delete_media(media_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteMedia, media_id)
    require_client_website_write(user, row.tenant_id)
    if row.url.startswith("/sites/media/"):
        parts = row.url.rsplit("/", 1)
        path = settings.data_dir / "media" / row.tenant_id / Path(parts[-1]).name
        if path.exists():
            path.unlink()
    tenant_id = row.tenant_id
    db.delete(row)
    audit(db, user, "website.media.deleted", tenant_id=tenant_id, entity_type="website_media", entity_id=media_id)
    db.commit()
    return {"ok": True}


@router.delete("/blog-posts/{post_id}")
def delete_blog(post_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteBlogPost, post_id)
    require_client_website_write(user, row.tenant_id)
    tenant_id = row.tenant_id
    db.delete(row)
    audit(db, user, "website.blog.deleted", tenant_id=tenant_id, entity_type="blog_post", entity_id=post_id)
    db.commit()
    return {"ok": True}


@router.patch("/website-resources/{resource_id}")
def update_resource(resource_id: str, payload: ResourceIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteResource, resource_id)
    require_client_website_write(user, row.tenant_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, user, "website.resource.updated", tenant_id=row.tenant_id, entity_type="website_resource", entity_id=row.id)
    db.commit()
    return {"resource": model_dict(row)}


@router.delete("/website-resources/{resource_id}")
def delete_resource(resource_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteResource, resource_id)
    require_client_website_write(user, row.tenant_id)
    tenant_id = row.tenant_id
    db.delete(row)
    audit(db, user, "website.resource.deleted", tenant_id=tenant_id, entity_type="website_resource", entity_id=resource_id)
    db.commit()
    return {"ok": True}


@router.patch("/website-team/{profile_id}")
def update_team_profile(profile_id: str, payload: TeamProfileIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteTeamProfile, profile_id)
    require_client_website_write(user, row.tenant_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, user, "website.team.updated", tenant_id=row.tenant_id, entity_type="website_team_profile", entity_id=row.id)
    db.commit()
    return {"profile": model_dict(row)}


@router.delete("/website-team/{profile_id}")
def delete_team_profile(profile_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, WebsiteTeamProfile, profile_id)
    require_client_website_write(user, row.tenant_id)
    tenant_id = row.tenant_id
    db.delete(row)
    audit(db, user, "website.team.deleted", tenant_id=tenant_id, entity_type="website_team_profile", entity_id=profile_id)
    db.commit()
    return {"ok": True}


class AppointmentStatusIn(BaseModel):
    status: Literal["new", "contacted", "scheduled", "complete", "closed"]


@router.patch("/appointments/{request_id}")
def update_appointment(request_id: str, payload: AppointmentStatusIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = _owned_row(db, AppointmentRequest, request_id)
    require_client_operational_write(user, row.tenant_id)
    row.status = payload.status
    audit(db, user, "website.appointment.updated", tenant_id=row.tenant_id, entity_type="appointment_request", entity_id=row.id, data={"status": row.status})
    db.commit()
    return {"appointment": model_dict(row)}


class ManagedSessionIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    minutes: int = Field(default=60, ge=5, le=240)


@router.post("/tenants/{tenant_id}/managed-session")
def start_managed_session(tenant_id: str, payload: ManagedSessionIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    for active in db.scalars(select(ManagedTenantSession).where(
        ManagedTenantSession.admin_user_id == user.id,
        ManagedTenantSession.status == "active",
    )):
        active.status = "ended"
        active.ended_at = datetime.now(timezone.utc)
    row = ManagedTenantSession(
        admin_user_id=user.id,
        tenant_id=tenant_id,
        reason=payload.reason,
        access_type="managed_write",
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=payload.minutes),
    )
    db.add(row)
    db.flush()
    db.add(SupportAccess(
        admin_user_id=user.id,
        tenant_id=tenant_id,
        area="Unified Client Workspace",
        purpose=payload.reason,
        access_type="managed_write",
    ))
    audit(db, user, "managed_session.started", tenant_id=tenant_id, entity_type="managed_tenant_session", entity_id=row.id, data={"reason": payload.reason, "expires_at": row.expires_at.isoformat()})
    db.commit()
    return {"session": model_dict(row), "tenant": model_dict(tenant)}


@router.get("/managed-session/current")
def current_managed_session(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not is_global_admin(user):
        return {"session": None}
    now = datetime.now(timezone.utc)
    row = db.scalar(select(ManagedTenantSession).where(
        ManagedTenantSession.admin_user_id == user.id,
        ManagedTenantSession.status == "active",
        ManagedTenantSession.expires_at > now,
    ).order_by(ManagedTenantSession.created_at.desc()))
    return {"session": model_dict(row) if row else None}


@router.post("/managed-session/{session_id}/end")
def end_managed_session(session_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_global_admin(user)
    row = db.get(ManagedTenantSession, session_id)
    if not row or row.admin_user_id != user.id:
        raise HTTPException(status_code=404, detail="Managed session not found")
    row.status = "ended"
    row.ended_at = datetime.now(timezone.utc)
    audit(db, user, "managed_session.ended", tenant_id=row.tenant_id, entity_type="managed_tenant_session", entity_id=row.id)
    db.commit()
    return {"ok": True}
