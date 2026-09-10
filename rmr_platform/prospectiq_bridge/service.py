"""Short-lived, read-only federation. No provider or CRM delivery code."""
import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

import jwt
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models import User, Tenant, utcnow
from ..permissions import require_tenant_access, require_client_operational_write, is_global_admin, CLIENT_ROLES
from ..routes.piq import _require_piq_access
from ..security import COOKIE_NAME, decode_token
from ..unified_models import ManagedTenantSession
from .models import ProspectiqAuthorizationGrant as Grant, ProspectiqClientMapping as Mapping, ProspectiqReplayNonce as Replay
from .contracts import AssertionClaims, GrantContext


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def authorized(db, user, mapping, cfg, managed_id=None):
    if not user or not user.active or user.must_change_password:
        raise HTTPException(403, "Bridge user unavailable")
    if not mapping or mapping.status != "active" or mapping.integration_instance_id != cfg.instance:
        raise HTTPException(403, "Active ProspectIQ mapping required")
    if not db.get(Tenant, mapping.tenant_id):
        raise HTTPException(403, "Tenant unavailable")
    require_tenant_access(user, mapping.tenant_id)
    managed = None
    if is_global_admin(user):
        managed_ref = managed_id or getattr(user, "_managed_session_id", None)
        managed = db.get(ManagedTenantSession, managed_ref) if managed_ref else None
        if (not managed or managed.admin_user_id != user.id or managed.tenant_id != mapping.tenant_id
                or managed.status != "active" or managed.access_type != "managed_write"
                or aware(managed.expires_at) <= utcnow()):
            raise HTTPException(403, "Active managed workspace session required")
        user._managed_tenant_id = managed.tenant_id
        user._managed_access_type = managed.access_type
        require_client_operational_write(user, mapping.tenant_id)
    elif user.tenant_role not in CLIENT_ROLES:
        raise HTTPException(403, "Tenant role required")
    _require_piq_access(db, mapping.tenant_id)
    return managed


def browser_origin(request, cfg):
    if request.headers.get("Origin") != cfg.rmr_origin or request.headers.get("X-RMR-Request") != "1":
        raise HTTPException(403, "Same-origin browser request required")


def create_launch(db, user, payload, request, cfg):
    browser_origin(request, cfg)
    mapping = db.get(Mapping, str(payload.mapping_id))
    managed = authorized(db, user, mapping, cfg)
    raw_session = request.cookies.get(COOKIE_NAME, "")
    session_expiry = datetime.fromtimestamp(decode_token(raw_session)["exp"], timezone.utc)
    now = utcnow()
    absolute = min(session_expiry, now + timedelta(minutes=5),
                   aware(managed.expires_at) if managed else session_expiry)
    if absolute <= now:
        raise HTTPException(403, "Session expired")
    row = Grant(user_id=user.id, tenant_id=mapping.tenant_id, mapping_id=mapping.id,
                mapping_version=mapping.mapping_version, piq_client_id=mapping.piq_client_id,
                integration_instance_id=cfg.instance, code_hash=digest(secrets.token_urlsafe(32)),
                code_expires_at=min(absolute, now + timedelta(minutes=3)), pkce_challenge="",
                binding_reference=str(uuid4()), capabilities_json=["prospects.read"],
                authorization_checked_at=now, managed_session_id=managed.id if managed else None,
                managed_session_expires_at=managed.expires_at if managed else None,
                browser_session_hash=digest(raw_session), absolute_expires_at=absolute,
                destination=payload.destination)
    db.add(row)
    db.commit()
    return {"version": "1", "transaction_id": row.id, "expires_at": int(aware(row.code_expires_at).timestamp()),
            "launch_url": cfg.piq_origin + "/#rmr-start=" + row.id}


def check_grant(db, grant, cfg):
    if (not grant or grant.revoked_at or grant.status not in ("pending", "consumed")
            or not grant.absolute_expires_at or aware(grant.absolute_expires_at) <= utcnow()
            or grant.integration_instance_id != cfg.instance):
        raise HTTPException(403, "Grant expired or revoked")
    mapping = db.get(Mapping, grant.mapping_id)
    user = db.get(User, grant.user_id)
    authorized(db, user, mapping, cfg, grant.managed_session_id)
    if (mapping.mapping_version != grant.mapping_version or mapping.tenant_id != grant.tenant_id
            or mapping.piq_client_id != grant.piq_client_id):
        raise HTTPException(403, "Mapping changed")
    return user


def authorize_launch(db, user, payload, request, cfg):
    browser_origin(request, cfg)
    row = db.get(Grant, str(payload.transaction_id))
    if (not row or row.user_id != user.id or row.status != "pending" or row.authorized_at
            or aware(row.code_expires_at) <= utcnow()
            or not hmac.compare_digest(row.browser_session_hash or "", digest(request.cookies.get(COOKIE_NAME, "")))):
        raise HTTPException(403, "Launch expired, consumed or not owned by this session")
    check_grant(db, row, cfg)
    if payload.callback_id != "piq-web":
        raise HTTPException(403, "Unregistered callback")
    code = secrets.token_urlsafe(32)
    now = utcnow()
    result = db.execute(update(Grant).execution_options(synchronize_session="fetch").where(
        Grant.id == row.id, Grant.status == "pending", Grant.authorized_at.is_(None),
        Grant.revoked_at.is_(None), Grant.code_expires_at > now,
    ).values(code_hash=digest(code), code_expires_at=min(aware(row.absolute_expires_at), now + timedelta(seconds=cfg.code_ttl)),
             pkce_challenge=payload.code_challenge, state_hash=digest(payload.state), nonce_hash=digest(payload.nonce),
             authorized_at=now, authorization_checked_at=now, binding_reference=row.id))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Launch already authorized")
    db.commit()
    callback = cfg.callback_url + "#" + urlencode({"rmr-callback": "1", "code": code,
                                                 "state": payload.state, "transaction_id": row.id})
    return {"version": "1", "code": code, "state": payload.state, "callback_url": callback}


def context(row):
    return GrantContext(grant_id=row.id, rmr_user_id=row.user_id, mapping_id=row.mapping_id,
                        mapping_version=row.mapping_version, piq_client_id=row.piq_client_id,
                        integration_instance_id=row.integration_instance_id, capabilities=["prospects.read"],
                        absolute_expires_at=int(aware(row.absolute_expires_at).timestamp()),
                        rmr_tenant_id=row.tenant_id, authorization_checked_at=int(utcnow().timestamp()),
                        managed_session_id=row.managed_session_id,
                        managed_session_expires_at=int(aware(row.managed_session_expires_at).timestamp()) if row.managed_session_expires_at else None,
                        destination=row.destination)


def exchange_code(db, payload, cfg):
    row = db.scalar(select(Grant).where(Grant.code_hash == digest(payload.code)))
    now = utcnow()
    if (not row or row.status != "pending" or not row.authorized_at or row.consumed_at
            or aware(row.code_expires_at) <= now or payload.integration_instance_id != cfg.instance
            or payload.callback_id != "piq-web" or payload.binding_reference != row.id
            or not hmac.compare_digest(row.state_hash or "", digest(payload.state))
            or not hmac.compare_digest(row.nonce_hash or "", digest(payload.nonce))):
        raise HTTPException(403, "Invalid or expired authorization code")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(payload.code_verifier.encode()).digest()).decode().rstrip("=")
    if not hmac.compare_digest(row.pkce_challenge, challenge):
        raise HTTPException(403, "Invalid authorization proof")
    user = check_grant(db, row, cfg)
    updated = db.execute(update(Grant).execution_options(synchronize_session="fetch").where(
        Grant.id == row.id, Grant.status == "pending", Grant.revoked_at.is_(None),
        Grant.consumed_at.is_(None), Grant.code_expires_at > now,
    ).values(status="consumed", consumed_at=now, authorization_checked_at=now))
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Authorization code already consumed")
    issued = int(now.timestamp())
    expires = min(issued + 30, int(aware(row.absolute_expires_at).timestamp()))
    claims = AssertionClaims(**context(row).model_dump(), iss=cfg.issuer, aud=cfg.audience,
                             sub=user.id, jti=uuid4(), iat=issued, nbf=issued, exp=expires,
                             nonce=digest(payload.nonce), typ="rmr-piq-federation-v1",
                             email=user.email, name=user.full_name)
    assertion = jwt.encode(claims.model_dump(mode="json"), cfg.private_key, algorithm="RS256",
                           headers={"kid": cfg.key_id, "typ": "rmr-piq-federation-v1"})
    db.commit()
    return {"version": "1", "assertion": assertion, "expires_at": expires}


def authenticate_service(db, headers, body, method, path, cfg):
    stamp, nonce = headers.get("X-Bridge-Timestamp", ""), headers.get("X-Bridge-Nonce", "")
    try:
        timestamp = int(stamp)
        if (str(timestamp) != stamp or abs(time.time() - timestamp) > 30 or len(nonce) != 64
                or any(c not in "0123456789abcdef" for c in nonce)
                or headers.get("X-Bridge-Instance") != cfg.instance
                or headers.get("X-Bridge-Key") != cfg.hmac_key_id):
            raise ValueError()
        canonical = "\n".join([cfg.instance, cfg.hmac_key_id, method, path, stamp, nonce, hashlib.sha256(body).hexdigest()])
        expected = hmac.new(cfg.hmac_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, headers.get("X-Bridge-Signature", "")):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(401, "Invalid partner authentication") from None
    db.add(Replay(integration_instance_id=cfg.instance, service_identity="piq", key_id=cfg.hmac_key_id,
                  nonce_hash=digest(nonce), request_timestamp=datetime.fromtimestamp(timestamp, timezone.utc),
                  expires_at=utcnow() + timedelta(minutes=2)))
    try:
        db.commit()  # Consume authenticated nonce even if subsequent exchange fails.
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Partner request replayed") from None


def revoke_browser_grants(db, user_id, cookie):
    db.execute(update(Grant).execution_options(synchronize_session="fetch").where(Grant.user_id == user_id, Grant.browser_session_hash == digest(cookie),
                                  Grant.revoked_at.is_(None)).values(status="revoked", revoked_at=utcnow()))
