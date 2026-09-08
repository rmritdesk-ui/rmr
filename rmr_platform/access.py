from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import OnboardingProject, PasswordResetToken, Tenant, User, UserInvitation
from .security import create_one_time_secret, hash_password, hash_one_time_secret, verify_password




def comparable_now(value: datetime | None = None) -> datetime:
    """Return UTC now with timezone-awareness matching a DB datetime.

    SQLite returns timezone-aware columns as naive datetimes while PostgreSQL
    preserves offsets. Matching the stored value keeps invitation/reset expiry
    checks portable across both engines.
    """
    now = datetime.now(timezone.utc)
    if value is not None and value.tzinfo is None:
        return now.replace(tzinfo=None)
    return now

def normalize_email(value: str) -> str:
    return value.strip().lower()


def invitation_url(raw_token: str) -> str:
    return f"{settings.base_url}/#/activate/{raw_token}"


def password_reset_url(raw_token: str) -> str:
    return f"{settings.base_url}/#/reset-password/{raw_token}"


def create_invitation(
    db: Session,
    *,
    tenant: Tenant,
    full_name: str,
    email: str,
    tenant_role: str,
    invited_by_user_id: str | None,
    manager_id: str | None = None,
    team_name: str = "",
) -> tuple[UserInvitation, str]:
    email = normalize_email(email)
    if "@" not in email:
        raise HTTPException(status_code=422, detail={"message": "Enter a valid email address", "field_errors": {"email": "Enter a valid email address"}})
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user:
        if existing_user.tenant_id == tenant.id:
            raise HTTPException(status_code=409, detail={"message": "This user already has access to the client", "field_errors": {"email": "This user already has access"}})
        raise HTTPException(status_code=409, detail={"message": "This email is already used by another account", "field_errors": {"email": "Email already exists"}})

    existing_invitations = list(db.scalars(select(UserInvitation).where(
        UserInvitation.tenant_id == tenant.id,
        UserInvitation.email == email,
        UserInvitation.status == "pending",
    )))
    now = datetime.now(timezone.utc)
    for row in existing_invitations:
        row.status = "revoked"

    raw_token, token_hash = create_one_time_secret()
    invitation = UserInvitation(
        tenant_id=tenant.id,
        email=email,
        full_name=full_name.strip(),
        tenant_role=tenant_role,
        manager_id=manager_id,
        team_name=team_name.strip(),
        token_hash=token_hash,
        status="pending",
        invited_by_user_id=invited_by_user_id,
        expires_at=now + timedelta(hours=settings.invitation_hours),
        created_at=now,
        last_sent_at=now,
    )
    db.add(invitation)
    db.flush()
    if tenant.status == "onboarding" and tenant.health_status == "Onboarding":
        tenant.health_status = "Awaiting Client Access"
    return invitation, raw_token


def invitation_summary(db: Session, tenant_id: str) -> dict[str, object]:
    active_users = list(db.scalars(select(User).where(
        User.tenant_id == tenant_id,
        User.tenant_role == "CLIENT_ADMIN",
        User.active.is_(True),
    ).order_by(User.created_at)))
    invitations = list(db.scalars(select(UserInvitation).where(
        UserInvitation.tenant_id == tenant_id,
        UserInvitation.tenant_role == "CLIENT_ADMIN",
    ).order_by(UserInvitation.created_at.desc())))
    pending = next((row for row in invitations if row.status == "pending" and row.expires_at > comparable_now(row.expires_at)), None)
    latest = invitations[0] if invitations else None
    return {
        "active_client_admins": [
            {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            }
            for user in active_users
        ],
        "pending_invitation": serialize_invitation(pending) if pending else None,
        "latest_invitation": serialize_invitation(latest) if latest else None,
        "access_state": "active" if active_users else "invitation_pending" if pending else "not_provisioned",
    }


def serialize_invitation(invitation: UserInvitation | None) -> dict[str, object] | None:
    if not invitation:
        return None
    return {
        "id": invitation.id,
        "tenant_id": invitation.tenant_id,
        "email": invitation.email,
        "full_name": invitation.full_name,
        "tenant_role": invitation.tenant_role,
        "team_name": invitation.team_name,
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
        "created_at": invitation.created_at.isoformat(),
        "last_sent_at": invitation.last_sent_at.isoformat(),
        "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
    }


def accept_invitation(db: Session, raw_token: str, password: str) -> tuple[User, Tenant]:
    token_hash = hash_one_time_secret(raw_token)
    invitation = db.scalar(select(UserInvitation).where(UserInvitation.token_hash == token_hash))
    now = comparable_now(invitation.expires_at if invitation else None)
    if not invitation or invitation.status != "pending" or invitation.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invitation is invalid, expired, or already used")
    existing = db.scalar(select(User).where(User.email == invitation.email))
    if existing:
        raise HTTPException(status_code=409, detail="An account already exists for this email")
    tenant = db.get(Tenant, invitation.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Client tenant no longer exists")
    user = User(
        email=invitation.email,
        password_hash=hash_password(password),
        full_name=invitation.full_name,
        tenant_id=invitation.tenant_id,
        tenant_role=invitation.tenant_role,
        manager_id=invitation.manager_id,
        team_name=invitation.team_name,
        active=True,
        must_change_password=False,
    )
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=500, detail="Password verification failed; account was not activated")
    db.add(user)
    db.flush()
    invitation.status = "accepted"
    invitation.accepted_user_id = user.id
    invitation.accepted_at = now
    project = db.scalar(select(OnboardingProject).where(OnboardingProject.tenant_id == tenant.id))
    if project and project.status == "complete":
        tenant.status = "live"
        tenant.health_status = "Healthy"
    elif tenant.status in {"onboarding", "invitation_pending"}:
        tenant.status = "onboarding"
        tenant.health_status = "Client Access Active"
    return user, tenant


def create_password_reset(db: Session, user: User, requested_ip: str = "") -> tuple[PasswordResetToken, str]:
    now = datetime.now(timezone.utc)
    for row in db.scalars(select(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    )):
        row.used_at = now
    raw_token, token_hash = create_one_time_secret()
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(minutes=settings.password_reset_minutes),
        requested_ip=requested_ip[:100],
    )
    db.add(reset)
    db.flush()
    return reset, raw_token


def complete_password_reset(db: Session, raw_token: str, new_password: str) -> User:
    token_hash = hash_one_time_secret(raw_token)
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    now = comparable_now(reset.expires_at if reset else None)
    if not reset or reset.used_at is not None or reset.expires_at <= now:
        raise HTTPException(status_code=400, detail="Reset link is invalid, expired, or already used")
    user = db.get(User, reset.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=404, detail="Account is unavailable")
    user.password_hash = hash_password(new_password)
    if not verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=500, detail="Password verification failed; password was not changed")
    user.must_change_password = False
    reset.used_at = now
    return user


def write_local_recovery_file(raw_token: str, email: str) -> Path:
    path = settings.data_dir / f"PASSWORD-RESET-{hash_one_time_secret(raw_token)[:12]}.txt"
    path.write_text(
        "RMR Platform local password recovery\n"
        f"Account: {email}\n"
        f"Reset URL: {password_reset_url(raw_token)}\n"
        "This one-time link expires shortly. Delete this file after use.\n",
        encoding="utf-8",
    )
    return path
