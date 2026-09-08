from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Activity, Opportunity, User
from .permissions import require_client_operational_write, require_tenant_access
from .security import current_user, require_request_origin
from .services import audit
from .utils import model_dict

router = APIRouter(prefix="/api/v531", tags=["v5.3.1-final-production-corrections"])

CLOSED_STAGES = {"Closed Won", "Closed Lost"}


class OpportunityQuickClose(BaseModel):
    stage: Literal["Closed Won", "Closed Lost"]
    close_date: date
    final_value_cents: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=2000)
    loss_reason: str = Field(default="", max_length=500)


def _opportunity_totals(db: Session, tenant_id: str) -> dict[str, int]:
    open_rows = list(
        db.scalars(
            select(Opportunity).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.stage.notin_(list(CLOSED_STAGES)),
            )
        )
    )
    won_rows = list(
        db.scalars(
            select(Opportunity).where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.stage == "Closed Won",
            )
        )
    )
    return {
        "open_opportunities": len(open_rows),
        "weighted_pipeline_cents": int(round(sum(row.value_cents * row.probability_pct / 100 for row in open_rows))),
        "won_opportunities": len(won_rows),
        "won_revenue_cents": int(sum(row.value_cents for row in won_rows)),
    }


@router.post("/opportunities/{opportunity_id}/quick-close")
def quick_close_opportunity(
    opportunity_id: str,
    payload: OpportunityQuickClose,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Close an existing opportunity through the same persisted CRM record.

    This is intentionally a bounded convenience endpoint. It does not create a
    second pipeline or reporting engine; it updates the existing Opportunity and
    records the event in the existing Activity/Audit streams.
    """
    require_request_origin(request)
    opportunity = db.get(Opportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    require_tenant_access(user, opportunity.tenant_id)
    require_client_operational_write(user, opportunity.tenant_id)

    if payload.stage == "Closed Lost" and not payload.loss_reason.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Enter a loss reason before marking the opportunity Closed Lost.",
                "field_errors": {"loss_reason": "Loss reason is required for Closed Lost."},
            },
        )

    previous_stage = opportunity.stage
    previous_value = opportunity.value_cents
    if payload.final_value_cents is not None:
        opportunity.value_cents = payload.final_value_cents
    opportunity.stage = payload.stage
    opportunity.expected_close_date = payload.close_date
    opportunity.probability_pct = 100 if payload.stage == "Closed Won" else 0
    opportunity.loss_reason = payload.loss_reason.strip() if payload.stage == "Closed Lost" else ""
    opportunity.next_action = "Closed — follow-up complete" if payload.stage == "Closed Won" else "Closed — review loss reason"

    body_lines = [
        f"Stage changed from {previous_stage} to {payload.stage}.",
        f"Final value: ${opportunity.value_cents / 100:,.2f}.",
        f"Close date: {payload.close_date.isoformat()}.",
    ]
    if payload.loss_reason.strip():
        body_lines.append(f"Loss reason: {payload.loss_reason.strip()}.")
    if payload.note.strip():
        body_lines.append(payload.note.strip())

    activity = Activity(
        tenant_id=opportunity.tenant_id,
        account_id=opportunity.account_id,
        opportunity_id=opportunity.id,
        user_id=user.id,
        activity_type="Opportunity Closed Won" if payload.stage == "Closed Won" else "Opportunity Closed Lost",
        subject=f"{opportunity.name} marked {payload.stage}",
        body="\n".join(body_lines),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(activity)
    audit(
        db,
        user,
        "crm.opportunity.quick_closed",
        tenant_id=opportunity.tenant_id,
        entity_type="opportunity",
        entity_id=opportunity.id,
        data={
            "previous_stage": previous_stage,
            "new_stage": payload.stage,
            "previous_value_cents": previous_value,
            "final_value_cents": opportunity.value_cents,
            "close_date": payload.close_date.isoformat(),
            "loss_reason": opportunity.loss_reason,
        },
    )
    db.commit()
    db.refresh(opportunity)
    db.refresh(activity)
    return {
        "opportunity": model_dict(opportunity),
        "activity": model_dict(activity),
        "summary": _opportunity_totals(db, opportunity.tenant_id),
    }
