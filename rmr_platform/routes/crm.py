from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        "read_only": is_global_admin(user),
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
        "read_only": is_global_admin(user),
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
        "read_only": is_global_admin(user),
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
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(opportunity, field, value)
    audit(db, user, "crm.opportunity.updated", tenant_id=opportunity.tenant_id, entity_type="opportunity", entity_id=opportunity.id,
          data=payload.model_dump(exclude_none=True, mode="json"))
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
        "read_only": is_global_admin(user),
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

