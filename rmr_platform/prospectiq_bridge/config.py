"""Dedicated credentials and strict origins; never reuse native session keys."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import HTTPException

from ..config import settings
from .keys import verification_keys


def origin(value):
    u = urlsplit(value)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.query or u.fragment or u.path not in ("", "/")):
        raise ValueError("Separate HTTPS origins are required")
    return value.rstrip("/")


@dataclass(frozen=True)
class BridgeConfig:
    rmr_origin: str
    piq_origin: str
    callback_url: str
    instance: str
    issuer: str
    audience: str
    key_id: str
    private_key: object = field(repr=False)
    hmac_key_id: str
    hmac_secret: str = field(repr=False)
    code_ttl: int
    grant_ttl: int = 28800
    hmac_keys: dict = field(default_factory=dict, repr=False)


def bridge_config():
    if not settings.prospectiq_bridge_enabled:
        raise HTTPException(404, "ProspectIQ bridge is disabled")
    category = 'invalid_rmr_origin'
    try:
        rmr = origin(settings.base_url)
        category = 'invalid_piq_origin'
        piq = origin(settings.prospectiq_base_url)
        category = 'secure_cookie_or_hostname_requirement'
        if urlsplit(rmr).hostname == urlsplit(piq).hostname or not settings.cookie_secure:
            raise ValueError("Host-only secure cookies require separate hostnames")
        category = 'callback_mismatch'
        callback = os.getenv("RMR_PROSPECTIQ_CALLBACK_URL", "")
        if callback != piq + "/":
            raise ValueError("Callback must be the registered PIQ root")
        category = 'grant_hmac_or_identity_configuration'
        key_id = os.getenv("RMR_PROSPECTIQ_SIGNING_KEY_ID", "").strip()
        hmac_id = os.getenv("RMR_PROSPECTIQ_HMAC_KEY_ID", "").strip()
        secret = os.getenv("RMR_PROSPECTIQ_HMAC_SECRET", "")
        if (len(secret) < 32 or secret == settings.secret_key or not key_id or not hmac_id
                or not settings.prospectiq_integration_instance_id
                or not settings.prospectiq_assertion_issuer or not settings.prospectiq_assertion_audience):
            raise ValueError("Dedicated bridge configuration required")
        category = 'signing_key_missing_unreadable_or_invalid'
        key = serialization.load_pem_private_key(
            Path(os.environ["RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE"]).read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("RSA signing key required")
        category = 'issuer_or_ttl_mismatch'
        ttl = int(os.getenv("RMR_PROSPECTIQ_GRANT_MAX_SECONDS", "28800"))
        if not 1800 <= ttl <= 28800 or settings.prospectiq_assertion_issuer != rmr:
            raise ValueError("Bounded grant and exact issuer required")
        category = 'grant_hmac_or_identity_configuration'
        keys = verification_keys(os.getenv("RMR_PROSPECTIQ_HMAC_KEYS_JSON", "{}"),
                                 {hmac_id: secret}, (settings.secret_key,))
        return BridgeConfig(rmr, piq, callback, settings.prospectiq_integration_instance_id,
                            settings.prospectiq_assertion_issuer, settings.prospectiq_assertion_audience,
                            key_id, key, hmac_id, secret, settings.prospectiq_authorization_code_ttl_seconds, ttl, keys)
    except (ValueError, KeyError, OSError, TypeError):
        error = HTTPException(503, "ProspectIQ bridge configuration unavailable")
        error.bridge_category = category
        raise error from None
