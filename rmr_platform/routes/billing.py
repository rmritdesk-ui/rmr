from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from stripe import StripeClient, StripeError, StripeObject, Webhook, SignatureVerificationError
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..db import get_db
from ..models import AuditEvent, BillingOperation, BillingSubscription, BillingServicePrice, Tenant, TenantBillingProfile, TenantLiveBillingProfile, User
from .. import billing_subscriptions as monthly
from ..permissions import is_global_admin, require_tenant_access
from ..security import current_user, require_request_origin
from ..services import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants/{tenant_id}/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/api/billing/stripe", tags=["billing"])


class SetupIntentComplete(BaseModel):
    setup_intent_id: str


class OperationRequest(BaseModel):
    operation_id: str


class PrepareOperation(BaseModel):
    previous_operation_id: str | None = None


class ActivateSubscription(OperationRequest):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool
    quote_hash: str


def _stripe_mode() -> str | None:
    if settings.payment_provider != "stripe":
        return None
    mode = settings.stripe_env
    if mode not in {"test", "live"} or not (
        settings.stripe_secret_key.startswith(f"sk_{mode}_")
        and settings.stripe_publishable_key.startswith(f"pk_{mode}_")
    ):
        return None
    if mode == "live" and (not settings.live_charging_enabled or not settings.stripe_webhook_secret):
        return None
    return mode


def stripe_readiness() -> dict[str, object]:
    mode = settings.stripe_env
    credentials = (mode in {"test", "live"} and
                   settings.stripe_secret_key.startswith(f"sk_{mode}_") and
                   settings.stripe_publishable_key.startswith(f"pk_{mode}_"))
    webhook = bool(settings.stripe_webhook_secret)
    charging_requested = bool(settings.monthly_billing_enabled or settings.ar_billing_mode != "track_only")
    reason = None
    if mode not in {"test", "live"}:
        reason = "invalid_stripe_environment"
    elif charging_requested and settings.payment_provider != "stripe":
        reason = "stripe_provider_disabled"
    elif charging_requested and not credentials:
        reason = "stripe_credentials_missing_or_mixed"
    elif charging_requested and not webhook:
        reason = "stripe_webhook_not_configured"
    elif mode == "live" and not settings.live_charging_enabled:
        reason = "live_charging_not_enabled"
    elif mode == "live" and settings.ar_billing_mode not in {"track_only", "post_run"}:
        reason = "unsupported_live_ar_billing_mode"
    return {
        "stripe_environment": mode if mode in {"test", "live"} else "invalid",
        "stripe_credentials_configured": bool(credentials),
        "webhook_configured": webhook,
        "live_charging_enabled": settings.live_charging_enabled,
        "monthly_billing_enabled": settings.monthly_billing_enabled,
        "ar_billing_mode": settings.ar_billing_mode,
        "configuration_ready": reason is None,
        "reason": reason,
    }


@webhook_router.get("/readiness")
def owner_stripe_readiness(user: User = Depends(current_user)):
    if user.global_role != "RMR_OWNER":
        raise HTTPException(status_code=403, detail="RMR Owner access required.")
    return stripe_readiness()


def _profile_model():
    # The original table remains sandbox-only; live cards have no fallback to it.
    return TenantLiveBillingProfile if settings.stripe_env == "live" else TenantBillingProfile


def _log_stripe_error(exc: StripeError, operation: str) -> None:
    def safe(value):
        if not isinstance(value, (str, int)):
            return None
        value = str(value)
        for secret in (settings.stripe_secret_key, settings.stripe_webhook_secret):
            if secret:
                value = value.replace(secret, "[redacted]")
        value = re.sub(r"\{.*\}|\[.*\]|(['\"]).*?\1", "[redacted]", value, flags=re.S)
        value = re.sub(r"\b(?:sk|rk|pk|whsec|seti|pi|pm|tok|src)_[A-Za-z0-9_]+", "[redacted]", value)
        value = re.sub(r"(?i)\b(?:cvc|cvv|pan|card_number|client_secret|api_key)\b\s*[:=]?\s*\S+", "[redacted]", value)
        return " ".join(re.sub(r"(?:\d[ -]?){3,}", "[number]", value).split())[:500]
    error = getattr(exc, "error", None)
    logger.warning("Stripe billing failure operation=%s class=%s type=%s code=%s decline=%s http=%s request=%s message=%s",
                   operation, type(exc).__name__, safe(getattr(error, "type", None)),
                   safe(getattr(exc, "code", None)), safe(getattr(error, "decline_code", None)),
                   getattr(exc, "http_status", None), safe(getattr(exc, "request_id", None)),
                   safe(getattr(exc, "user_message", None)))


def _lock_tenant(db: Session, tenant_id: str) -> None:
    # Database write lock: row lock on PostgreSQL, writer lock on SQLite.
    # All callers enter before making changes; discard dependency/read snapshots.
    db.rollback()
    result = db.execute(text("UPDATE tenants SET id=id WHERE id=:id"), {"id": tenant_id})
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Client tenant not found.")
    db.expire_all()


@router.post("/operations/{kind}")
def prepare_operation(kind: str, tenant_id: str, payload: PrepareOperation, request: Request,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    _require_billing_write(user, tenant_id)
    _stripe_client()  # Validate configuration without a provider call.
    mode = _stripe_mode()
    if kind not in {"setup", "subscription"} or (kind == "subscription" and not monthly.monthly_billing_enabled()):
        raise HTTPException(status_code=403, detail="Billing operation is unavailable.")
    _lock_tenant(db, tenant_id)
    slot = f"{tenant_id}:{mode}:{kind}"
    op = db.scalar(select(BillingOperation).where(BillingOperation.active_slot == slot))
    if kind != "subscription" and op and payload.previous_operation_id == op.id and op.result_data is not None:
        op.active_slot = None
        db.flush()
        op = None
    if op is None:
        op = BillingOperation(tenant_id=tenant_id, kind=kind, mode=mode, active_slot=slot)
        db.add(op)
    db.commit()
    return {"operation_id": op.id}


def _operation(db: Session, tenant_id: str, kind: str, operation_id: str) -> BillingOperation:
    _lock_tenant(db, tenant_id)
    op = db.get(BillingOperation, operation_id)
    if not op or op.tenant_id != tenant_id or op.kind != kind or op.mode != _stripe_mode():
        raise HTTPException(status_code=409, detail="Prepare a valid billing operation first.")
    created = op.created_at.replace(tzinfo=timezone.utc) if op.created_at.tzinfo is None else op.created_at
    # Stripe may prune idempotency keys after 24h. Never replay an uncertain
    # creation beyond that retention window; require operator reconciliation.
    if op.result_data is None and datetime.now(timezone.utc) - created > timedelta(hours=23):
        raise HTTPException(status_code=409, detail="Billing operation expired; administrator reconciliation is required.")
    return op


def _stripe_client() -> StripeClient:
    if settings.payment_provider != "stripe":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe billing is not enabled.",
        )

    if _stripe_mode() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe keys are missing, invalid, or use different test/live modes.",
        )

    return StripeClient(
        settings.stripe_secret_key,
        max_network_retries=2,
    )


def _tenant_or_404(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client tenant not found.",
        )
    return tenant


def _profile(db: Session, tenant_id: str):
    model = _profile_model()
    return db.scalar(
        select(model).where(model.tenant_id == tenant_id)
    )


def _get_or_create_profile(
    db: Session,
    tenant_id: str,
) -> TenantBillingProfile:
    profile = _profile(db, tenant_id)
    if profile:
        return profile

    profile = _profile_model()(
        tenant_id=tenant_id,
        provider="stripe",
        setup_status="not_configured",
    )
    db.add(profile)
    db.flush()
    return profile


def _require_billing_write(user: User, tenant_id: str) -> None:
    if is_global_admin(user):
        if (
            getattr(user, "_managed_tenant_id", None) == tenant_id
            and getattr(user, "_managed_access_type", "") == "managed_write"
        ):
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Start an authorized, audited client workspace session "
                "before changing billing details."
            ),
        )

    if user.tenant_id != tenant_id or user.tenant_role != "CLIENT_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client Administrator access is required to manage billing.",
        )


def _can_manage_billing(user: User, tenant_id: str) -> bool:
    if is_global_admin(user):
        return (
            getattr(user, "_managed_tenant_id", None) == tenant_id
            and getattr(user, "_managed_access_type", "") == "managed_write"
        )

    return user.tenant_id == tenant_id and user.tenant_role == "CLIENT_ADMIN"


def _serialize_profile(
    profile: TenantBillingProfile | None,
) -> dict[str, object]:
    if not profile:
        return {
            "setup_status": "not_configured",
            "payment_method": None,
        }

    payment_method = None
    if profile.default_payment_method_id and profile.card_last4:
        payment_method = {
            "brand": profile.card_brand,
            "last4": profile.card_last4,
            "exp_month": profile.card_exp_month,
            "exp_year": profile.card_exp_year,
        }

    return {
        "setup_status": profile.setup_status,
        "payment_method": payment_method,
    }


@router.get("")
def billing_status(
    tenant_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_tenant_access(user, tenant_id)
    tenant = _tenant_or_404(db, tenant_id)
    profile = _profile(db, tenant_id)

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
        },
        "provider": settings.payment_provider,
        "stripe_configured": _stripe_mode() is not None,
        "can_manage": _can_manage_billing(user, tenant_id),
        "monthly": monthly.summary(db, tenant_id, _stripe_mode(), profile),
        "subscription_activation_available": monthly.monthly_billing_enabled() and _stripe_mode() is not None and _can_manage_billing(user, tenant_id),
        **_serialize_profile(profile),
    }


@router.post("/setup-intent")
def create_setup_intent(
    tenant_id: str,
    payload: OperationRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    _require_billing_write(user, tenant_id)

    client = _stripe_client()
    op = _operation(db, tenant_id, "setup", payload.operation_id)
    tenant = _tenant_or_404(db, tenant_id)
    profile = _get_or_create_profile(db, tenant_id)
    if not op.request_data:
        op.request_data = {"customer_params": {
            "name": tenant.name,
            "metadata": {"rmr_tenant_id": tenant.id, "rmr_tenant_slug": tenant.slug},
            **({"email": tenant.primary_contact_email.strip()} if tenant.primary_contact_email.strip() else {}),
        }}
        db.commit()
        op = _operation(db, tenant_id, "setup", payload.operation_id)
        profile = _profile(db, tenant_id)

    try:
        if op.result_data:
            setup_intent = client.v1.setup_intents.retrieve(op.result_data["setup_intent_id"])
            return {"publishable_key": settings.stripe_publishable_key,
                    "client_secret": setup_intent.client_secret, "setup_intent_id": setup_intent.id}
        if not profile.stripe_customer_id:
            customer = client.v1.customers.create(
                op.request_data["customer_params"],
                options={
                    "idempotency_key": f"rmr-customer-{op.mode}-{profile.id}",
                },
            )

            profile.stripe_customer_id = customer.id
            profile.setup_status = "customer_created"

            audit(
                db,
                user,
                "billing.stripe_customer.created",
                tenant_id=tenant.id,
                entity_type="tenant_billing_profile",
                entity_id=profile.id,
                data={"provider": "stripe"},
            )

        setup_intent = client.v1.setup_intents.create(
            {
                "customer": profile.stripe_customer_id,
                "allowed_payment_method_types": ["card"],
                "usage": "off_session",
            },
            options={"idempotency_key": f"rmr-setup-{op.id}"},
        )

        # A pending replacement must not invalidate the currently saved card.
        profile.setup_status = (
            "ready"
            if profile.default_payment_method_id and profile.card_last4
            else "setup_pending"
        )

        audit(
            db,
            user,
            "billing.setup_intent.created",
            tenant_id=tenant.id,
            entity_type="tenant_billing_profile",
            entity_id=profile.id,
            data={"setup_intent_id": setup_intent.id},
        )

        op.result_data = {"setup_intent_id": setup_intent.id}
        db.commit()

        return {
            "publishable_key": settings.stripe_publishable_key,
            "client_secret": setup_intent.client_secret,
            "setup_intent_id": setup_intent.id,
        }

    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, payload.operation_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe could not start payment-method setup. Retry the same operation.",
        ) from exc


@router.post("/payment-method/complete")
def complete_payment_method(
    tenant_id: str,
    payload: SetupIntentComplete,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    _require_billing_write(user, tenant_id)

    tenant = _tenant_or_404(db, tenant_id)
    profile = _profile(db, tenant_id)

    if not profile or not profile.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Billing setup has not been started for this client.",
        )

    return _complete_setup_intent(db, profile, payload.setup_intent_id, user)


def _complete_setup_intent(
    db: Session, profile: TenantBillingProfile, setup_intent_id: str,
    user: User | None = None,
):
    tenant_id = profile.tenant_id
    client = _stripe_client()
    _lock_tenant(db, tenant_id)
    profile = _profile(db, tenant_id)

    try:
        completed = db.scalar(select(AuditEvent.id).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.entity_id == profile.id,
            AuditEvent.event_type == "billing.payment_method.saved",
            AuditEvent.event_data["setup_intent_id"].as_string() == setup_intent_id,
        ).limit(1))
        if completed:
            db.commit()
            return {"ok": True, **_serialize_profile(profile)}
        setup_intent = client.v1.setup_intents.retrieve(setup_intent_id)
        if setup_intent.livemode != (_stripe_mode() == "live"):
            raise HTTPException(status_code=400, detail="SetupIntent mode does not match billing configuration.")

        setup_customer_id = (
            setup_intent.customer.id
            if hasattr(setup_intent.customer, "id")
            else setup_intent.customer
        )

        if setup_customer_id != profile.stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SetupIntent does not belong to this client.",
            )

        if setup_intent.status != "succeeded":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment method setup has not completed successfully.",
            )

        payment_method_id = (
            setup_intent.payment_method.id
            if hasattr(setup_intent.payment_method, "id")
            else setup_intent.payment_method
        )

        if not payment_method_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stripe did not return a payment method.",
            )

        payment_method = client.v1.payment_methods.retrieve(payment_method_id)

        payment_customer_id = (
            payment_method.customer.id
            if hasattr(payment_method.customer, "id")
            else payment_method.customer
        )

        if payment_customer_id != profile.stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment method does not belong to this client.",
            )

        card = getattr(payment_method, "card", None)
        if not card:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only card payment methods are supported.",
            )

        # Order by the server-issued setup operation; legacy intents use Stripe's
        # creation time. Fail safely on ambiguous same-second legacy replacements.
        operation = db.scalar(select(BillingOperation).where(
            BillingOperation.tenant_id == tenant_id,
            BillingOperation.kind == "setup",
            BillingOperation.result_data["setup_intent_id"].as_string() == setup_intent.id,
        ))
        setup_order = (operation.created_at.replace(tzinfo=timezone.utc).timestamp()
                       if operation else float(setup_intent.created))
        latest = db.scalar(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.entity_id == profile.id,
            AuditEvent.event_type == "billing.payment_method.saved",
        ).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(1))
        if latest:
            previous_order = latest.event_data.get("setup_order")
            if previous_order is None:
                previous = client.v1.setup_intents.retrieve(latest.event_data["setup_intent_id"])
                previous_order = float(previous.created)
            if setup_order <= previous_order:
                db.commit()
                return {"ok": True, **_serialize_profile(profile)}
        elif profile.default_payment_method_id and profile.default_payment_method_id != payment_method_id:
            # Preserve legacy ready cards where no reliable ordering exists.
            if setup_order <= profile.updated_at.replace(tzinfo=timezone.utc).timestamp():
                db.commit()
                return {"ok": True, **_serialize_profile(profile)}

        if not payment_method.card:
            return {"ok": True, **_serialize_profile(profile)}

        client.v1.customers.update(
            profile.stripe_customer_id,
            {
                "invoice_settings": {
                    "default_payment_method": payment_method_id,
                }
            },
            options={"idempotency_key": f"rmr-default-{profile.id}-{setup_intent.id}"},
        )

        profile.default_payment_method_id = payment_method_id
        agreement = monthly.subscription(db, tenant_id, _stripe_mode())
        if agreement and agreement.stripe_subscription_id and agreement.status not in {"canceled", "incomplete_expired"}:
            from ..billing_renewals import sync_schedule_payment_method
            sync_schedule_payment_method(db, client, agreement, payment_method_id, setup_intent.id)
            client.v1.subscriptions.update(agreement.stripe_subscription_id,
                {"default_payment_method": payment_method_id},
                options={"idempotency_key": f"rmr-sub-default-{profile.id}-{setup_intent.id}"})
        profile.card_brand = card.brand or ""
        profile.card_last4 = card.last4 or ""
        profile.card_exp_month = card.exp_month
        profile.card_exp_year = card.exp_year
        profile.setup_status = "ready"

        audit(
            db,
            user,
            "billing.payment_method.saved",
            tenant_id=tenant_id,
            entity_type="tenant_billing_profile",
            entity_id=profile.id,
            data={
                "provider": "stripe",
                "brand": profile.card_brand,
                "last4": profile.card_last4,
                "setup_intent_id": setup_intent.id,
                "setup_order": setup_order,
            },
        )

        db.commit()

        return {
            "ok": True,
            **_serialize_profile(profile),
        }

    except HTTPException:
        db.rollback()
        raise
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, setup_intent_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe could not complete payment-method setup. Retry shortly.",
        ) from exc


@webhook_router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.stripe_webhook_secret or _stripe_mode() is None:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured.")
    try:
        event = Webhook.construct_event(
            await request.body(), request.headers.get("stripe-signature", ""),
            settings.stripe_webhook_secret,
        )
    except (ValueError, SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature or payload.") from exc
    if (_value(event, "livemode") is not (_stripe_mode() == "live") or _value(event, "account")):
        raise HTTPException(status_code=400, detail="Stripe webhook environment mismatch.")

    if event["type"] in {"payment_intent.succeeded", "payment_intent.payment_failed"}:
        from ..prospectiq_bridge.ar_billing import reconcile_post_run_webhook
        return await run_in_threadpool(reconcile_post_run_webhook, db, event["data"]["object"])

    if event["type"] in {"invoice.paid", "invoice.payment_failed", "customer.subscription.updated", "customer.subscription.deleted"}:
        obj = event["data"]["object"]
        return await run_in_threadpool(_reconcile_subscription_event, db, event["type"], obj)
    if event["type"] != "setup_intent.succeeded":
        return {"ok": True, "ignored": True}
    obj = event["data"]["object"]
    customer_id = getattr(obj, "customer", None)
    if not isinstance(customer_id, str) or not getattr(obj, "id", None):
        raise HTTPException(status_code=400, detail="Missing SetupIntent customer or ID.")
    return await run_in_threadpool(_reconcile_setup_intent, db, customer_id, obj["id"])


def _reconcile_setup_intent(db: Session, customer_id: str, setup_intent_id: str):
    # The persisted unique Stripe Customer mapping is authoritative, never a tenant
    # ID supplied in a request or event metadata. Lock for concurrent completions.
    model = _profile_model()
    profile = db.scalar(select(model).where(
        model.stripe_customer_id == customer_id,
        model.provider == "stripe",
    ).with_for_update())
    if profile is None:
        return {"ok": True, "ignored": True}
    _complete_setup_intent(db, profile, setup_intent_id)
    return {"ok": True}


def _sandbox_subscriptions():
    # Historical helper name; the configured environment is now authoritative.
    if _stripe_mode() not in {"test", "live"}:
        raise HTTPException(403, "Monthly subscription charging is not configured.")
    return _stripe_client()


def _value(obj, key, default=None):
    if isinstance(obj, StripeObject):
        try:
            return obj[key]
        except KeyError:
            return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _id(obj):
    return obj if isinstance(obj, str) else _value(obj, "id")


def _invoice_subscription(invoice):
    parent = _value(invoice, "parent")
    return _id(_value(_value(parent, "subscription_details"), "subscription")) or _id(_value(invoice, "subscription"))


def _sync_subscription(db, row, client, remote=None):
    """Called under the tenant lock. Never apply state from event snapshots."""
    if remote is None:
        remote = client.v1.subscriptions.retrieve(row.stripe_subscription_id,
            {"expand": ["latest_invoice.confirmation_secret"]})
    if (_id(remote.customer) != row.stripe_customer_id or remote.livemode != (row.mode == "live")
            or remote.id != row.stripe_subscription_id):
        raise HTTPException(409, "Stripe subscription ownership or mode mismatch.")
    invoice = remote.latest_invoice
    if isinstance(invoice, str):
        invoice = client.v1.invoices.retrieve(invoice, {"expand": ["confirmation_secret"]})
    if invoice and (_id(_value(invoice, "customer")) != row.stripe_customer_id
                    or _invoice_subscription(invoice) != row.stripe_subscription_id):
        raise HTTPException(409, "Stripe invoice ownership mismatch.")
    row.status = remote.status
    row.latest_invoice_id = _id(invoice)
    row.last_payment_status = _value(invoice, "status", "pending")
    items = _value(_value(remote, "items"), "data", [])
    if _value(_value(remote, "items"), "has_more", False):
        raise HTTPException(409, "Complete subscription items required for billing reconciliation.")
    start = min((_value(i, "current_period_start", 0) for i in items), default=0)
    end = min((_value(i, "current_period_end", 0) for i in items), default=0)
    row.current_period_start = datetime.fromtimestamp(start, timezone.utc) if start else None
    row.current_period_end = datetime.fromtimestamp(end, timezone.utc) if end else None
    from ..billing_renewals import sync_current_items
    if remote.status != "canceled":
        sync_current_items(db, row, items)
    if monthly.paid(row) and row.activated_at is None:
        row.activated_at = datetime.now(timezone.utc)
    if remote.status == "canceled":
        row.cancelled_at = datetime.fromtimestamp(_value(remote, "canceled_at") or datetime.now(timezone.utc).timestamp(), timezone.utc)
    # Never persist/log the invoice confirmation secret. Only an authorized
    # billing browser receives it, and only for an unpaid actionable invoice.
    secret = _value(_value(invoice, "confirmation_secret"), "client_secret")
    return secret if _value(invoice, "status") == "open" and remote.status in {"incomplete", "past_due", "active"} else None


def _monthly_result(db, tenant_id, secret=None):
    profile = _profile(db, tenant_id)
    result = {"monthly": monthly.summary(db, tenant_id, _stripe_mode(), profile)}
    if secret:
        result.update(client_secret=secret, publishable_key=settings.stripe_publishable_key,
                      payment_method_id=profile.default_payment_method_id)
    return result


@router.post("/subscription/activate")
def activate_subscription(tenant_id: str, payload: ActivateSubscription, request: Request,
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not monthly.monthly_billing_enabled():
        raise HTTPException(403, "Monthly billing is disabled")
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    _require_billing_write(user, tenant_id)
    client = _sandbox_subscriptions()
    if not payload.confirmed:
        raise HTTPException(400, "Explicit monthly billing authorization is required.")
    op = _operation(db, tenant_id, "subscription", payload.operation_id)
    row = monthly.subscription(db, tenant_id, _stripe_mode())
    if row and row.operation_id != op.id:
        raise HTTPException(409, "This tenant already has a monthly billing agreement.")
    profile = _profile(db, tenant_id)
    if not row:
        review = monthly.quote(db, tenant_id)
        if not review["services"] or payload.quote_hash != review["quote_hash"]:
            raise HTTPException(409, "Services changed or no priced services are assigned. Review billing again.")
        if not profile or profile.setup_status != "ready" or not profile.default_payment_method_id or not profile.stripe_customer_id:
            raise HTTPException(409, "Save a payment method before activating services.")
        # Write once; subsequent requests never replace this acceptance snapshot.
        op.request_data = {"acceptance": {**review, "user_id": user.id,
            "accepted_at": datetime.now(timezone.utc).isoformat(), "operation_id": op.id},
            "customer": profile.stripe_customer_id, "payment_method": profile.default_payment_method_id}
        row = BillingSubscription(tenant_id=tenant_id, mode=_stripe_mode(), operation_id=op.id,
            stripe_customer_id=profile.stripe_customer_id, monthly_amount_cents=review["total_cents"])
        db.add(row)
        db.commit()  # Durable consent before ANY provider side effect.
        op = _operation(db, tenant_id, "subscription", payload.operation_id)
        row = monthly.subscription(db, tenant_id, _stripe_mode())
    try:
        if not row.stripe_subscription_id:
            params = op.request_data
            from ..billing_renewals import ensure_prices
            items = ensure_prices(db, client, tenant_id, op, params["acceptance"]["services"])
            db.commit()  # Keep Product/Price mappings if subscription HTTP fails.
            op = _operation(db, tenant_id, "subscription", payload.operation_id)
            row = monthly.subscription(db, tenant_id, _stripe_mode())
            if not row.stripe_subscription_id:
                remote = client.v1.subscriptions.create({"customer": params["customer"],
                    "default_payment_method": params["payment_method"], "collection_method": "charge_automatically",
                    "payment_behavior": "allow_incomplete", "items": items,
                    "metadata": {"rmr_tenant_id": tenant_id, "rmr_operation_id": op.id, "rmr_billing_mode": row.mode}},
                    options={"idempotency_key": f"rmr-subscription-{op.id}"})
                if remote.livemode != (row.mode == "live") or _id(remote.customer) != row.stripe_customer_id:
                    raise HTTPException(409, "Stripe subscription ownership or mode mismatch.")
                row.stripe_subscription_id = remote.id
                op.result_data = {"subscription_id": remote.id}
                db.commit()  # Preserve the mapping even if the following read fails.
                _lock_tenant(db, tenant_id)
                row = monthly.subscription(db, tenant_id, _stripe_mode())
        secret = _sync_subscription(db, row, client)
        db.commit()
        return _monthly_result(db, tenant_id, secret)
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, payload.operation_id)
        raise HTTPException(502, "Stripe could not finish monthly activation. Retry the same operation or refresh billing status.") from exc


@router.post("/subscription/refresh")
def refresh_subscription(tenant_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not monthly.monthly_billing_enabled():
        raise HTTPException(403, "Monthly billing is disabled")
    require_request_origin(request)
    require_tenant_access(user, tenant_id)
    _require_billing_write(user, tenant_id)
    client = _sandbox_subscriptions()
    _lock_tenant(db, tenant_id)
    row = monthly.subscription(db, tenant_id, _stripe_mode())
    if not row or not row.stripe_subscription_id:
        raise HTTPException(409, "Retry the existing activation to finish preparing the subscription.")
    try:
        secret = _sync_subscription(db, row, client)
        db.commit()
        return _monthly_result(db, tenant_id, secret)
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, "subscription-refresh")
        raise HTTPException(502, "Stripe billing status could not be refreshed. Retry shortly.") from exc


def _reconcile_subscription_event(db, event_type, obj):
    customer_id = _id(_value(obj, "customer"))
    sub_id = _id(obj) if event_type.startswith("customer.subscription.") else _invoice_subscription(obj)
    if not isinstance(customer_id, str) or not isinstance(sub_id, str):
        return {"ok": True, "ignored": True}
    model = _profile_model()
    profile = db.scalar(select(model).where(model.stripe_customer_id == customer_id))
    if not profile:
        return {"ok": True, "ignored": True}
    tenant_id = profile.tenant_id
    _lock_tenant(db, tenant_id)
    row = monthly.subscription(db, tenant_id, _stripe_mode())
    if not row or row.stripe_customer_id != customer_id or (row.stripe_subscription_id and row.stripe_subscription_id != sub_id):
        db.rollback()
        return {"ok": True, "ignored": True}
    try:
        client = _stripe_client()
        remote = None
        if not row.stripe_subscription_id:
            # Recover a successful creation whose HTTP response was lost. Only
            # server-retrieved metadata bound to our DURABLE consent can adopt it.
            remote = client.v1.subscriptions.retrieve(sub_id, {"expand": ["latest_invoice.confirmation_secret"]})
            metadata = _value(remote, "metadata")
            if (_value(metadata, "rmr_operation_id") != row.operation_id
                    or _value(metadata, "rmr_tenant_id") != tenant_id
                    or _id(remote.customer) != customer_id or remote.livemode != (row.mode == "live")):
                db.rollback()
                return {"ok": True, "ignored": True}
            row.stripe_subscription_id = sub_id
            db.get(BillingOperation, row.operation_id).result_data = {"subscription_id": sub_id}
        _sync_subscription(db, row, client, remote)
        db.commit()
        return {"ok": True}
    except StripeError as exc:
        db.rollback()
        _log_stripe_error(exc, "subscription-webhook")
        raise HTTPException(502, "Stripe reconciliation temporarily unavailable.") from exc
