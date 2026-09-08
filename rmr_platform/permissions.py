from __future__ import annotations

from fastapi import HTTPException, status

from .models import User

GLOBAL_ROLES = {"RMR_OWNER", "STEP2_ADMIN"}
CLIENT_ROLES = {
    "CLIENT_ADMIN",
    "VP_SALES",
    "SALES_MANAGER",
    "SALES_REP",
    "MARKETING_USER",
    "EXECUTIVE_VIEWER",
}
CLIENT_OPERATION_WRITERS = {"CLIENT_ADMIN", "VP_SALES", "SALES_MANAGER", "SALES_REP"}
CLIENT_WEBSITE_WRITERS = {"CLIENT_ADMIN", "MARKETING_USER"}
CLIENT_CAMPAIGN_WRITERS = {"CLIENT_ADMIN", "MARKETING_USER"}


def is_global_admin(user: User) -> bool:
    return user.global_role in GLOBAL_ROLES


def require_global_admin(user: User) -> None:
    if not is_global_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Global administrative access required")


def require_tenant_access(user: User, tenant_id: str) -> None:
    if is_global_admin(user):
        return
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access denied")


def _require_global_managed_write(user: User, tenant_id: str, area: str) -> bool:
    """Return True for an authorized global-admin managed-service session.

    Global administrators keep their own identity and may change client-owned
    records only while an active, tenant-bound, audited managed session is
    attached by the authentication layer.
    """
    if not is_global_admin(user):
        return False
    if getattr(user, "_managed_tenant_id", None) == tenant_id and getattr(user, "_managed_access_type", "") == "managed_write":
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Start an authorized, audited client workspace session before changing client {area}",
    )


def require_client_operational_write(user: User, tenant_id: str) -> None:
    if _require_global_managed_write(user, tenant_id, "operational data"):
        return
    if user.tenant_id != tenant_id or user.tenant_role not in CLIENT_OPERATION_WRITERS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client operational write access denied")


def require_client_website_write(user: User, tenant_id: str) -> None:
    if _require_global_managed_write(user, tenant_id, "website content"):
        return
    if user.tenant_id != tenant_id or user.tenant_role not in CLIENT_WEBSITE_WRITERS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Website configuration access denied")


def require_client_campaign_write(user: User, tenant_id: str) -> None:
    if _require_global_managed_write(user, tenant_id, "campaigns"):
        return
    if user.tenant_id != tenant_id or user.tenant_role not in CLIENT_CAMPAIGN_WRITERS:
        raise HTTPException(status_code=403, detail="Campaign write access denied")
