"""Bounded verification overlap. Never log or return key material."""
import json
import math
import re
import time


def verification_keys(raw, fallback=None, forbidden=()):
    values = dict(fallback or {})
    extra = json.loads(raw or "{}")
    if not isinstance(extra, dict):
        raise ValueError("Invalid key ring")
    values.update(extra)
    if not 1 <= len(values) <= 4:
        raise ValueError("Invalid key ring")
    resolved, permanent = {}, 0
    now = time.time()
    for kid, entry in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", kid):
            raise ValueError("Invalid key ID")
        if isinstance(entry, dict):
            if set(entry) != {"secret", "not_after"}:
                raise ValueError("Invalid overlap key")
            secret, expiry = entry["secret"], entry["not_after"]
            if (not isinstance(expiry, (float, int)) or isinstance(expiry, bool)
                    or not math.isfinite(expiry) or expiry > now + 86400):
                raise ValueError("Overlap must be bounded to 24 hours")
            if expiry <= now:
                continue
        else:
            secret = entry
            permanent += 1
        if (not isinstance(secret, str) or not 32 <= len(secret) <= 512
                or "\n" in secret or "\r" in secret or secret in forbidden):
            raise ValueError("Invalid dedicated secret")
        resolved[kid] = secret
    if permanent > 1 or not resolved:
        raise ValueError("One permanent active key and bounded overlap required")
    return resolved
