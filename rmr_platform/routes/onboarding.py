from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import invitation_summary
from ..db import get_db
from ..models import Notification, OnboardingProject, OnboardingStep, Tenant, TenantService, User, WebsiteSite
from ..permissions import require_global_admin
from ..schemas import OnboardingStepUpdate
from ..security import current_user, require_request_origin
from ..services import audit, recalculate_onboarding
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["onboarding"])


def _stage_requirement(db: Session, tenant: Tenant, step: OnboardingStep, access: dict[str, object]) -> dict[str, object]:
    """Return objective completion evidence for a single onboarding stage.

    Optional stages remain optional. Required stages are derived from existing
    tenant/application state so a blank notes field cannot falsely complete a
    stage and an RMR user is not forced to invent information that does not
    apply to the customer.
    """
    missing: list[str] = []
    status = "ready"
    summary = "Required setup evidence is present."

    if step.stage_number == 1:
        if not tenant.name.strip():
            missing.append("Company name")
        if not tenant.primary_contact_name.strip():
            missing.append("Primary contact name")
        if not tenant.primary_contact_email.strip() or "@" not in tenant.primary_contact_email:
            missing.append("Valid primary contact email")
        if not tenant.timezone.strip():
            missing.append("Client time zone")
        summary = "Client identity, primary contact and time zone are required."
    elif step.stage_number == 2:
        active = bool(access.get("active_client_admins"))
        pending = bool(access.get("pending_invitation"))
        if not (active or pending):
            missing.append("Client Administrator invitation or active Client Administrator")
        summary = "Create a Client Administrator invitation; activation is required before final go-live."
    elif step.stage_number == 3:
        site = db.scalar(select(WebsiteSite).where(WebsiteSite.tenant_id == tenant.id))
        if tenant.website_mode in {"external", "custom"}:
            external_url = (site.external_url if site else "") or tenant.website_url
            if not str(external_url or "").strip():
                missing.append("External/custom website URL")
            summary = "A connected website URL is required for the selected website mode."
        else:
            if not site:
                missing.append("Managed website configuration")
            summary = "A managed website configuration is required."
    elif step.stage_number == 4:
        active_users = db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id, User.active.is_(True))) or 0
        if not active_users and not access.get("pending_invitation"):
            missing.append("At least one client user or pending Client Administrator invitation")
        summary = "The initial sales organization must include a client user or invitation."
    elif step.stage_number == 5:
        status = "optional"
        summary = "Historical sales import is optional and may be completed later."
    elif step.stage_number == 6:
        active_services = db.scalar(select(func.count(TenantService.id)).where(TenantService.tenant_id == tenant.id, TenantService.status == "active")) or 0
        if not active_services:
            missing.append("At least one active client service/module")
        summary = "At least one active service/module is required."
    elif step.stage_number == 7:
        status = "optional"
        summary = "Training assignments are optional at initial go-live and may be added later."
    elif step.stage_number == 8:
        if not access.get("active_client_admins"):
            missing.append("Activated Client Administrator")
        summary = "All prior stages and an activated Client Administrator are required for go-live."

    if missing:
        status = "blocked"
    return {"status": status, "summary": summary, "missing": missing}


def _validate_stage_requirements(db: Session, tenant: Tenant, step: OnboardingStep) -> None:
    access = invitation_summary(db, tenant.id)
    requirement = _stage_requirement(db, tenant, step, access)
    if requirement["status"] == "blocked":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Complete the required setup before marking this stage complete.",
                "gate": "stage_requirements",
                "stage": step.stage_number,
                "missing": requirement["missing"],
            },
        )


def _project_payload(db: Session, tenant: Tenant, project: OnboardingProject) -> dict[str, object]:
    steps = list(
        db.scalars(
            select(OnboardingStep)
            .where(OnboardingStep.project_id == project.id)
            .order_by(OnboardingStep.stage_number)
        )
    )
    access = invitation_summary(db, tenant.id)
    step_rows = [
        {**model_dict(step), "requirement": _stage_requirement(db, tenant, step, access)}
        for step in steps
    ]
    waiting = bool(access.get("pending_invitation")) and not bool(access.get("active_client_admins"))
    return {
        "project": model_dict(project),
        "tenant": model_dict(tenant),
        "steps": step_rows,
        "access": access,
        "completion": {
            "completed_steps": sum(1 for step in steps if step.status == "complete"),
            "total_steps": len(steps),
            "ready_for_go_live": bool(access["active_client_admins"]) and all(
                step.status == "complete" for step in steps[:-1]
            ),
            "waiting_for_client_admin_activation": waiting,
        },
    }


def _go_live_gate(db: Session, project: OnboardingProject, step: OnboardingStep) -> None:
    if step.stage_number != 8:
        return
    steps = list(
        db.scalars(
            select(OnboardingStep)
            .where(OnboardingStep.project_id == project.id)
            .order_by(OnboardingStep.stage_number)
        )
    )
    incomplete_prior = [row.name for row in steps if row.stage_number < 8 and row.status != "complete"]
    if incomplete_prior:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Complete the earlier onboarding stages before go-live validation.",
                "gate": "prior_stages",
                "incomplete_stages": incomplete_prior,
            },
        )
    access = invitation_summary(db, project.tenant_id)
    if not access["active_client_admins"]:
        message = (
            "The Client Administrator invitation is awaiting activation. The client must accept the invitation "
            "before go-live can be completed."
            if access["pending_invitation"]
            else "Invite and activate at least one Client Administrator before go-live can be completed."
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": message,
                "gate": "client_admin_access",
                "access": access,
            },
        )


def _activate_tenant_if_complete(db: Session, project: OnboardingProject) -> Tenant:
    tenant = db.get(Tenant, project.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    if project.status == "complete" and tenant.status != "live":
        tenant.status = "live"
        tenant.health_status = "Healthy"
        db.add(
            Notification(
                recipient_scope="GLOBAL_ADMIN",
                tenant_id=tenant.id,
                notification_type="client_go_live",
                title=f"{tenant.name} is live",
                body="Onboarding and client access are complete.",
                action_route=f"client-360?tenant={tenant.id}",
                action_label="Open Client 360",
                entity_type="tenant",
                entity_id=tenant.id,
            )
        )
    return tenant


@router.get("/onboarding")
def list_onboarding(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    rows = list(
        db.execute(
            select(OnboardingProject, Tenant)
            .join(Tenant, Tenant.id == OnboardingProject.tenant_id)
            .order_by(OnboardingProject.status, Tenant.name)
        )
    )
    return {"projects": [_project_payload(db, tenant, project) for project, tenant in rows]}


@router.get("/tenants/{tenant_id}/onboarding")
def tenant_onboarding(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    tenant = db.get(Tenant, tenant_id)
    project = db.scalar(select(OnboardingProject).where(OnboardingProject.tenant_id == tenant_id))
    if not tenant or not project:
        raise HTTPException(status_code=404, detail="Onboarding record not found")
    return _project_payload(db, tenant, project)


@router.patch("/onboarding/steps/{step_id}")
def update_step(
    step_id: str,
    payload: OnboardingStepUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    step = db.get(OnboardingStep, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Onboarding step not found")
    project = db.get(OnboardingProject, step.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Onboarding project not found")
    tenant = db.get(Tenant, project.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")

    step.data_json = payload.data
    step.notes = payload.notes
    if payload.status:
        if payload.status == "complete":
            _validate_stage_requirements(db, tenant, step)
            _go_live_gate(db, project, step)
        step.status = payload.status
        if payload.status == "complete":
            step.completed_at = datetime.now(timezone.utc)
            step.completed_by = user.full_name
        else:
            step.completed_at = None
            step.completed_by = ""
    recalculate_onboarding(db, project)
    _activate_tenant_if_complete(db, project)
    audit(
        db,
        user,
        "onboarding.step.updated",
        tenant_id=project.tenant_id,
        entity_type="onboarding_step",
        entity_id=step.id,
        data={"stage": step.stage_number, "status": step.status},
    )
    db.commit()
    return {
        **_project_payload(db, tenant, project),
        "step": model_dict(step),
        "next_route": "client-360" if project.status == "complete" else "onboarding",
    }


@router.post("/onboarding/steps/{step_id}/complete")
def complete_step(
    step_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    step = db.get(OnboardingStep, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Onboarding step not found")
    project = db.get(OnboardingProject, step.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Onboarding project not found")
    tenant = db.get(Tenant, project.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client not found")

    _validate_stage_requirements(db, tenant, step)
    _go_live_gate(db, project, step)
    step.status = "complete"
    step.completed_at = datetime.now(timezone.utc)
    step.completed_by = user.full_name
    recalculate_onboarding(db, project)
    _activate_tenant_if_complete(db, project)
    audit(
        db,
        user,
        "onboarding.step.completed",
        tenant_id=project.tenant_id,
        entity_type="onboarding_step",
        entity_id=step.id,
        data={"stage": step.stage_number},
    )
    db.commit()
    return {
        **_project_payload(db, tenant, project),
        "step": model_dict(step),
        "next_route": "client-360" if project.status == "complete" else "onboarding",
    }
