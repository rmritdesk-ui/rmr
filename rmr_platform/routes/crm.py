from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..crm_conversion import create_prospect_from_lead, sync_won_opportunity, find_account_by_name
from ..models import CrmProspect
from ..schemas import CrmProspectUpdate, ProspectOpportunityCreate
from ..utils import datetime_iso_utc

from ..access import create_invitation, create_password_reset, invitation_url, password_reset_url, write_local_recovery_file
from ..config import settings
from ..db import get_db
from ..models import Account, Activity, Contact, Lead, Opportunity, Tenant, User
from ..permissions import is_global_admin, require_client_operational_write, require_tenant_access
from ..schemas import (
    AccountCreate,
    AccountUpdate,
    ActivityCreate,
    ContactCreate,
    LeadCreate,
    OpportunityCreate,
    OpportunityUpdate,
    TenantUserCreate,
    TenantUserUpdate,
)
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["crm"])


def _outreach_context(db, user, prospect_id):
    prospect = db.scalar(select(CrmProspect).where(CrmProspect.id == prospect_id).with_for_update())
    if not prospect:
        raise HTTPException(404, "Prospect not found")
    require_client_operational_write(user, prospect.tenant_id)
    account = db.get(Account, prospect.account_id)
    lead = db.get(Lead, prospect.source_lead_id)
    if not account or not lead or account.tenant_id != prospect.tenant_id or lead.tenant_id != prospect.tenant_id:
        raise HTTPException(404, "Prospect relationship unavailable")
    _require_account_scope(user, account, db)
    if prospect.stage != "Prospecting" or db.scalar(select(Opportunity.id).where(Opportunity.prospect_id == prospect.id)):
        raise HTTPException(409, "Introductory email is available only for Prospecting prospects without an Opportunity")
    contact = db.get(Contact, prospect.contact_id) if prospect.contact_id else None
    if contact and (contact.tenant_id != prospect.tenant_id or contact.account_id != account.id):
        raise HTTPException(404, "Prospect contact unavailable")
    return prospect, account, contact, lead


@router.get("/prospects/{prospect_id}/outreach")
def prospect_outreach(prospect_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prospect, account, contact, lead = _outreach_context(db, user, prospect_id)
    tenant = db.get(Tenant, prospect.tenant_id)
    email = (contact.email if contact and contact.email else lead.email) or ""
    email = email.strip()
    valid_email = (len(email) <= 254 and bool(re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", email))
        and not email.split("@")[0].startswith(".") and not email.split("@")[0].endswith(".")
        and ".." not in email.split("@")[0])
    phone = ((contact.phone if contact and contact.phone else lead.phone) or "").strip()
    name = f"{contact.first_name} {contact.last_name}".strip() if contact else lead.contact_name
    sender = user.full_name or tenant.primary_contact_name or tenant.name
    subject = f"Introduction from {tenant.name}"
    body = (f"Hello {name or 'there'},\n\n"
            f"I'm {sender} with {tenant.name}. I wanted to introduce myself to the team at {account.name} "
            "and learn a little more about your business.\n\n"
            "Would you be open to a brief conversation to see whether staying in touch would be useful?\n\n"
            f"Best regards,\n{sender}\n{tenant.name}")
    return {"prospect_id": prospect.id, "tenant_id": prospect.tenant_id, "contact_id": contact.id if contact else None,
            "email": email if valid_email else "", "invalid_email": bool(email and not valid_email),
            "phone": phone, "subject": subject, "body": body,
            "contact": model_dict(contact) if contact else None}


class ProspectContactedIn(BaseModel):
    request_id: UUID
    method: Literal["Email", "Phone"]
    confirmed: Literal[True]
    note: str = Field(default="", max_length=2000)


@router.post("/prospects/{prospect_id}/contacted")
def prospect_contacted(prospect_id: str, payload: ProspectContactedIn, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    prospect, account, _, _ = _outreach_context(db, user, prospect_id)
    # One atomic completed activity, not a send/delivery record. A stable request
    # UUID makes network retries harmless without a new table or schema.
    body = f"Prospect ID: {prospect.id}\nMethod: {payload.method}\nUser confirmed contact was made.\n{payload.note}"
    activity_id = str(payload.request_id)
    existing = db.get(Activity, activity_id)
    if existing:
        if (existing.tenant_id != prospect.tenant_id or existing.account_id != account.id
                or existing.user_id != user.id or existing.activity_type not in {"Outreach Confirmed", "Contact Confirmed"} or existing.body != body):
            raise HTTPException(409, "Contact confirmation identifier already used")
        return {"activity": model_dict(existing)}
    activity = Activity(id=activity_id, tenant_id=prospect.tenant_id, account_id=account.id,
                        user_id=user.id, activity_type="Contact Confirmed",
                        subject=f"{payload.method} contact manually confirmed", body=body,
                        completed_at=datetime.now(timezone.utc))
    db.add(activity)
    try:
        db.flush()
        audit(db, user, "crm.prospect.contacted", tenant_id=prospect.tenant_id,
              entity_type="prospect", entity_id=prospect.id,
              data={"activity_id": activity.id, "method": payload.method})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Contact confirmation is being recorded; retry with the same confirmation")
    return {"activity": model_dict(activity)}


def _team_user_ids(db: Session, tenant_id: str, team_name: str) -> list[str]:
    if not team_name:
        return []
    return list(db.scalars(select(User.id).where(
        User.tenant_id == tenant_id,
        User.team_name == team_name,
        User.active.is_(True),
    )))


def _scope_accounts(query, user: User):
    if user.tenant_role == "SALES_REP":
        return query.where(Account.owner_user_id == user.id)
    if user.tenant_role == "SALES_MANAGER":
        return query.where(Account.team_name == user.team_name)
    return query


def _require_account_scope(user: User, account: Account, db: Session) -> None:
    if user.tenant_role == "SALES_REP" and account.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="This account is not assigned to you")
    if user.tenant_role == "SALES_MANAGER" and account.team_name != user.team_name:
        raise HTTPException(status_code=403, detail="This account is outside your team")


@router.get("/tenants/{tenant_id}/crm/summary")
def crm_summary(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    account_query = select(func.count(Account.id)).where(Account.tenant_id == tenant_id)
    opp_query = select(func.count(Opportunity.id)).where(Opportunity.tenant_id == tenant_id)
    lead_query = select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id)
    scope_conditions = []
    if user.tenant_role == "SALES_REP":
        account_query = account_query.where(Account.owner_user_id == user.id)
        opp_query = opp_query.where(Opportunity.owner_user_id == user.id)
        lead_query = lead_query.where(Lead.assigned_user_id == user.id)
        scope_conditions = [Opportunity.owner_user_id == user.id]
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        account_query = account_query.where(Account.team_name == user.team_name)
        opp_query = opp_query.where(Opportunity.owner_user_id.in_(team_ids) if team_ids else False)
        lead_query = lead_query.where(Lead.assigned_user_id.in_(team_ids) if team_ids else False)
        scope_conditions = [Opportunity.owner_user_id.in_(team_ids) if team_ids else False]
    weighted = db.scalar(select(func.coalesce(func.sum(Opportunity.value_cents * Opportunity.probability_pct / 100.0), 0)).where(
        Opportunity.tenant_id == tenant_id,
        Opportunity.stage.notin_(["Closed Won", "Closed Lost"]),
        *scope_conditions,
    )) or 0
    return {
        "accounts": db.scalar(account_query) or 0,
        "opportunities": db.scalar(opp_query) or 0,
        "leads": db.scalar(lead_query) or 0,
        "weighted_pipeline_cents": round(float(weighted)),
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }


@router.get("/tenants/{tenant_id}/accounts")
def list_accounts(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = select(Account).where(Account.tenant_id == tenant_id).order_by(Account.name)
    query = _scope_accounts(query, user)
    rows = list(db.scalars(query))
    users = {u.id: u for u in db.scalars(select(User).where(User.tenant_id == tenant_id))}
    return {
        "accounts": [
            {**model_dict(row), "owner_name": users.get(row.owner_user_id).full_name if row.owner_user_id in users else "Unassigned"}
            for row in rows
        ],
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }


@router.post("/tenants/{tenant_id}/accounts")
def create_account(tenant_id: str, payload: AccountCreate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    account = Account(tenant_id=tenant_id, **payload.model_dump())
    if not account.owner_user_id:
        account.owner_user_id = user.id
    if not account.team_name:
        account.team_name = user.team_name
    db.add(account)
    db.flush()
    audit(db, user, "crm.account.created", tenant_id=tenant_id, entity_type="account", entity_id=account.id)
    db.commit()
    return {"account": model_dict(account)}


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, payload: AccountUpdate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_client_operational_write(user, account.tenant_id)
    _require_account_scope(user, account, db)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    audit(db, user, "crm.account.updated", tenant_id=account.tenant_id, entity_type="account", entity_id=account.id,
          data=payload.model_dump(exclude_none=True, mode="json"))
    db.commit()
    return {"account": model_dict(account)}


@router.get("/accounts/{account_id}/360")
def account_360(account_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_tenant_access(user, account.tenant_id)
    _require_account_scope(user, account, db)
    contacts = list(db.scalars(select(Contact).where(Contact.account_id == account_id).order_by(Contact.primary_contact.desc(), Contact.last_name)))
    opportunities = list(db.scalars(select(Opportunity).where(Opportunity.account_id == account_id).order_by(Opportunity.created_at.desc())))
    activities = list(db.scalars(select(Activity).where(Activity.account_id == account_id).order_by(Activity.created_at.desc()).limit(100)))
    owner = db.get(User, account.owner_user_id) if account.owner_user_id else None
    return {
        "account": {**model_dict(account), "owner_name": owner.full_name if owner else "Unassigned"},
        "contacts": [model_dict(row) for row in contacts],
        "opportunities": [model_dict(row) for row in opportunities],
        "activities": [model_dict(row) for row in activities],
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }


@router.get("/tenants/{tenant_id}/contacts")
def list_contacts(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = (
        select(Contact, Account)
        .outerjoin(Account, Account.id == Contact.account_id)
        .where(Contact.tenant_id == tenant_id)
    )
    if user.tenant_role == "SALES_REP":
        query = query.where(Account.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        query = query.where(Account.team_name == user.team_name)
    rows = list(db.execute(query.order_by(Contact.last_name, Contact.first_name)))
    return {"contacts": [{**model_dict(contact), "account_name": account.name if account else ""} for contact, account in rows], "read_only": is_global_admin(user)}


@router.post("/tenants/{tenant_id}/contacts")
def create_contact(tenant_id: str, payload: ContactCreate, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    if payload.account_id:
        account = db.get(Account, payload.account_id)
        if not account or account.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="Invalid account")
        _require_account_scope(user, account, db)
    contact = Contact(tenant_id=tenant_id, **payload.model_dump())
    db.add(contact)
    db.flush()
    audit(db, user, "crm.contact.created", tenant_id=tenant_id, entity_type="contact", entity_id=contact.id)
    db.commit()
    return {"contact": model_dict(contact)}


@router.get("/tenants/{tenant_id}/leads")
def list_leads(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = select(Lead).where(Lead.tenant_id == tenant_id).order_by(Lead.created_at.desc())
    if user.tenant_role == "SALES_REP":
        query = query.where(Lead.assigned_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        query = query.where(Lead.assigned_user_id.in_(team_ids) if team_ids else False)
    rows = list(db.scalars(query))
    return {"leads": [model_dict(row) for row in rows], "read_only": is_global_admin(user)}


@router.post("/tenants/{tenant_id}/leads")
def create_lead(tenant_id: str, payload: LeadCreate, request: Request,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    lead = Lead(tenant_id=tenant_id, **payload.model_dump())
    if not lead.assigned_user_id:
        lead.assigned_user_id = user.id
    db.add(lead)
    db.flush()
    audit(db, user, "crm.lead.created", tenant_id=tenant_id, entity_type="lead", entity_id=lead.id)
    db.commit()
    return {"lead": model_dict(lead)}


@router.post("/leads/{lead_id}/convert")
def convert_lead(lead_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    require_client_operational_write(user, lead.tenant_id)
    if user.tenant_role == "SALES_REP" and lead.assigned_user_id not in {None, user.id}:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    if user.tenant_role == "SALES_MANAGER" and lead.assigned_user_id:
        team_ids = set(_team_user_ids(db, lead.tenant_id, user.team_name))
        if lead.assigned_user_id not in team_ids:
            raise HTTPException(status_code=403, detail="This lead is outside your team")
    account = Account(
        tenant_id=lead.tenant_id,
        name=lead.company_name or lead.contact_name or "Converted Lead",
        status="Active",
        owner_user_id=lead.assigned_user_id or user.id,
        team_name=user.team_name,
        annual_value_cents=0,
        source=lead.source,
        risk="Low",
        notes=lead.notes,
    )
    db.add(account)
    db.flush()
    first_name, _, last_name = lead.contact_name.partition(" ")
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
    opportunity = Opportunity(
        tenant_id=lead.tenant_id,
        account_id=account.id,
        contact_id=contact.id,
        owner_user_id=lead.assigned_user_id or user.id,
        name=f"{account.name} opportunity",
        stage="Qualified",
        value_cents=0,
        probability_pct=25,
        source=lead.source,
        next_action="Schedule discovery conversation.",
    )
    db.add(opportunity)
    lead.status = "Converted"
    audit(db, user, "crm.lead.converted", tenant_id=lead.tenant_id, entity_type="lead", entity_id=lead.id,
          data={"account_id": account.id, "opportunity_id": opportunity.id})
    db.commit()
    return {"account": model_dict(account), "contact": model_dict(contact), "opportunity": model_dict(opportunity)}


@router.get("/tenants/{tenant_id}/opportunities")
def list_opportunities(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = select(Opportunity, Account).outerjoin(Account, Account.id == Opportunity.account_id).where(Opportunity.tenant_id == tenant_id)
    if user.tenant_role == "SALES_REP":
        query = query.where(Opportunity.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        query = query.where(Opportunity.owner_user_id.in_(team_ids) if team_ids else False)
    rows = list(db.execute(query.order_by(Opportunity.updated_at.desc())))
    return {"opportunities": [{**model_dict(opp), "account_name": account.name if account else ""} for opp, account in rows], "read_only": is_global_admin(user)}


@router.post("/tenants/{tenant_id}/opportunities")
def create_opportunity(tenant_id: str, payload: OpportunityCreate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    if payload.account_id:
        account = db.get(Account, payload.account_id)
        if not account or account.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="Invalid account")
        _require_account_scope(user, account, db)
    if payload.owner_user_id and user.tenant_role in {"SALES_REP", "SALES_MANAGER"}:
        allowed_ids = {user.id} if user.tenant_role == "SALES_REP" else set(_team_user_ids(db, tenant_id, user.team_name))
        if payload.owner_user_id not in allowed_ids:
            raise HTTPException(status_code=403, detail="Opportunity owner is outside your permitted scope")
    opportunity = Opportunity(tenant_id=tenant_id, **payload.model_dump())
    if not opportunity.owner_user_id:
        opportunity.owner_user_id = user.id
    db.add(opportunity)
    db.flush()
    audit(db, user, "crm.opportunity.created", tenant_id=tenant_id, entity_type="opportunity", entity_id=opportunity.id)
    db.commit()
    return {"opportunity": model_dict(opportunity)}


@router.patch("/opportunities/{opportunity_id}")
def update_opportunity(opportunity_id: str, payload: OpportunityUpdate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    opportunity = db.get(Opportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    require_client_operational_write(user, opportunity.tenant_id)
    if user.tenant_role == "SALES_REP" and opportunity.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="This opportunity is not assigned to you")
    if user.tenant_role == "SALES_MANAGER":
        team_ids = set(_team_user_ids(db, opportunity.tenant_id, user.team_name))
        if opportunity.owner_user_id not in team_ids:
            raise HTTPException(status_code=403, detail="This opportunity is outside your team")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("name", "stage", "value_cents", "probability_pct", "next_action", "loss_reason"):
        if key in updates and updates[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be null")
    expected_stage = updates.pop("expected_stage", None)
    if expected_stage is not None and opportunity.stage != expected_stage:
        raise HTTPException(
            status_code=409,
            detail=f"Opportunity stage changed from {expected_stage} to {opportunity.stage}; refresh and try again",
        )
    if updates.get("stage") == "Closed Lost" and not (updates.get("loss_reason", opportunity.loss_reason) or "").strip():
        raise HTTPException(status_code=422, detail="A loss reason is required when closing an opportunity as lost")
    # Claim the expected stage atomically before any history/outcome side effect.
    if expected_stage is not None:
        claimed = db.execute(update(Opportunity).where(
            Opportunity.id == opportunity.id, Opportunity.tenant_id == opportunity.tenant_id,
            Opportunity.stage == expected_stage).values(stage=updates.get("stage", expected_stage)),
            execution_options={"synchronize_session": False})
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Opportunity changed; refresh and try again")
    tracked_fields = ("name", "stage", "value_cents", "probability_pct", "expected_close_date", "next_action", "loss_reason")
    previous = {field: getattr(opportunity, field) for field in tracked_fields}
    for field, value in updates.items():
        setattr(opportunity, field, value)
    sync_won_opportunity(
        db,
        opportunity,
        previous_opportunity_stage=previous["stage"],
    )
    labels = {
        "name": "Opportunity name", "stage": "Stage", "value_cents": "Value (cents)",
        "probability_pct": "Probability", "expected_close_date": "Expected close",
        "next_action": "Next action", "loss_reason": "Lost reason",
    }
    changes = []
    for field in tracked_fields:
        if previous[field] == getattr(opportunity, field):
            continue
        value = getattr(opportunity, field)
        if field == "expected_close_date":
            value = value.isoformat() if value else "Cleared"
        elif field == "value_cents":
            value = f"{value / 100:,.2f}"
        elif field == "probability_pct":
            value = f"{value}%"
        else:
            value = value or "Cleared"
        changes.append(f"{labels[field]}: {value}")
    if changes:
        db.add(Activity(
            tenant_id=opportunity.tenant_id,
            account_id=opportunity.account_id,
            opportunity_id=opportunity.id,
            user_id=user.id,
            activity_type="Opportunity Updated",
            subject=f"Opportunity updated · {opportunity.name}",
            body="\n".join(changes),
            completed_at=datetime.now(timezone.utc),
        ))
    audit(db, user, "crm.opportunity.updated", tenant_id=opportunity.tenant_id, entity_type="opportunity", entity_id=opportunity.id,
          data={**payload.model_dump(exclude_unset=True, mode="json"), "expected_stage": expected_stage})
    db.commit()
    return {"opportunity": model_dict(opportunity)}


@router.get("/tenants/{tenant_id}/activities")
def list_activities(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = select(Activity).where(Activity.tenant_id == tenant_id)
    if user.tenant_role == "SALES_REP":
        query = query.where(Activity.user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        query = query.where(Activity.user_id.in_(team_ids) if team_ids else False)
    rows = list(db.scalars(query.order_by(Activity.created_at.desc()).limit(300)))
    return {"activities": [model_dict(row) for row in rows], "read_only": is_global_admin(user)}


@router.post("/tenants/{tenant_id}/activities")
def create_activity(tenant_id: str, payload: ActivityCreate, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_operational_write(user, tenant_id)
    if payload.account_id:
        account = db.get(Account, payload.account_id)
        if not account or account.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="Invalid account")
        _require_account_scope(user, account, db)
    activity = Activity(tenant_id=tenant_id, user_id=user.id, **payload.model_dump())
    db.add(activity)
    db.flush()
    audit(db, user, "crm.activity.created", tenant_id=tenant_id, entity_type="activity", entity_id=activity.id)
    db.commit()
    return {"activity": model_dict(activity)}


@router.get("/tenants/{tenant_id}/sales-organization")
def sales_organization(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    people_query = select(User).where(User.tenant_id == tenant_id, User.active.is_(True))
    account_count_query = select(Account.owner_user_id, func.count(Account.id)).where(Account.tenant_id == tenant_id)
    if user.tenant_role == "SALES_MANAGER":
        people_query = people_query.where(User.team_name == user.team_name)
        account_count_query = account_count_query.where(Account.team_name == user.team_name)
    elif user.tenant_role == "SALES_REP":
        people_query = people_query.where(User.id.in_([user.id, user.manager_id] if user.manager_id else [user.id]))
        account_count_query = account_count_query.where(Account.owner_user_id == user.id)
    users = list(db.scalars(people_query.order_by(User.full_name)))
    counts = dict(db.execute(account_count_query.group_by(Account.owner_user_id)).all())
    return {
        "people": [
            {**model_dict(person, exclude={"password_hash"}), "account_count": int(counts.get(person.id, 0))}
            for person in users
        ],
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }

def _require_client_user_manager(user: User, tenant_id: str) -> None:
    if is_global_admin(user):
        return
    if user.tenant_id != tenant_id or user.tenant_role != "CLIENT_ADMIN":
        raise HTTPException(status_code=403, detail="Client Administrator access required")


@router.post("/tenants/{tenant_id}/users")
def create_tenant_user(tenant_id: str, payload: TenantUserCreate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create a secure invitation rather than an administrator-known password."""
    require_request_origin(request)
    _require_client_user_manager(user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    if payload.manager_id:
        manager = db.get(User, payload.manager_id)
        if not manager or manager.tenant_id != tenant_id:
            raise HTTPException(status_code=400, detail="Invalid manager")
    invitation, raw_token = create_invitation(
        db,
        tenant=tenant,
        full_name=payload.full_name,
        email=payload.email,
        tenant_role=payload.tenant_role,
        manager_id=payload.manager_id,
        team_name=payload.team_name,
        invited_by_user_id=user.id,
    )
    audit(db, user, "sales_org.user.invited", tenant_id=tenant_id, entity_type="user_invitation", entity_id=invitation.id,
          data={"tenant_role": invitation.tenant_role, "team_name": invitation.team_name})
    db.commit()
    response = {"invitation": {
        "id": invitation.id,
        "email": invitation.email,
        "full_name": invitation.full_name,
        "tenant_role": invitation.tenant_role,
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
    }, "delivery": "local_link" if settings.local_recovery_mode else "email_required"}
    if settings.local_recovery_mode:
        response["activation_url"] = invitation_url(raw_token)
    return response


@router.patch("/tenant-users/{person_id}")
def update_tenant_user(person_id: str, payload: TenantUserUpdate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    person = db.get(User, person_id)
    if not person or not person.tenant_id:
        raise HTTPException(status_code=404, detail="Client user not found")
    _require_client_user_manager(user, person.tenant_id)
    if person.id == user.id and payload.active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    updates = payload.model_dump(exclude_unset=True)
    if "manager_id" in updates and updates["manager_id"]:
        manager = db.get(User, updates["manager_id"])
        if not manager or manager.tenant_id != person.tenant_id or manager.id == person.id:
            raise HTTPException(status_code=400, detail="Invalid manager")
    for field, value in updates.items():
        setattr(person, field, value)
    audit(db, user, "sales_org.user.updated", tenant_id=person.tenant_id, entity_type="user", entity_id=person.id,
          data={k: v for k, v in updates.items() if k != "active" or v is not None})
    db.commit()
    return {"user": model_dict(person, exclude={"password_hash"})}


@router.post("/tenant-users/{person_id}/reset-password")
def reset_tenant_user_password(person_id: str, request: Request, user: User = Depends(current_user),
                               db: Session = Depends(get_db)):
    """Create a one-time reset link. Passwords are never assigned by RMR/Step2."""
    require_request_origin(request)
    person = db.get(User, person_id)
    if not person or not person.tenant_id:
        raise HTTPException(status_code=404, detail="Client user not found")
    _require_client_user_manager(user, person.tenant_id)
    reset, raw_token = create_password_reset(db, person, request.client.host if request.client else "")
    audit(db, user, "sales_org.user.password_reset_requested", tenant_id=person.tenant_id, entity_type="password_reset", entity_id=reset.id)
    response = {"ok": True, "delivery": "local_link" if settings.local_recovery_mode else "email_required"}
    if settings.local_recovery_mode:
        path = write_local_recovery_file(raw_token, person.email)
        response.update({"reset_url": password_reset_url(raw_token), "recovery_file": path.name})
    db.commit()
    return response



@router.get("/tenants/{tenant_id}/prospects")
def list_crm_prospects(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    query = (
        select(CrmProspect, Account, Contact, Lead, Opportunity)
        .join(Account, Account.id == CrmProspect.account_id)
        .outerjoin(Contact, Contact.id == CrmProspect.contact_id)
        .join(Lead, Lead.id == CrmProspect.source_lead_id)
        .outerjoin(Opportunity, Opportunity.prospect_id == CrmProspect.id)
        .where(CrmProspect.tenant_id == tenant_id)
    )
    if user.tenant_role == "SALES_REP":
        query = query.where(CrmProspect.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        query = query.where(CrmProspect.owner_user_id.in_(team_ids) if team_ids else False)
    rows = list(db.execute(query.order_by(CrmProspect.updated_at.desc())))
    return {
        "prospects": [
            {
                **model_dict(prospect),
                "account_name": account.name,
                "contact_name": f"{contact.first_name} {contact.last_name}".strip() if contact else "",
                "contact_email": (contact.email if contact and contact.email else lead.email or ""),
                "contact_id": contact.id if contact else None,
                "source": lead.source,
                "opportunity_id": opportunity.id if opportunity else None,
                "opportunity_name": opportunity.name if opportunity else "",
                "opportunity_stage": opportunity.stage if opportunity else "",
            }
            for prospect, account, contact, lead, opportunity in rows
        ],
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }


@router.patch("/prospects/{prospect_id}")
def update_crm_prospect(prospect_id: str, payload: CrmProspectUpdate, request: Request,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    prospect = db.get(CrmProspect, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    require_client_operational_write(user, prospect.tenant_id)
    account = db.get(Account, prospect.account_id)
    if account:
        _require_account_scope(user, account, db)
    linked_opportunity = db.scalar(select(Opportunity).where(Opportunity.prospect_id == prospect.id))
    if linked_opportunity and linked_opportunity.stage == "Closed Won" and payload.stage != "Customer":
        raise HTTPException(status_code=409, detail="A prospect with a Closed Won opportunity must remain Customer")
    if payload.stage == "Customer":
        if not linked_opportunity or linked_opportunity.stage != "Closed Won":
            raise HTTPException(status_code=409, detail="A prospect becomes a customer when its opportunity is Closed Won")
    if payload.stage == "Not Pursuing" and linked_opportunity and linked_opportunity.stage not in {"Closed Won", "Closed Lost"}:
        raise HTTPException(status_code=409, detail="Close the linked opportunity before marking this prospect Not Pursuing")
    previous_stage = prospect.stage
    if (payload.stage == "Not Pursuing" and "not_pursuing_reason" in payload.model_fields_set
            and not payload.not_pursuing_reason.strip() and prospect.not_pursuing_reason):
        raise HTTPException(status_code=422, detail="A reason is required when marking a prospect Not Pursuing")
    if payload.stage == "Not Pursuing" and previous_stage != "Not Pursuing" and not (payload.not_pursuing_reason or prospect.not_pursuing_reason).strip():
        raise HTTPException(status_code=422, detail="A reason is required when marking a prospect Not Pursuing")
    updates = payload.model_dump(exclude_unset=True)
    previous_values = {
        field: getattr(prospect, field)
        for field in ("stage", "next_action", "follow_up_date", "stage_note", "not_pursuing_reason")
    }
    for field, value in updates.items():
        setattr(prospect, field, value)
    changes = []
    if previous_values["stage"] != prospect.stage:
        changes.append(f"Stage: {previous_values['stage']} → {prospect.stage}")
    if previous_values["next_action"] != prospect.next_action:
        changes.append(f"Next action: {prospect.next_action or 'Cleared'}")
    if previous_values["follow_up_date"] != prospect.follow_up_date:
        changes.append(f"Follow-up date: {prospect.follow_up_date.isoformat() if prospect.follow_up_date else 'Cleared'}")
    if previous_values["stage_note"] != prospect.stage_note:
        changes.append(f"Prospect notes: {prospect.stage_note or 'Cleared'}")
    if previous_values["not_pursuing_reason"] != prospect.not_pursuing_reason:
        changes.append(f"Not pursuing reason: {prospect.not_pursuing_reason or 'Cleared'}")
    if changes:
        subject = (
            f"Prospect moved from {previous_stage} to {prospect.stage}"
            if previous_stage != prospect.stage
            else "Prospect details updated"
        )
        db.add(Activity(
            tenant_id=prospect.tenant_id,
            account_id=prospect.account_id,
            user_id=user.id,
            activity_type="Prospect Updated",
            subject=subject,
            body=f"Account: {account.name if account else 'Unknown account'}.\n" + "\n".join(changes),
            completed_at=datetime.now(timezone.utc),
        ))
    audit(db, user, "crm.prospect.updated", tenant_id=prospect.tenant_id,
          entity_type="prospect", entity_id=prospect.id,
          data={"previous_stage": previous_stage, **payload.model_dump(exclude_unset=True, mode="json")})
    db.commit()
    return {"prospect": model_dict(prospect)}


@router.post("/prospects/{prospect_id}/convert-to-opportunity")
def convert_prospect_to_opportunity(prospect_id: str, payload: ProspectOpportunityCreate, request: Request,
                                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    prospect = db.get(CrmProspect, prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    require_client_operational_write(user, prospect.tenant_id)
    account = db.get(Account, prospect.account_id)
    if not account or account.tenant_id != prospect.tenant_id:
        raise HTTPException(status_code=409, detail="The prospect account is missing or invalid")
    _require_account_scope(user, account, db)
    if prospect.stage in {"Not Pursuing", "Customer"}:
        raise HTTPException(status_code=409, detail=f"A prospect in {prospect.stage} cannot be promoted to an opportunity")
    existing = db.scalar(select(Opportunity).where(Opportunity.prospect_id == prospect.id))
    if existing:
        raise HTTPException(status_code=409, detail="This prospect already has an opportunity")
    contact = db.get(Contact, prospect.contact_id) if prospect.contact_id else None
    lead = db.get(Lead, prospect.source_lead_id)
    opportunity = Opportunity(
        tenant_id=prospect.tenant_id,
        prospect_id=prospect.id,
        account_id=account.id,
        contact_id=contact.id if contact else None,
        owner_user_id=prospect.owner_user_id or user.id,
        name=(payload.name or "").strip() or f"{account.name} opportunity",
        stage="Qualified",
        value_cents=payload.value_cents,
        probability_pct=payload.probability_pct,
        expected_close_date=payload.expected_close_date,
        source=lead.source if lead else "CRM Prospect",
        next_action=payload.next_action.strip(),
    )
    db.add(opportunity)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This prospect already has an opportunity") from exc
    db.add(Activity(
        tenant_id=prospect.tenant_id,
        account_id=account.id,
        opportunity_id=opportunity.id,
        user_id=user.id,
        activity_type="Prospect Conversion",
        subject=f"Prospect promoted to opportunity: {opportunity.name}",
        body=f"Opportunity created at {opportunity.stage} from prospect stage {prospect.stage}.",
        completed_at=datetime.now(timezone.utc),
    ))
    audit(db, user, "crm.prospect.converted_to_opportunity", tenant_id=prospect.tenant_id,
          entity_type="prospect", entity_id=prospect.id,
          data={"opportunity_id": opportunity.id, "stage": opportunity.stage})
    db.commit()
    return {"prospect": model_dict(prospect), "opportunity": model_dict(opportunity)}


@router.get("/tenants/{tenant_id}/crm/my-work")
def list_crm_my_work(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Return open due activities and prospect follow-ups within the caller's CRM scope."""
    require_tenant_access(user, tenant_id)

    activity_query = select(Activity).where(
        Activity.tenant_id == tenant_id,
        Activity.due_at.is_not(None),
        Activity.completed_at.is_(None),
    )
    prospect_query = select(CrmProspect).where(
        CrmProspect.tenant_id == tenant_id,
        CrmProspect.follow_up_date.is_not(None),
    )
    if user.tenant_role == "SALES_REP":
        activity_query = activity_query.where(Activity.user_id == user.id)
        prospect_query = prospect_query.where(CrmProspect.owner_user_id == user.id)
    elif user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, tenant_id, user.team_name)
        activity_query = activity_query.where(Activity.user_id.in_(team_ids) if team_ids else False)
        prospect_query = prospect_query.where(CrmProspect.owner_user_id.in_(team_ids) if team_ids else False)

    activities = list(db.scalars(activity_query.order_by(Activity.due_at.asc()).limit(500)))
    prospects = list(db.scalars(prospect_query.order_by(CrmProspect.follow_up_date.asc()).limit(500)))
    account_ids = {row.account_id for row in activities if row.account_id}
    account_ids.update(row.account_id for row in prospects if row.account_id)
    accounts = {
        row.id: row for row in db.scalars(
            select(Account).where(Account.tenant_id == tenant_id, Account.id.in_(account_ids))
        )
    } if account_ids else {}
    opportunity_ids = {row.opportunity_id for row in activities if row.opportunity_id}
    opportunities = {
        row.id: row for row in db.scalars(
            select(Opportunity).where(Opportunity.tenant_id == tenant_id, Opportunity.id.in_(opportunity_ids))
        )
    } if opportunity_ids else {}
    contact_ids = {row.contact_id for row in prospects if row.contact_id}
    contacts = {
        row.id: row for row in db.scalars(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.id.in_(contact_ids))
        )
    } if contact_ids else {}
    return {
        "activities": [
            {
                **model_dict(row),
                **({"due_at": datetime_iso_utc(row.due_at)} if isinstance(row, Activity) else {}),
                "account_name": accounts[row.account_id].name if row.account_id in accounts else "",
                "opportunity_name": opportunities[row.opportunity_id].name if row.opportunity_id in opportunities else "",
            }
            for row in activities
        ],
        "prospects": [
            {
                **model_dict(row),
                **({"due_at": datetime_iso_utc(row.due_at)} if isinstance(row, Activity) else {}),
                "account_name": accounts[row.account_id].name if row.account_id in accounts else "",
                "contact_name": (
                    f"{contacts[row.contact_id].first_name} {contacts[row.contact_id].last_name}".strip()
                    if row.contact_id in contacts else ""
                ),
            }
            for row in prospects
        ],
        "read_only": is_global_admin(user) and not (getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write"),
    }


@router.patch("/activities/{activity_id}/complete")
def complete_activity(activity_id: str, request: Request,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Mark an Activity complete, limited to records visible in the caller's CRM scope."""
    require_request_origin(request)
    activity = db.get(Activity, activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    require_client_operational_write(user, activity.tenant_id)
    if user.tenant_role == "SALES_REP" and activity.user_id != user.id:
        raise HTTPException(status_code=403, detail="Activity access denied")
    if user.tenant_role == "SALES_MANAGER":
        team_ids = _team_user_ids(db, activity.tenant_id, user.team_name)
        if activity.user_id not in team_ids:
            raise HTTPException(status_code=403, detail="Activity access denied")
    if activity.completed_at is None:
        activity.completed_at = datetime.now(timezone.utc)
        audit(db, user, "crm.activity.completed", tenant_id=activity.tenant_id,
              entity_type="activity", entity_id=activity.id)
        db.commit()
    return {"activity": model_dict(activity)}


@router.post("/leads/{lead_id}/convert-to-prospect")
def convert_lead_to_prospect(lead_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    require_client_operational_write(user, lead.tenant_id)
    if user.tenant_role == "SALES_REP" and lead.assigned_user_id not in {None, user.id}:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    if user.tenant_role == "SALES_MANAGER" and lead.assigned_user_id:
        team_ids = set(_team_user_ids(db, lead.tenant_id, user.team_name))
        if lead.assigned_user_id not in team_ids:
            raise HTTPException(status_code=403, detail="This lead is outside your team")
    resolved_account_name = lead.company_name or lead.contact_name or "Converted Lead"
    existing_account = find_account_by_name(db, lead.tenant_id, resolved_account_name)
    if existing_account:
        _require_account_scope(user, existing_account, db)
    account, contact, prospect = create_prospect_from_lead(db, lead, user)
    db.commit()
    return {"account": model_dict(account), "contact": model_dict(contact), "prospect": model_dict(prospect)}
