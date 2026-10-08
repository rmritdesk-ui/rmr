"""Server-owned tenant billing decision, independent of Stripe test/live identity."""
from fastapi import HTTPException
from sqlalchemy import select

from .config import settings
from .models import TenantBillingProfile


def effective_billing_policy(db, tenant_id: str) -> dict:
    exempt = bool(db.scalar(select(TenantBillingProfile.billing_exempt).where(
        TenantBillingProfile.tenant_id == tenant_id)))
    ar_mode = "track_only" if exempt else settings.ar_billing_mode
    monthly_required = bool(settings.monthly_billing_enabled and not exempt)
    return {
        "billing_exempt": exempt,
        "monthly_billing_required": monthly_required,
        "ar_billing_mode": ar_mode,
        "ar_chargeable": ar_mode != "track_only",
        "payment_method_required": monthly_required or ar_mode != "track_only",
    }


def require_billing_allowed(db, tenant_id: str) -> None:
    if effective_billing_policy(db, tenant_id)["billing_exempt"]:
        raise HTTPException(403, "Billing is disabled for this client.")
