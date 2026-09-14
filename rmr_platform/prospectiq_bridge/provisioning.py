"""First-use coordinator. Tenant authority is checked BEFORE any signed PIQ call.

Recovery needs no extra RMR state: PIQ owns the unique external-workspace ledger;
RMR's existing unique mapping is the local commit record. Never import profiles.
"""
import hashlib
import hmac
import secrets
import time

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..models import Tenant
from ..services import audit
from . import service
from .capabilities import capabilities_for
from .contracts import WorkspaceRequest, WorkspaceResponse
from .models import ProspectiqClientMapping as Mapping

WORKSPACE_PATH = "/api/integrations/rmr/v1/workspaces/resolve"


def mapping_for(db, tenant_id, cfg):
    return db.scalar(select(Mapping).where(Mapping.tenant_id == tenant_id,
                     Mapping.integration_instance_id == cfg.instance))


def require_provision_authority(db, user, tenant_id):
    managed = service.authorized_tenant(db, user, tenant_id)
    if "profiles.create" not in capabilities_for(user, tenant_id, managed):
        raise HTTPException(403, "ProspectIQ workspace preparation requires operational access")


def ready(row):
    if row.status != "active":
        raise HTTPException(409, "Existing ProspectIQ mapping requires administrator review")
    return {"version": "1", "status": "ready", "mapping_id": row.id}


def resolve_remote(cfg, tenant, transport=None):
    # Only server-read display metadata is signed. Browser cannot supply client IDs,
    # destination URLs, issuer, instance, display name, or service credentials.
    body = WorkspaceRequest(rmr_tenant_id=tenant.id, tenant_name=tenant.name).model_dump_json().encode()
    stamp, nonce = str(int(time.time())), secrets.token_hex(32)
    canonical = "\n".join([cfg.instance, cfg.hmac_key_id, "POST", WORKSPACE_PATH,
                            stamp, nonce, hashlib.sha256(body).hexdigest()])
    headers = {"Content-Type": "application/json", "X-Bridge-Instance": cfg.instance,
               "X-Bridge-Key": cfg.hmac_key_id, "X-Bridge-Timestamp": stamp, "X-Bridge-Nonce": nonce,
               "X-Bridge-Signature": hmac.new(cfg.hmac_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()}
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False, transport=transport) as client:
            with client.stream("POST", cfg.piq_origin + WORKSPACE_PATH, content=body, headers=headers) as response:
                if response.status_code != 200:
                    raise ValueError()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 32768:
                        raise ValueError()
        result = WorkspaceResponse.model_validate_json(bytes(raw))
        if (result.issuer != cfg.issuer or result.integration_instance_id != cfg.instance
                or str(result.rmr_tenant_id) != tenant.id):
            raise ValueError()
        return str(result.piq_client_id)
    except Exception:
        raise HTTPException(503, "ProspectIQ preparation unavailable. Retry shortly; contact your administrator if it persists.") from None


def provision(db, user, tenant_id, request, cfg, transport=None):
    service.browser_origin(request, cfg)
    require_provision_authority(db, user, tenant_id)
    row = mapping_for(db, tenant_id, cfg)
    if row:
        return ready(row)  # Preserve reviewed/manual mappings WITHOUT contacting PIQ.
    tenant = db.get(Tenant, tenant_id)
    client_id = resolve_remote(cfg, tenant, transport)
    # Do not hold DB write locks across a network operation. Re-read authority and
    # canonical state in a fresh transaction after remote success.
    db.rollback()
    try:
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        else:
            db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        db.refresh(user)
        require_provision_authority(db, user, tenant_id)
        row = mapping_for(db, tenant_id, cfg)
        if row:
            result = ready(row)
            if row.piq_client_id != client_id:
                raise HTTPException(409, "ProspectIQ mapping conflict requires administrator review")
        else:
            row = Mapping(tenant_id=tenant_id, piq_client_id=client_id, integration_instance_id=cfg.instance,
                          status="active", mapping_version=1, created_by_user_id=user.id)
            db.add(row)
            db.flush()
            audit(db, user, "prospectiq.workspace.provisioned", tenant_id=tenant_id,
                  entity_type="prospectiq_client_mapping", entity_id=row.id,
                  data={"integration_instance_id": cfg.instance, "policy": "authorized_first_use"})
            result = ready(row)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(409, "ProspectIQ mapping could not be completed. Retry or contact your administrator.") from None
