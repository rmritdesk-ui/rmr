from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE_NAME = "rmr_session"
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_one_time_secret(length: int = 32) -> tuple[str, str]:
    raw = base64.urlsafe_b64encode(os.urandom(length)).decode().rstrip("=")
    return raw, hash_one_time_secret(raw)


def hash_one_time_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_one_time_secret(raw: str, encoded_hash: str) -> bool:
    return hmac.compare_digest(hash_one_time_secret(raw), encoded_hash)


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.id,
        "email": user.email,
        "global_role": user.global_role,
        "tenant_id": user.tenant_id,
        "tenant_role": user.tenant_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_hours)).timestamp()),
        "iss": "rmr-platform",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"], issuer="rmr-platform")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid") from exc


def current_user(
    request: Request,
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = decode_token(token)
    user = db.scalar(select(User).where(User.id == payload.get("sub"), User.active.is_(True)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or missing")
    allowed_password_paths = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}
    if user.must_change_password and request.url.path not in allowed_password_paths:
        raise HTTPException(status_code=428, detail="Password change required")
    managed_session_id = request.headers.get("X-RMR-Managed-Session", "").strip()
    if managed_session_id and user.global_role in {"RMR_OWNER", "STEP2_ADMIN"}:
        from .unified_models import ManagedTenantSession
        session = db.get(ManagedTenantSession, managed_session_id)
        now = datetime.now(timezone.utc)
        expires_at = session.expires_at if session else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if session and session.admin_user_id == user.id and session.status == "active" and expires_at and expires_at > now:
            user._managed_tenant_id = session.tenant_id
            user._managed_session_id = session.id
            user._managed_access_type = session.access_type
    return user


def require_request_origin(request: Request) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("X-RMR-Request") != "1":
            raise HTTPException(status_code=400, detail="Missing required request header")
