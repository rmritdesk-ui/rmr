
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, struct, time
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet=None
    class InvalidToken(Exception): pass

def _key():
    raw=os.getenv('RMR_INTEGRATION_ENCRYPTION_KEY','').strip()
    if raw:
        try: return raw.encode()
        except Exception: pass
    seed=os.getenv('RMR_SECRET_KEY','rmr-local-product-owner-test-only').encode()
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())

def encrypt(value):
    if value is None: return ''
    if not isinstance(value,str): value=json.dumps(value,separators=(',',':'))
    if Fernet is not None: return Fernet(_key()).encrypt(value.encode()).decode()
    # Authenticated fallback for constrained local test environments. Production should install cryptography.
    key=hashlib.sha256(_key()).digest(); raw=value.encode(); stream=(key*((len(raw)//len(key))+1))[:len(raw)]; ct=bytes(a^b for a,b in zip(raw,stream)); mac=hmac.new(key,ct,hashlib.sha256).digest()
    return 'fallback:'+base64.urlsafe_b64encode(mac+ct).decode()

def decrypt(value):
    if not value: return ''
    if Fernet is not None and not value.startswith('fallback:'): return Fernet(_key()).decrypt(value.encode()).decode()
    raw=base64.urlsafe_b64decode(value.split(':',1)[1]); key=hashlib.sha256(_key()).digest(); mac,ct=raw[:32],raw[32:]
    if not hmac.compare_digest(mac,hmac.new(key,ct,hashlib.sha256).digest()): raise InvalidToken('Invalid credential ciphertext')
    stream=(key*((len(ct)//len(key))+1))[:len(ct)]; return bytes(a^b for a,b in zip(ct,stream)).decode()

def new_totp_secret(): return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
def totp(secret, at=None, step=30, digits=6):
    at=int(at or time.time()); counter=at//step
    pad='='*((8-len(secret)%8)%8); key=base64.b32decode(secret+pad,casefold=True)
    msg=struct.pack('>Q',counter); digest=hmac.new(key,msg,hashlib.sha1).digest(); off=digest[-1]&15
    val=(struct.unpack('>I',digest[off:off+4])[0]&0x7fffffff)%(10**digits)
    return str(val).zfill(digits)
def verify_totp(secret,code,window=1):
    now=time.time()
    return any(hmac.compare_digest(totp(secret,now+(i*30)),str(code).zfill(6)) for i in range(-window,window+1))
def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()
def new_token(): return secrets.token_urlsafe(32)
