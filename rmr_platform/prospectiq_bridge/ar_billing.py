"""RMR-owned, tenant-bound one-time purchases for ProspectIQ research."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from stripe import StripeError

from ..models import BillingOperation, TenantService
from ..config import settings
from ..routes.billing import _lock_tenant, _stripe_client, _stripe_mode, _log_stripe_error, _profile
from .models import ProspectiqAuthorizationGrant as Grant
from . import service


class ResearchPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID
    mapping_id: UUID
    mapping_version: int = Field(ge=1)
    rmr_tenant_id: UUID
    rmr_user_id: UUID
    piq_client_id: UUID
    piq_user_id: UUID
    target_profile_id: UUID | None = None
    lead_ids: list[UUID] = Field(min_length=1, max_length=100)
    operation_id: UUID | None = None
    previous_operation_id: UUID | None = None
    piq_run_id: UUID | None = None
    approved: StrictBool = False
    approved_quote_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class PostRunFreeze(ResearchPurchase):
    confirmation_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    estimate_min_cents_per_record: int = Field(ge=0)
    estimate_max_cents_per_record: int = Field(ge=0)


class PostRunLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    piq_run_id: UUID
    rmr_tenant_id: UUID
    piq_client_id: UUID


class PostRunSettlement(PostRunLink):
    run_status: Literal["completed", "partial", "failed"]
    actual_provider_cost_usd: Decimal | None = Field(default=None, ge=0)


def _context(db, payload, cfg):
    grant = db.get(Grant, str(payload.grant_id))
    if not grant or grant.status != "consumed":
        raise HTTPException(403, "Active RMR bridge grant required")
    service.check_grant(db, grant, cfg)
    if (grant.id != str(payload.grant_id)
            or grant.mapping_id != str(payload.mapping_id)
            or grant.mapping_version != payload.mapping_version
            or grant.tenant_id != str(payload.rmr_tenant_id)
            or grant.user_id != str(payload.rmr_user_id)
            or grant.piq_client_id != str(payload.piq_client_id)
            or grant.integration_instance_id != cfg.instance
            or not {"research.run", "research.confirm_cost"}.issubset(grant.capabilities_json)):
        raise HTTPException(403, "Research purchase context unavailable")
    if len(set(payload.lead_ids)) != len(payload.lead_ids):
        raise HTTPException(422, "Duplicate lead selection")
    return grant


def _selection(payload):
    return {
        "instance": str(payload.mapping_id),
        "mapping_version": payload.mapping_version,
        "rmr_tenant_id": str(payload.rmr_tenant_id),
        "rmr_user_id": str(payload.rmr_user_id),
        "piq_client_id": str(payload.piq_client_id),
        "piq_user_id": str(payload.piq_user_id),
        "target_profile_id": str(payload.target_profile_id) if payload.target_profile_id else None,
        "lead_ids": sorted(str(value) for value in payload.lead_ids),
    }


def _fingerprint(payload):
    raw = json.dumps(_selection(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _present(op):
    data, result = op.request_data, op.result_data or {}
    return {
        "operation_id": op.id,
        "quote_hash": _quote_hash(op),
        "status": result.get("status", "quoted"),
        "record_count": data["record_count"],
        "unit_price_cents": data["unit_price_cents"],
        "total_cents": data["total_cents"],
        "currency": data["currency"],
        "payable": data["total_cents"] >= 50,
        "expires_at": data["expires_at"],
        "payment_intent_id": result.get("payment_intent_id"),
        "piq_run_id": result.get("piq_run_id"),
    }


def _quote_hash(op):
    data=op.request_data
    frozen={"operation_id":op.id,"selection":data["selection"],
            "record_count":data["record_count"],"unit_price_cents":data["unit_price_cents"],
            "total_cents":data["total_cents"],"currency":data["currency"]}
    return hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(",", ":")).encode()).hexdigest()


def quote(db, payload, cfg):
    if settings.ar_billing_mode == "track_only":
        raise HTTPException(403, "Adaptive Research purchases are disabled")
    mode = _stripe_mode()
    if mode == "live":
        raise HTTPException(403, "Legacy prepayment is not enabled for live research billing")
    if not mode:
        raise HTTPException(503, "RMR Stripe billing unavailable")
    _lock_tenant(db, str(payload.rmr_tenant_id))
    _context(db, payload, cfg)
    assignment = db.scalar(select(TenantService).where(
        TenantService.tenant_id == str(payload.rmr_tenant_id),
        TenantService.service_code == "piq_enhancement",
        TenantService.status == "active",
        TenantService.cadence == "usage",
    ))
    rate = int(assignment.usage_price_cents or 0) if assignment else 0
    if rate <= 0:
        raise HTTPException(403, "Tenant enhancement rate is not configured")
    key = "ar:" + _fingerprint(payload)
    prior = db.scalar(select(BillingOperation).where(BillingOperation.active_slot == key))
    if prior:
        expires = datetime.fromisoformat(prior.request_data["expires_at"])
        if (prior.tenant_id != str(payload.rmr_tenant_id) or prior.kind != "piq_ar" or prior.mode != mode
                or prior.request_data.get("selection") != _selection(payload)):
            raise HTTPException(409, "Purchase selection conflict")
        if (prior.result_data or {}).get("status") == "succeeded":
            if (str(payload.previous_operation_id) == prior.id
                    and (prior.result_data or {}).get("piq_run_id")):
                # An explicitly requested later research cycle gets a fresh
                # frozen quote. A retry of the old quote still reuses it.
                prior.active_slot = None
                db.flush()
            else:
                return _present(prior)
        elif (prior.result_data or {}).get("status") == "payment_attempted" or expires > datetime.now(timezone.utc):
            return _present(prior)
        # Only an unpaid expired quote may be replaced; uncertain payments stay locked.
        if prior.active_slot and prior.result_data and prior.result_data.get("payment_intent_id"):
            raise HTTPException(409, "Purchase requires payment reconciliation")
        prior.active_slot = None
        db.flush()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    op = BillingOperation(
        tenant_id=str(payload.rmr_tenant_id), kind="piq_ar", mode=mode, active_slot=key,
        request_data={
            "selection": _selection(payload), "record_count": len(payload.lead_ids),
            "unit_price_cents": rate, "total_cents": rate * len(payload.lead_ids),
            "currency": "usd", "expires_at": expires.isoformat(),
        },
    )
    db.add(op)
    db.commit()
    return _present(op)


def _operation(db, payload, cfg):
    if not payload.operation_id:
        raise HTTPException(422, "Purchase operation required")
    _lock_tenant(db, str(payload.rmr_tenant_id))
    _context(db, payload, cfg)
    op = db.get(BillingOperation, str(payload.operation_id))
    if (not op or op.kind != "piq_ar" or op.tenant_id != str(payload.rmr_tenant_id)
            or op.mode != _stripe_mode() or op.request_data.get("selection") != _selection(payload)):
        raise HTTPException(403, "Purchase operation does not match this tenant and selection")
    return op


def charge(db, payload, cfg):
    if settings.ar_billing_mode == "track_only":
        raise HTTPException(403, "Adaptive Research purchases are disabled")
    if _stripe_mode() == "live":
        raise HTTPException(403, "Legacy prepayment is not enabled for live research billing")
    op = _operation(db, payload, cfg)
    if not payload.approved or not payload.approved_quote_hash or not hmac.compare_digest(
            payload.approved_quote_hash, _quote_hash(op)):
        raise HTTPException(403, "Explicit approval of the frozen customer charge is required")
    if (op.result_data or {}).get("status") == "succeeded":
        return _present(op)
    if op.result_data and op.result_data.get("payment_intent_id"):
        return _present(op)  # Incomplete payment cannot trigger research.
    now = datetime.now(timezone.utc)
    attempted = (op.result_data or {}).get("status") == "payment_attempted"
    if not attempted and datetime.fromisoformat(op.request_data["expires_at"]) <= now:
        raise HTTPException(409, "Purchase quote expired")
    if op.request_data["total_cents"] < 50:
        raise HTTPException(409, "Stripe requires at least USD 0.50 for a one-time card payment")
    created = op.created_at.replace(tzinfo=timezone.utc) if op.created_at.tzinfo is None else op.created_at
    if now - created >= timedelta(hours=23):
        raise HTTPException(409, "Purchase requires payment reconciliation")
    if not attempted:
        profile = _profile(db, op.tenant_id)
        if (not profile or profile.setup_status != "ready" or not profile.stripe_customer_id
                or not profile.default_payment_method_id):
            raise HTTPException(409, "RMR tenant has no ready saved payment method")
        frozen = {**op.request_data, "payment_customer_id": profile.stripe_customer_id,
                  "payment_method_id": profile.default_payment_method_id}
        op.request_data = frozen
        op.result_data = {"status": "payment_attempted"}
        db.commit()  # Durable before the external call; an uncertain response keeps this operation locked.
    else:
        frozen = op.request_data
    try:
        intent = _stripe_client().v1.payment_intents.create({
            "amount": frozen["total_cents"], "currency": frozen["currency"],
            "customer": frozen["payment_customer_id"],
            "payment_method": frozen["payment_method_id"],
            "off_session": True, "confirm": True,
            "metadata": {"purpose": "rmr_piq_adaptive_research", "tenant_id": op.tenant_id,
                         "billing_operation_id": op.id},
        }, options={"idempotency_key": f"rmr-piq-ar-{op.id}"})
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, "piq_ar")
        raise HTTPException(502, "RMR could not complete the research payment; retry this purchase") from exc
    _lock_tenant(db, str(payload.rmr_tenant_id))
    op = db.get(BillingOperation, str(payload.operation_id))
    op.result_data = {"status": intent.status, "payment_intent_id": intent.id}
    db.commit()
    return _present(op)


def link_run(db, payload, cfg):
    op = _operation(db, payload, cfg)
    if not payload.piq_run_id or (op.result_data or {}).get("status") != "succeeded":
        raise HTTPException(409, "Successful payment and research run required")
    result = dict(op.result_data)
    if result.get("piq_run_id") and result["piq_run_id"] != str(payload.piq_run_id):
        raise HTTPException(409, "Purchase already bound to another research run")
    result["piq_run_id"] = str(payload.piq_run_id)
    op.result_data = result
    db.commit()
    return _present(op)


def _post_run_present(op):
    data, result = op.request_data, op.result_data or {}
    return {
        "operation_id": op.id, "status": result.get("status", "awaiting_research"),
        "piq_run_id": result.get("piq_run_id"), "record_count": data["record_count"],
        "unit_price_cents": data["unit_price_cents"],
        "enhancement_fee_cents": data["enhancement_fee_cents"],
        "estimate_min_cents_per_record": data["estimate_min_cents_per_record"],
        "estimate_max_cents_per_record": data["estimate_max_cents_per_record"],
        "actual_provider_cost_usd": result.get("actual_provider_cost_usd"),
        "final_amount_cents": result.get("final_amount_cents"),
        "payment_intent_id": result.get("payment_intent_id"), "currency": "usd",
    }


def freeze_post_run(db, payload: PostRunFreeze, cfg):
    """Freeze RMR commercial terms before PIQ queues research; never charge here."""
    mode = _stripe_mode()
    if settings.ar_billing_mode != "post_run" or mode not in {"test", "live"}:
        raise HTTPException(403, "Post-run research billing is not enabled")
    if payload.estimate_min_cents_per_record > payload.estimate_max_cents_per_record:
        raise HTTPException(422, "Invalid research estimate range")
    _lock_tenant(db, str(payload.rmr_tenant_id))
    _context(db, payload, cfg)
    slot = "arpost:" + payload.confirmation_hash
    prior = db.scalar(select(BillingOperation).where(BillingOperation.active_slot == slot))
    selection = _selection(payload)
    if prior:
        if (prior.kind != "piq_ar_post_run" or prior.mode != mode
                or prior.tenant_id != str(payload.rmr_tenant_id)
                or prior.request_data.get("selection") != selection
                or prior.request_data.get("estimate_min_cents_per_record") != payload.estimate_min_cents_per_record
                or prior.request_data.get("estimate_max_cents_per_record") != payload.estimate_max_cents_per_record):
            raise HTTPException(409, "Research confirmation conflicts with frozen terms")
        return _post_run_present(prior)
    assignment = db.scalar(select(TenantService).where(
        TenantService.tenant_id == str(payload.rmr_tenant_id),
        TenantService.service_code == "piq_enhancement",
        TenantService.status == "active", TenantService.cadence == "usage",
    ))
    rate = int(assignment.usage_price_cents or 0) if assignment else 0
    if rate <= 0:
        raise HTTPException(403, "Tenant enhancement rate is not configured")
    op = BillingOperation(tenant_id=str(payload.rmr_tenant_id), kind="piq_ar_post_run",
        mode=mode, active_slot=slot,
        request_data={"selection": selection, "record_count": len(payload.lead_ids),
            "unit_price_cents": rate, "enhancement_fee_cents": rate * len(payload.lead_ids),
            "estimate_min_cents_per_record": payload.estimate_min_cents_per_record,
            "estimate_max_cents_per_record": payload.estimate_max_cents_per_record,
            "confirmation_hash": payload.confirmation_hash,
            "confirmed_at": datetime.now(timezone.utc).isoformat(), "currency": "usd"},
        result_data={"status": "awaiting_research"})
    db.add(op)
    db.commit()
    return _post_run_present(op)


def _post_run_operation(db, payload: PostRunLink):
    _lock_tenant(db, str(payload.rmr_tenant_id))
    op = db.get(BillingOperation, str(payload.operation_id))
    if (not op or op.kind != "piq_ar_post_run" or op.mode != _stripe_mode()
            or op.tenant_id != str(payload.rmr_tenant_id)
            or op.request_data.get("selection", {}).get("piq_client_id") != str(payload.piq_client_id)):
        raise HTTPException(403, "Research settlement tenant or operation mismatch")
    prior_run = (op.result_data or {}).get("piq_run_id")
    if prior_run and prior_run != str(payload.piq_run_id):
        raise HTTPException(409, "Research settlement already bound to another run")
    return op


def link_post_run(db, payload: PostRunLink):
    if settings.ar_billing_mode != "post_run" or _stripe_mode() not in {"test", "live"}:
        raise HTTPException(403, "Post-run research settlement is not enabled")
    op = _post_run_operation(db, payload)
    result = dict(op.result_data or {})
    result["piq_run_id"] = str(payload.piq_run_id)
    result["run_linked_at"] = result.get("run_linked_at") or datetime.now(timezone.utc).isoformat()
    op.result_data = result
    db.commit()
    return _post_run_present(op)


def _freeze_post_run_amount(op, actual: Decimal):
    if not actual.is_finite() or actual < 0:
        raise HTTPException(422, "Invalid provider cost")
    result = dict(op.result_data or {})
    exact = str(actual)
    if (result.get("actual_provider_cost_usd") is not None
            and Decimal(result["actual_provider_cost_usd"]) != actual):
        raise HTTPException(409, "Recorded provider cost changed after settlement")
    provider_cents = int((actual * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = op.request_data["enhancement_fee_cents"] + provider_cents
    if result.get("final_amount_cents") not in (None, total):
        raise HTTPException(409, "Frozen settlement amount changed")
    result.update(actual_provider_cost_usd=exact, provider_cost_cents=provider_cents,
                  final_amount_cents=total, amount_frozen_at=result.get("amount_frozen_at")
                  or datetime.now(timezone.utc).isoformat())
    op.result_data = result
    return result


def _stripe_value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _sync_post_run_intent(db, op, intent):
    result = dict(op.result_data or {})
    frozen = op.request_data
    metadata = _stripe_value(intent, "metadata") or {}
    if (_stripe_value(intent, "customer") != frozen.get("payment_customer_id")
            or _stripe_value(intent, "amount") != result.get("final_amount_cents")
            or _stripe_value(intent, "currency") != "usd"
            or _stripe_value(intent, "livemode") is not (op.mode == "live")
            or _stripe_value(metadata, "billing_operation_id") != op.id
            or _stripe_value(metadata, "tenant_id") != op.tenant_id
            or _stripe_value(metadata, "piq_run_id") != result.get("piq_run_id")):
        raise HTTPException(409, "Stripe research settlement ownership mismatch")
    intent_id = _stripe_value(intent, "id")
    if result.get("payment_intent_id") not in (None, intent_id):
        raise HTTPException(409, "Research settlement PaymentIntent mismatch")
    status = _stripe_value(intent, "status")
    now = datetime.now(timezone.utc).isoformat()
    result.update(payment_intent_id=intent_id,
                  status="paid" if status == "succeeded" else
                  "payment_failed" if status in {"requires_payment_method", "canceled", "requires_action"}
                  else "payment_pending",
                  stripe_status=status, reconciled_at=now)
    if status == "succeeded":
        result["paid_at"] = result.get("paid_at") or now
    elif status in {"requires_payment_method", "canceled", "requires_action"}:
        result["payment_failed_at"] = result.get("payment_failed_at") or now
    op.result_data = result
    db.commit()
    return _post_run_present(op)


def _pay_post_run(db, op):
    result = dict(op.result_data or {})
    if result.get("status") in {"paid", "payment_failed", "below_minimum", "reconciliation_required"}:
        return _post_run_present(op)
    if result.get("payment_intent_id"):
        try:
            intent = _stripe_client().v1.payment_intents.retrieve(result["payment_intent_id"])
            return _sync_post_run_intent(db, op, intent)
        except StripeError as exc:
            _log_stripe_error(exc, "piq_ar_post_run_reconcile")
            raise HTTPException(502, "Research payment reconciliation unavailable") from exc
    if result.get("status") == "payment_attempted":
        attempted = datetime.fromisoformat(result["payment_attempted_at"])
        if datetime.now(timezone.utc) - attempted >= timedelta(hours=23):
            result["status"] = "reconciliation_required"
            op.result_data = result
            db.commit()
            return _post_run_present(op)
    else:
        profile = _profile(db, op.tenant_id)
        if (not profile or profile.setup_status != "ready" or not profile.stripe_customer_id
                or not profile.default_payment_method_id):
            result["status"] = "amount_due"
            op.result_data = result
            db.commit()
            return _post_run_present(op)
        op.request_data = {**op.request_data, "payment_customer_id": profile.stripe_customer_id,
                           "payment_method_id": profile.default_payment_method_id}
        result.update(status="payment_attempted", payment_attempted_at=datetime.now(timezone.utc).isoformat())
        op.result_data = result
        db.commit()  # Durable amount and consent precede the Stripe side effect.
    frozen = op.request_data
    try:
        intent = _stripe_client().v1.payment_intents.create({
            "amount": result["final_amount_cents"], "currency": "usd",
            "customer": frozen["payment_customer_id"],
            "payment_method": frozen["payment_method_id"],
            "off_session": True, "confirm": True,
            "metadata": {"purpose": "rmr_piq_adaptive_research_post_run",
                         "tenant_id": op.tenant_id, "billing_operation_id": op.id,
                         "piq_run_id": result["piq_run_id"]},
        }, options={"idempotency_key": f"rmr-piq-ar-post-{op.id}-{result.get('payment_attempt', 1)}"})
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, "piq_ar_post_run")
        error_intent = (_stripe_value(_stripe_value(exc, "error"), "payment_intent")
                        or _stripe_value(_stripe_value(_stripe_value(exc, "json_body"), "error"),
                                         "payment_intent"))
        error_intent_id = _stripe_value(error_intent, "id") if error_intent else None
        if error_intent_id:
            try:
                remote = _stripe_client().v1.payment_intents.retrieve(error_intent_id)
                _lock_tenant(db, op.tenant_id)
                return _sync_post_run_intent(db, db.get(BillingOperation, op.id), remote)
            except StripeError:
                db.rollback()  # Uncertain remote state stays locked to the same operation.
        raise HTTPException(502, "Research payment state requires reconciliation") from exc
    _lock_tenant(db, op.tenant_id)
    op = db.get(BillingOperation, op.id)
    return _sync_post_run_intent(db, op, intent)


def settle_post_run(db, payload: PostRunSettlement):
    if settings.ar_billing_mode != "post_run" or _stripe_mode() not in {"test", "live"}:
        raise HTTPException(403, "Post-run research settlement is not enabled")
    op = _post_run_operation(db, payload)
    result = dict(op.result_data or {})
    result["piq_run_id"] = str(payload.piq_run_id)
    if payload.run_status != "completed":
        if result.get("status") not in {"awaiting_research", "pending_cost", "no_auto_charge"}:
            raise HTTPException(409, "Research settlement already advanced")
        result.update(status="no_auto_charge", run_status=payload.run_status,
                      actual_provider_cost_usd=(str(payload.actual_provider_cost_usd)
                                                if payload.actual_provider_cost_usd is not None else None))
        op.result_data = result
        db.commit()
        return _post_run_present(op)
    if result.get("run_status") not in (None, "completed"):
        raise HTTPException(409, "Research terminal status changed")
    result["run_status"] = "completed"
    op.result_data = result
    if payload.actual_provider_cost_usd is None:
        if result.get("final_amount_cents") is None:
            result["status"] = "pending_cost"
            result["pending_cost_at"] = result.get("pending_cost_at") or datetime.now(timezone.utc).isoformat()
            op.result_data = result
            db.commit()
        return _post_run_present(op)
    result = _freeze_post_run_amount(op, payload.actual_provider_cost_usd)
    if result["final_amount_cents"] < 50:
        result["status"] = "below_minimum"
        op.result_data = result
        db.commit()
        return _post_run_present(op)
    db.commit()
    return _pay_post_run(db, op)


def retry_post_run(db, payload: PostRunSettlement):
    """Explicit retry only after the prior PaymentIntent is proven unsuccessful."""
    if settings.ar_billing_mode != "post_run" or _stripe_mode() not in {"test", "live"}:
        raise HTTPException(403, "Post-run research settlement is not enabled")
    op = _post_run_operation(db, payload)
    result = dict(op.result_data or {})
    if (result.get("piq_run_id") != str(payload.piq_run_id)
            or result.get("run_status") != "completed"
            or (payload.actual_provider_cost_usd is None or
                Decimal(result.get("actual_provider_cost_usd") or "-1") != payload.actual_provider_cost_usd)
            or result.get("final_amount_cents") is None
            or result.get("status") not in {"payment_failed", "amount_due"}):
        raise HTTPException(409, "Research settlement is not eligible for retry")
    prior_id = result.get("payment_intent_id")
    if prior_id:
        try:
            remote = _stripe_client().v1.payment_intents.retrieve(prior_id)
            _sync_post_run_intent(db, op, remote)
        except StripeError as exc:
            db.rollback()
            _log_stripe_error(exc, "piq_ar_post_run_retry_check")
            raise HTTPException(502, "Prior research payment could not be reconciled") from exc
        if (op.result_data or {}).get("status") != "payment_failed":
            return _post_run_present(op)
        result = dict(op.result_data)
        result["prior_payment_intent_ids"] = [
            *(result.get("prior_payment_intent_ids") or []), prior_id]
        result["payment_intent_id"] = None
        result["payment_attempt"] = int(result.get("payment_attempt", 1)) + 1
        op.request_data = {key:value for key,value in op.request_data.items()
                           if key not in {"payment_customer_id", "payment_method_id"}}
    result["status"] = "amount_due"
    op.result_data = result
    db.commit()
    return _pay_post_run(db, op)


def reconcile_post_run_webhook(db, obj):
    metadata = _stripe_value(obj, "metadata") or {}
    if _stripe_value(metadata, "purpose") != "rmr_piq_adaptive_research_post_run":
        return {"ok": True, "ignored": True}
    op_id = _stripe_value(metadata, "billing_operation_id")
    tenant_id = _stripe_value(metadata, "tenant_id")
    if not op_id or not tenant_id:
        return {"ok": True, "ignored": True}
    _lock_tenant(db, tenant_id)
    op = db.get(BillingOperation, op_id)
    if not op or op.tenant_id != tenant_id or op.kind != "piq_ar_post_run" or op.mode != _stripe_mode():
        return {"ok": True, "ignored": True}
    if _stripe_value(obj,"id") in ((op.result_data or {}).get("prior_payment_intent_ids") or []):
        return {"ok": True, "ignored": True}
    try:
        remote = _stripe_client().v1.payment_intents.retrieve(_stripe_value(obj, "id"))
        _sync_post_run_intent(db, op, remote)
        return {"ok": True}
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, "piq_ar_post_run_webhook")
        raise HTTPException(502, "Research payment reconciliation unavailable") from exc
