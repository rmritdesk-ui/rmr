"""Owner-only, read-through PIQ Adaptive Research cost reporting."""
import json
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from ..models import Tenant
from .models import ProspectiqClientMapping as Mapping
from .partner import partner_headers

REPORT_PATH = "/api/integrations/rmr/v1/adaptive-research/usage"


def owner_only(user):
    if user.global_role != "RMR_OWNER":
        raise HTTPException(403, "RMR Owner access required")


def report(db, cfg, *, tenant_id=None, run_id=None, from_date=None, to_date=None, transport=None):
    if run_id and not tenant_id:
        raise HTTPException(422, "Client required for run detail")
    if tenant_id:
        UUID(tenant_id)
    if run_id:
        UUID(run_id)
    query = select(Mapping, Tenant.name).join(Tenant, Tenant.id == Mapping.tenant_id).where(
        Mapping.integration_instance_id == cfg.instance, Mapping.status == "active")
    if tenant_id:
        query = query.where(Mapping.tenant_id == tenant_id)
    mapped = db.execute(query).all()
    if tenant_id and not mapped:
        raise HTTPException(404, "Mapped client not found")
    if len(mapped) > 500:
        raise HTTPException(413, "Too many mapped clients for one report")
    payload = {"tenants": [{"tenant_id": row.tenant_id, "client_id": row.piq_client_id} for row, _ in mapped],
               "tenant_id": tenant_id, "run_id": run_id, "from": from_date, "to": to_date}
    body = json.dumps(payload, separators=(",", ":")).encode()
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False, transport=transport) as client:
            with client.stream("POST", cfg.piq_origin + REPORT_PATH, content=body,
                               headers=partner_headers(cfg, REPORT_PATH, body)) as response:
                if response.status_code != 200:
                    raise ValueError("PIQ report unavailable")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 10_000_000:
                        raise ValueError("PIQ report too large")
        data = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Adaptive Research cost report is temporarily unavailable") from None
    names = {row.tenant_id: name for row, name in mapped}
    if "clients" in data:
        data["clients"] = [{**client, "client_name": names[client["tenant_id"]]}
                           for client in data["clients"] if client.get("tenant_id") in names]
    return data
