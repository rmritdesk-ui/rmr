"""Dedicated service-only CRM receiver. No providers or CRM conversion."""
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import settings
from ..models import Lead, User, utcnow
from ..permissions import require_client_operational_write
from ..services import audit
from .config import bridge_config
from .keys import verification_keys
from .models import (
    ProspectiqClientMapping as Mapping, ProspectiqAuthorizationGrant as Grant,
    ProspectiqCrmReceipt as Receipt, ProspectiqCrmEvent as Event,
    ProspectiqReplayNonce as Replay,
)
from . import service

PATH = "/api/integrations/prospectiq/v1/crm/leads"
SERVICE = "piq-crm"
MAX_BODY = 262144


@dataclass(frozen=True)
class CrmConfig:
    bridge: object
    keys: dict = field(repr=False)


def crm_config():
    cfg = bridge_config()  # Existing disabled flag and registered instance/origins.
    try:
        keys = verification_keys(os.getenv("RMR_PROSPECTIQ_CRM_KEYS_JSON", "{}"),
                                 forbidden=(settings.secret_key, *(cfg.hmac_keys or {cfg.hmac_key_id: cfg.hmac_secret}).values()))
        return CrmConfig(cfg, keys)
    except (ValueError, TypeError):
        raise HTTPException(503, {"code": "crm_configuration_unavailable"}) from None


def deny(code, status=403):
    raise HTTPException(status, {"code": code})


def authenticate(db, headers, body, method, path, cfg):
    """Consume a valid nonce separately, including when a later payload is rejected."""
    stamp = headers.get("X-Bridge-Timestamp", "")
    nonce = headers.get("X-Bridge-Nonce", "")
    key = headers.get("X-Bridge-Key", "")
    try:
        timestamp = int(stamp)
        lookup = method == "GET" and re.fullmatch(r"/api/integrations/prospectiq/v1/crm/handoffs/[a-fA-F0-9-]{36}", path.split("?")[0])
        if (not ((method == "POST" and path == PATH) or lookup) or len(body) > MAX_BODY
                or headers.get("X-Bridge-Service") != SERVICE
                or headers.get("X-Bridge-Instance") != cfg.bridge.instance
                or key not in cfg.keys or str(timestamp) != stamp
                or abs(time.time() - timestamp) > 30
                or not re.fullmatch(r"[a-f0-9]{64}", nonce)):
            raise ValueError()
        canonical = "\n".join([SERVICE, cfg.bridge.instance, key, method, path, stamp, nonce,
                              hashlib.sha256(body).hexdigest()])
        expected = hmac.new(cfg.keys[key].encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, headers.get("X-Bridge-Signature", "")):
            raise ValueError()
    except (ValueError, TypeError):
        deny("invalid_crm_authentication", 401)
    db.add(Replay(integration_instance_id=cfg.bridge.instance, service_identity=SERVICE, key_id=key,
                  nonce_hash=service.digest(nonce),
                  request_timestamp=datetime.fromtimestamp(timestamp, timezone.utc),
                  expires_at=utcnow() + timedelta(minutes=2)))
    db.info["bridge_key_id"] = key
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        deny("crm_request_replayed", 409)


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _insert(db, model, values):
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    return db.scalar(insert(model).values(**values).on_conflict_do_nothing().returning(model.id)) is not None


def receive(db, payload, cfg):
    bridge = cfg.bridge
    # Canonical destination: never accept an RMR tenant or actor in the wire schema.
    mapping = db.scalar(select(Mapping).where(
        Mapping.integration_instance_id == bridge.instance,
        Mapping.piq_client_id == str(payload.piq_client_id)).with_for_update(read=True))
    if (payload.integration_instance_id != bridge.instance or not mapping
            or mapping.status != "active" or mapping.id != str(payload.mapping_id)
            or mapping.mapping_version != payload.mapping_version):
        deny("crm_mapping_unavailable")
    grant = db.get(Grant, str(payload.actor_grant_id))
    try:
        actor = service.check_grant(db, grant, bridge)
        if (grant.status != "consumed" or grant.mapping_id != mapping.id
                or grant.piq_client_id != mapping.piq_client_id
                or grant.tenant_id != mapping.tenant_id
                or "crm.move_to_rmr" not in grant.capabilities_json):
            raise ValueError()
        require_client_operational_write(actor, mapping.tenant_id)
    except (HTTPException, ValueError):
        deny("crm_actor_not_authorized")
    p = payload.prospect
    if not p.company_name.strip():
        deny("crm_invalid_prospect", 422)
    if p.email and (not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", p.email)
                    or not any(p.email.casefold() in e.claim.casefold()
                               and "google" not in e.provider.casefold() for e in p.email_provenance)):
        deny("crm_email_provenance_required", 422)

    digest = payload_hash(payload)
    public_id, event_id = str(payload.prospect_public_id), str(payload.integration_event_id)
    new_receipt_id = str(uuid4())
    try:
        created = _insert(db, Receipt, dict(
            id=new_receipt_id, integration_instance_id=bridge.instance, mapping_id=mapping.id,
            piq_client_id=mapping.piq_client_id, prospect_public_id=public_id,
            integration_event_id=event_id, tenant_id=mapping.tenant_id,
            actor_user_id=actor.id, status="pending", payload_hash=digest,
            provenance_json={"import": payload.model_dump(mode="json"), "grant_id": grant.id,
                             "verification": "Imported PIQ assertions; not independently verified by RMR"}))
        row = db.scalar(select(Receipt).where(
            Receipt.integration_instance_id == bridge.instance,
            Receipt.prospect_public_id == public_id).with_for_update().execution_options(populate_existing=True))
        if (not row or row.mapping_id != mapping.id or row.piq_client_id != mapping.piq_client_id
                or row.tenant_id != mapping.tenant_id):
            deny("crm_identity_conflict", 409)
        if row.integration_event_id == event_id and row.payload_hash != digest:
            deny("crm_event_conflict", 409)
        _insert(db, Event, dict(id=str(uuid4()), integration_instance_id=bridge.instance,
                               integration_event_id=event_id, receipt_id=row.id, payload_hash=digest))
        event = db.scalar(select(Event).where(Event.integration_instance_id == bridge.instance,
                                              Event.integration_event_id == event_id))
        if not event or event.receipt_id != row.id or event.payload_hash != digest:
            deny("crm_event_conflict", 409)
        if created:
            notes = ["Imported from standalone ProspectIQ. PIQ intelligence is not RMR verification."]
            for label, value in [("Website", p.website), ("Address", p.address), ("Industry", p.industry),
                                 ("PIQ profile match score", p.piq_score)]:
                if value is not None:
                    notes.append(f"{label}: {value}")
            lead = Lead(tenant_id=mapping.tenant_id, company_name=p.company_name.strip(),
                        contact_name=(p.contact_name or "")[:160], email=p.email or "",
                        phone=(p.phone or "")[:80], source="ProspectIQ", status="New",
                        notes="\n".join(notes), assigned_user_id=actor.id)
            db.add(lead)
            db.flush()
            row.lead_id, row.status = lead.id, "accepted"
        else:
            lead = db.get(Lead, row.lead_id) if row.lead_id else None
            if row.status == "tombstoned" or (row.status == "accepted" and not lead):
                row.status = "tombstoned"
                db.commit()
                deny("crm_lead_unavailable", 410)
            if row.status != "accepted" or not lead or lead.tenant_id != mapping.tenant_id:
                deny("crm_receipt_unavailable", 409)
        result = "created" if created else "already_exists"
        audit(db, actor, "prospectiq.crm." + result, tenant_id=mapping.tenant_id,
              entity_type="lead", entity_id=lead.id, data={
                  "integration_service": "ProspectIQ", "integration_instance_id": bridge.instance,
                  "service_key_id": db.info.get("bridge_key_id"),
                  "piq_client_id": mapping.piq_client_id, "mapping_id": mapping.id,
                  "mapping_version": mapping.mapping_version, "grant_id": grant.id,
                  "prospect_public_id": public_id, "integration_event_id": event_id,
                  "rmr_lead_id": lead.id, "payload_hash": digest, "result": result})
        db.commit()
        return (201 if created else 200), {
            "version": "1", "receipt_id": row.id, "prospect_public_id": public_id,
            "status": result, "rmr_lead_id": lead.id, "integration_event_id": event_id,
            "crm_url": f"{bridge.rmr_origin}/#/crm?tenant={mapping.tenant_id}&lead={lead.id}",
            "crm_path": None}
    except Exception:
        db.rollback()
        raise
