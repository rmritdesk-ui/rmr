from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import InitialSetupRequest
from ..security import COOKIE_NAME, create_token, hash_password, require_request_origin, verify_password
from ..seed import seed_reference_data

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _global_user_count(db: Session) -> int:
    return int(db.scalar(select(func.count(User.id)).where(User.global_role.is_not(None))) or 0)


def _user_payload(user: User) -> dict[str, object]:
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


def _cleanup_setup_token_file() -> None:
    path = settings.data_dir / "INITIAL-SETUP.txt"
    try:
        if path.exists():
            path.unlink()
    except OSError:
        # The token is still invalidated by the presence of a global user. If
        # filesystem cleanup is blocked, neutralize the file without retaining
        # the secret.
        try:
            path.write_text("RMR Platform initial setup is complete. The one-time setup token has been invalidated.\n", encoding="utf-8")
        except OSError:
            pass


@router.get("/status")
def setup_status(db: Session = Depends(get_db)):
    count = _global_user_count(db)
    return {
        "setup_required": count == 0,
        "environment": settings.environment,
        "install_profile": settings.install_profile,
    }


@router.post("/complete")
def complete_setup(
    payload: InitialSetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    if _global_user_count(db) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initial setup is already complete")
    if not settings.setup_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Initial setup token is not configured")
    if not hmac.compare_digest(payload.setup_token, settings.setup_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid initial setup token")

    owner_email = payload.owner_email.strip().lower()
    field_errors: dict[str, str] = {}
    if "@" not in owner_email:
        field_errors["owner_email"] = "Enter a valid RMR owner email address"
    if db.scalar(select(User).where(User.email == owner_email)):
        field_errors["owner_email"] = "This email is already in use"

    step2_email = ""
    if payload.create_step2_admin:
        step2_email = payload.step2_email.strip().lower()
        if "@" not in step2_email:
            field_errors["step2_email"] = "Enter a valid Step2 administrator email address"
        if len(payload.step2_password) < 12:
            field_errors["step2_password"] = "Use at least 12 characters"
        if step2_email == owner_email:
            field_errors["step2_email"] = "Use a different email from the RMR owner"
        if step2_email and db.scalar(select(User).where(User.email == step2_email)):
            field_errors["step2_email"] = "This email is already in use"
    if field_errors:
        raise HTTPException(status_code=422, detail={"message": "Correct the highlighted setup fields", "field_errors": field_errors})

    seed_reference_data(db)
    owner_hash = hash_password(payload.owner_password)
    if not verify_password(payload.owner_password, owner_hash):
        raise HTTPException(status_code=500, detail="Owner credentials could not be verified. Setup was not completed.")
    owner = User(
        email=owner_email,
        password_hash=owner_hash,
        full_name=payload.owner_name.strip(),
        global_role="RMR_OWNER",
        active=True,
        must_change_password=False,
    )
    db.add(owner)
    db.flush()

    if payload.create_step2_admin:
        step2_hash = hash_password(payload.step2_password)
        if not verify_password(payload.step2_password, step2_hash):
            raise HTTPException(status_code=500, detail="Step2 credentials could not be verified. Setup was not completed.")
        db.add(User(
            email=step2_email,
            password_hash=step2_hash,
            full_name=payload.step2_name.strip() or "Step2 Platform Administrator",
            global_role="STEP2_ADMIN",
            active=True,
            must_change_password=False,
        ))

    db.commit()
    db.refresh(owner)
    # Verify the stored hash after the database transaction before declaring
    # setup complete. This directly guards the first-run failure discovered in
    # v5.0 hands-on QC.
    stored_owner = db.scalar(select(User).where(User.id == owner.id))
    if not stored_owner or not verify_password(payload.owner_password, stored_owner.password_hash):
        raise HTTPException(status_code=500, detail="Stored owner credentials failed verification. Setup requires correction.")

    token = create_token(stored_owner)
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    _cleanup_setup_token_file()
    return {"ok": True, "owner_email": stored_owner.email, "user": _user_payload(stored_owner), "authenticated": True}
