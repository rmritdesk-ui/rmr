"""Authenticated, one-time initialization. PIQ owns durable completion and profiles."""
import hashlib
import hmac
import json
import secrets
import time

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from ..unified_models import PiqTargetProfile
from . import service
from .provisioning import mapping_for, require_provision_authority
from .profile_export import serialize_export

BOOTSTRAP_PATH = '/api/integrations/rmr/v1/profiles/bootstrap'


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def remote(cfg, payload, transport=None):
    body = json.dumps(payload, separators=(',', ':')).encode()
    if len(body) > 65536:
        raise HTTPException(413, 'Initial profiles exceed the bootstrap limit. Contact your administrator.')
    stamp, nonce = str(int(time.time())), secrets.token_hex(32)
    canonical = '\n'.join([cfg.instance, cfg.hmac_key_id, 'POST', BOOTSTRAP_PATH,
                           stamp, nonce, hashlib.sha256(body).hexdigest()])
    headers = {'Content-Type': 'application/json', 'X-Bridge-Instance': cfg.instance,
               'X-Bridge-Key': cfg.hmac_key_id, 'X-Bridge-Timestamp': stamp, 'X-Bridge-Nonce': nonce,
               'X-Bridge-Signature': hmac.new(cfg.hmac_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()}
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, transport=transport) as client:
            with client.stream('POST', cfg.piq_origin + BOOTSTRAP_PATH, content=body, headers=headers) as response:
                if response.status_code != 200:
                    raise ValueError()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 32768:
                        raise ValueError()
        data = json.loads(raw)
        if (set(data) != {'version', 'status', 'mapping_id', 'piq_client_id'} or data['version'] != '1'
                or data['status'] not in ('never_attempted', 'failed', 'completed')
                or data['mapping_id'] != payload['mapping_id'] or data['piq_client_id'] != payload['piq_client_id']):
            raise ValueError()
        return data
    except Exception:
        raise HTTPException(503, 'Initial Target Profiles could not be prepared. Retry shortly or contact your administrator.') from None


def ensure_bootstrap(db, user, tenant_id, request, cfg, transport=None):
    service.browser_origin(request, cfg)
    mapping = mapping_for(db, tenant_id, cfg)
    if not mapping:
        raise HTTPException(409, 'Prepare the ProspectIQ workspace first')
    service.authorized(db, user, mapping, cfg)
    envelope = {'version': '1', 'mapping_id': mapping.id, 'mapping_version': mapping.mapping_version,
                'rmr_tenant_id': mapping.tenant_id, 'piq_client_id': mapping.piq_client_id,
                'integration_instance_id': cfg.instance, 'operation': 'status'}
    result = remote(cfg, envelope, transport)
    if result['status'] == 'completed':
        return result  # Do not even read RMR profiles after completion.
    require_provision_authority(db, user, tenant_id)
    profiles = db.scalars(select(PiqTargetProfile).where(PiqTargetProfile.tenant_id == tenant_id,
                          PiqTargetProfile.active.is_(True)).order_by(PiqTargetProfile.id)).all()
    export = serialize_export([record(mapping)], [record(p) for p in profiles], cfg.issuer)
    result = remote(cfg, {**envelope, 'operation': 'import', 'export': export}, transport)
    if result['status'] != 'completed':
        raise HTTPException(503, 'Initial Target Profiles could not be prepared. Retry preparation.')
    return result
