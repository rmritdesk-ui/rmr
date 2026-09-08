from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class InitialSetupRequest(BaseModel):
    setup_token: str
    owner_name: str = Field(min_length=2, max_length=160)
    owner_email: str = Field(min_length=5, max_length=255)
    owner_password: str = Field(min_length=12, max_length=200)
    create_step2_admin: bool = True
    step2_name: str = Field(default="Hasan — Step2", max_length=160)
    step2_email: str = Field(default="", max_length=255)
    step2_password: str = Field(default="", max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    new_password: str = Field(min_length=12, max_length=200)


class InvitationCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=5, max_length=255)
    tenant_role: Literal["CLIENT_ADMIN", "VP_SALES", "SALES_MANAGER", "SALES_REP", "MARKETING_USER", "EXECUTIVE_VIEWER"] = "CLIENT_ADMIN"
    manager_id: str | None = None
    team_name: str = ""


class InvitationAccept(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    password: str = Field(min_length=12, max_length=200)


class TenantUserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=5, max_length=255)
    tenant_role: Literal["CLIENT_ADMIN", "VP_SALES", "SALES_MANAGER", "SALES_REP", "MARKETING_USER", "EXECUTIVE_VIEWER"]
    manager_id: str | None = None
    team_name: str = ""


class TenantUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, min_length=5, max_length=255)
    tenant_role: Literal["CLIENT_ADMIN", "VP_SALES", "SALES_MANAGER", "SALES_REP", "MARKETING_USER", "EXECUTIVE_VIEWER"] | None = None
    manager_id: str | None = None
    team_name: str | None = None
    active: bool | None = None


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    industry: str = "Professional Services"
    country: str = "United States"
    timezone: str = "America/Phoenix"
    seller_org: Literal["RMR", "Step2"] = "RMR"
    seller_name: str = ""
    website_mode: Literal["managed", "custom", "external"] = "managed"
    website_url: str = ""
    primary_contact_name: str
    primary_contact_email: str
    invite_primary_admin: bool = False
    services: list[dict[str, Any]] = Field(default_factory=list)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    industry: str | None = None
    country: str | None = None
    timezone: str | None = None
    seller_org: Literal["RMR", "Step2"] | None = None
    seller_name: str | None = None
    website_mode: Literal["managed", "custom", "external"] | None = None
    website_url: str | None = None
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    health_status: str | None = None
    renewal_risk: str | None = None


class CostEntryCreate(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    category_code: str
    tenant_id: str | None = None
    service_code: str | None = None
    amount_cents: int = Field(ge=0)
    allocation_scope: Literal["direct_tenant_service", "tenant", "portfolio"] = "direct_tenant_service"
    allocation_basis: str = "direct"
    partner_settlement_treatment: str = "pending_policy"
    description: str = ""
    evidence_reference: str = ""


class CostAllocationRuleCreate(BaseModel):
    category_code: str
    allocation_basis: str
    partner_settlement_treatment: str = "pending_policy"
    effective_date: date | None = None
    end_date: date | None = None
    notes: str = ""


class OnboardingStepUpdate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    status: Literal["not_started", "in_progress", "complete"] | None = None


class TenantServiceCreate(BaseModel):
    service_code: str
    contract_price_cents: int = Field(ge=0)
    usage_price_cents: int = Field(default=0, ge=0)
    cadence: str | None = None
    effective_date: date | None = None
    notes: str = ""


class TenantServiceUpdate(BaseModel):
    contract_price_cents: int | None = Field(default=None, ge=0)
    usage_price_cents: int | None = Field(default=None, ge=0)
    cadence: str | None = None
    status: Literal["active", "suspended", "pending"] | None = None
    notes: str | None = None


class AccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    status: str = "Active"
    owner_user_id: str | None = None
    team_name: str = ""
    annual_value_cents: int = Field(default=0, ge=0)
    source: str = "Manual"
    risk: str = "Low"
    notes: str = ""


class AccountUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    owner_user_id: str | None = None
    team_name: str | None = None
    annual_value_cents: int | None = Field(default=None, ge=0)
    source: str | None = None
    risk: str | None = None
    notes: str | None = None


class ContactCreate(BaseModel):
    account_id: str | None = None
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    primary_contact: bool = False


class LeadCreate(BaseModel):
    company_name: str = ""
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    source: str = "Manual"
    status: str = "New"
    notes: str = ""
    assigned_user_id: str | None = None


class OpportunityCreate(BaseModel):
    account_id: str | None = None
    contact_id: str | None = None
    owner_user_id: str | None = None
    name: str
    stage: str = "Prospecting"
    value_cents: int = Field(default=0, ge=0)
    probability_pct: int = Field(default=10, ge=0, le=100)
    expected_close_date: date | None = None
    source: str = "Manual"
    next_action: str = ""


class OpportunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    stage: str | None = None
    value_cents: int | None = Field(default=None, ge=0)
    probability_pct: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    next_action: str | None = None
    loss_reason: str | None = None


class ActivityCreate(BaseModel):
    account_id: str | None = None
    opportunity_id: str | None = None
    activity_type: str = "Note"
    subject: str = ""
    body: str = ""
    due_at: datetime | None = None


class ForecastMonthUpdate(BaseModel):
    prior_actual_cents: int | None = Field(default=None, ge=0)
    forecast_cents: int | None = Field(default=None, ge=0)
    actual_cents: int | None = Field(default=None, ge=0)
    growth_pct: float | None = None
    notes: str | None = None


class ForecastVersionCreate(BaseModel):
    fiscal_year: int
    name: str = "Operating Forecast"
    annual_goal_cents: int = Field(default=0, ge=0)


class TrainingProgressUpdate(BaseModel):
    status: Literal["not_started", "in_progress", "complete"]
    progress_pct: int = Field(ge=0, le=100)


class WebsiteUpdate(BaseModel):
    template_family: str | None = None
    company_name: str | None = None
    wordmark: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    accent_color: str | None = None
    heading_font: str | None = None
    body_font: str | None = None
    button_style: str | None = None
    nav_style: str | None = None
    status: str | None = None
    external_url: str | None = None


class WebsitePageCreate(BaseModel):
    title: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    show_in_nav: bool = True
    status: str = "draft"
    seo_title: str = ""
    seo_description: str = ""


class WebsitePageUpdate(BaseModel):
    title: str | None = None
    show_in_nav: bool | None = None
    status: str | None = None
    nav_order: int | None = None
    seo_title: str | None = None
    seo_description: str | None = None


class WebsiteSectionCreate(BaseModel):
    page_id: str
    section_type: str
    position: int = 1
    settings: dict[str, Any] = {}


class WebsiteSectionUpdate(BaseModel):
    position: int | None = None
    visible: bool | None = None
    settings: dict[str, Any] | None = None


class SolutionInterestCreate(BaseModel):
    service_code: str
    event_type: Literal["view", "demo_view", "pricing_view"] = "view"


class SolutionRequestCreate(BaseModel):
    service_code: str
    note: str = ""
    preferred_contact_method: str = "Email"
    best_time: str = ""


class SolutionRequestReview(BaseModel):
    status: Literal["Requested", "Pending Activation", "Active", "Declined"]
    review_note: str = ""
    contract_price_cents: int | None = Field(default=None, ge=0)
    usage_price_cents: int | None = Field(default=None, ge=0)


class CampaignCreate(BaseModel):
    title: str
    channel: str = "Social"
    status: str = "Draft"
    content: str = ""
    scheduled_at: datetime | None = None


class CampaignUpdate(BaseModel):
    title: str | None = None
    channel: str | None = None
    status: str | None = None
    content: str | None = None
    scheduled_at: datetime | None = None


class PiqEnhanceRequest(BaseModel):
    payment_confirmation: bool


class PublicLeadCreate(BaseModel):
    name: str
    email: str
    phone: str = ""
    company: str = ""
    message: str = ""
