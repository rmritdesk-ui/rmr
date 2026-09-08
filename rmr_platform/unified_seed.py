from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cb1_models
from .models import (
    Account,
    Activity,
    Campaign,
    Contact,
    Lead,
    Opportunity,
    PiqOpportunity,
    Tenant,
    User,
    WebsitePage,
    WebsiteSection,
    WebsiteSite,
)
from .unified_models import (
    AppointmentRequest,
    PiqEvidence,
    PiqTargetProfile,
    SeoWorkItem,
    WebsiteBlogPost,
    WebsiteMedia,
    WebsiteResource,
    WebsiteTeamProfile,
)


def _existing(db: Session, model, *criteria):
    return db.scalar(select(model).where(*criteria))



def _seed_commercial_readiness(db: Session, tenant: Tenant, admin: User) -> None:
    """Create complete, internally consistent Product Owner demo evidence.

    This function is called only when explicit demo seeding is enabled. It is
    idempotent and is never executed during protected customer-data upgrades.
    """
    now = datetime.now(timezone.utc)
    profile = _existing(db, cb1_models.CB1CommercialProfile, cb1_models.CB1CommercialProfile.tenant_id == tenant.id)
    if not profile:
        db.add(cb1_models.CB1CommercialProfile(tenant_id=tenant.id, managed_no_login=False, managed_reason=None, updated_by=admin.id))

    invite = _existing(
        db, cb1_models.CB1ClientAdminInvite,
        cb1_models.CB1ClientAdminInvite.tenant_id == tenant.id,
        cb1_models.CB1ClientAdminInvite.email == admin.email,
    )
    if not invite:
        token_hash = hashlib.sha256(f"product-owner-demo:{tenant.slug}:{admin.email}".encode()).hexdigest()
        db.add(cb1_models.CB1ClientAdminInvite(
            tenant_id=tenant.id, email=admin.email, full_name=admin.full_name, status="ACTIVATED",
            token_hash=token_hash, expires_at=now + timedelta(days=3650), activated_user_id=admin.id,
            created_by=admin.id, activated_at=now, last_sent_at=now,
        ))
    else:
        invite.status = "ACTIVATED"
        invite.activated_user_id = admin.id
        invite.activated_at = invite.activated_at or now

    reference = f"PO-DEMO-{tenant.slug.upper()}"
    order = _existing(
        db, cb1_models.CB1OrderForm,
        cb1_models.CB1OrderForm.tenant_id == tenant.id,
        cb1_models.CB1OrderForm.reference == reference,
    )
    if not order:
        order = cb1_models.CB1OrderForm(
            tenant_id=tenant.id, reference=reference, status="ACTIVE",
            effective_date=now.date().isoformat(), signed_at=now,
            notes="Isolated Product Owner demonstration entitlement record.", created_by=admin.id,
        )
        db.add(order)
        db.flush()
    else:
        order.status = "ACTIVE"
        order.signed_at = order.signed_at or now

    module_keys = ["website", "crm", "piq", "campaigns", "email", "forecast", "reports", "training", "organization"]
    for key in module_keys:
        entitlement = _existing(
            db, cb1_models.CB1Entitlement,
            cb1_models.CB1Entitlement.tenant_id == tenant.id,
            cb1_models.CB1Entitlement.order_form_id == order.id,
            cb1_models.CB1Entitlement.module_key == key,
        )
        if not entitlement:
            db.add(cb1_models.CB1Entitlement(
                order_form_id=order.id, tenant_id=tenant.id, module_key=key, enabled=True, starts_at=now,
            ))
        else:
            entitlement.enabled = True

    provider = _existing(
        db, cb1_models.CB1ProviderConnection,
        cb1_models.CB1ProviderConnection.tenant_id == tenant.id,
        cb1_models.CB1ProviderConnection.provider == "MOCK",
    )
    if not provider:
        db.add(cb1_models.CB1ProviderConnection(
            tenant_id=tenant.id, provider="MOCK", sender_email=admin.email, sender_name=admin.full_name,
            physical_address="Product Owner demonstration address", status="ACTIVE",
            config_json=json.dumps({"mode": "product_owner_demo"}), created_by=admin.id,
        ))
    else:
        provider.status = "ACTIVE"

    worker = db.get(cb1_models.CB1WorkerState, "drip-worker")
    if not worker:
        db.add(cb1_models.CB1WorkerState(worker_name="drip-worker", status="HEALTHY", heartbeat_at=now, detail_json=json.dumps({"mode": "product_owner_demo"})))
    else:
        worker.status = "HEALTHY"
        worker.heartbeat_at = now


def _seed_kerry_website(db: Session, tenant: Tenant, admin: User) -> None:
    site = _existing(db, WebsiteSite, WebsiteSite.tenant_id == tenant.id)
    if not site:
        return
    site.mode = "managed"
    site.slug = "kerry-real-estate"
    site.company_name = "Kerry Laughlin Real Estate"
    site.wordmark = "KERRY LAUGHLIN"
    site.template_family = "calm-real-estate"
    site.primary_color = "#20314f"
    site.secondary_color = "#f6f2ec"
    site.accent_color = "#b78a5d"
    site.heading_font = "Georgia"
    site.body_font = "Arial"
    site.nav_style = "light"
    site.status = "published"
    site.external_url = ""

    page = _existing(db, WebsitePage, WebsitePage.site_id == site.id, WebsitePage.slug == "home")
    if page:
        page.title = "Home"
        page.seo_title = "Kerry Laughlin | Arizona and Colorado Real Estate"
        page.seo_description = "Personal real estate guidance for buyers, sellers and relocating families in Arizona and Colorado."
        sections = list(db.scalars(select(WebsiteSection).where(WebsiteSection.page_id == page.id).order_by(WebsiteSection.position)))
        settings = {
            "hero": {
                "eyebrow": "ARIZONA & COLORADO REAL ESTATE",
                "headline": "Find a home—and a process—that feels right.",
                "supporting_text": "Personal guidance for buyers, sellers and relocating families, backed by responsive communication and local market knowledge.",
                "primary_button": "Plan Your Next Move",
                "secondary_button": "Explore Communities",
                "layout": "split",
                "background": "brand",
            },
            "services": {
                "headline": "Real estate guidance built around your goals.",
                "items": ["Buy with confidence", "Sell with a clear plan", "Relocate with local support"],
            },
            "metrics": {
                "headline": "A more personal real estate experience.",
                "items": [
                    {"value": "2", "label": "Markets served"},
                    {"value": "1:1", "label": "Personal guidance"},
                    {"value": "100%", "label": "Client-focused"},
                ],
            },
            "contact": {
                "headline": "Ready to talk about your next move?",
                "body": "Tell Kerry what you are considering. She will follow up personally.",
            },
        }
        for section in sections:
            if section.section_type in settings:
                section.settings_json = settings[section.section_type]

    extra_pages = [
        ("About", "about", 2, "Meet Kerry", "Real estate guidance should feel personal, clear and grounded in what matters to you."),
        ("Communities", "communities", 3, "Explore Arizona and Colorado Communities", "Compare neighborhoods, lifestyle and the next steps for your move."),
        ("Resources", "resources", 4, "Buyer and Seller Resources", "Practical guidance for preparing, financing, moving and closing."),
    ]
    for title, slug, order, headline, body in extra_pages:
        row = _existing(db, WebsitePage, WebsitePage.site_id == site.id, WebsitePage.slug == slug)
        if not row:
            row = WebsitePage(site_id=site.id, title=title, slug=slug, nav_order=order, show_in_nav=True, status="published", seo_title=f"{title} | Kerry Laughlin Real Estate", seo_description=body)
            db.add(row)
            db.flush()
            db.add(WebsiteSection(page_id=row.id, section_type="hero", position=1, settings_json={"eyebrow": title.upper(), "headline": headline, "supporting_text": body, "primary_button": "Contact Kerry", "layout": "centered", "background": "editorial"}))
            db.add(WebsiteSection(page_id=row.id, section_type="text", position=2, settings_json={"headline": headline, "body": body}))

    if not _existing(db, WebsiteMedia, WebsiteMedia.tenant_id == tenant.id):
        db.add_all([
            WebsiteMedia(tenant_id=tenant.id, title="Kerry brand portrait", media_type="image", url="https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=1200&q=80", alt_text="Bright modern home exterior", tags_json=["hero", "real estate"], created_by=admin.id),
            WebsiteMedia(tenant_id=tenant.id, title="Arizona community", media_type="image", url="https://images.unsplash.com/photo-1613490493576-7fde63acd811?auto=format&fit=crop&w=1200&q=80", alt_text="Arizona luxury home", tags_json=["Arizona", "community"], created_by=admin.id),
            WebsiteMedia(tenant_id=tenant.id, title="Colorado community", media_type="image", url="https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?auto=format&fit=crop&w=1200&q=80", alt_text="Warm home interior", tags_json=["Colorado", "home"], created_by=admin.id),
        ])

    if not _existing(db, WebsiteBlogPost, WebsiteBlogPost.tenant_id == tenant.id):
        now = datetime.now(timezone.utc)
        db.add_all([
            WebsiteBlogPost(tenant_id=tenant.id, title="Preparing to Sell Without Feeling Overwhelmed", slug="prepare-to-sell", summary="A calm first-step checklist for homeowners considering a move.", body="Start with your goals, timeline and the condition of the home. From there, build a practical preparation plan rather than trying to do everything at once.", status="published", seo_title="How to Prepare to Sell Your Home", seo_description="A practical home-selling preparation guide from Kerry Laughlin.", published_at=now-timedelta(days=12), created_by=admin.id),
            WebsiteBlogPost(tenant_id=tenant.id, title="What Relocating Families Should Compare First", slug="relocation-comparison", summary="How to compare communities beyond the listing price.", body="Commute, schools, daily routines, insurance, utilities and the feel of the community all matter. A good relocation plan compares the full lifestyle.", status="published", seo_title="Relocating to Arizona or Colorado", seo_description="Important factors to compare when relocating.", published_at=now-timedelta(days=5), created_by=admin.id),
        ])

    if not _existing(db, WebsiteResource, WebsiteResource.tenant_id == tenant.id):
        db.add_all([
            WebsiteResource(tenant_id=tenant.id, title="Home Buyer Planning Guide", description="Questions to answer before touring homes.", resource_type="guide", url="/sites/kerry-real-estate?page=resources", lead_capture_required=True, status="published", created_by=admin.id),
            WebsiteResource(tenant_id=tenant.id, title="Seller Preparation Checklist", description="A practical room-by-room preparation list.", resource_type="checklist", url="/sites/kerry-real-estate?page=resources", lead_capture_required=True, status="published", created_by=admin.id),
        ])

    if not _existing(db, WebsiteTeamProfile, WebsiteTeamProfile.tenant_id == tenant.id):
        db.add(WebsiteTeamProfile(tenant_id=tenant.id, full_name="Kerry Laughlin", title="REALTOR®", bio="Kerry helps buyers, sellers and relocating families make confident real estate decisions with personal guidance and clear communication.", email="kerry@laughlinrealestate.demo", phone="602-555-0147", photo_url="", display_order=1, visible=True))

    if not _existing(db, SeoWorkItem, SeoWorkItem.tenant_id == tenant.id):
        db.add_all([
            SeoWorkItem(tenant_id=tenant.id, page_id=page.id if page else None, item_type="local_seo", title="Complete Arizona and Colorado market-area metadata", status="in_progress", priority="high", recommendation="Add brokerage-approved service-area language and local-market descriptions.", evidence_json={"owner": "Kerry", "module": "Website"}, created_by=admin.id),
            SeoWorkItem(tenant_id=tenant.id, page_id=page.id if page else None, item_type="content", title="Publish monthly buyer or seller article", status="open", priority="medium", recommendation="Use one market question from current clients as the article topic.", evidence_json={"cadence": "monthly"}, created_by=admin.id),
        ])


def _seed_kerry_growth(db: Session, tenant: Tenant, admin: User) -> None:
    if not _existing(db, PiqTargetProfile, PiqTargetProfile.tenant_id == tenant.id):
        db.add(PiqTargetProfile(
            tenant_id=tenant.id,
            name="Arizona & Colorado Referral Partners",
            industries_json=["Mortgage", "Title & Escrow", "Relocation", "Home Services"],
            locations_json=["Phoenix Metro, Arizona", "Northern Colorado"],
            employee_min=2,
            employee_max=250,
            revenue_min_cents=50000000,
            keywords_json=["relocation", "home buyer", "referral partner", "new office", "hiring"],
            exclusions_json=["direct residential real estate competitors"],
            created_by=admin.id,
        ))

    piq_rows = [
        ("Copper State Home Lending", 91, "Hiring loan officers and expanding regional home-buyer education.", 12500000),
        ("Sonoran Title & Escrow", 86, "Opened a new West Valley office and announced referral partnerships.", 8500000),
        ("Front Range Relocation Network", 82, "Growing employer relocation relationships in Northern Colorado.", 9800000),
        ("Summit Property Services", 76, "Increased homeowner education and vendor partnership activity.", 6000000),
    ]
    for company, score, signal, value in piq_rows:
        row = _existing(db, PiqOpportunity, PiqOpportunity.tenant_id == tenant.id, PiqOpportunity.company_name == company)
        if not row:
            row = PiqOpportunity(tenant_id=tenant.id, company_name=company, score=score, signal=signal, evidence_count=2, enhanced=score >= 85, estimated_value_cents=value, status="Priority" if score >= 85 else "Qualified", enhancement_price_cents=400)
            db.add(row)
            db.flush()
            db.add_all([
                PiqEvidence(opportunity_id=row.id, evidence_type="growth_signal", source_name="RMR Demonstration Provider", source_url="https://example.com/public-signal", fact=signal, confidence_pct=score, verified=True),
                PiqEvidence(opportunity_id=row.id, evidence_type="profile_match", source_name="Kerry Target Profile", fact="Matches an approved referral-partner industry and geographic market.", confidence_pct=max(65, score-8), verified=True),
            ])

    if not _existing(db, cb1_models.CB1ProviderConnection, cb1_models.CB1ProviderConnection.tenant_id == tenant.id):
        db.add(cb1_models.CB1ProviderConnection(tenant_id=tenant.id, provider="MOCK", sender_email="kerry@laughlinrealestate.demo", sender_name="Kerry Laughlin", physical_address="Phoenix, Arizona", status="ACTIVE", config_json=json.dumps({"mode": "product_owner_demo"}), created_by=admin.id))

    if not _existing(db, cb1_models.CB1SocialContent, cb1_models.CB1SocialContent.tenant_id == tenant.id):
        tags = "#ArizonaRealEstate #ColoradoRealEstate #HomeBuying"
        db.add_all([
            cb1_models.CB1SocialContent(tenant_id=tenant.id, platform="FACEBOOK", title="Buyer planning", post_text="The best home search starts before the first showing. Clarify the budget, timing and daily-life priorities that matter most.", hashtags=tags, status="DRAFT", created_by=admin.id),
            cb1_models.CB1SocialContent(tenant_id=tenant.id, platform="INSTAGRAM", title="Buyer planning", post_text="A calmer home search starts with a clear plan—not more listings. Let’s define what matters before we tour.", hashtags=tags, status="DRAFT", created_by=admin.id),
            cb1_models.CB1SocialContent(tenant_id=tenant.id, platform="LINKEDIN", title="Relocation partnerships", post_text="Relocating employees need more than a list of homes. Local coordination, community context and a clear process make the transition easier.", hashtags="#Relocation #RealEstate", status="DRAFT", created_by=admin.id),
            cb1_models.CB1SocialContent(tenant_id=tenant.id, platform="X", title="Seller preparation", post_text="Selling feels more manageable when the preparation plan matches your timeline and goals.", hashtags="#HomeSelling", status="DRAFT", created_by=admin.id),
        ])

    if not _existing(db, cb1_models.CB1Message, cb1_models.CB1Message.tenant_id == tenant.id):
        db.add(cb1_models.CB1Message(
            tenant_id=tenant.id,
            campaign_id=None,
            crm_record_id=None,
            piq_record_id=None,
            recipient_email="partner@example.com",
            subject="Arizona relocation referral partnership",
            body_draft="Hi Jordan, I help relocating buyers understand the Arizona market and coordinate a clear home-search plan. Would a brief introduction be worthwhile?",
            body_approved="Hi Jordan, I help relocating buyers understand the Arizona market and coordinate a clear home-search plan. Would a brief introduction be worthwhile?",
            approved_hash="demo-approved-message",
            status="SENT",
            approved_by=admin.id,
            approved_at=datetime.now(timezone.utc)-timedelta(days=2),
            sent_at=datetime.now(timezone.utc)-timedelta(days=2),
            idempotency_key="kerry-demo-message-1",
            supported_facts_json=json.dumps(["Kerry serves Arizona and Colorado", "Kerry supports relocating buyers"]),
            created_by=admin.id,
        ))

    if not _existing(db, AppointmentRequest, AppointmentRequest.tenant_id == tenant.id):
        lead = Lead(tenant_id=tenant.id, company_name="", contact_name="Taylor Morgan", email="taylor@example.com", phone="602-555-0188", source="Website Appointment Request", status="New", notes="Preferred time: Thursday afternoon\nConsidering a move to the West Valley.", assigned_user_id=admin.id)
        db.add(lead)
        db.flush()
        db.add(AppointmentRequest(tenant_id=tenant.id, name="Taylor Morgan", email="taylor@example.com", phone="602-555-0188", preferred_time="Thursday afternoon", message="Considering a move to the West Valley.", lead_id=lead.id))


def seed_unified_demo(db: Session) -> None:
    """Seed additive product-owner data only when demo seeding is explicitly enabled.

    The function is idempotent and never runs during a protected customer-data
    upgrade unless RMR_AUTO_SEED is deliberately enabled for the isolated demo.
    """
    kerry = db.scalar(select(Tenant).where(Tenant.slug == "kerry-real-estate"))
    if not kerry:
        return
    admin = db.scalar(select(User).where(User.tenant_id == kerry.id, User.tenant_role == "CLIENT_ADMIN"))
    if not admin:
        return
    _seed_kerry_website(db, kerry, admin)
    _seed_kerry_growth(db, kerry, admin)
    _seed_commercial_readiness(db, kerry, admin)

    caf = db.scalar(select(Tenant).where(Tenant.slug == "cactus-air-filters"))
    if caf:
        caf_admin = db.scalar(select(User).where(User.tenant_id == caf.id, User.tenant_role == "CLIENT_ADMIN"))
        if caf_admin:
            _seed_commercial_readiness(db, caf, caf_admin)
    db.commit()
