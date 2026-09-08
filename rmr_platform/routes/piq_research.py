from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..piq_models import PiqResearchRun
from ..security import current_user, require_request_origin
from ..piq_engine import research_service as service
from ..piq_engine.contracts import PiqProviderError

router = APIRouter()


class ResearchConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=36)
    confirmation_token: str = Field(min_length=20, max_length=100)


def translate(call):
    try:
        return call()
    except PiqProviderError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.public_message}) from None


@router.post("/piq/{opportunity_id}/adaptive-research/estimate")
def research_estimate(opportunity_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .unified import settings
    require_request_origin(request)
    return translate(lambda: service.estimate(db, user, opportunity_id, settings))


@router.get("/piq/{opportunity_id}/adaptive-research/{run_id}")
def research_status(opportunity_id: str, run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = service.access(db, user, opportunity_id)
    run = db.scalar(select(PiqResearchRun).where(PiqResearchRun.id == run_id,
        PiqResearchRun.opportunity_id == row.id, PiqResearchRun.tenant_id == row.tenant_id))
    if not run:
        raise HTTPException(404, "Research run not found")
    return service.safe_run(run)
