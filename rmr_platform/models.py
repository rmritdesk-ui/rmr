from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uuid4_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    industry: Mapped[str] = mapped_column(String(120), default="Professional Services")
    country: Mapped[str] = mapped_column(String(80), default="United States")
    timezone: Mapped[str] = mapped_column(String(80), default="America/Phoenix")
    status: Mapped[str] = mapped_column(String(40), default="onboarding", index=True)
    seller_org: Mapped[str] = mapped_column(String(40), default="RMR")
    seller_name: Mapped[str] = mapped_column(String(160), default="")
    onboarding_owner: Mapped[str] = mapped_column(String(80), default="Step2")
    website_mode: Mapped[str] = mapped_column(String(40), default="managed")
    website_url: Mapped[str] = mapped_column(String(500), default="")
    managed_site_slug: Mapped[str] = mapped_column(String(120), default="")
    adoption_score: Mapped[int] = mapped_column(Integer, default=0)
    training_completion_pct: Mapped[int] = mapped_column(Integer, default=0)
    health_status: Mapped[str] = mapped_column(String(40), default="Onboarding")
    renewal_risk: Mapped[str] = mapped_column(String(40), default="Low")
    primary_contact_name: Mapped[str] = mapped_column(String(160), default="")
    primary_contact_email: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    global_role: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    tenant_role: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_name: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped[Tenant | None] = relationship("Tenant")


class UserInvitation(Base):
    __tablename__ = "user_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_role: Mapped[str] = mapped_column(String(50), default="CLIENT_ADMIN", index=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_name: Mapped[str] = mapped_column(String(120), default="")
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    requested_ip: Mapped[str] = mapped_column(String(100), default="")


class CostCategory(Base):
    __tablename__ = "cost_categories"
    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    cost_type: Mapped[str] = mapped_column(String(40), default="direct")
    default_allocation_basis: Mapped[str] = mapped_column(String(50), default="direct")
    partner_settlement_treatment: Mapped[str] = mapped_column(String(50), default="pending_policy")
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CostAllocationRule(Base):
    __tablename__ = "cost_allocation_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    category_code: Mapped[str] = mapped_column(ForeignKey("cost_categories.code"), index=True)
    allocation_basis: Mapped[str] = mapped_column(String(50), default="manual")
    partner_settlement_treatment: Mapped[str] = mapped_column(String(50), default="pending_policy")
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostEntry(Base):
    __tablename__ = "cost_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    period: Mapped[str] = mapped_column(String(20), index=True)
    category_code: Mapped[str] = mapped_column(ForeignKey("cost_categories.code"), index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    service_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    allocation_scope: Mapped[str] = mapped_column(String(50), default="direct_tenant_service")
    allocation_basis: Mapped[str] = mapped_column(String(50), default="direct")
    partner_settlement_treatment: Mapped[str] = mapped_column(String(50), default="pending_policy")
    description: Mapped[str] = mapped_column(Text, default="")
    evidence_reference: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(80), default="manual")
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceCatalog(Base):
    __tablename__ = "service_catalog"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="Platform")
    description: Mapped[str] = mapped_column(Text, default="")
    standard_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    cadence: Mapped[str] = mapped_column(String(30), default="monthly")
    unit: Mapped[str] = mapped_column(String(50), default="subscription")
    direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    split_basis: Mapped[str] = mapped_column(String(20), default="gross")
    rmr_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    step2_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TenantService(Base):
    __tablename__ = "tenant_services"
    __table_args__ = (UniqueConstraint("tenant_id", "service_code", name="uq_tenant_service"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    service_code: Mapped[str] = mapped_column(ForeignKey("service_catalog.code"), index=True)
    contract_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    usage_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    cadence: Mapped[str] = mapped_column(String(30), default="monthly")
    status: Mapped[str] = mapped_column(String(30), default="active")
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)
    next_billing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EconomicTransaction(Base):
    __tablename__ = "economic_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    service_code: Mapped[str] = mapped_column(String(80), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    split_basis: Mapped[str] = mapped_column(String(20), default="gross")
    rmr_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    step2_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    rmr_share_cents: Mapped[int] = mapped_column(Integer, default=0)
    step2_share_cents: Mapped[int] = mapped_column(Integer, default=0)
    invoice_reference: Mapped[str] = mapped_column(String(120), default="")
    trace_reference: Mapped[str] = mapped_column(String(120), unique=True, default=uuid4_str)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OnboardingProject(Base):
    __tablename__ = "onboarding_projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    current_stage: Mapped[int] = mapped_column(Integer, default=1)
    readiness_pct: Mapped[int] = mapped_column(Integer, default=0)
    target_go_live: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OnboardingStep(Base):
    __tablename__ = "onboarding_steps"
    __table_args__ = (UniqueConstraint("project_id", "stage_number", name="uq_onboarding_stage"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    project_id: Mapped[str] = mapped_column(ForeignKey("onboarding_projects.id", ondelete="CASCADE"), index=True)
    stage_number: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    owner_role: Mapped[str] = mapped_column(String(100), default="Step2")
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    completed_by: Mapped[str] = mapped_column(String(160), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="Active")
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_name: Mapped[str] = mapped_column(String(120), default="")
    annual_value_cents: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(80), default="Manual")
    risk: Mapped[str] = mapped_column(String(40), default="Low")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), default="")
    last_name: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(140), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    contact_name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(80), default="Manual")
    status: Mapped[str] = mapped_column(String(40), default="New")
    notes: Mapped[str] = mapped_column(Text, default="")
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stage: Mapped[str] = mapped_column(String(60), default="Prospecting")
    value_cents: Mapped[int] = mapped_column(Integer, default=0)
    probability_pct: Mapped[int] = mapped_column(Integer, default=10)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="Manual")
    next_action: Mapped[str] = mapped_column(String(300), default="")
    loss_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activity_type: Mapped[str] = mapped_column(String(40), default="Note")
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastVersion(Base):
    __tablename__ = "forecast_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(160), default="Operating Forecast")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    annual_goal_cents: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastMonth(Base):
    __tablename__ = "forecast_months"
    __table_args__ = (UniqueConstraint("version_id", "account_id", "month", name="uq_forecast_account_month"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    version_id: Mapped[str] = mapped_column(ForeignKey("forecast_versions.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    month: Mapped[int] = mapped_column(Integer)
    prior_actual_cents: Mapped[int] = mapped_column(Integer, default=0)
    forecast_cents: Mapped[int] = mapped_column(Integer, default=0)
    actual_cents: Mapped[int] = mapped_column(Integer, default=0)
    growth_pct: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")


class TrainingResource(Base):
    __tablename__ = "training_resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    module: Mapped[str] = mapped_column(String(100), default="Platform")
    media_type: Mapped[str] = mapped_column(String(30), default="external_link")
    media_url: Mapped[str] = mapped_column(String(1000), default="")
    file_path: Mapped[str] = mapped_column(String(500), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    roles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    product_version: Mapped[str] = mapped_column(String(40), default="5.0")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingProgress(Base):
    __tablename__ = "training_progress"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "resource_id", name="uq_training_progress"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("training_resources.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebsiteSite(Base):
    __tablename__ = "website_sites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(40), default="managed")
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    template_family: Mapped[str] = mapped_column(String(80), default="executive-authority")
    company_name: Mapped[str] = mapped_column(String(200), default="")
    wordmark: Mapped[str] = mapped_column(String(160), default="")
    primary_color: Mapped[str] = mapped_column(String(20), default="#0d2945")
    secondary_color: Mapped[str] = mapped_column(String(20), default="#f6f2eb")
    accent_color: Mapped[str] = mapped_column(String(20), default="#2f6bff")
    heading_font: Mapped[str] = mapped_column(String(80), default="Georgia")
    body_font: Mapped[str] = mapped_column(String(80), default="Arial")
    button_style: Mapped[str] = mapped_column(String(40), default="rounded")
    nav_style: Mapped[str] = mapped_column(String(40), default="light")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    external_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebsitePage(Base):
    __tablename__ = "website_pages"
    __table_args__ = (UniqueConstraint("site_id", "slug", name="uq_site_page_slug"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    site_id: Mapped[str] = mapped_column(ForeignKey("website_sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    nav_order: Mapped[int] = mapped_column(Integer, default=0)
    show_in_nav: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="published")
    seo_title: Mapped[str] = mapped_column(String(200), default="")
    seo_description: Mapped[str] = mapped_column(String(400), default="")


class WebsiteSection(Base):
    __tablename__ = "website_sections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    page_id: Mapped[str] = mapped_column(ForeignKey("website_pages.id", ondelete="CASCADE"), index=True)
    section_type: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SolutionRequest(Base):
    __tablename__ = "solution_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    service_code: Mapped[str] = mapped_column(String(80), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(40), default="Requested", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    proposed_monthly_cents: Mapped[int] = mapped_column(Integer, default=0)
    proposed_usage_cents: Mapped[int] = mapped_column(Integer, default=0)
    preferred_contact_method: Mapped[str] = mapped_column(String(40), default="Email")
    best_time: Mapped[str] = mapped_column(String(120), default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SolutionInterest(Base):
    __tablename__ = "solution_interest"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    service_code: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(50), default="view")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    recipient_scope: Mapped[str] = mapped_column(String(80), default="GLOBAL_ADMIN", index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(80), default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="unread", index=True)
    action_route: Mapped[str] = mapped_column(String(160), default="")
    action_label: Mapped[str] = mapped_column(String(100), default="Open")
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportAccess(Base):
    __tablename__ = "support_access"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    admin_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    area: Mapped[str] = mapped_column(String(120), default="Client 360")
    purpose: Mapped[str] = mapped_column(String(300), default="Authorized support review")
    access_type: Mapped[str] = mapped_column(String(40), default="read_only")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(80), default="Social")
    status: Mapped[str] = mapped_column(String(40), default="Draft")
    content: Mapped[str] = mapped_column(Text, default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PiqOpportunity(Base):
    __tablename__ = "piq_opportunities"
    __table_args__ = (
        Index("uq_piq_opportunity_tenant_fingerprint", "tenant_id", "fingerprint", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    signal: Mapped[str] = mapped_column(String(300), default="")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_value_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="Priority")
    enhanced: Mapped[bool] = mapped_column(Boolean, default=False)
    enhancement_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    moved_to_crm: Mapped[bool] = mapped_column(Boolean, default=False)
    target_profile_id: Mapped[str | None] = mapped_column(ForeignKey("piq_target_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(180), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    base_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_completeness_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adaptive_score_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
