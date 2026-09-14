"""One canonical grant/check signing format; CRM keeps its independent key/direction."""
import hashlib
import hmac
import secrets
import time


def partner_headers(cfg, path, body):
    stamp, nonce = str(int(time.time())), secrets.token_hex(32)
    canonical = '\n'.join([cfg.instance, cfg.hmac_key_id, 'POST', path,
                           stamp, nonce, hashlib.sha256(body).hexdigest()])
    return {'Content-Type': 'application/json', 'X-Bridge-Instance': cfg.instance,
            'X-Bridge-Key': cfg.hmac_key_id, 'X-Bridge-Timestamp': stamp, 'X-Bridge-Nonce': nonce,
            'X-Bridge-Signature': hmac.new(cfg.hmac_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()}
