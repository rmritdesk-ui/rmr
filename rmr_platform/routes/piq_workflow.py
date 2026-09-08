"""PIQ collection/history reads and validated profile management; no provider I/O."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User, TenantService, PiqOpportunity
from ..unified_models import PiqTargetProfile
from ..piq_models import PiqDiscoveryRun, PiqProfileMatch, PiqResearchRun
from ..permissions import require_tenant_access, require_client_operational_write
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict

router = APIRouter()
Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
    industries: list[Term] = Field(min_length=1, max_length=25)
    locations: list[Term] = Field(min_length=1, max_length=25)
    keywords: list[Term] = Field(default_factory=list, max_length=25)
    exclusions: list[Term] = Field(default_factory=list, max_length=25)
    employee_min: int = Field(default=0, ge=0, strict=True)
    employee_max: int = Field(default=0, ge=0, strict=True)
    revenue_min_cents: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def valid_range(self):
        if self.employee_max and self.employee_min > self.employee_max:
            raise ValueError("Maximum employees must be at least minimum employees")
        return self

def access(db, user, tenant_id, *, write=False):
    require_tenant_access(user, tenant_id)
    if not user.active or not db.scalar(select(TenantService.id).where(
        TenantService.tenant_id == tenant_id, TenantService.service_code == "piq_access",
        TenantService.status == "active")):
        raise HTTPException(403, "ProspectIQ access required")
    if write:
        require_client_operational_write(user, tenant_id)

def profile_for(db, tenant_id, profile_id=None, *, active=False):
    if profile_id:
        row = db.scalar(select(PiqTargetProfile).where(PiqTargetProfile.id == profile_id,
                                                     PiqTargetProfile.tenant_id == tenant_id))
        if not row:
            raise HTTPException(404, "Target Profile not found")
    else:
        # Compatibility for older one-profile callers; never guess between profiles.
        rows = list(db.scalars(select(PiqTargetProfile).where(
            PiqTargetProfile.tenant_id == tenant_id, PiqTargetProfile.active.is_(True))))
        if len(rows) > 1:
            raise HTTPException(409, "Select a Target Profile explicitly")
        row = rows[0] if rows else None
    if active and (not row or not row.active):
        raise HTTPException(400, "An active Target Profile is required")
    return row

def update_fields(row, payload):
    for key, value in payload.model_dump().items():
        setattr(row, key + "_json" if key in {"industries","locations","keywords","exclusions"} else key, value)

@router.get("/tenants/{tenant_id}/piq/target-profiles")
def profiles(tenant_id: str, include_archived: bool=False, user: User=Depends(current_user), db: Session=Depends(get_db)):
    access(db,user,tenant_id)
    query=select(PiqTargetProfile).where(PiqTargetProfile.tenant_id==tenant_id)
    if not include_archived: query=query.where(PiqTargetProfile.active.is_(True))
    writable=True
    try: access(db,user,tenant_id,write=True)
    except HTTPException: writable=False
    from .unified import settings
    can_move = writable and bool(db.scalar(select(TenantService.id).where(
        TenantService.tenant_id==tenant_id,TenantService.service_code=="piq_enhancement",TenantService.status=="active")))
    return {"profiles":[model_dict(p) for p in db.scalars(query.order_by(PiqTargetProfile.created_at,PiqTargetProfile.id))],
            "can_move":can_move,
            "can_write":writable, "max_requested_count":min(50,settings.piq_max_results_per_run),
            "discovery_live":settings.piq_live_discovery_enabled,
            "research_live":getattr(settings,"piq_live_research_enabled",False)}

@router.get("/tenants/{tenant_id}/piq/target-profiles/{profile_id}")
def get_profile(tenant_id: str, profile_id: str, user: User=Depends(current_user), db: Session=Depends(get_db)):
    access(db,user,tenant_id)
    return {"profile":model_dict(profile_for(db,tenant_id,profile_id))}

@router.post("/tenants/{tenant_id}/piq/target-profiles",status_code=201)
def create_profile(tenant_id: str, payload: ProfileInput, request: Request, user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_request_origin(request);access(db,user,tenant_id,write=True)
    row=PiqTargetProfile(tenant_id=tenant_id,created_by=user.id)
    update_fields(row,payload);db.add(row);db.flush()
    audit(db,user,"piq.target.created",tenant_id=tenant_id,entity_type="piq_target_profile",entity_id=row.id)
    db.commit()
    return {"profile":model_dict(row)}

@router.put("/tenants/{tenant_id}/piq/target-profiles/{profile_id}")
def edit_profile(tenant_id: str, profile_id: str, payload: ProfileInput, request: Request, user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_request_origin(request);access(db,user,tenant_id,write=True)
    row=profile_for(db,tenant_id,profile_id,active=True);update_fields(row,payload)
    audit(db,user,"piq.target.updated",tenant_id=tenant_id,entity_type="piq_target_profile",entity_id=row.id)
    db.commit()
    return {"profile":model_dict(row)}

@router.delete("/tenants/{tenant_id}/piq/target-profiles/{profile_id}")
def archive_profile(tenant_id: str, profile_id: str, request: Request, user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_request_origin(request);access(db,user,tenant_id,write=True)
    row=profile_for(db,tenant_id,profile_id)
    if row.active:
        row.active=False
        audit(db,user,"piq.target.archived",tenant_id=tenant_id,entity_type="piq_target_profile",entity_id=row.id)
        db.commit()
    return {"profile":model_dict(row),"archived":True}

@router.get("/tenants/{tenant_id}/piq/target-profiles/{profile_id}/runs")
def profile_runs(tenant_id: str, profile_id: str, user: User=Depends(current_user), db: Session=Depends(get_db)):
    access(db,user,tenant_id);profile_for(db,tenant_id,profile_id)
    from .unified import discovery_run_status
    rows=db.scalars(select(PiqDiscoveryRun).where(PiqDiscoveryRun.tenant_id==tenant_id,
        PiqDiscoveryRun.target_profile_id==profile_id).order_by(PiqDiscoveryRun.created_at.desc(),PiqDiscoveryRun.id.desc()))
    return {"runs":[discovery_run_status(tenant_id,r.id,user,db) for r in rows]}

def research_state(db,user,row):
    from .unified import settings
    from ..piq_engine import research_service as rs
    from ..piq_engine.research import configuration
    latest=db.scalar(select(PiqResearchRun).where(PiqResearchRun.tenant_id==row.tenant_id,
        PiqResearchRun.opportunity_id==row.id).order_by(PiqResearchRun.created_at.desc(),PiqResearchRun.id.desc()).limit(1))
    live=getattr(settings,"piq_live_research_enabled",False)
    eligible=True;reason="";can_confirm=False
    can_move=False
    try:
        access(db,user,row.tenant_id,write=True)
        can_move=bool(db.scalar(select(TenantService.id).where(
            TenantService.tenant_id==row.tenant_id,TenantService.service_code=="piq_enhancement",
            TenantService.status=="active")))
    except HTTPException: pass
    try:
        rs.access(db,user,row.id,spend=True)
        can_confirm=True
    except HTTPException: pass
    try:
        if live:
            configuration(settings);rs.snapshot_for(db,row)
        elif row.moved_to_crm:
            raise HTTPException(409,"This prospect is already in CRM")
        if latest and latest.status in ("queued","running","retry_wait"):
            raise HTTPException(409,"Research is already in progress")
    except HTTPException as exc:
        eligible=False;reason=str(exc.detail)
    except Exception:
        eligible=False;reason="Live research configuration is unavailable"
    return {"mode":"live" if live else "demonstration","eligible":eligible,"reason":reason,
            "can_confirm":can_confirm,"can_move":can_move,"latest":rs.safe_run(latest) if latest else None}

@router.get("/piq/{opportunity_id}/research-state")
def opportunity_research_state(opportunity_id: str,user: User=Depends(current_user),db: Session=Depends(get_db)):
    row=db.get(PiqOpportunity,opportunity_id)
    if not row or row.tenant_id!=user.tenant_id and not user.global_role:
        raise HTTPException(404,"ProspectIQ record not found")
    access(db,user,row.tenant_id)
    return research_state(db,user,row)

@router.get("/tenants/{tenant_id}/piq/target-profiles/{profile_id}/results")
def profile_results(tenant_id: str,profile_id: str,run_id: str|None=None,user: User=Depends(current_user),db: Session=Depends(get_db)):
    access(db,user,tenant_id);profile_for(db,tenant_id,profile_id)
    query=select(PiqOpportunity).where(PiqOpportunity.tenant_id==tenant_id,
                                       PiqOpportunity.target_profile_id==profile_id)
    if run_id:
        run=db.scalar(select(PiqDiscoveryRun).where(PiqDiscoveryRun.id==run_id,
            PiqDiscoveryRun.tenant_id==tenant_id,PiqDiscoveryRun.target_profile_id==profile_id))
        if not run: raise HTTPException(404,"Discovery run not found")
        query=query.join(PiqProfileMatch,PiqProfileMatch.opportunity_id==PiqOpportunity.id).where(
            PiqProfileMatch.tenant_id==tenant_id,PiqProfileMatch.discovery_run_id==run_id)
    rows=list(db.scalars(query.order_by(PiqOpportunity.score.desc(),PiqOpportunity.id)))
    return {"opportunities":[{**model_dict(r),"research":research_state(db,user,r)} for r in rows]}
