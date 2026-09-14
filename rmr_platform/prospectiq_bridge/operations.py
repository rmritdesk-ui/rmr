"""Local bridge readiness/maintenance and signed receipt-only reconciliation."""
import hashlib
import logging
from datetime import timedelta
from sqlalchemy import select, delete, update, func, text
from fastapi import HTTPException
from ..config import settings
from ..models import Lead, utcnow
from ..services import audit
from .models import ProspectiqAuthorizationGrant as Grant, ProspectiqReplayNonce as Replay
from .models import ProspectiqClientMapping as Mapping, ProspectiqCrmReceipt as Receipt, ProspectiqCrmEvent as Event
from .config import bridge_config
from .crm import crm_config


def validate_startup():
    if settings.prospectiq_bridge_enabled:
        try:
            bridge_config()
            crm_config()
        except Exception as error:
            category = getattr(error, 'bridge_category', 'configuration_unavailable')
            logging.getLogger(__name__).error('prospectiq.configuration.failed category=%s', category)
            raise RuntimeError("Enabled ProspectIQ bridge configuration is unsafe or incomplete: " + category) from None


def readiness(db):
    result={"enabled":settings.prospectiq_bridge_enabled,"configuration":False,"federation_signing":False,
            "service_hmac":False,"grant_hmac":False,"crm_hmac":False,"database":False,"mapping_subsystem":False}
    if not result["enabled"]:
        return {**result,"status":"disabled"}
    failures=[]
    try:
        bridge_config()
        result["federation_signing"]=True
        result['grant_hmac']=True
        crm_config()
        result['crm_hmac']=True
        result["service_hmac"]=True
        result["configuration"]=True
    except Exception as error:
        failures.append(getattr(error,'bridge_category','configuration_unavailable'))
    try:
        db.execute(text("SELECT 1"))
        result["database"]=True
    except Exception:
        db.rollback();failures.append('database_unavailable')
    try:
        db.scalar(select(Mapping.id).limit(1))
        result["mapping_subsystem"]=True
    except Exception:
        db.rollback();failures.append('mapping_subsystem_unavailable')
    return {**result,"failure_categories":failures,"status":"not_ready" if failures else "ready"}


def cleanup(db, now=None):
    now=now or utcnow()
    nonces=db.execute(delete(Replay).where(Replay.expires_at<=now)).rowcount
    pending=db.execute(delete(Grant).where(Grant.status=="pending",Grant.code_expires_at<now-timedelta(days=1))).rowcount
    # Keep attribution/tombstones for consumed grants; destroy obsolete launch verifiers.
    rows=list(db.scalars(select(Grant).where(Grant.absolute_expires_at<now-timedelta(days=30))))
    for row in rows:
        row.status="expired"
        row.code_hash=hashlib.sha256(("retired:"+row.id).encode()).hexdigest()
        row.pkce_challenge=""
        row.browser_session_hash=row.state_hash=row.nonce_hash=None
    db.commit()
    return {"nonces_deleted":nonces,"expired_pending_grants_deleted":pending,"expired_grants_compacted":len(rows),
            "crm_receipts_deleted":0,"crm_events_deleted":0}


def lookup_receipt(db, public_id, payload, cfg):
    # Authenticated service lookup discloses only existing identity, never payload/contact data.
    # It cannot create a Lead or restore authority. Expired original grants may reconcile acceptance.
    mapping=db.get(Mapping,str(payload.mapping_id))
    if (not mapping or mapping.integration_instance_id!=cfg.bridge.instance or
        payload.integration_instance_id!=cfg.bridge.instance or mapping.piq_client_id!=str(payload.piq_client_id)
        or mapping.mapping_version!=payload.mapping_version or mapping.status!="active"):
        raise HTTPException(403,{"code":"crm_mapping_unavailable"})
    row=db.scalar(select(Receipt).where(Receipt.integration_instance_id==cfg.bridge.instance,
        Receipt.prospect_public_id==str(public_id)).with_for_update())
    event=db.scalar(select(Event).where(Event.integration_instance_id==cfg.bridge.instance,
        Event.integration_event_id==str(payload.integration_event_id)))
    result={"version":"1","status":"not_found","prospect_public_id":str(public_id),
        "integration_event_id":str(payload.integration_event_id),"rmr_lead_id":None,"crm_url":None}
    if event and (not row or event.receipt_id!=row.id or event.payload_hash!=payload.payload_hash):
        result["status"]="conflict"
    elif row:
        original=row.provenance_json.get("import",{})
        if (row.mapping_id!=mapping.id or row.piq_client_id!=mapping.piq_client_id or
            row.tenant_id!=mapping.tenant_id or original.get("actor_grant_id")!=str(payload.actor_grant_id) or
            row.payload_hash!=payload.payload_hash or row.integration_event_id!=str(payload.integration_event_id)):
            result["status"]="conflict"
        else:
            lead=db.get(Lead,row.lead_id) if row.lead_id else None
            if row.status=="tombstoned" or (row.status=="accepted" and not lead):
                row.status="tombstoned";result["status"]="tombstoned"
            elif row.status=="accepted" and lead and lead.tenant_id==mapping.tenant_id:
                result.update(status="accepted",rmr_lead_id=lead.id,
                    crm_url=f"{cfg.bridge.rmr_origin}/#/crm?tenant={mapping.tenant_id}&lead={lead.id}")
            else: result["status"]="conflict"
    audit(db,None,"prospectiq.crm.reconciled",tenant_id=mapping.tenant_id,entity_type="integration",
        entity_id=str(public_id),data={"integration_service":"ProspectIQ","service_key_id":db.info.get("bridge_key_id"),
        "integration_instance_id":cfg.bridge.instance,"mapping_id":mapping.id,
        "integration_event_id":str(payload.integration_event_id),"result":result["status"]})
    db.commit()
    return result
