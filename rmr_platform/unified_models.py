from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import utcnow, uuid4_str


class WebsiteMedia(Base):
    __tablename__ = "website_media"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(40), default="image")
    url: Mapped[str] = mapped_column(String(1000), default="")
    alt_text: Mapped[str] = mapped_column(String(300), default="")
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsiteBlogPost(Base):
    __tablename__ = "website_blog_posts"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_blog_tenant_slug"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    seo_title: Mapped[str] = mapped_column(String(220), default="")
    seo_description: Mapped[str] = mapped_column(String(500), default="")
    featured_image_url: Mapped[str] = mapped_column(String(1000), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebsiteResource(Base):
    __tablename__ = "website_resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    resource_type: Mapped[str] = mapped_column(String(50), default="guide")
    url: Mapped[str] = mapped_column(String(1000), default="")
    lead_capture_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebsiteTeamProfile(Base):
    __tablename__ = "website_team_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    title: Mapped[str] = mapped_column(String(180), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    photo_url: Mapped[str] = mapped_column(String(1000), default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppointmentRequest(Base):
    __tablename__ = "appointment_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    preferred_time: Mapped[str] = mapped_column(String(180), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(120), default="Website Appointment Request")
    status: Mapped[str] = mapped_column(String(30), default="new")
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SeoWorkItem(Base):
    __tablename__ = "seo_work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=True)
    item_type: Mapped[str] = mapped_column(String(60), default="content")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PiqTargetProfile(Base):
    __tablename__ = "piq_target_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180), default="Primary Target Profile")
    industries_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    employee_min: Mapped[int] = mapped_column(Integer, default=0)
    employee_max: Mapped[int] = mapped_column(Integer, default=0)
    revenue_min_cents: Mapped[int] = mapped_column(Integer, default=0)
    keywords_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclusions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PiqEvidence(Base):
    __tablename__ = "piq_evidence"
    __table_args__ = (
        Index("uq_piq_evidence_tenant_hash", "tenant_id", "evidence_hash", unique=True),
        Index("ix_piq_evidence_discovery_run", "discovery_run_id"),
        Index("ix_piq_evidence_research_run", "research_run_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("piq_opportunities.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(60), default="public_signal")
    source_name: Mapped[str] = mapped_column(String(180), default="RMR Demo Provider")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fact: Mapped[str] = mapped_column(Text, default="")
    confidence_pct: Mapped[int] = mapped_column(Integer, default=75)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_state: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    profile_criterion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    discovery_run_id: Mapped[str | None] = mapped_column(ForeignKey("piq_discovery_runs.id", ondelete="SET NULL"), nullable=True)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("piq_research_runs.id", ondelete="SET NULL"), nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_synthesized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PiqImportBatch(Base):
    __tablename__ = "piq_import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(260), default="pasted-list.csv")
    status: Mapped[str] = mapped_column(String(30), default="preview")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    preview_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManagedTenantSession(Base):
    __tablename__ = "managed_tenant_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    admin_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    access_type: Mapped[str] = mapped_column(String(40), default="managed_write")
    status: Mapped[str] = mapped_column(String(30), default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
