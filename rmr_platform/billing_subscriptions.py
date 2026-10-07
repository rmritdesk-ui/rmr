"""Monthly agreements. No provider calls from entitlement/read helpers."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from .models import BillingOperation, BillingSubscription, ServiceCatalog, TenantService
from .permissions import CLIENT_ROLES, is_global_admin
from .config import settings


def monthly_billing_enabled():
    return settings.monthly_billing_enabled

# Monthly charges use the tenant's saved contract price, never catalog defaults.
# Zero/unset prices and non-monthly assignments do not create recurring charges.


def quote(db, tenant_id):
    assignments = list(db.scalars(select(TenantService).where(
        TenantService.tenant_id == tenant_id, TenantService.status == "active"
    ).order_by(TenantService.service_code)))
    services, unpriced = [], []
    for assignment in assignments:
        catalog = db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == assignment.service_code))
        name = catalog.name if catalog else assignment.service_code
        price = assignment.contract_price_cents or 0
        if assignment.cadence == "monthly" and price > 0:
            services.append({"assignment_id": assignment.id, "service_code": assignment.service_code,
                             "name": name, "amount_cents": price, "quantity": 1})
        else:
            unpriced.append({"service_code": assignment.service_code,
                            "name": name})
    value = {"tenant_id": tenant_id, "services": services, "currency": "usd",
             "interval": "month", "total_cents": sum(s["amount_cents"] for s in services)}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**value, "quote_hash": digest, "unpriced_services": unpriced}


def subscription(db, tenant_id, mode):
    return db.scalar(select(BillingSubscription).where(
        BillingSubscription.tenant_id == tenant_id, BillingSubscription.mode == mode))


def current_services(db, row):
    agreement = db.get(BillingOperation, row.operation_id) if row else None
    if not agreement:
        return []
    return (agreement.result_data or {}).get('current_services', agreement.request_data.get('acceptance', {}).get('services', []))


def paid(row):
    end = row.current_period_end if row else None
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return bool(row and row.status == "active" and row.last_payment_status == "paid"
                and end and end > datetime.now(timezone.utc))


def onboarding_required(db, user):
    if not monthly_billing_enabled():
        return False
    if is_global_admin(user) or not user.tenant_id or user.tenant_role not in CLIENT_ROLES:
        return False
    from .routes.billing import _stripe_mode
    row = subscription(db, user.tenant_id, _stripe_mode())
    return bool((quote(db, user.tenant_id)["services"] or (row and row.monthly_amount_cents)) and not paid(row))


def require_onboarding_access(db, user, request):
    """Allow billing/account essentials, not tenant modules, before paid activation."""
    tenant_id = user.tenant_id
    path = request.url.path.rstrip("/")
    billing_path = f"/api/tenants/{tenant_id}/billing"
    if path == billing_path or path.startswith(billing_path + "/"):
        return  # Billing routes retain their existing tenant/write/origin checks.
    essentials = {
        ("GET", "/api/auth/me"), ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/change-password"), ("GET", "/api/tenants"),
        ("GET", f"/api/tenants/{tenant_id}/modules"),
        ("GET", f"/api/tenants/{tenant_id}/theme"),
    }
    if (request.method, path) in essentials:
        return
    if onboarding_required(db, user):
        raise HTTPException(402, {"code": "billing_required",
            "message": "Complete billing setup to unlock", "billing_url": "/#/billing"})


def require_paid_service(db, tenant_id, service_code, user=None):
    if not monthly_billing_enabled():
        return
    if user and is_global_admin(user):
        return
    # Import lazily to share the existing mode validation without a dependency cycle.
    from .routes.billing import _stripe_mode
    row = subscription(db, tenant_id, _stripe_mode())
    codes = {s["service_code"] for s in current_services(db, row)}
    current_codes = {s["service_code"] for s in quote(db, tenant_id)["services"]}
    if service_code not in current_codes and service_code not in codes:
        return
    if not paid(row) or service_code not in codes:
        raise HTTPException(402, {"code": "billing_required", "message": "Activate or resolve your monthly subscription in Billing & Payments.",
                                  "billing_url": "/#/billing"})


def summary(db, tenant_id, mode, profile):
    current = quote(db, tenant_id)
    row = subscription(db, tenant_id, mode)
    active = paid(row)
    stage = ("active" if active else "payment_problem" if row and row.stripe_subscription_id
             else "activating" if row else "ready_to_activate" if profile and profile.setup_status == "ready"
             and profile.default_payment_method_id else "payment_method_required")
    if not current["services"] and (not row or (row.status == 'canceled' and row.monthly_amount_cents == 0)):
        stage = "no_billable_services"
    from .billing_renewals import pending
    change = pending(db, tenant_id, mode) if mode in {'test', 'live'} else None
    upcoming = None if not change else {'total_cents': change.request_data['desired']['total_cents'],
        'status': (change.result_data or {}).get('state', 'pending'),
        'effective_at': (change.result_data or {}).get('effective_at')}
    if upcoming is not None:
        # Until Stripe scheduling completes, the existing period end is the
        # intended renewal date, not a claim that the update is confirmed.
        if upcoming['effective_at'] is None and row and row.current_period_end:
            end = row.current_period_end
            upcoming['effective_at'] = int((end if end.tzinfo else end.replace(tzinfo=timezone.utc)).timestamp())
        upcoming['effective_date'] = (datetime.fromtimestamp(upcoming['effective_at'], timezone.utc).date().isoformat()
                                      if upcoming['effective_at'] is not None else None)
    return {**current, "stage": stage, "billing_required": bool(monthly_billing_enabled() and
            (current["services"] or (row and row.monthly_amount_cents)) and not active),
            'next_cycle': upcoming,
            "subscription": None if not row else {
                "id": row.stripe_subscription_id, "status": row.status,
                "last_payment_status": row.last_payment_status,
                "payment_action_required": bool(row.stripe_subscription_id and row.status in {"incomplete", "past_due", "active"}
                                                and row.last_payment_status == "open"),
                "monthly_amount_cents": row.monthly_amount_cents,
                "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
                "services": current_services(db, row),
            }}
