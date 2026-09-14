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
from . import provisioning
from . import profile_bootstrap
from .contracts import MappingCheckRequest
from .contracts import ProvisionRequest, ProvisionResponse
from .contracts import CrmLeadRequest, CrmLeadResponse, ReceiptLookupRequest

router = APIRouter(prefix="/api/integrations/prospectiq/v1", tags=["ProspectIQ federation"])


@router.get("/health")
def bridge_health(db: Session = Depends(get_db)):
    from .operations import readiness
    result=readiness(db)
    return JSONResponse(result,status_code=503 if result["status"]=="not_ready" else 200)


@router.get("/crm/handoffs/{external_id}")
async def receipt_lookup(external_id: UUID, request: Request, db: Session = Depends(get_db), cfg=Depends(crm.crm_config)):
    from .operations import lookup_receipt
    path=request.url.path+("?" + request.url.query if request.url.query else "")
    if len(path)>3000 or await request.body():
        raise HTTPException(422,{"code":"crm_invalid_lookup"})
    crm.authenticate(db,request.headers,b"",request.method,path,cfg)
    try:
        if len(request.query_params.multi_items())!=len(dict(request.query_params)):
            raise ValueError()
        data=dict(request.query_params)
        if "mapping_version" in data:
            data["mapping_version"]=int(data["mapping_version"])
        payload=ReceiptLookupRequest.model_validate(data)
    except (ValidationError,ValueError):
        raise HTTPException(422,{"code":"crm_invalid_lookup"}) from None
    result=lookup_receipt(db,external_id,payload,cfg)
    return JSONResponse(result,headers={"Cache-Control":"no-store"})


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
                    Mapping.integration_instance_id == cfg.instance))
    if not row:
        managed = service.authorized_tenant(db, user, str(tenant_id))
        return {"enabled": True, "status": "unprovisioned", "can_provision":
                "profiles.create" in service.capabilities_for(user, str(tenant_id), managed)}
    service.authorized(db, user, row, cfg)
    return {"enabled": True, "status": "ready", "mapping_id": row.id}


@router.post("/provision", response_model=ProvisionResponse)
def provision_workspace(payload: ProvisionRequest, request: Request, user=Depends(current_user),
                        db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    result = provisioning.provision(db, user, str(payload.tenant_id), request, cfg)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/launch", response_model=LaunchResponse)
def launch(payload: LaunchRequest, request: Request, user=Depends(current_user),
           db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    return service.create_launch(db, user, payload, request, cfg)


@router.post('/profiles/bootstrap')
def bootstrap_profiles(payload: ProvisionRequest, request: Request, user=Depends(current_user),
                       db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    result = profile_bootstrap.ensure_bootstrap(db, user, str(payload.tenant_id), request, cfg)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@router.post('/mappings/check')
async def check_mapping(payload: MappingCheckRequest, request: Request,
                        db: Session = Depends(get_db), cfg=Depends(bridge_config)):
    service.authenticate_service(db, request.headers, await request.body(), request.method, request.url.path, cfg)
    row = db.get(Mapping, str(payload.mapping_id))
    active = bool(row and row.status == 'active' and row.mapping_version == payload.mapping_version
                  and row.tenant_id == str(payload.rmr_tenant_id) and row.piq_client_id == str(payload.piq_client_id)
                  and row.integration_instance_id == payload.integration_instance_id == cfg.instance)
    if active:
        try:
            service.require_operational_tenant(db, row.tenant_id)
        except HTTPException:
            active = False
    return JSONResponse({'active': active}, headers={'Cache-Control': 'no-store'})


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
    if (not grant or grant.mapping_version != payload.mapping_version
            or payload.integration_instance_id != cfg.instance):
        return {"active": False, "reason": "access_denied", "context": None}
    try:
        service.check_grant(db, grant, cfg)
        if (grant.status != "consumed" or grant.mapping_version != payload.mapping_version
                or payload.integration_instance_id != cfg.instance):
            raise HTTPException(403, "Inactive grant")
        result = {"active": True, "reason": "active", "context": service.context(grant)}
        db.commit()
        return result
    except HTTPException:
        if grant and grant.status != "revoked":
            grant.status = "revoked"
            grant.revoked_at = service.utcnow()
            db.commit()
        return {"active": False, "reason": "access_denied", "context": None}
