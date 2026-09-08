from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    Account,
    Activity,
    AuditEvent,
    Campaign,
    Contact,
    CostCategory,
    EconomicTransaction,
    ForecastMonth,
    ForecastVersion,
    Lead,
    Notification,
    OnboardingProject,
    OnboardingStep,
    Opportunity,
    PiqOpportunity,
    ServiceCatalog,
    SolutionInterest,
    SolutionRequest,
    SupportAccess,
    Tenant,
    TenantService,
    TrainingProgress,
    TrainingResource,
    User,
    WebsitePage,
    WebsiteSection,
    WebsiteSite,
)
from .security import hash_password

RNG = random.Random(20260809)

COST_CATEGORY_DEFINITIONS = [
    ("hosting_infrastructure", "Hosting & Server Infrastructure", "shared_platform", "revenue_share", "pending_policy", "Servers, storage, monitoring, networking, backups and related platform infrastructure."),
    ("software_api", "Software & API Expense", "shared_platform", "usage_or_revenue", "pending_policy", "Model, enrichment, communications, analytics and other third-party software/API costs."),
    ("payment_processing", "Payment Processing", "direct", "direct", "included_before_split", "Card and payment-provider fees attributable to a client transaction."),
    ("staff_labor", "Staff & Labor", "operating", "manual_or_time", "pending_policy", "RMR or Step2 implementation, onboarding, support and operational labor."),
    ("client_support", "Client Support", "direct", "manual_or_time", "pending_policy", "Support work attributable to a specific client or service."),
    ("sales_commission", "Sales Commission", "direct", "direct", "separate_commission", "Originating salesperson or channel commission, separate from partner revenue share."),
    ("general_operating", "General Operating Expense", "operating", "management_only", "management_only", "Insurance, accounting, legal, administration and other general RMR operating costs."),
    ("other_direct", "Other Direct Cost", "direct", "direct", "pending_policy", "Other evidence-backed cost directly attributable to a client or service."),
]


SERVICE_DEFINITIONS = [
    ("platform_core", "RMR Platform Core", "Platform", 29500, "monthly", "subscription", 3500, "net", 55.0, 45.0),
    ("crm", "Enterprise CRM & Sales Organization", "Sales", 17500, "monthly", "subscription", 1800, "net", 55.0, 45.0),
    ("forecasting", "Sales Forecasting", "Sales", 15000, "monthly", "subscription", 1200, "net", 55.0, 45.0),
    ("management_intelligence", "Management Intelligence", "Sales", 15000, "monthly", "subscription", 1200, "net", 55.0, 45.0),
    ("forecasting_management", "Forecasting & Management Intelligence", "Sales", 25000, "monthly", "subscription", 2100, "net", 55.0, 45.0),
    ("managed_website", "RMR Managed Website", "Website", 14500, "monthly", "subscription", 2500, "gross", 40.0, 60.0),
    ("custom_website_connection", "Custom Website Connection", "Website", 9500, "monthly", "subscription", 1600, "gross", 45.0, 55.0),
    ("external_website_connection", "External Website Connection", "Website", 7500, "monthly", "subscription", 900, "gross", 50.0, 50.0),
    ("monthly_seo", "Monthly SEO", "Marketing", 75000, "monthly", "subscription", 26000, "net", 40.0, 60.0),
    ("piq_access", "ProspectIQ Monthly Access", "Intelligence", 17500, "monthly", "subscription", 2200, "net", 80.0, 20.0),
    ("piq_enhancement", "ProspectIQ Record Enhancement", "Intelligence", 400, "usage", "record", 125, "net", 80.0, 20.0),
    ("training", "Training & Adoption Library", "Training", 10000, "monthly", "subscription", 800, "net", 50.0, 50.0),
    ("campaigns", "Campaigns & Content Operations", "Marketing", 29500, "monthly", "subscription", 6500, "net", 45.0, 55.0),
    ("private_reference", "Private RMR Reference Deployment", "Private", 0, "monthly", "subscription", 0, "gross", 100.0, 0.0),
]

ONBOARDING_STAGES = [
    (1, "client_structure", "Client setup", "Step2"),
    (2, "tenant_provisioning", "Tenant provisioning & client access", "Step2"),
    (3, "website_brand", "Website & brand", "Step2"),
    (4, "crm_sales_org", "CRM & sales organization", "Client + Step2"),
    (5, "historical_sales", "Historical sales data", "Client"),
    (6, "modules_integrations", "Modules & integrations", "Step2"),
    (7, "training_adoption", "Training & adoption", "Step2 + Client"),
    (8, "go_live", "Go-live validation", "RMR + Step2"),
]

TENANTS = [
    {
        "name": "Desert Peak Facilities Group",
        "slug": "desert-peak",
        "industry": "Facilities Services",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "managed",
        "adoption_score": 94,
        "training_completion_pct": 87,
        "health_status": "Strong",
        "renewal_risk": "Low",
        "contact": ("Maya Chen", "maya@desertpeak.example"),
        "services": {"platform_core": 29500, "crm": 17500, "forecasting_management": 25000, "managed_website": 14500, "piq_access": 17500, "piq_enhancement": 400, "training": 10000},
    },
    {
        "name": "Crescent Accounting & Tax",
        "slug": "crescent-accounting",
        "industry": "Accounting & Tax",
        "country": "Pakistan",
        "status": "live",
        "seller_org": "Step2",
        "seller_name": "Step2 Sales",
        "website_mode": "managed",
        "adoption_score": 88,
        "training_completion_pct": 79,
        "health_status": "Healthy",
        "renewal_risk": "Low",
        "contact": ("Adeel Khan", "adeel@crescent.example"),
        "services": {"platform_core": 27500, "crm": 16000, "forecasting_management": 22000, "managed_website": 13000, "piq_access": 15000, "piq_enhancement": 350, "training": 9000},
    },
    {
        "name": "PakShield Insurance Advisors",
        "slug": "pakshield",
        "industry": "Insurance",
        "country": "Pakistan",
        "status": "live",
        "seller_org": "Step2",
        "seller_name": "Step2 Sales",
        "website_mode": "external",
        "adoption_score": 79,
        "training_completion_pct": 72,
        "health_status": "Healthy",
        "renewal_risk": "Low",
        "contact": ("Sara Ahmed", "sara@pakshield.example"),
        "services": {"platform_core": 29500, "crm": 17500, "external_website_connection": 7500, "piq_access": 17500, "piq_enhancement": 400},
    },
    {
        "name": "Northstar Tax Advisory",
        "slug": "northstar-tax",
        "industry": "Tax Advisory",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "managed",
        "adoption_score": 91,
        "training_completion_pct": 82,
        "health_status": "Strong",
        "renewal_risk": "Low",
        "contact": ("Jordan Ellis", "jordan@northstar.example"),
        "services": {"platform_core": 29500, "crm": 17500, "management_intelligence": 15000, "managed_website": 14500, "piq_access": 17500, "piq_enhancement": 450, "training": 10000},
    },
    {
        "name": "BlueMesa Home Services",
        "slug": "bluemesa",
        "industry": "Home Services",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "managed",
        "adoption_score": 90,
        "training_completion_pct": 84,
        "health_status": "Strong",
        "renewal_risk": "Low",
        "contact": ("Luis Romero", "luis@bluemesa.example"),
        "services": {"platform_core": 29500, "crm": 17500, "forecasting_management": 25000, "managed_website": 14500, "campaigns": 29500, "training": 10000},
    },
    {
        "name": "Apex Growth Collective",
        "slug": "apex-growth",
        "industry": "Marketing Agency",
        "country": "United States",
        "status": "live",
        "seller_org": "Step2",
        "seller_name": "Step2 Sales",
        "website_mode": "custom",
        "adoption_score": 67,
        "training_completion_pct": 52,
        "health_status": "Attention",
        "renewal_risk": "Moderate",
        "contact": ("Morgan Lee", "morgan@apex.example"),
        "services": {"platform_core": 29500, "crm": 17500, "custom_website_connection": 9500, "campaigns": 29500},
    },
    {
        "name": "Horizon Community Alliance",
        "slug": "horizon-community",
        "industry": "Nonprofit",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "managed",
        "adoption_score": 83,
        "training_completion_pct": 78,
        "health_status": "Healthy",
        "renewal_risk": "Low",
        "contact": ("Tara Brooks", "tara@horizon.example"),
        "services": {"platform_core": 25000, "crm": 15000, "managed_website": 12500, "training": 8500},
    },
    {
        "name": "Kerry Laughlin Real Estate",
        "slug": "kerry-real-estate",
        "industry": "Real Estate",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "managed",
        "adoption_score": 96,
        "training_completion_pct": 90,
        "health_status": "Strong",
        "renewal_risk": "Low",
        "contact": ("Kerry Laughlin", "kerry@laughlinrealestate.demo"),
        "services": {
            "platform_core": 0,
            "private_reference": 0,
            "crm": 0,
            "forecasting_management": 0,
            "managed_website": 0,
            "monthly_seo": 0,
            "piq_access": 0,
            "piq_enhancement": 0,
            "campaigns": 0,
            "training": 0,
        },
    },
    {
        "name": "Cactus Air Filters",
        "slug": "cactus-air-filters",
        "industry": "Home Services Subscription",
        "country": "United States",
        "status": "live",
        "seller_org": "RMR",
        "seller_name": "Dave Laughlin",
        "website_mode": "external",
        "website_url": "https://example.com/cactus-air-filters",
        "adoption_score": 84,
        "training_completion_pct": 70,
        "health_status": "Healthy",
        "renewal_risk": "Low",
        "contact": ("CAF Administrator", "admin@cactus-air-filters.demo"),
        "services": {
            "platform_core": 0,
            "crm": 0,
            "forecasting_management": 0,
            "external_website_connection": 0,
            "piq_access": 0,
            "piq_enhancement": 0,
            "campaigns": 0,
            "training": 0,
        },
    },
    {
        "name": "Lahore Business Consultants",
        "slug": "lahore-consultants",
        "industry": "Business Consulting",
        "country": "Pakistan",
        "status": "onboarding",
        "seller_org": "Step2",
        "seller_name": "Step2 Sales",
        "website_mode": "managed",
        "adoption_score": 10,
        "training_completion_pct": 0,
        "health_status": "Onboarding",
        "renewal_risk": "Low",
        "contact": ("Farah Malik", "farah@lahore.example"),
        "services": {"platform_core": 25000, "crm": 15000, "managed_website": 12500},
    },
]


def seed_reference_data(db: Session) -> dict[str, ServiceCatalog]:
    """Create or update governed reference records without creating demo tenants."""
    catalog: dict[str, ServiceCatalog] = {}
    for sort_order, row in enumerate(SERVICE_DEFINITIONS, 1):
        code, name, category, price, cadence, unit, cost, basis, rmr_pct, step2_pct = row
        service = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == code))
        if not service:
            service = ServiceCatalog(code=code)
            db.add(service)
        service.name = name
        service.category = category
        service.description = f"{name} service available through RMR Platform."
        service.standard_price_cents = price
        service.cadence = cadence
        service.unit = unit
        service.direct_cost_cents = cost
        service.split_basis = basis
        service.rmr_share_pct = rmr_pct
        service.step2_share_pct = step2_pct
        service.sort_order = sort_order
        service.active = True
        catalog[code] = service
    for sort_order, row in enumerate(COST_CATEGORY_DEFINITIONS, 1):
        code, name, cost_type, basis, settlement, description = row
        category = db.get(CostCategory, code)
        if not category:
            category = CostCategory(code=code)
            db.add(category)
        category.name = name
        category.cost_type = cost_type
        category.default_allocation_basis = basis
        category.partner_settlement_treatment = settlement
        category.description = description
        category.active = True
        category.sort_order = sort_order
    db.flush()
    return catalog


def _create_service_catalog(db: Session) -> dict[str, ServiceCatalog]:
    return seed_reference_data(db)


def _create_user(db: Session, *, email: str, password: str, full_name: str, global_role: str | None = None,
                 tenant_id: str | None = None, tenant_role: str | None = None, manager_id: str | None = None,
                 team_name: str = "") -> User:
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        global_role=global_role,
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        manager_id=manager_id,
        team_name=team_name,
    )
    db.add(user)
    db.flush()
    return user


def _create_onboarding(db: Session, tenant: Tenant, completed_stages: int) -> None:
    project = OnboardingProject(
        tenant_id=tenant.id,
        status="complete" if completed_stages == 8 else "active",
        current_stage=min(completed_stages + 1, 8),
        readiness_pct=round(completed_stages / 8 * 100),
        target_go_live=date.today() + timedelta(days=max(0, 30 - completed_stages * 3)),
    )
    db.add(project)
    db.flush()
    for stage_number, code, name, owner in ONBOARDING_STAGES:
        completed = stage_number <= completed_stages
        step = OnboardingStep(
            project_id=project.id,
            stage_number=stage_number,
            code=code,
            name=name,
            owner_role=owner,
            status="complete" if completed else ("in_progress" if stage_number == completed_stages + 1 else "not_started"),
            data_json={"verified": completed},
            notes="Validated during onboarding." if completed else "",
            completed_by="Step2 Platform Administrator" if completed else "",
            completed_at=datetime.now(timezone.utc) - timedelta(days=(8-stage_number)) if completed else None,
        )
        db.add(step)


def _create_website(db: Session, tenant: Tenant, family: str) -> None:
    site = WebsiteSite(
        tenant_id=tenant.id,
        mode=tenant.website_mode,
        slug=tenant.slug,
        template_family=family,
        company_name=tenant.name,
        wordmark=tenant.name.split()[0].upper(),
        primary_color="#0d2945" if family == "executive-authority" else "#101828",
        secondary_color="#f4f7fb",
        accent_color="#2f6bff" if family != "community-impact" else "#0f9f83",
        heading_font="Georgia" if family == "executive-authority" else "Arial",
        body_font="Arial",
        button_style="rounded",
        nav_style="light",
        status="published" if tenant.status in {"live", "private"} else "draft",
        external_url=tenant.website_url,
    )
    db.add(site)
    db.flush()
    page = WebsitePage(
        site_id=site.id,
        title="Home",
        slug="home",
        nav_order=1,
        show_in_nav=True,
        status="published",
        seo_title=f"{tenant.name} | Professional Services",
        seo_description=f"Learn how {tenant.name} helps clients move forward with confidence.",
    )
    db.add(page)
    db.flush()
    sections = [
        ("hero", {
            "eyebrow": "WELCOME",
            "headline": f"Built for the work that matters at {tenant.name}.",
            "supporting_text": "Clear expertise, responsive service, and measurable follow-through.",
            "primary_button": "Start a Conversation",
            "secondary_button": "Explore Services",
            "layout": "split",
            "background": "brand",
        }),
        ("services", {
            "headline": "Services designed around your next decision.",
            "items": ["Strategic guidance", "Responsive support", "Measurable outcomes"],
        }),
        ("metrics", {
            "headline": "The work becomes visible.",
            "items": [{"value": "24/7", "label": "Access"}, {"value": "98%", "label": "Client retention"}, {"value": "1", "label": "Dedicated team"}],
        }),
        ("contact", {
            "headline": "Ready to talk?",
            "body": "Tell us what you are working toward and our team will follow up.",
        }),
    ]
    for position, (section_type, settings) in enumerate(sections, 1):
        db.add(WebsiteSection(page_id=page.id, section_type=section_type, position=position, settings_json=settings))


def _create_tenant_users(db: Session, tenant: Tenant, index: int) -> dict[str, User]:
    suffix = tenant.slug.replace("-", "")
    admin = _create_user(
        db,
        email=f"admin@{tenant.slug}.demo",
        password="Client-Admin-2026!",
        full_name=f"{tenant.name} Administrator",
        tenant_id=tenant.id,
        tenant_role="CLIENT_ADMIN",
        team_name="Executive",
    )
    vp = _create_user(
        db,
        email=f"vp@{tenant.slug}.demo",
        password="VP-Sales-2026!",
        full_name=f"{tenant.name.split()[0]} VP Sales",
        tenant_id=tenant.id,
        tenant_role="VP_SALES",
        team_name="Sales Leadership",
    )
    manager = _create_user(
        db,
        email=f"manager@{tenant.slug}.demo",
        password="Manager-2026!",
        full_name=f"{tenant.name.split()[0]} Sales Manager",
        tenant_id=tenant.id,
        tenant_role="SALES_MANAGER",
        manager_id=vp.id,
        team_name="Growth Team",
    )
    reps: list[User] = []
    for rep_index in range(1, 4 if index == 0 else 3):
        reps.append(_create_user(
            db,
            email=f"rep{rep_index}@{tenant.slug}.demo",
            password="Rep-2026!",
            full_name=f"Sales Representative {rep_index}",
            tenant_id=tenant.id,
            tenant_role="SALES_REP",
            manager_id=manager.id,
            team_name="Growth Team",
        ))
    marketing = _create_user(
        db,
        email=f"marketing@{tenant.slug}.demo",
        password="Marketing-2026!",
        full_name=f"{tenant.name.split()[0]} Marketing",
        tenant_id=tenant.id,
        tenant_role="MARKETING_USER",
        team_name="Marketing",
    )
    return {"admin": admin, "vp": vp, "manager": manager, "marketing": marketing, "reps": reps}


def _create_crm_and_forecast(db: Session, tenant: Tenant, users: dict[str, User], account_count: int) -> None:
    reps: list[User] = users["reps"]  # type: ignore[assignment]
    base_names = [
        "Apex Distribution Center", "Summit Ridge Partners", "Copperline Medical Group", "Redstone Hospitality",
        "Meridian Manufacturing", "Pioneer Charter Network", "North Basin Logistics", "Canyon Lighting Group",
        "Westbridge Senior Living", "Atlas Food Processing", "Sterling Civic Center", "Cobalt Equipment Company",
        "Ironwood Education", "Bluewater Systems", "Sierra Commercial", "Highland Operations", "Suncrest Holdings",
        "Mesa River Group", "Valley Technical", "Clearpoint Advisors", "Northfield Partners", "Keystone Industrial",
        "Evergreen Community", "Frontier Business Group", "Granite Peak Services", "Silverline Networks",
        "BrightPath Solutions", "Harbor View Management", "Oakstone Partners", "Liberty Professional Group",
    ]
    version = ForecastVersion(
        tenant_id=tenant.id,
        fiscal_year=date.today().year,
        name="Operating Forecast",
        status="active",
        annual_goal_cents=account_count * 140_000_00,
        is_active=True,
        created_by=users["vp"].id,  # type: ignore[union-attr]
    )
    db.add(version)
    db.flush()
    for i in range(account_count):
        owner = reps[i % len(reps)]
        name = base_names[i % len(base_names)] + (f" {i//len(base_names)+2}" if i >= len(base_names) else "")
        annual_value = RNG.randint(70_000, 520_000) * 100
        risk = RNG.choices(["Low", "Moderate", "High"], weights=[70, 22, 8])[0]
        status = RNG.choices(["Active", "Growing", "At Risk", "Expected Termination"], weights=[55, 25, 15, 5])[0]
        account = Account(
            tenant_id=tenant.id,
            name=name,
            status=status,
            owner_user_id=owner.id,
            team_name=owner.team_name,
            annual_value_cents=annual_value,
            source=RNG.choice(["Referral", "Website", "ProspectIQ", "Campaign", "Manual"]),
            risk=risk,
            notes="Synthetic demonstration account for product validation.",
        )
        db.add(account)
        db.flush()
        contact = Contact(
            tenant_id=tenant.id,
            account_id=account.id,
            first_name=RNG.choice(["Alex", "Jordan", "Maya", "Luis", "Taylor", "Avery", "Morgan", "Riley"]),
            last_name=RNG.choice(["Chen", "Patel", "Williams", "Garcia", "Smith", "Brooks", "Khan", "Lee"]),
            title=RNG.choice(["Owner", "COO", "VP Operations", "Controller", "Director"]),
            email=f"contact{i+1}@{tenant.slug}.example",
            phone=f"555-01{i:02d}",
            primary_contact=True,
        )
        db.add(contact)
        db.flush()
        monthly_base = annual_value // 12
        total_forecast = 0
        for month in range(1, 13):
            seasonality = 0.85 + (month % 5) * 0.06
            prior = int(monthly_base * seasonality * RNG.uniform(0.92, 1.08))
            growth = RNG.choice([-12.0, -5.0, 0.0, 5.0, 8.0, 12.0, 18.0])
            if status == "Expected Termination" and month >= 8:
                forecast = 0
            else:
                forecast = max(0, int(prior * (1 + growth / 100)))
            actual = int(forecast * RNG.uniform(0.84, 1.12)) if month <= date.today().month else 0
            total_forecast += forecast
            db.add(ForecastMonth(
                version_id=version.id,
                account_id=account.id,
                month=month,
                prior_actual_cents=prior,
                forecast_cents=forecast,
                actual_cents=actual,
                growth_pct=growth,
                notes="",
            ))
        if i < max(4, account_count // 3):
            opportunity = Opportunity(
                tenant_id=tenant.id,
                account_id=account.id,
                contact_id=contact.id,
                owner_user_id=owner.id,
                name=f"{name} expansion",
                stage=RNG.choice(["Qualified", "Proposal", "Verbal Commitment"]),
                value_cents=RNG.randint(15_000, 180_000) * 100,
                probability_pct=RNG.choice([25, 50, 80]),
                expected_close_date=date.today() + timedelta(days=RNG.randint(15, 120)),
                source=account.source,
                next_action="Confirm decision timeline and next meeting.",
            )
            db.add(opportunity)
            db.flush()
            db.add(Activity(
                tenant_id=tenant.id,
                account_id=account.id,
                opportunity_id=opportunity.id,
                user_id=owner.id,
                activity_type="Meeting",
                subject="Opportunity review",
                body="Reviewed priorities and agreed on follow-up items.",
                due_at=datetime.now(timezone.utc) + timedelta(days=7),
            ))
    for i in range(max(3, account_count // 4)):
        db.add(Lead(
            tenant_id=tenant.id,
            company_name=f"New Prospect {i+1} — {tenant.name.split()[0]}",
            contact_name=RNG.choice(["Jamie Ortiz", "Chris Allen", "Rosa Malik", "Drew Carter"]),
            email=f"lead{i+1}@{tenant.slug}.example",
            phone=f"555-20{i:02d}",
            source=RNG.choice(["Website", "ProspectIQ", "Referral"]),
            status=RNG.choice(["New", "Contacted", "Qualified"]),
            notes="Synthetic lead record.",
            assigned_user_id=reps[i % len(reps)].id,
        ))
    for i in range(10 if tenant.slug == "desert-peak" else 4):
        db.add(PiqOpportunity(
            tenant_id=tenant.id,
            company_name=f"{RNG.choice(['Nova', 'Summit', 'Crescent', 'Redwood', 'Harbor'])} {RNG.choice(['Industries', 'Group', 'Holdings', 'Partners', 'Services'])} {i+1}",
            score=RNG.randint(68, 97),
            signal=RNG.choice(["Expansion signal detected", "Executive hire and growth", "New location activity", "Service demand indicator"]),
            evidence_count=RNG.randint(3, 8),
            estimated_value_cents=RNG.randint(18_000, 160_000) * 100,
            status="Priority",
            enhanced=i < 2,
            enhancement_price_cents=400,
            moved_to_crm=i == 0,
        ))


def _create_training(db: Session, global_admin: User, tenants: list[Tenant], tenant_users: dict[str, dict[str, User]]) -> None:
    resources = [
        ("Platform Orientation for Client Administrators", "Platform", ["CLIENT_ADMIN"], 12, True),
        ("Step2 Client Provisioning and Go-Live", "Onboarding", ["STEP2_ADMIN"], 18, True),
        ("CRM Daily Workflow for Sales Representatives", "CRM", ["SALES_REP"], 14, True),
        ("Managing a Sales Team in RMR Platform", "Sales Management", ["SALES_MANAGER"], 16, True),
        ("Executive Forecast and Revenue Review", "Forecasting", ["VP_SALES", "EXECUTIVE_VIEWER"], 20, True),
        ("Importing Prior-Year Sales Data", "Sales Data", ["CLIENT_ADMIN", "SALES_MANAGER"], 11, True),
        ("Turning Website Leads into CRM Opportunities", "Website", ["MARKETING_USER", "SALES_REP"], 10, False),
        ("ProspectIQ Paid Enhancement Workflow", "ProspectIQ", ["CLIENT_ADMIN", "VP_SALES", "SALES_REP"], 9, True),
        ("Content Review, Editing and Approval", "Marketing", ["MARKETING_USER", "CLIENT_ADMIN"], 13, True),
    ]
    created: list[TrainingResource] = []
    for title, module, roles, duration, required in resources:
        resource = TrainingResource(
            title=title,
            description=f"Role-focused training for {module.lower()} operations.",
            module=module,
            media_type="external_link",
            media_url="https://example.com/training-placeholder",
            required=required,
            roles_json=roles,
            duration_minutes=duration,
            created_by=global_admin.id,
        )
        db.add(resource)
        db.flush()
        created.append(resource)
    for tenant in tenants:
        users = tenant_users[tenant.slug]
        all_users = [users["admin"], users["vp"], users["manager"], users["marketing"], *users["reps"]]  # type: ignore[list-item]
        for user in all_users:
            for resource in created:
                if user.tenant_role in resource.roles_json:
                    complete = RNG.random() < (tenant.training_completion_pct / 100)
                    db.add(TrainingProgress(
                        tenant_id=tenant.id,
                        user_id=user.id,
                        resource_id=resource.id,
                        status="complete" if complete else "not_started",
                        progress_pct=100 if complete else 0,
                        completed_at=datetime.now(timezone.utc) - timedelta(days=RNG.randint(1, 40)) if complete else None,
                    ))


def _create_campaigns(db: Session, tenant: Tenant, users: dict[str, User]) -> None:
    marketing: User = users["marketing"]  # type: ignore[assignment]
    campaigns = [
        ("September Client Education Series", "LinkedIn", "Approved"),
        ("Quarterly Growth Campaign", "Email", "Draft"),
        ("Service Spotlight", "Facebook", "Scheduled"),
    ]
    for title, channel, status in campaigns:
        db.add(Campaign(
            tenant_id=tenant.id,
            title=title,
            channel=channel,
            status=status,
            content=f"Human-reviewed content draft for {title}.",
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=10) if status == "Scheduled" else None,
            approved_by=marketing.id if status in {"Approved", "Scheduled"} else None,
            created_by=marketing.id,
        ))


def _calculate_allocation(revenue: int, direct_cost: int, basis: str, rmr_pct: float, step2_pct: float) -> tuple[int, int]:
    pool = revenue - direct_cost if basis == "net" else revenue
    pool = max(pool, 0)
    return round(pool * rmr_pct / 100), round(pool * step2_pct / 100)


def seed_demo(db: Session, reset: bool = False) -> None:
    if reset:
        # Delete in foreign-key-safe order.
        for model in [
            TrainingProgress, TrainingResource, ForecastMonth, ForecastVersion, Activity, Opportunity, Contact, Lead,
            Account, PiqOpportunity, Campaign, WebsiteSection, WebsitePage, WebsiteSite, OnboardingStep,
            OnboardingProject, EconomicTransaction, TenantService, SolutionInterest, SolutionRequest, Notification,
            SupportAccess, AuditEvent, User, Tenant, ServiceCatalog,
        ]:
            db.execute(delete(model))
        db.commit()

    if db.scalar(select(func.count(User.id))) and not reset:
        return

    catalog = _create_service_catalog(db)
    owner = _create_user(
        db,
        email=os.getenv("RMR_OWNER_EMAIL", "dave@rmr.local"),
        password=os.getenv("RMR_OWNER_PASSWORD", "RMR-Owner-2026!"),
        full_name="Dave Laughlin",
        global_role="RMR_OWNER",
    )
    step2 = _create_user(
        db,
        email=os.getenv("STEP2_ADMIN_EMAIL", "hasan@step2.local"),
        password=os.getenv("STEP2_ADMIN_PASSWORD", "Step2-Admin-2026!"),
        full_name="Hasan — Step2",
        global_role="STEP2_ADMIN",
    )

    tenants: list[Tenant] = []
    tenant_users: dict[str, dict[str, User]] = {}
    families = ["executive-authority", "executive-authority", "executive-authority", "executive-authority", "bold-local-growth", "modern-agency", "community-impact", "calm-real-estate", "bold-local-growth", "modern-agency"]
    current_period = date.today().strftime("%Y-%m")

    for index, info in enumerate(TENANTS):
        contact_name, contact_email = info["contact"]
        tenant = Tenant(
            name=info["name"], slug=info["slug"], industry=info["industry"], country=info["country"],
            status=info["status"], seller_org=info["seller_org"], seller_name=info["seller_name"],
            onboarding_owner="Step2", website_mode=info["website_mode"],
            website_url=info.get("website_url", ""),
            managed_site_slug=info["slug"], adoption_score=info["adoption_score"],
            training_completion_pct=info["training_completion_pct"], health_status=info["health_status"],
            renewal_risk=info["renewal_risk"], primary_contact_name=contact_name, primary_contact_email=contact_email,
        )
        db.add(tenant)
        db.flush()
        tenants.append(tenant)
        completed = 8 if info["status"] in {"live", "private"} else 1
        _create_onboarding(db, tenant, completed)
        _create_website(db, tenant, families[index])
        users = _create_tenant_users(db, tenant, index)
        tenant_users[tenant.slug] = users
        if info["status"] != "onboarding":
            _create_crm_and_forecast(db, tenant, users, 30 if tenant.slug == "desert-peak" else 10)
            _create_campaigns(db, tenant, users)

        for code, contract_price in info["services"].items():
            service = catalog[code]
            tenant_service = TenantService(
                tenant_id=tenant.id,
                service_code=code,
                contract_price_cents=contract_price,
                usage_price_cents=contract_price if service.cadence == "usage" else 0,
                cadence=service.cadence,
                status="active",
                effective_date=date(date.today().year, 1, 1),
                next_billing_date=date.today() + timedelta(days=30),
            )
            db.add(tenant_service)
            quantity = 84 if code == "piq_enhancement" and tenant.slug == "desert-peak" else (RNG.randint(12, 55) if code == "piq_enhancement" else 1)
            revenue = int(contract_price * quantity)
            direct_cost = int(service.direct_cost_cents * quantity)
            rmr_share, step2_share = _calculate_allocation(revenue, direct_cost, service.split_basis, service.rmr_share_pct, service.step2_share_pct)
            db.add(EconomicTransaction(
                tenant_id=tenant.id,
                service_code=code,
                period=current_period,
                quantity=quantity,
                unit_price_cents=contract_price,
                revenue_cents=revenue,
                direct_cost_cents=direct_cost,
                split_basis=service.split_basis,
                rmr_share_pct=service.rmr_share_pct,
                step2_share_pct=service.step2_share_pct,
                rmr_share_cents=rmr_share,
                step2_share_cents=step2_share,
                invoice_reference=f"INV-{date.today().year}-{index+1:03d}-{code[:5].upper()}",
                trace_reference=f"TRACE-{tenant.slug}-{code}-{current_period}",
            ))

    _create_training(db, owner, tenants, tenant_users)

    # Demonstrate an active request and meaningful repeated exploration.
    apex = next(t for t in tenants if t.slug == "apex-growth")
    apex_admin: User = tenant_users[apex.slug]["admin"]  # type: ignore[assignment]
    request = SolutionRequest(
        tenant_id=apex.id,
        service_code="piq_access",
        requested_by=apex_admin.id,
        status="Requested",
        note="Interested in a structured ProspectIQ trial for the agency sales team.",
        proposed_monthly_cents=17500,
        proposed_usage_cents=400,
        preferred_contact_method="Email",
        best_time="Weekday mornings",
    )
    db.add(request)
    db.add(Notification(
        recipient_scope="GLOBAL_ADMIN",
        tenant_id=apex.id,
        notification_type="solution_request",
        title="New solution request — ProspectIQ",
        body="Apex Growth Collective requested ProspectIQ. Assign an RMR/Step2 sales follow-up.",
    ))
    for offset in [1, 3, 6, 9]:
        db.add(SolutionInterest(
            tenant_id=apex.id,
            user_id=apex_admin.id,
            service_code="piq_access",
            event_type="pricing_view" if offset in {3, 9} else "demo_view",
            created_at=datetime.now(timezone.utc) - timedelta(days=offset),
        ))

    db.add(SupportAccess(
        admin_user_id=owner.id,
        tenant_id=tenants[0].id,
        area="CRM — Read Only",
        purpose="Authorized support review",
        access_type="read_only",
    ))
    db.add(AuditEvent(
        actor_user_id=owner.id,
        tenant_id=tenants[0].id,
        event_type="support.view",
        entity_type="tenant",
        entity_id=tenants[0].id,
        event_data={"area": "CRM", "access": "read_only"},
    ))
    db.commit()
