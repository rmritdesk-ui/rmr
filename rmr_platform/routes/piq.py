from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Lead, PiqOpportunity, TenantService, User
from ..permissions import is_global_admin, require_client_operational_write, require_tenant_access
from ..schemas import PiqEnhanceRequest
from ..security import current_user, require_request_origin
from ..services import audit, create_monthly_transaction
from ..utils import model_dict
from ..unified_models import PiqEvidence

router = APIRouter(prefix="/api", tags=["piq"])


def _require_piq_access(db: Session, tenant_id: str) -> tuple[TenantService, TenantService]:
    access = db.scalar(select(TenantService).where(
        TenantService.tenant_id == tenant_id,
        TenantService.service_code == "piq_access",
        TenantService.status == "active",
    ))
    enhancement = db.scalar(select(TenantService).where(
        TenantService.tenant_id == tenant_id,
        TenantService.service_code == "piq_enhancement",
        TenantService.status == "active",
    ))
    if not access or not enhancement:
        raise HTTPException(status_code=403, detail="ProspectIQ is not active for this client")
    return access, enhancement


@router.get("/tenants/{tenant_id}/piq")
def list_piq(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    _require_piq_access(db, tenant_id)
    rows = list(db.scalars(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant_id).order_by(PiqOpportunity.score.desc())))
    return {
        "opportunities": [model_dict(row) for row in rows],
        "read_only": is_global_admin(user),
        "payment_provider": settings.payment_provider,
    }


@router.post("/piq/{opportunity_id}/enhance")
def enhance_piq(opportunity_id: str, payload: PiqEnhanceRequest, request: Request,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    opportunity = db.get(PiqOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="ProspectIQ opportunity not found")
    require_client_operational_write(user, opportunity.tenant_id)
    _, enhancement_service = _require_piq_access(db, opportunity.tenant_id)
    if opportunity.enhanced:
        return {"opportunity": model_dict(opportunity), "charged": False, "message": "This profile is already enhanced"}
    if not payload.payment_confirmation:
        raise HTTPException(status_code=400, detail="Paid enhancement confirmation is required")
    # v5.0 pilot uses a payment-provider adapter in mock mode. The transaction
    # is recorded before enrichment. Live processor credentials are a deployment gate.
    transaction = create_monthly_transaction(db, opportunity.tenant_id, enhancement_service, quantity=1)
    db.flush()
    opportunity.enhanced = True
    opportunity.enhancement_price_cents = enhancement_service.usage_price_cents or enhancement_service.contract_price_cents
    opportunity.score = min(100, max(opportunity.score or 0, 72) + 8)
    opportunity.status = "Enhanced"
    facts = [
        f"Enhanced company profile completed for {opportunity.company_name}.",
        "Profile-match and growth-signal evidence should be reviewed by a person before outreach.",
    ]
    for fact in facts:
        db.add(PiqEvidence(
            opportunity_id=opportunity.id,
            evidence_type="paid_enhancement",
            source_name="RMR Enhancement Adapter",
            source_url="",
            fact=fact,
            confidence_pct=82,
            verified=True,
        ))
    opportunity.evidence_count = (opportunity.evidence_count or 0) + len(facts)
    audit(db, user, "piq.profile.enhanced", tenant_id=opportunity.tenant_id, entity_type="piq_opportunity", entity_id=opportunity.id,
          data={"transaction_id": transaction.id, "payment_provider": settings.payment_provider, "evidence_added": len(facts)})
    db.commit()
    return {"opportunity": model_dict(opportunity), "transaction": model_dict(transaction), "charged": True}


@router.post("/piq/{opportunity_id}/move-to-crm")
def move_piq_to_crm(opportunity_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    opportunity = db.get(PiqOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="ProspectIQ opportunity not found")
    require_client_operational_write(user, opportunity.tenant_id)
    _require_piq_access(db, opportunity.tenant_id)
    if opportunity.moved_to_crm:
        return {"opportunity": model_dict(opportunity), "created": False}
    tenant_id = opportunity.tenant_id
    try:
        # The database, not the previously loaded boolean, elects one converter.
        # Claim, Lead and audit must commit together so failure releases the claim.
        claimed = db.execute(update(PiqOpportunity).where(
            PiqOpportunity.id == opportunity_id,
            PiqOpportunity.tenant_id == tenant_id,
            PiqOpportunity.moved_to_crm.is_(False),
        ).values(moved_to_crm=True).execution_options(synchronize_session=False))
        opportunity = db.scalar(select(PiqOpportunity).where(
            PiqOpportunity.id == opportunity_id,
            PiqOpportunity.tenant_id == tenant_id,
        ).execution_options(populate_existing=True))
        if not opportunity:
            raise HTTPException(status_code=404, detail="ProspectIQ opportunity not found")
        if claimed.rowcount == 0:
            return {"opportunity": model_dict(opportunity), "created": False}
        lead = Lead(
            tenant_id=opportunity.tenant_id,
            company_name=opportunity.company_name,
            contact_name="",
            email="",
            phone=opportunity.phone or "",
            source="ProspectIQ",
            status="New",
            notes=f"Signal: {opportunity.signal}. Score: {opportunity.score}. Evidence items: {opportunity.evidence_count}.",
            assigned_user_id=user.id,
        )
        db.add(lead)
        db.flush()
        audit(db, user, "piq.moved_to_crm", tenant_id=opportunity.tenant_id, entity_type="piq_opportunity", entity_id=opportunity.id,
              data={"lead_id": lead.id})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"opportunity": model_dict(opportunity), "lead": model_dict(lead), "created": True}
