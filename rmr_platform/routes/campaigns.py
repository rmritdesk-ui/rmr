from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Campaign, User
from ..permissions import is_global_admin, require_client_campaign_write, require_tenant_access
from ..schemas import CampaignCreate, CampaignUpdate
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict

router = APIRouter(prefix="/api", tags=["campaigns"])


@router.get("/tenants/{tenant_id}/campaigns")
def list_campaigns(tenant_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_tenant_access(user, tenant_id)
    rows = list(db.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id).order_by(Campaign.updated_at.desc())))
    return {"campaigns": [model_dict(row) for row in rows], "read_only": is_global_admin(user)}


@router.post("/tenants/{tenant_id}/campaigns")
def create_campaign(tenant_id: str, payload: CampaignCreate, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_client_campaign_write(user, tenant_id)
    campaign = Campaign(tenant_id=tenant_id, created_by=user.id, **payload.model_dump())
    if campaign.status in {"Approved", "Scheduled", "Published"}:
        campaign.approved_by = user.id
    db.add(campaign)
    db.flush()
    audit(db, user, "campaign.created", tenant_id=tenant_id, entity_type="campaign", entity_id=campaign.id,
          data={"channel": campaign.channel, "status": campaign.status})
    db.commit()
    return {"campaign": model_dict(campaign)}


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, payload: CampaignUpdate, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    require_client_campaign_write(user, campaign.tenant_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(campaign, field, value)
    if payload.status in {"Approved", "Scheduled", "Published"}:
        campaign.approved_by = user.id
    audit(db, user, "campaign.updated", tenant_id=campaign.tenant_id, entity_type="campaign", entity_id=campaign.id,
          data=payload.model_dump(exclude_none=True))
    db.commit()
    return {"campaign": model_dict(campaign)}
