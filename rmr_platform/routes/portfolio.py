from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import create_invitation, invitation_summary, invitation_url, serialize_invitation
from ..config import settings
from ..db import get_db
from ..models import (
    EconomicTransaction,
    Notification,
    OnboardingProject,
    OnboardingStep,
    ServiceCatalog,
    SupportAccess,
    Tenant,
    TenantService,
    User,
    UserInvitation,
    WebsitePage,
    WebsiteSection,
    WebsiteSite,
)
from ..permissions import is_global_admin, require_global_admin, require_tenant_access
from ..schemas import InvitationCreate, TenantCreate, TenantUpdate
from ..security import current_user, require_request_origin
from ..seed import ONBOARDING_STAGES
from ..services import audit, tenant_success_metrics
from ..utils import model_dict, slugify

router = APIRouter(prefix="/api", tags=["portfolio"])


def _tenant_financials(db: Session, tenant_id: str) -> dict[str, int | bool]:
    rows = list(
        db.execute(
            select(TenantService, ServiceCatalog)
            .join(ServiceCatalog, ServiceCatalog.code == TenantService.service_code)
            .where(TenantService.tenant_id == tenant_id, TenantService.status == "active")
        )
    )
    mrr = sum(ts.contract_price_cents for ts, catalog in rows if catalog.cadence == "monthly")
    current_period = date.today().strftime("%Y-%m")
    usage = (
        db.scalar(
            select(func.coalesce(func.sum(EconomicTransaction.revenue_cents), 0)).where(
                EconomicTransaction.tenant_id == tenant_id,
                EconomicTransaction.period == current_period,
                EconomicTransaction.quantity > 1,
            )
        )
        or 0
    )
    active_codes = {catalog.code for _, catalog in rows}
    return {
        "mrr_cents": int(mrr),
        "arr_cents": int(mrr * 12),
        "usage_revenue_cents": int(usage),
        "piq_active": "piq_access" in active_codes,
    }


def _onboarding_summary(db: Session, tenant_id: str) -> dict[str, object] | None:
    project = db.scalar(select(OnboardingProject).where(OnboardingProject.tenant_id == tenant_id))
    if not project:
        return None
    steps = list(
        db.scalars(
            select(OnboardingStep)
            .where(OnboardingStep.project_id == project.id)
            .order_by(OnboardingStep.stage_number)
        )
    )
    return {
        "project": model_dict(project),
        "steps": [model_dict(step) for step in steps],
        "completed_steps": sum(1 for step in steps if step.status == "complete"),
        "total_steps": len(steps),
    }


def _website_summary(db: Session, tenant: Tenant) -> dict[str, object]:
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant.id))
    if not site:
        return {
            "mode": tenant.website_mode,
            "status": "not_configured",
            "url": tenant.website_url,
            "manage_route": "website",
            "open_url": tenant.website_url or "",
        }
    if site.mode == "managed":
        open_url = f"/sites/{site.slug}?preview=1"
    else:
        open_url = site.external_url or tenant.website_url or ""
    return {
        **model_dict(site),
        "url": open_url,
        "open_url": open_url,
        "manage_route": "website",
        "configured": bool(open_url),
    }


def _can_manage_client_users(user: User, tenant_id: str) -> bool:
    return is_global_admin(user) or (user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN")


def _invitation_delivery_label(invitation: UserInvitation) -> str:
    if invitation.status == "accepted":
        return "Accepted / Active"
    if invitation.status == "revoked":
        return "Revoked"
    if invitation.status != "pending":
        return invitation.status.replace("_", " ").title()
    if settings.local_recovery_mode:
        return "Created / local delivery required"
    return "Delivery pending"


def _serialized_invitation_with_delivery(invitation: UserInvitation) -> dict[str, object]:
    return {
        **(serialize_invitation(invitation) or {}),
        "delivery_status": _invitation_delivery_label(invitation),
        "delivery_mode": "local_link" if settings.local_recovery_mode else "configured_email",
    }


def _invitation_delivery(invitation: UserInvitation, raw_token: str) -> dict[str, object]:
    data: dict[str, object] = {
        "invitation": _serialized_invitation_with_delivery(invitation),
        "delivery": "local_link" if settings.local_recovery_mode else "email_required",
        "delivery_status": _invitation_delivery_label(invitation),
    }
    if settings.local_recovery_mode:
        data["activation_url"] = invitation_url(raw_token)
    return data


@router.get("/portfolio/summary")
def portfolio_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    tenants = list(db.scalars(select(Tenant).order_by(Tenant.name)))
    financials = {tenant.id: _tenant_financials(db, tenant.id) for tenant in tenants}
    total_mrr = sum(int(item["mrr_cents"]) for item in financials.values())
    current_period = date.today().strftime("%Y-%m")
    totals = db.execute(
        select(
            func.coalesce(func.sum(EconomicTransaction.revenue_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.direct_cost_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.rmr_share_cents), 0),
            func.coalesce(func.sum(EconomicTransaction.step2_share_cents), 0),
        ).where(EconomicTransaction.period == current_period)
    ).one()
    unread = (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_scope == "GLOBAL_ADMIN", Notification.status == "unread"
            )
        )
        or 0
    )
    pending_requests = (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.notification_type.in_(["solution_request", "expansion_interest"]),
                Notification.status == "unread",
            )
        )
        or 0
    )
    return {
        "kpis": {
            "active_clients": sum(1 for t in tenants if t.status in {"live", "private"}),
            "onboarding_clients": sum(1 for t in tenants if t.status in {"onboarding", "invitation_pending"}),
            "mrr_cents": total_mrr,
            "arr_cents": total_mrr * 12,
            "recognized_revenue_cents": int(totals[0]),
            "direct_costs_cents": int(totals[1]),
            "rmr_share_cents": int(totals[2]),
            "step2_share_cents": int(totals[3]),
            "average_adoption": round(sum(t.adoption_score for t in tenants) / max(len(tenants), 1)),
            "needs_attention": sum(1 for t in tenants if t.health_status in {"Attention", "At Risk"}),
            "unread_notifications": unread,
            "expansion_signals": pending_requests,
        },
        "tenants": [
            {
                **model_dict(tenant),
                **financials[tenant.id],
                "access_state": invitation_summary(db, tenant.id)["access_state"],
            }
            for tenant in tenants
        ],
    }


@router.get("/tenants")
def list_tenants(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if is_global_admin(user):
        tenants = list(db.scalars(select(Tenant).order_by(Tenant.name)))
    else:
        tenants = [db.get(Tenant, user.tenant_id)] if user.tenant_id else []
    return {"tenants": [model_dict(t) for t in tenants if t]}


@router.post("/tenants")
def create_tenant(
    payload: TenantCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    slug = slugify(payload.slug or payload.name)
    field_errors: dict[str, str] = {}
    if db.scalar(select(Tenant).where(Tenant.slug == slug)):
        field_errors["slug"] = "A client with this URL slug already exists."
    if payload.invite_primary_admin:
        email = payload.primary_contact_email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            field_errors["primary_contact_email"] = "This email already has an account."
        pending = db.scalar(
            select(UserInvitation).where(
                UserInvitation.email == email,
                UserInvitation.status == "pending",
            )
        )
        if pending:
            field_errors["primary_contact_email"] = "A pending invitation already exists for this email."
    if field_errors:
        raise HTTPException(
            status_code=409,
            detail={"message": "Correct the highlighted fields and try again.", "field_errors": field_errors},
        )

    tenant = Tenant(
        name=payload.name.strip(),
        slug=slug,
        industry=payload.industry.strip() or "Professional Services",
        country=payload.country.strip() or "United States",
        timezone=payload.timezone.strip() or "America/Phoenix",
        status="onboarding",
        seller_org=payload.seller_org,
        seller_name=payload.seller_name.strip(),
        onboarding_owner="Step2",
        website_mode=payload.website_mode,
        website_url=payload.website_url.strip(),
        managed_site_slug=slug,
        adoption_score=0,
        training_completion_pct=0,
        health_status="Onboarding",
        renewal_risk="Low",
        primary_contact_name=payload.primary_contact_name.strip(),
        primary_contact_email=payload.primary_contact_email.strip().lower(),
    )
    db.add(tenant)
    db.flush()

    project = OnboardingProject(
        tenant_id=tenant.id,
        status="active",
        current_stage=1,
        readiness_pct=0,
        target_go_live=date.today() + timedelta(days=30),
    )
    db.add(project)
    db.flush()
    for stage_number, code, name, owner in ONBOARDING_STAGES:
        display_name = "Tenant provisioning & client access" if stage_number == 2 else name
        db.add(
            OnboardingStep(
                project_id=project.id,
                stage_number=stage_number,
                code=code,
                name=display_name,
                owner_role=owner,
                status="in_progress" if stage_number == 1 else "not_started",
                data_json={},
            )
        )

    site = WebsiteSite(
        tenant_id=tenant.id,
        mode=payload.website_mode,
        slug=slug,
        template_family="executive-authority",
        company_name=payload.name.strip(),
        wordmark=(payload.name.split()[0] if payload.name.split() else payload.name).upper(),
        status="draft",
        external_url=payload.website_url.strip(),
    )
    db.add(site)
    db.flush()
    home = WebsitePage(
        site_id=site.id,
        title="Home",
        slug="home",
        nav_order=1,
        show_in_nav=True,
        status="draft",
        seo_title=f"{payload.name} | Home",
        seo_description=f"Welcome to {payload.name}.",
    )
    db.add(home)
    db.flush()
    db.add(
        WebsiteSection(
            page_id=home.id,
            section_type="hero",
            position=1,
            settings_json={
                "eyebrow": "WELCOME",
                "headline": f"Welcome to {payload.name}.",
                "supporting_text": "Tell your customers why your organization is the right choice.",
                "primary_button": "Contact Us",
                "layout": "split",
                "background": "brand",
            },
        )
    )

    for service_item in payload.services:
        code = str(service_item.get("service_code", ""))
        catalog = db.scalar(
            select(ServiceCatalog).where(ServiceCatalog.code == code, ServiceCatalog.active.is_(True))
        )
        if not catalog:
            continue
        db.add(
            TenantService(
                tenant_id=tenant.id,
                service_code=code,
                contract_price_cents=int(
                    service_item.get("contract_price_cents", catalog.standard_price_cents)
                ),
                usage_price_cents=int(service_item.get("usage_price_cents", 0)),
                cadence=catalog.cadence,
                status="active",
                effective_date=date.today(),
                next_billing_date=date.today() + timedelta(days=30),
            )
        )

    invitation_data: dict[str, object] | None = None
    if payload.invite_primary_admin:
        invitation, raw_token = create_invitation(
            db,
            tenant=tenant,
            full_name=payload.primary_contact_name,
            email=payload.primary_contact_email,
            tenant_role="CLIENT_ADMIN",
            invited_by_user_id=user.id,
            team_name="Administration",
        )
        invitation_data = _invitation_delivery(invitation, raw_token)

    db.add(
        Notification(
            recipient_scope="GLOBAL_ADMIN",
            tenant_id=tenant.id,
            notification_type="client_created",
            title=f"New client added — {tenant.name}",
            body="The client is ready for onboarding.",
            action_route=f"client-360?tenant={tenant.id}",
            action_label="Open Client 360",
            entity_type="tenant",
            entity_id=tenant.id,
        )
    )
    audit(
        db,
        user,
        "tenant.created",
        tenant_id=tenant.id,
        entity_type="tenant",
        entity_id=tenant.id,
        data={"seller_org": tenant.seller_org, "website_mode": tenant.website_mode},
    )
    db.commit()
    db.refresh(tenant)
    return {
        "tenant": model_dict(tenant),
        "invitation": invitation_data,
        "next_route": f"onboarding?tenant={tenant.id}",
    }


@router.patch("/tenants/{tenant_id}")
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = payload.model_dump(exclude_unset=True)
    if "primary_contact_email" in updates and updates["primary_contact_email"]:
        updates["primary_contact_email"] = updates["primary_contact_email"].strip().lower()
    for field, value in updates.items():
        setattr(tenant, field, value)
    audit(db, user, "tenant.updated", tenant_id=tenant.id, entity_type="tenant", entity_id=tenant.id, data=updates)
    db.commit()
    return {"tenant": model_dict(tenant)}


@router.get("/tenants/{tenant_id}/access")
def tenant_access(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    if not _can_manage_client_users(user, tenant_id):
        raise HTTPException(status_code=403, detail="Client user administration access required")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    invitations = list(
        db.scalars(
            select(UserInvitation)
            .where(UserInvitation.tenant_id == tenant_id)
            .order_by(UserInvitation.created_at.desc())
        )
    )
    users = list(db.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.full_name)))
    return {
        "access": invitation_summary(db, tenant_id),
        "delivery_environment": {
            "mode": "local_link" if settings.local_recovery_mode else "configured_email",
            "label": "Local Product Owner delivery" if settings.local_recovery_mode else "Configured email delivery",
            "description": (
                "Copy or open the secure activation link. No email is claimed as sent in this local environment."
                if settings.local_recovery_mode
                else "Invitation delivery depends on the configured production email provider."
            ),
        },
        "invitations": [_serialized_invitation_with_delivery(row) for row in invitations],
        "users": [model_dict(row, exclude={"password_hash"}) for row in users],
    }


@router.post("/tenants/{tenant_id}/invitations")
def invite_tenant_user(
    tenant_id: str,
    payload: InvitationCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    if not _can_manage_client_users(user, tenant_id):
        raise HTTPException(status_code=403, detail="Client user administration access required")
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
    db.add(
        Notification(
            recipient_scope="GLOBAL_ADMIN",
            tenant_id=tenant.id,
            notification_type="client_user_invited",
            title=f"Client access invitation created — {tenant.name}",
            body=f"{payload.full_name} was invited as {payload.tenant_role.replace('_', ' ').title()}.",
            action_route=f"client-360?tenant={tenant.id}",
            action_label="Open Client 360",
            entity_type="user_invitation",
            entity_id=invitation.id,
        )
    )
    audit(
        db,
        user,
        "client.invitation.created",
        tenant_id=tenant.id,
        entity_type="user_invitation",
        entity_id=invitation.id,
        data={"email": invitation.email, "tenant_role": invitation.tenant_role},
    )
    db.commit()
    return _invitation_delivery(invitation, raw_token)


@router.post("/invitations/{invitation_id}/resend")
def resend_invitation(
    invitation_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    old = db.get(UserInvitation, invitation_id)
    if not old:
        raise HTTPException(status_code=404, detail="Invitation not found")
    require_tenant_access(user, old.tenant_id)
    if not _can_manage_client_users(user, old.tenant_id):
        raise HTTPException(status_code=403, detail="Client user administration access required")
    tenant = db.get(Tenant, old.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    invitation, raw_token = create_invitation(
        db,
        tenant=tenant,
        full_name=old.full_name,
        email=old.email,
        tenant_role=old.tenant_role,
        manager_id=old.manager_id,
        team_name=old.team_name,
        invited_by_user_id=user.id,
    )
    old.status = "revoked"
    audit(
        db,
        user,
        "client.invitation.resent",
        tenant_id=tenant.id,
        entity_type="user_invitation",
        entity_id=invitation.id,
        data={"replaces": old.id},
    )
    db.commit()
    return _invitation_delivery(invitation, raw_token)


@router.get("/tenants/{tenant_id}/client360")
def client_360(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    metrics = tenant_success_metrics(db, tenant)
    financials = _tenant_financials(db, tenant.id)
    services = list(
        db.execute(
            select(TenantService, ServiceCatalog)
            .join(ServiceCatalog, ServiceCatalog.code == TenantService.service_code)
            .where(TenantService.tenant_id == tenant.id)
            .order_by(ServiceCatalog.sort_order)
        )
    )
    access = invitation_summary(db, tenant.id)
    return {
        "tenant": model_dict(tenant),
        "metrics": metrics,
        "financials": financials,
        "services": [
            {"tenant_service": model_dict(ts), "catalog": model_dict(cat)} for ts, cat in services
        ],
        "access": access,
        "onboarding": _onboarding_summary(db, tenant.id),
        "website": _website_summary(db, tenant),
        "admin_view": is_global_admin(user),
        "read_only_operations": is_global_admin(user),
        "actions": {
            "return_route": "portfolio" if is_global_admin(user) else "home",
            "onboarding_route": "onboarding",
            "pricing_route": "pricing",
            "crm_route": "crm",
            "website_route": "website",
            "access_route": "client-access",
        },
        "metric_provenance": {
            "financials": "RMR client pricing and recognized transactions",
            "adoption": "Platform activity and training records",
            "operations": "Client-owned CRM, forecasting, and campaign records; read-only for RMR/Step2",
        },
    }


@router.get("/tenants/{tenant_id}/success")
def client_success(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    metrics = tenant_success_metrics(db, tenant)
    actions: list[dict[str, str]] = []
    if metrics["training_completion_pct"] < 70:
        actions.append(
            {
                "type": "Coaching",
                "title": "Training completion needs attention",
                "action": "Schedule a role-based training review.",
            }
        )
    if tenant.adoption_score < 70:
        actions.append(
            {
                "type": "Adoption",
                "title": "Low platform adoption",
                "action": "Review inactive users and underused modules.",
            }
        )
    if tenant.renewal_risk != "Low":
        actions.append(
            {
                "type": "Retention",
                "title": "Renewal attention",
                "action": "Prepare a value review with usage evidence.",
            }
        )
    active_codes = set(
        db.scalars(
            select(TenantService.service_code).where(
                TenantService.tenant_id == tenant.id, TenantService.status == "active"
            )
        )
    )
    if "piq_access" not in active_codes:
        actions.append(
            {
                "type": "Expansion",
                "title": "ProspectIQ is available",
                "action": "Review client interest signals before outreach.",
            }
        )
    if "campaigns" not in active_codes:
        actions.append(
            {
                "type": "Expansion",
                "title": "Campaigns & Content is available",
                "action": "Offer only when client activity supports the conversation.",
            }
        )
    return {"tenant": model_dict(tenant), "metrics": metrics, "actions": actions}


@router.post("/tenants/{tenant_id}/support-access")
def record_support_access(
    tenant_id: str,
    request: Request,
    payload: dict,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    access = SupportAccess(
        admin_user_id=user.id,
        tenant_id=tenant_id,
        area=str(payload.get("area", "Client Operations — Read Only"))[:120],
        purpose=str(payload.get("purpose", "Authorized support review"))[:300],
        access_type="read_only",
    )
    db.add(access)
    audit(
        db,
        user,
        "support.view",
        tenant_id=tenant_id,
        entity_type="support_access",
        entity_id=access.id,
        data={"area": access.area, "access_type": "read_only"},
    )
    db.commit()
    return {"access": model_dict(access)}


@router.get("/support-access")
def support_access_log(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    rows = list(
        db.execute(
            select(SupportAccess, User, Tenant)
            .join(User, User.id == SupportAccess.admin_user_id)
            .join(Tenant, Tenant.id == SupportAccess.tenant_id)
            .order_by(SupportAccess.created_at.desc())
            .limit(200)
        )
    )
    return {
        "events": [
            {"access": model_dict(a), "administrator": u.full_name, "tenant": t.name}
            for a, u, t in rows
        ]
    }


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if is_global_admin(user):
        rows = list(
            db.scalars(
                select(Notification)
                .where(Notification.recipient_scope == "GLOBAL_ADMIN")
                .order_by(Notification.created_at.desc())
                .limit(100)
            )
        )
    else:
        rows = list(
            db.scalars(
                select(Notification)
                .where(Notification.recipient_scope == f"TENANT:{user.tenant_id}")
                .order_by(Notification.created_at.desc())
                .limit(100)
            )
        )
    return {"notifications": [model_dict(row) for row in rows]}


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not is_global_admin(user) and notification.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")
    notification.status = "read"
    db.commit()
    return {"ok": True, "action_route": notification.action_route}
