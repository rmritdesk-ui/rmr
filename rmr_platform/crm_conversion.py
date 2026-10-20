from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Account, Activity, Contact, CrmProspect, Lead, Opportunity, User
from .services import audit


def normalize_account_name(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def find_account_by_name(db: Session, tenant_id: str, name: str) -> Account | None:
    normalized_name = normalize_account_name(name)
    if not normalized_name:
        return None
    accounts = db.scalars(select(Account).where(Account.tenant_id == tenant_id))
    return next((account for account in accounts if normalize_account_name(account.name) == normalized_name), None)


def create_prospect_from_lead(
    db: Session,
    lead: Lead,
    user: User,
    *,
    account_name: str | None = None,
) -> tuple[Account, Contact, CrmProspect]:
    if lead.status == "Converted" or db.scalar(
        select(CrmProspect.id).where(CrmProspect.source_lead_id == lead.id)
    ):
        raise HTTPException(status_code=409, detail="This lead has already been converted to a prospect")

    # Apply the same lead/team/account scope to both explicit prospect endpoints.
    from .routes.crm import _require_account_scope, _team_user_ids
    if user.tenant_role == "SALES_REP" and lead.assigned_user_id not in {None, user.id}:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    if user.tenant_role == "SALES_MANAGER" and lead.assigned_user_id:
        if lead.assigned_user_id not in set(_team_user_ids(db, lead.tenant_id, user.team_name)):
            raise HTTPException(status_code=403, detail="This lead is outside your team")
    resolved_account_name = (account_name or lead.company_name or lead.contact_name or "Converted Lead").strip()
    if not resolved_account_name:
        raise HTTPException(status_code=422, detail="Account name is required")

    owner_user_id = lead.assigned_user_id or user.id
    account = find_account_by_name(db, lead.tenant_id, resolved_account_name)
    if account is not None:
        _require_account_scope(user, account, db)
    if account is None:
        account = Account(
            tenant_id=lead.tenant_id,
            name=resolved_account_name,
            status="Prospect",
            owner_user_id=owner_user_id,
            team_name=user.team_name,
            annual_value_cents=0,
            source=lead.source,
            risk="Low",
            notes=lead.notes,
        )
        db.add(account)
        db.flush()

    first_name, _, last_name = (lead.contact_name or resolved_account_name).partition(" ")
    contact = Contact(
        tenant_id=lead.tenant_id,
        account_id=account.id,
        first_name=first_name,
        last_name=last_name,
        email=lead.email,
        phone=lead.phone,
        primary_contact=not bool(db.scalar(select(Contact.id).where(Contact.tenant_id == lead.tenant_id, Contact.account_id == account.id, Contact.primary_contact.is_(True)))),
    )
    db.add(contact)
    db.flush()

    prospect = CrmProspect(
        tenant_id=lead.tenant_id,
        source_lead_id=lead.id,
        account_id=account.id,
        contact_id=contact.id,
        owner_user_id=owner_user_id,
        stage="Prospecting",
    )
    db.add(prospect)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This lead has already been converted to a prospect") from exc

    lead.status = "Converted"
    db.add(
        Activity(
            tenant_id=lead.tenant_id,
            account_id=account.id,
            user_id=user.id,
            activity_type="Lead Conversion",
            subject=f"Lead converted to prospect: {lead.contact_name or lead.company_name or account.name}",
            body=f"Prospect created at Prospecting stage. Source: {lead.source}.",
            completed_at=datetime.now(timezone.utc),
        )
    )
    audit(
        db,
        user,
        "crm.lead.converted_to_prospect",
        tenant_id=lead.tenant_id,
        entity_type="prospect",
        entity_id=prospect.id,
        data={"lead_id": lead.id, "account_id": account.id, "contact_id": contact.id, "stage": prospect.stage},
    )
    return account, contact, prospect


ACTIVE_PROSPECT_STAGES = {"Prospecting", "Engaged", "Nurture"}
CLOSED_OPPORTUNITY_STAGES = {"Closed Won", "Closed Lost"}


def _prospect_loss_reason(loss_reason: str) -> str:
    prefix = "Opportunity was closed as lost. Reason: "
    return f"{prefix}{loss_reason.strip()}"[:500]


def sync_won_opportunity(
    db: Session,
    opportunity: Opportunity,
    *,
    previous_opportunity_stage: str | None = None,
) -> None:
    if not opportunity.prospect_id:
        return
    prospect = db.get(CrmProspect, opportunity.prospect_id)
    if not prospect:
        return

    entering_outcome = (
        opportunity.stage in CLOSED_OPPORTUNITY_STAGES
        and previous_opportunity_stage not in CLOSED_OPPORTUNITY_STAGES
    )
    reopening = (
        opportunity.stage not in CLOSED_OPPORTUNITY_STAGES
        and previous_opportunity_stage in CLOSED_OPPORTUNITY_STAGES
    )

    if entering_outcome and prospect.stage in ACTIVE_PROSPECT_STAGES:
        prospect.stage_before_opportunity_outcome = prospect.stage

    if opportunity.stage == "Closed Won":
        prospect.stage = "Customer"
        prospect.not_pursuing_reason = ""
        account = db.get(Account, prospect.account_id)
        if account:
            if not account.customer_since:
                account.customer_since = datetime.now(timezone.utc).date()
            if account.status != "Inactive":
                account.status = "Active"
    elif opportunity.stage == "Closed Lost":
        prospect.stage = "Not Pursuing"
        prospect.not_pursuing_reason = _prospect_loss_reason(opportunity.loss_reason)
    elif reopening:
        prospect.stage = (
            prospect.stage_before_opportunity_outcome
            if prospect.stage_before_opportunity_outcome in ACTIVE_PROSPECT_STAGES
            else "Engaged"
        )
        prospect.stage_before_opportunity_outcome = None
        prospect.not_pursuing_reason = ""
