from __future__ import annotations

from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import (
    accept_invitation,
    comparable_now,
    complete_password_reset,
    create_password_reset,
    invitation_summary,
    password_reset_url,
    serialize_invitation,
    write_local_recovery_file,
)
from ..config import settings
from ..db import get_db
from ..models import Notification, Tenant, User, UserInvitation
from ..schemas import (
    InvitationAccept,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetComplete,
    PasswordResetRequest,
)
from ..security import COOKIE_NAME, create_token, current_user, hash_one_time_secret, hash_password, require_request_origin, verify_password
from ..services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_token(user),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    require_request_origin(request)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user.last_login_at = datetime.now(timezone.utc)
    _set_session_cookie(response, user)
    audit(db, user, "auth.login", tenant_id=user.tenant_id, entity_type="user", entity_id=user.id)
    db.commit()
    return {"user": serialize_user(user)}


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    response.delete_cookie(COOKIE_NAME, path="/")
    audit(db, user, "auth.logout", tenant_id=user.tenant_id, entity_type="user", entity_id=user.id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": serialize_user(user)}


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    user.password_hash = hash_password(payload.new_password)
    if not verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=500, detail="Password verification failed; password was not changed")
    user.must_change_password = False
    _set_session_cookie(response, user)
    audit(db, user, "auth.password.changed", tenant_id=user.tenant_id, entity_type="user", entity_id=user.id)
    db.commit()
    return {"user": serialize_user(user)}


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    require_request_origin(request)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
    response: dict[str, object] = {
        "ok": True,
        "message": "If an active account exists, a password reset link has been created.",
    }
    if not user:
        return response
    reset, raw_token = create_password_reset(db, user, request.client.host if request.client else "")
    audit(db, user, "auth.password_reset.requested", tenant_id=user.tenant_id, entity_type="password_reset", entity_id=reset.id)
    if settings.local_recovery_mode:
        path = write_local_recovery_file(raw_token, user.email)
        response.update({
            "local_recovery": True,
            "reset_url": password_reset_url(raw_token),
            "recovery_file": path.name,
            "message": "A one-time reset link was created for this pilot installation.",
        })
    db.commit()
    return response


@router.post("/password-reset/complete")
def reset_password(payload: PasswordResetComplete, request: Request, response: Response, db: Session = Depends(get_db)):
    require_request_origin(request)
    user = complete_password_reset(db, payload.token, payload.new_password)
    audit(db, user, "auth.password_reset.completed", tenant_id=user.tenant_id, entity_type="user", entity_id=user.id)
    _set_session_cookie(response, user)
    db.commit()
    return {"ok": True, "user": serialize_user(user)}


@router.get("/invitations/{token}")
def invitation_details(token: str, db: Session = Depends(get_db)):
    invitation = db.scalar(select(UserInvitation).where(UserInvitation.token_hash == hash_one_time_secret(token)))
    now = comparable_now(invitation.expires_at if invitation else None)
    if not invitation or invitation.status != "pending" or invitation.expires_at <= now:
        raise HTTPException(status_code=404, detail="Invitation is invalid, expired, or already used")
    tenant = db.get(Tenant, invitation.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client tenant is unavailable")
    return {
        "invitation": serialize_invitation(invitation),
        "tenant": {"id": tenant.id, "name": tenant.name, "industry": tenant.industry},
    }


@router.post("/invitations/accept")
def accept_client_invitation(payload: InvitationAccept, request: Request, response: Response, db: Session = Depends(get_db)):
    require_request_origin(request)
    user, tenant = accept_invitation(db, payload.token, payload.password)
    audit(db, user, "client.invitation.accepted", tenant_id=tenant.id, entity_type="user", entity_id=user.id)
    db.add(Notification(
        recipient_scope="GLOBAL_ADMIN",
        tenant_id=tenant.id,
        notification_type="client_access_activated",
        title=f"Client access activated — {tenant.name}",
        body=f"{user.full_name} accepted the {user.tenant_role.replace('_', ' ').title()} invitation.",
        action_route=f"client-360?tenant={tenant.id}",
        action_label="Open Client 360",
        entity_type="user",
        entity_id=user.id,
    ))
    _set_session_cookie(response, user)
    db.commit()
    return {"ok": True, "user": serialize_user(user), "tenant": {"id": tenant.id, "name": tenant.name, "status": tenant.status}}


@router.get("/demo-users")
def demo_users():
    if not settings.allow_demo_credentials:
        return {"users": []}
    return {
        "users": [
            {"label": "RMR Owner", "email": os.getenv("RMR_OWNER_EMAIL", "dave@rmr.local"), "password": os.getenv("RMR_OWNER_PASSWORD", "RMR-Owner-2026!")},
            {"label": "Step2 Platform Administrator", "email": os.getenv("STEP2_ADMIN_EMAIL", "hasan@step2.local"), "password": os.getenv("STEP2_ADMIN_PASSWORD", "Step2-Admin-2026!")},
            {"label": "Kerry — Client Administrator", "email": "admin@kerry-real-estate.demo", "password": "Client-Admin-2026!"},
            {"label": "Kerry — Marketing User", "email": "marketing@kerry-real-estate.demo", "password": "Marketing-2026!"},
            {"label": "CAF — Client Administrator", "email": "admin@cactus-air-filters.demo", "password": "Client-Admin-2026!"},
            {"label": "Desert Peak — Sales Representative", "email": "rep1@desert-peak.demo", "password": "Rep-2026!"},
        ]
    }


def serialize_user(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "global_role": user.global_role,
        "tenant_id": user.tenant_id,
        "tenant_role": user.tenant_role,
        "manager_id": user.manager_id,
        "team_name": user.team_name,
        "must_change_password": user.must_change_password,
    }
