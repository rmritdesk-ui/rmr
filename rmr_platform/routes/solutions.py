from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Notification, ServiceCatalog, SolutionInterest, SolutionRequest, Tenant, TenantService, User
from ..permissions import is_global_admin, require_global_admin, require_tenant_access
from ..schemas import SolutionInterestCreate, SolutionRequestCreate, SolutionRequestReview
from ..security import current_user, require_request_origin
from ..services import activate_solution, audit, maybe_create_interest_notification
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["solutions"])


@router.get("/tenants/{tenant_id}/solutions")
def list_solutions(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    catalog = list(db.scalars(select(ServiceCatalog).where(ServiceCatalog.active.is_(True)).order_by(ServiceCatalog.sort_order)))
    active = {row.service_code: row for row in db.scalars(select(TenantService).where(TenantService.tenant_id == tenant_id, TenantService.status == "active"))}
    requests = {row.service_code: row for row in db.scalars(select(SolutionRequest).where(
        SolutionRequest.tenant_id == tenant_id,
        SolutionRequest.status.in_(["Requested", "Pending Activation"]),
    ).order_by(SolutionRequest.created_at.desc()))}
    solutions = []
    for service in catalog:
        if service.code == "private_reference":
            continue
        if service.code in active:
            status = "Active"
        elif service.code in requests:
            status = requests[service.code].status
        else:
            status = "Available"
        data = model_dict(service)
        if not is_global_admin(user):
            for key in ["direct_cost_cents", "split_basis", "rmr_share_pct", "step2_share_pct"]:
                data.pop(key, None)
        solutions.append({
            "service": data,
            "status": status,
            "tenant_service": model_dict(active[service.code]) if service.code in active else None,
            "request": model_dict(requests[service.code]) if service.code in requests else None,
        })
    return {"solutions": solutions}


@router.post("/tenants/{tenant_id}/solution-interest")
def record_interest(tenant_id: str, payload: SolutionInterestCreate, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    if is_global_admin(user):
        return {"recorded": False, "reason": "Administrative previews do not create client intent signals"}
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == payload.service_code, ServiceCatalog.active.is_(True)))
    if not catalog:
        raise HTTPException(status_code=404, detail="Solution not found")
    event = SolutionInterest(
        tenant_id=tenant_id,
        user_id=user.id,
        service_code=payload.service_code,
        event_type=payload.event_type,
    )
    db.add(event)
    db.flush()
    maybe_create_interest_notification(db, tenant_id, payload.service_code)
    audit(db, user, "solution.interest.recorded", tenant_id=tenant_id, entity_type="service_catalog", entity_id=payload.service_code,
          data={"event_type": payload.event_type})
    db.commit()
    return {"recorded": True}


@router.post("/tenants/{tenant_id}/solution-requests")
def request_solution(tenant_id: str, payload: SolutionRequestCreate, request: Request,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    if is_global_admin(user):
        raise HTTPException(status_code=403, detail="Use Client Pricing to add services administratively")
    if user.tenant_role != "CLIENT_ADMIN":
        raise HTTPException(status_code=403, detail="Client Administrator access required")
    catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == payload.service_code, ServiceCatalog.active.is_(True)))
    if not catalog:
        raise HTTPException(status_code=404, detail="Solution not found")
    active = db.scalar(select(TenantService).where(TenantService.tenant_id == tenant_id, TenantService.service_code == payload.service_code, TenantService.status == "active"))
    if active:
        raise HTTPException(status_code=409, detail="This solution is already active")
    existing = db.scalar(select(SolutionRequest).where(
        SolutionRequest.tenant_id == tenant_id,
        SolutionRequest.service_code == payload.service_code,
        SolutionRequest.status.in_(["Requested", "Pending Activation"]),
    ))
    if existing:
        raise HTTPException(status_code=409, detail="A request is already in progress")
    request_row = SolutionRequest(
        tenant_id=tenant_id,
        service_code=payload.service_code,
        requested_by=user.id,
        status="Requested",
        note=payload.note,
        proposed_monthly_cents=catalog.standard_price_cents if catalog.cadence == "monthly" else 0,
        proposed_usage_cents=catalog.standard_price_cents if catalog.cadence == "usage" else 0,
        preferred_contact_method=payload.preferred_contact_method,
        best_time=payload.best_time,
    )
    db.add(request_row)
    db.flush()
    tenant = db.get(Tenant, tenant_id)
    db.add(Notification(
        recipient_scope="GLOBAL_ADMIN",
        tenant_id=tenant_id,
        notification_type="solution_request",
        title=f"New solution request — {catalog.name}",
        body=f"{tenant.name if tenant else 'Client'} requested {catalog.name}.",
        action_route="service-requests",
        action_label="Review request",
        entity_type="solution_request",
        entity_id=request_row.id,
    ))
    audit(db, user, "solution.requested", tenant_id=tenant_id, entity_type="solution_request", entity_id=request_row.id,
          data={"service_code": payload.service_code})
    db.commit()
    return {"request": model_dict(request_row)}


@router.get("/solution-requests")
def list_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_global_admin(user)
    rows = list(db.execute(
        select(SolutionRequest, Tenant, ServiceCatalog, User)
        .join(Tenant, Tenant.id == SolutionRequest.tenant_id)
        .join(ServiceCatalog, ServiceCatalog.code == SolutionRequest.service_code)
        .join(User, User.id == SolutionRequest.requested_by)
        .order_by(SolutionRequest.created_at.desc())
    ))
    return {
        "requests": [
            {
                "request": model_dict(request_row),
                "tenant_id": tenant.id,
                "service_code": catalog.code,
                "tenant": tenant.name,
                "service": catalog.name,
                "requested_by_name": requester.full_name,
            }
            for request_row, tenant, catalog, requester in rows
        ]
    }


@router.patch("/solution-requests/{request_id}")
def review_request(request_id: str, payload: SolutionRequestReview, request: Request,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_global_admin(user)
    request_row = db.get(SolutionRequest, request_id)
    if not request_row:
        raise HTTPException(status_code=404, detail="Service request not found")
    if payload.status == "Active":
        if payload.review_note.strip():
            request_row.note = (request_row.note + "\n" + payload.review_note).strip()
        request_row.reviewed_by = user.id
        from datetime import datetime, timezone
        request_row.reviewed_at = datetime.now(timezone.utc)
        service = activate_solution(
            db,
            request_row,
            user,
            contract_price_cents=payload.contract_price_cents,
            usage_price_cents=payload.usage_price_cents,
        )
        db.commit()
        return {"request": model_dict(request_row), "service": model_dict(service)}
    request_row.status = payload.status
    request_row.note = (request_row.note + "\n" + payload.review_note).strip()
    request_row.reviewed_by = user.id
    from datetime import datetime, timezone
    request_row.reviewed_at = datetime.now(timezone.utc)
    audit(db, user, "solution.request.reviewed", tenant_id=request_row.tenant_id, entity_type="solution_request", entity_id=request_row.id,
          data={"status": payload.status})
    db.commit()
    return {"request": model_dict(request_row)}
