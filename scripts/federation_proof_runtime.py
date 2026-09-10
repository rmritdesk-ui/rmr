"""Disposable HTTPS proof support. Never point this at an installed runtime."""
import json
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT=Path("/proof")
assert ROOT.is_dir(), "Dedicated disposable proof volume required"


def initialize():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    tls=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Disposable federation proof")])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(tls.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
          .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
          .add_extension(x509.SubjectAlternativeName([x509.DNSName("rmr.test"),x509.DNSName("piq.test")]),critical=False)
          .sign(tls,hashes.SHA256()))
    for filename,value in [("signing.pem",key),("tls.key",tls)]:
        (ROOT/filename).write_bytes(value.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (ROOT/"verification.pem").write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    (ROOT/"tls.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    data={name:str(uuid4()) for name in ["user","tenant","mapping","clientA","clientB","leadA","leadB","piqUser","profileA","profileB","runA"]}
    data.update(password=secrets.token_urlsafe(24),native_password=secrets.token_urlsafe(24),
                rmr_secret=secrets.token_hex(32),piq_secret=secrets.token_hex(32),hmac=secrets.token_hex(32))
    (ROOT/"fixture.json").write_text(json.dumps(data))
    write_proxy()
    print("Disposable proof configuration generated; no secrets displayed")


def write_proxy():
    (ROOT/"nginx.conf").write_text("""
events {}
http {
  include /etc/nginx/mime.types;
  access_log off;
  server {
    listen 443 ssl; server_name rmr.test;
    ssl_certificate /proof/tls.crt; ssl_certificate_key /proof/tls.key;
    location / { proxy_pass http://rmr-federation-phase1-rmr:8000; proxy_set_header Host rmr.test; }
  }
  server {
    listen 443 ssl; server_name piq.test;
    ssl_certificate /proof/tls.crt; ssl_certificate_key /proof/tls.key;
    root /proof/piq-dist;
    location /api/ { proxy_pass http://rmr-federation-phase1-piq:4000; proxy_set_header Host piq.test; }
    location / { try_files $uri $uri/ /index.html; }
  }
}
""")


def run_rmr():
    f=json.loads((ROOT/"fixture.json").read_text())
    os.environ.update(RMR_DATA_DIR="/tmp/federation-rmr",RMR_DATABASE_URL="sqlite:////tmp/federation-rmr/app.db",
       RMR_SECRET_KEY=f["rmr_secret"],RMR_BASE_URL="https://rmr.test",RMR_COOKIE_SECURE="true",
       RMR_AUTO_MIGRATE="false",RMR_AUTO_SEED="false",RMR_ALLOW_DEMO_CREDENTIALS="false",RMR_INSTALL_PROFILE="empty",
       RMR_LOCAL_RECOVERY_MODE="false",RMR_PIQ_WORKER_ENABLED="false",RMR_CB1_WORKER_ENABLED="false",
       RMR_PIQ_LIVE_DISCOVERY_ENABLED="false",RMR_PIQ_LIVE_RESEARCH_ENABLED="false",
       RMR_PROSPECTIQ_BRIDGE_ENABLED="true",RMR_PROSPECTIQ_BASE_URL="https://piq.test",
       RMR_PROSPECTIQ_INTEGRATION_INSTANCE_ID="proof-piq",RMR_PROSPECTIQ_ASSERTION_ISSUER="https://rmr.test",
       RMR_PROSPECTIQ_ASSERTION_AUDIENCE="proof-piq-ui",RMR_PROSPECTIQ_CALLBACK_URL="https://piq.test/",
       RMR_PROSPECTIQ_SIGNING_PRIVATE_KEY_FILE="/proof/signing.pem",RMR_PROSPECTIQ_SIGNING_KEY_ID="proof",
       RMR_PROSPECTIQ_HMAC_KEY_ID="proof",RMR_PROSPECTIQ_HMAC_SECRET=f["hmac"])
    from rmr_platform.migrations import migrate
    from rmr_platform.db import db_session
    from rmr_platform.models import User,Tenant,TenantService
    from rmr_platform.security import hash_password
    from rmr_platform.prospectiq_bridge.models import ProspectiqClientMapping
    migrate()
    with db_session() as db:
        db.add(User(full_name="Synthetic installation owner",email="proof-owner@example.invalid",
                    global_role="RMR_OWNER",password_hash="not-a-login-hash"))
        db.add(Tenant(id=f["tenant"],name="Federation Tenant A",slug="federation-proof"));db.flush()
        db.add(User(id=f["user"],tenant_id=f["tenant"],tenant_role="CLIENT_ADMIN",full_name="Federation User",
                    email="federation-proof@example.invalid",password_hash=hash_password(f["password"])))
        for code in ["piq_access","piq_enhancement"]:
            db.add(TenantService(tenant_id=f["tenant"],service_code=code,status="active"))
        db.add(ProspectiqClientMapping(id=f["mapping"],tenant_id=f["tenant"],piq_client_id=f["clientA"],
                                      integration_instance_id="proof-piq",status="active"))
    import uvicorn
    uvicorn.run("rmr_platform.main:app",host="0.0.0.0",port=8000,access_log=False,log_level="warning")


if __name__=="__main__":
    if sys.argv[1]=="init": initialize()
    elif sys.argv[1]=="proxy": write_proxy()
    elif sys.argv[1]=="rmr": run_rmr()
    else: raise SystemExit("Unknown isolated proof action")
