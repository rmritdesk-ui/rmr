from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..config import settings
from ..db import get_db
from ..security import current_user
from .config import bridge_config
from .contracts import LaunchRequest, LaunchResponse, AuthorizeRequest, AuthorizeResponse, ExchangeRequest, ExchangeResponse, GrantCheckRequest, GrantCheckResponse
from .models import ProspectiqClientMapping as Mapping, ProspectiqAuthorizationGrant as Grant
from . import service
from . import crm
from .contracts import CrmLeadRequest, CrmLeadResponse

router = APIRouter(prefix="/api/integrations/prospectiq/v1", tags=["ProspectIQ federation"])


@router.post("/crm/leads", response_model=CrmLeadResponse)
async def receive_crm_lead(request: Request, db: Session = Depends(get_db), cfg=Depends(crm.crm_config)):
    # Authenticate raw bytes before exposing the strict versioned payload parser.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > crm.MAX_BODY:
            raise HTTPException(413, {"code": "crm_payload_too_large"})
    crm.authenticate(db, request.headers, bytes(body), request.method, request.url.path, cfg)
    try:
        payload = CrmLeadRequest.model_validate_json(bytes(body))
    except ValidationError:
        raise HTTPException(422, {"code": "crm_invalid_payload"}) from None
    status, result = crm.receive(db, payload, cfg)
    return JSONResponse(status_code=status, content=CrmLeadResponse(**result).model_dump(mode="json"))


@router.get("/availability")
def availability(tenant_id: UUID, user=Depends(current_user), db: Session = Depends(get_db)):
    if not settings.prospectiq_bridge_enabled:
        return {"enabled": False}
    cfg = bridge_config()
    row = db.scalar(select(Mapping).where(Mapping.tenant_id == str(tenant_id),
                    Mapping.integration_instance_id == cfg.instance, Mapping.status == "active"))
    service.authorized(db, user, row, cfg)
    return {"enabled": True, "mapping_id": row.id}


@router.post("/launch", response_model=LaunchResponse)
def launch(payload: LaunchRequest, request: Request, user=Depends(current_user),
           db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    return service.create_launch(db, user, payload, request, cfg)


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize(payload: AuthorizeRequest, request: Request, user=Depends(current_user),
              db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    return service.authorize_launch(db, user, payload, request, cfg)


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange(payload: ExchangeRequest, request: Request, db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    service.authenticate_service(db, request.headers, await request.body(), request.method, request.url.path, cfg)
    return service.exchange_code(db, payload, cfg)


@router.post("/grants/check", response_model=GrantCheckResponse)
async def check(payload: GrantCheckRequest, request: Request, db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    service.authenticate_service(db, request.headers, await request.body(), request.method, request.url.path, cfg)
    grant = db.get(Grant, str(payload.grant_id))
    try:
        service.check_grant(db, grant, cfg)
        if (grant.status != "consumed" or grant.mapping_version != payload.mapping_version
                or payload.integration_instance_id != cfg.instance):
            raise HTTPException(403, "Inactive grant")
        return {"active": True, "reason": "active", "context": service.context(grant)}
    except HTTPException:
        return {"active": False, "reason": "access_denied", "context": None}
