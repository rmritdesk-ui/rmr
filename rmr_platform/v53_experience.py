from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .cb1_models import CB1Message, CB1SocialContent
from .client_admin_models import CampaignExportPackage, ClientTrainingAssignment, ClientTrainingResource
from .cumulative_product_models import MessageDeliveryContext
from .db import get_db
from .models import (
    Account,
    Activity,
    Contact,
    ForecastMonth,
    ForecastVersion,
    Lead,
    Opportunity,
    PiqOpportunity,
    Tenant,
    User,
)
from .permissions import is_global_admin, require_client_operational_write, require_tenant_access
from .security import current_user, require_request_origin
from .services import audit
from .unified_models import AppointmentRequest, PiqEvidence
from .utils import model_dict

router = APIRouter(prefix="/api/v53", tags=["v5.3-client-experience"])

CLOSED_STAGES = {"Closed Won", "Closed Lost"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return model_dict(obj, exclude=set(exclude))


def _require_client_admin_scope(user: User, tenant_id: str) -> None:
    require_tenant_access(user, tenant_id)
    if is_global_admin(user):
        return
    if user.tenant_id != tenant_id or user.tenant_role != "CLIENT_ADMIN":
        raise HTTPException(status_code=403, detail="Client Administrator access required")


def _user_map(db: Session, tenant_id: str) -> dict[str, User]:
    return {row.id: row for row in db.scalars(select(User).where(User.tenant_id == tenant_id))}


def _piq_for_company(db: Session, tenant_id: str, company_name: str) -> dict[str, Any] | None:
    name = (company_name or "").strip()
    if not name:
        return None
    row = db.scalar(
        select(PiqOpportunity)
        .where(PiqOpportunity.tenant_id == tenant_id, func.lower(PiqOpportunity.company_name) == name.lower())
        .order_by(PiqOpportunity.created_at.desc())
    )
    if not row:
        return None
    evidence = list(
        db.scalars(
            select(PiqEvidence)
            .where(PiqEvidence.opportunity_id == row.id)
            .order_by(PiqEvidence.observed_at.desc())
        )
    )
    return {
        **_row(row),
        "evidence": [_row(item) for item in evidence],
        "provider_state": "production_provider_required" if "Demo" in " ".join(item.source_name for item in evidence) else "provider_evidence",
    }


def _messages_for_record(db: Session, tenant_id: str, *, account_id: str | None = None,
                         opportunity_id: str | None = None, contact_id: str | None = None,
                         lead_id: str | None = None) -> list[dict[str, Any]]:
    predicates = []
    if account_id:
        predicates.append(MessageDeliveryContext.account_id == account_id)
    if opportunity_id:
        predicates.append(MessageDeliveryContext.opportunity_id == opportunity_id)
    if contact_id:
        predicates.append(MessageDeliveryContext.contact_id == contact_id)
    if lead_id:
        predicates.append(MessageDeliveryContext.lead_id == lead_id)
    if not predicates:
        return []
    rows = list(
        db.execute(
            select(CB1Message, MessageDeliveryContext)
            .join(MessageDeliveryContext, MessageDeliveryContext.message_id == CB1Message.id)
            .where(CB1Message.tenant_id == tenant_id, or_(*predicates))
            .order_by(CB1Message.created_at.desc())
        )
    )
    return [
        {
            "id": msg.id,
            "subject": msg.subject,
            "recipient_email": msg.recipient_email,
            "status": ctx.delivery_status or msg.status,
            "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "body": msg.body_approved or msg.body_draft,
            "sender_email": ctx.sender_email,
            "sender_name": ctx.sender_name,
            "recipient_name": ctx.recipient_name,
            "provider": ctx.provider,
        }
        for msg, ctx in rows
    ]


@router.get("/tenants/{tenant_id}/dashboard")
def client_dashboard(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_client_admin_scope(user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")

    accounts = db.scalar(select(func.count(Account.id)).where(Account.tenant_id == tenant_id)) or 0
    leads = db.scalar(select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id, Lead.status != "Converted")) or 0
    open_opps = db.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage.notin_(list(CLOSED_STAGES)),
        )
    ) or 0
    weighted = db.scalar(
        select(func.coalesce(func.sum(Opportunity.value_cents * Opportunity.probability_pct / 100.0), 0)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage.notin_(list(CLOSED_STAGES)),
        )
    ) or 0
    website_leads = db.scalar(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id, Lead.source.like("Website%"))
    ) or 0
    appointments = db.scalar(select(func.count(AppointmentRequest.id)).where(AppointmentRequest.tenant_id == tenant_id)) or 0
    piq_records = db.scalar(select(func.count(PiqOpportunity.id)).where(PiqOpportunity.tenant_id == tenant_id)) or 0
    piq_to_crm = db.scalar(
        select(func.count(PiqOpportunity.id)).where(PiqOpportunity.tenant_id == tenant_id, PiqOpportunity.moved_to_crm.is_(True))
    ) or 0
    social_drafts = db.scalar(
        select(func.count(CB1SocialContent.id)).where(CB1SocialContent.tenant_id == tenant_id, CB1SocialContent.status == "DRAFT")
    ) or 0
    messages = db.scalar(select(func.count(CB1Message.id)).where(CB1Message.tenant_id == tenant_id)) or 0
    won_opps = db.scalar(
        select(func.count(Opportunity.id)).where(Opportunity.tenant_id == tenant_id, Opportunity.stage == "Closed Won")
    ) or 0
    won_revenue = db.scalar(
        select(func.coalesce(func.sum(Opportunity.value_cents), 0)).where(
            Opportunity.tenant_id == tenant_id, Opportunity.stage == "Closed Won"
        )
    ) or 0

    stale_cutoff = _now() - timedelta(days=7)
    stale_opps = db.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage.notin_(list(CLOSED_STAGES)),
            Opportunity.updated_at < stale_cutoff,
        )
    ) or 0
    attention: list[dict[str, Any]] = []
    if leads:
        attention.append({"title": f"{leads} active lead{'s' if leads != 1 else ''}", "detail": "Review new leads and assign the next follow-up.", "route": "crm?tab=leads", "label": "Work Leads", "tone": "blue"})
    if stale_opps:
        attention.append({"title": f"{stale_opps} opportunity follow-up{'s' if stale_opps != 1 else ''}", "detail": "These opportunities have not been updated in more than seven days.", "route": "crm?tab=opportunities&filter=stale", "label": "Review Pipeline", "tone": "amber"})
    if piq_records > piq_to_crm:
        attention.append({"title": f"{piq_records - piq_to_crm} ProspectIQ record{'s' if piq_records - piq_to_crm != 1 else ''} to review", "detail": "Review intelligence and move qualified prospects into CRM.", "route": "piq", "label": "Review Prospects", "tone": "purple"})
    if social_drafts:
        attention.append({"title": f"{social_drafts} social draft{'s' if social_drafts != 1 else ''}", "detail": "Review, edit and copy approved content for publication.", "route": "campaigns?tab=social", "label": "Review Content", "tone": "green"})

    recent = list(
        db.scalars(
            select(Activity)
            .where(Activity.tenant_id == tenant_id)
            .order_by(Activity.created_at.desc())
            .limit(12)
        )
    )
    kpis = [
        {"key": "accounts", "label": "Accounts", "value": int(accounts), "detail": "Customer and partner relationships", "route": "crm?tab=accounts"},
        {"key": "leads", "label": "Active Leads", "value": int(leads), "detail": "Prospects requiring follow-up", "route": "crm?tab=leads"},
        {"key": "opportunities", "label": "Open Opportunities", "value": int(open_opps), "detail": "Active sales pipeline", "route": "crm?tab=opportunities"},
        {"key": "weighted", "label": "Weighted Pipeline", "value_cents": int(round(float(weighted))), "detail": "Probability-adjusted opportunity value", "route": "crm?tab=opportunities"},
        {"key": "website", "label": "Website Leads", "value": int(website_leads), "detail": f"{appointments} appointment request(s)", "route": "crm?tab=leads&source=Website"},
        {"key": "piq", "label": "ProspectIQ", "value": int(piq_records), "detail": f"{piq_to_crm} moved to CRM", "route": "piq"},
        {"key": "won", "label": "Won Revenue", "value_cents": int(won_revenue), "detail": f"{won_opps} closed-won opportunity(s)", "route": "reports"},
        {"key": "communications", "label": "Recorded Emails", "value": int(messages), "detail": "One-to-one CRM communication", "route": "email?tab=messages"},
    ]
    return {
        "tenant": _row(tenant),
        "kpis": kpis,
        "attention": attention,
        "recent_activity": [_row(item) for item in recent],
        "data_scope": {
            "tenant_id": tenant_id,
            "tenant_name": tenant.name,
            "description": f"All metrics on this screen are scoped to {tenant.name}.",
        },
    }


@router.get("/tenants/{tenant_id}/crm/overview")
def crm_overview(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_client_admin_scope(user, tenant_id)
    users = _user_map(db, tenant_id)
    accounts = list(db.scalars(select(Account).where(Account.tenant_id == tenant_id).order_by(Account.name)))
    contacts = list(db.scalars(select(Contact).where(Contact.tenant_id == tenant_id).order_by(Contact.last_name, Contact.first_name)))
    leads = list(db.scalars(select(Lead).where(Lead.tenant_id == tenant_id).order_by(Lead.created_at.desc())))
    opportunities = list(db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id).order_by(Opportunity.updated_at.desc())))
    activities = list(db.scalars(select(Activity).where(Activity.tenant_id == tenant_id).order_by(Activity.created_at.desc()).limit(300)))

    account_map = {row.id: row for row in accounts}
    contact_map = {row.id: row for row in contacts}
    opp_map = {row.id: row for row in opportunities}
    account_contact_counts = dict(db.execute(select(Contact.account_id, func.count(Contact.id)).where(Contact.tenant_id == tenant_id).group_by(Contact.account_id)).all())
    account_opp_counts = dict(db.execute(select(Opportunity.account_id, func.count(Opportunity.id)).where(Opportunity.tenant_id == tenant_id).group_by(Opportunity.account_id)).all())
    activity_counts = dict(db.execute(select(Activity.opportunity_id, func.count(Activity.id)).where(Activity.tenant_id == tenant_id).group_by(Activity.opportunity_id)).all())
    last_activity = dict(db.execute(select(Activity.opportunity_id, func.max(Activity.created_at)).where(Activity.tenant_id == tenant_id).group_by(Activity.opportunity_id)).all())

    weighted = sum(row.value_cents * row.probability_pct / 100 for row in opportunities if row.stage not in CLOSED_STAGES)
    summary = {
        "accounts": len(accounts),
        "active_leads": len([row for row in leads if row.status != "Converted"]),
        "open_opportunities": len([row for row in opportunities if row.stage not in CLOSED_STAGES]),
        "weighted_pipeline_cents": int(round(weighted)),
    }
    return {
        "summary": summary,
        "accounts": [
            {
                **_row(row),
                "owner_name": users.get(row.owner_user_id).full_name if row.owner_user_id in users else "Unassigned",
                "contact_count": int(account_contact_counts.get(row.id, 0)),
                "opportunity_count": int(account_opp_counts.get(row.id, 0)),
            }
            for row in accounts
        ],
        "contacts": [
            {
                **_row(row),
                "account_name": account_map.get(row.account_id).name if row.account_id in account_map else "",
                "open_opportunity_count": len([opp for opp in opportunities if opp.contact_id == row.id and opp.stage not in CLOSED_STAGES]),
            }
            for row in contacts
        ],
        "leads": [
            {
                **_row(row),
                "assigned_name": users.get(row.assigned_user_id).full_name if row.assigned_user_id in users else "Unassigned",
                "piq": _piq_for_company(db, tenant_id, row.company_name),
            }
            for row in leads
        ],
        "opportunities": [
            {
                **_row(row),
                "account_name": account_map.get(row.account_id).name if row.account_id in account_map else "",
                "contact_name": (
                    f"{contact_map.get(row.contact_id).first_name} {contact_map.get(row.contact_id).last_name}".strip()
                    if row.contact_id in contact_map else ""
                ),
                "contact_email": contact_map.get(row.contact_id).email if row.contact_id in contact_map else "",
                "owner_name": users.get(row.owner_user_id).full_name if row.owner_user_id in users else "Unassigned",
                "activity_count": int(activity_counts.get(row.id, 0)),
                "last_activity_at": last_activity.get(row.id).isoformat() if last_activity.get(row.id) else None,
                "piq": _piq_for_company(db, tenant_id, account_map.get(row.account_id).name if row.account_id in account_map else row.name.replace(" opportunity", "")),
            }
            for row in opportunities
        ],
        "activities": [
            {
                **_row(row),
                "account_name": account_map.get(row.account_id).name if row.account_id in account_map else "",
                "opportunity_name": opp_map.get(row.opportunity_id).name if row.opportunity_id in opp_map else "",
                "actor_name": users.get(row.user_id).full_name if row.user_id in users else "System",
            }
            for row in activities
        ],
        "data_scope": f"CRM records for {db.get(Tenant, tenant_id).name}",
    }


@router.get("/tenants/{tenant_id}/crm/records/{record_type}/{record_id}")
def crm_record_detail(tenant_id: str, record_type: Literal["account", "contact", "lead", "opportunity"], record_id: str,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_client_admin_scope(user, tenant_id)
    users = _user_map(db, tenant_id)
    if record_type == "account":
        account = db.get(Account, record_id)
        if not account or account.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Account not found")
        contacts = list(db.scalars(select(Contact).where(Contact.account_id == account.id).order_by(Contact.primary_contact.desc(), Contact.last_name)))
        opportunities = list(db.scalars(select(Opportunity).where(Opportunity.account_id == account.id).order_by(Opportunity.updated_at.desc())))
        activities = list(db.scalars(select(Activity).where(Activity.account_id == account.id).order_by(Activity.created_at.desc()).limit(100)))
        primary = {**_row(account), "owner_name": users.get(account.owner_user_id).full_name if account.owner_user_id in users else "Unassigned"}
        messages = _messages_for_record(db, tenant_id, account_id=account.id)
        piq = _piq_for_company(db, tenant_id, account.name)
        related = {"contacts": [_row(row) for row in contacts], "opportunities": [_row(row) for row in opportunities]}
    elif record_type == "contact":
        contact = db.get(Contact, record_id)
        if not contact or contact.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Contact not found")
        account = db.get(Account, contact.account_id) if contact.account_id else None
        opportunities = list(db.scalars(select(Opportunity).where(Opportunity.contact_id == contact.id).order_by(Opportunity.updated_at.desc())))
        activity_predicates = []
        if contact.account_id:
            activity_predicates.append(Activity.account_id == contact.account_id)
        if opportunities:
            activity_predicates.append(Activity.opportunity_id.in_([x.id for x in opportunities]))
        activities = list(db.scalars(select(Activity).where(or_(*activity_predicates)).order_by(Activity.created_at.desc()).limit(100))) if activity_predicates else []
        primary = {**_row(contact), "name": f"{contact.first_name} {contact.last_name}".strip(), "account_name": account.name if account else ""}
        messages = _messages_for_record(db, tenant_id, account_id=contact.account_id, contact_id=contact.id)
        piq = _piq_for_company(db, tenant_id, account.name if account else "")
        related = {"account": _row(account) if account else None, "opportunities": [_row(row) for row in opportunities]}
    elif record_type == "lead":
        lead = db.get(Lead, record_id)
        if not lead or lead.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Lead not found")
        primary = {**_row(lead), "assigned_name": users.get(lead.assigned_user_id).full_name if lead.assigned_user_id in users else "Unassigned"}
        messages = _messages_for_record(db, tenant_id, lead_id=lead.id)
        piq = _piq_for_company(db, tenant_id, lead.company_name)
        activities = []
        related = {}
    else:
        opportunity = db.get(Opportunity, record_id)
        if not opportunity or opportunity.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        account = db.get(Account, opportunity.account_id) if opportunity.account_id else None
        contact = db.get(Contact, opportunity.contact_id) if opportunity.contact_id else None
        activities = list(db.scalars(select(Activity).where(Activity.opportunity_id == opportunity.id).order_by(Activity.created_at.desc()).limit(100)))
        primary = {
            **_row(opportunity),
            "account_name": account.name if account else "",
            "contact_name": f"{contact.first_name} {contact.last_name}".strip() if contact else "",
            "contact_email": contact.email if contact else "",
            "contact_phone": contact.phone if contact else "",
            "owner_name": users.get(opportunity.owner_user_id).full_name if opportunity.owner_user_id in users else "Unassigned",
        }
        messages = _messages_for_record(db, tenant_id, account_id=opportunity.account_id, opportunity_id=opportunity.id, contact_id=opportunity.contact_id)
        piq = _piq_for_company(db, tenant_id, account.name if account else opportunity.name.replace(" opportunity", ""))
        related = {"account": _row(account) if account else None, "contact": _row(contact) if contact else None}

    return {
        "record_type": record_type,
        "record": primary,
        "related": related,
        "activities": [_row(row) for row in activities],
        "messages": messages,
        "piq": piq,
        "read_only": is_global_admin(user),
    }


class LeadConversionIn(BaseModel):
    account_name: str = Field(min_length=1, max_length=200)
    create_contact: bool = True
    create_opportunity: bool = True
    opportunity_name: str = Field(default="", max_length=200)
    stage: str = Field(default="Prospecting", max_length=60)
    value_cents: int = Field(default=0, ge=0)
    probability_pct: int = Field(default=10, ge=0, le=100)
    expected_close_date: date | None = None
    next_action: str = Field(default="", max_length=300)


@router.post("/leads/{lead_id}/convert")
def controlled_lead_conversion(lead_id: str, payload: LeadConversionIn, request: Request,
                               user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    require_client_operational_write(user, lead.tenant_id)
    if lead.status == "Converted":
        raise HTTPException(status_code=409, detail="This lead has already been converted")
    account = Account(
        tenant_id=lead.tenant_id,
        name=payload.account_name.strip(),
        status="Active",
        owner_user_id=lead.assigned_user_id or user.id,
        team_name=user.team_name,
        annual_value_cents=payload.value_cents,
        source=lead.source,
        risk="Low",
        notes=lead.notes,
    )
    db.add(account)
    db.flush()
    contact = None
    if payload.create_contact:
        first_name, _, last_name = (lead.contact_name or payload.account_name).partition(" ")
        contact = Contact(
            tenant_id=lead.tenant_id,
            account_id=account.id,
            first_name=first_name,
            last_name=last_name,
            email=lead.email,
            phone=lead.phone,
            primary_contact=True,
        )
        db.add(contact)
        db.flush()
    opportunity = None
    if payload.create_opportunity:
        opportunity = Opportunity(
            tenant_id=lead.tenant_id,
            account_id=account.id,
            contact_id=contact.id if contact else None,
            owner_user_id=lead.assigned_user_id or user.id,
            name=payload.opportunity_name.strip() or f"{account.name} opportunity",
            stage=payload.stage,
            value_cents=payload.value_cents,
            probability_pct=payload.probability_pct,
            expected_close_date=payload.expected_close_date,
            source=lead.source,
            next_action=payload.next_action.strip(),
        )
        db.add(opportunity)
        db.flush()
    activity = Activity(
        tenant_id=lead.tenant_id,
        account_id=account.id,
        opportunity_id=opportunity.id if opportunity else None,
        user_id=user.id,
        activity_type="Lead Conversion",
        subject=f"Converted lead: {lead.contact_name or lead.company_name or account.name}",
        body=f"Source: {lead.source}. Account created: {account.name}." + (f" Opportunity created: {opportunity.name}." if opportunity else ""),
        completed_at=_now(),
    )
    db.add(activity)
    lead.status = "Converted"
    audit(
        db,
        user,
        "crm.lead.converted.controlled",
        tenant_id=lead.tenant_id,
        entity_type="lead",
        entity_id=lead.id,
        data={
            "account_id": account.id,
            "contact_id": contact.id if contact else None,
            "opportunity_id": opportunity.id if opportunity else None,
            "value_cents": payload.value_cents,
            "stage": payload.stage,
        },
    )
    db.commit()
    return {
        "lead": _row(lead),
        "account": _row(account),
        "contact": _row(contact) if contact else None,
        "opportunity": _row(opportunity) if opportunity else None,
        "activity": _row(activity),
    }


class ContactUpdateIn(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=140)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=80)
    primary_contact: bool | None = None


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: str, payload: ContactUpdateIn, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = db.get(Contact, contact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
    require_client_operational_write(user, row.tenant_id)
    for name, value in payload.model_dump(exclude_none=True).items():
        setattr(row, name, value)
    audit(db, user, "crm.contact.updated", tenant_id=row.tenant_id, entity_type="contact", entity_id=row.id, data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"contact": _row(row)}


class LeadUpdateIn(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=5000)
    assigned_user_id: str | None = None


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: str, payload: LeadUpdateIn, request: Request,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    row = db.get(Lead, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    require_client_operational_write(user, row.tenant_id)
    for name, value in payload.model_dump(exclude_none=True).items():
        setattr(row, name, value)
    audit(db, user, "crm.lead.updated", tenant_id=row.tenant_id, entity_type="lead", entity_id=row.id, data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"lead": _row(row)}


@router.get("/campaign-exports/{package_id}")
def campaign_export_detail(package_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(CampaignExportPackage, package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Campaign export package not found")
    require_tenant_access(user, row.tenant_id)
    return {
        "package": _row(row),
        "download_url": f"/api/v521/campaign-exports/{row.id}/download",
        "instructions": {
            "summary": f"Download the recipient CSV and import it into {row.provider_format.replace('_', ' ').title()}.",
            "steps": [
                "Download the recipient CSV to your computer.",
                f"Open {row.provider_format.replace('_', ' ').title()} and import the recipient file.",
                "Copy the subject, preview text and approved email content from this package into the email platform.",
                "Review suppression, consent and provider compliance settings before sending.",
            ],
            "bulk_delivery": False,
        },
    }


@router.get("/tenants/{tenant_id}/forecast-dashboard")
def forecast_dashboard(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_client_admin_scope(user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    version = db.scalar(
        select(ForecastVersion)
        .where(ForecastVersion.tenant_id == tenant_id, ForecastVersion.is_active.is_(True))
        .order_by(ForecastVersion.created_at.desc())
    )
    if not version:
        return {"tenant": _row(tenant), "version": None, "months": [], "summary": {}, "data_scope": f"No active forecast for {tenant.name}."}
    rows = list(db.scalars(select(ForecastMonth).where(ForecastMonth.version_id == version.id).order_by(ForecastMonth.month)))
    monthly = []
    for month in range(1, 13):
        month_rows = [row for row in rows if row.month == month]
        monthly.append({
            "month": month,
            "prior_actual_cents": sum(row.prior_actual_cents for row in month_rows),
            "forecast_cents": sum(row.forecast_cents for row in month_rows),
            "actual_cents": sum(row.actual_cents for row in month_rows),
        })
    closed_won = db.scalar(
        select(func.coalesce(func.sum(Opportunity.value_cents), 0)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage == "Closed Won",
        )
    ) or 0
    open_pipeline = db.scalar(
        select(func.coalesce(func.sum(Opportunity.value_cents), 0)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage.notin_(list(CLOSED_STAGES)),
        )
    ) or 0
    weighted = db.scalar(
        select(func.coalesce(func.sum(Opportunity.value_cents * Opportunity.probability_pct / 100.0), 0)).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.stage.notin_(list(CLOSED_STAGES)),
        )
    ) or 0
    return {
        "tenant": _row(tenant),
        "version": _row(version),
        "months": monthly,
        "summary": {
            "annual_goal_cents": version.annual_goal_cents,
            "forecast_cents": sum(row.forecast_cents for row in rows),
            "actual_imported_cents": sum(row.actual_cents for row in rows),
            "prior_actual_cents": sum(row.prior_actual_cents for row in rows),
            "closed_won_cents": int(closed_won),
            "open_pipeline_cents": int(open_pipeline),
            "weighted_pipeline_cents": int(round(float(weighted))),
        },
        "sources": {
            "forecast": "Client-entered or imported operating forecast",
            "actual_imported": "Imported historical/current actuals stored in the active forecast",
            "closed_won": "CRM opportunities for this tenant marked Closed Won",
            "pipeline": "Open CRM opportunities for this tenant",
        },
        "data_scope": f"Forecast and CRM values for {tenant.name} only.",
    }
