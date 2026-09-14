"""Explicit historical-source copy; never runs during onboarding or page reads."""
import json
from uuid import UUID
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from ..unified_models import PiqTargetProfile
from . import service
from .provisioning import mapping_for, require_provision_authority
from .profile_bootstrap import record
from .profile_export import serialize_export
from .partner import partner_headers

COPY_PATH='/api/integrations/rmr/v1/profiles/history-copy'

class HistoryCopyRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_profile_id: UUID
    request_id: UUID

def copy_history(db,user,payload,request,cfg,transport=None):
    service.browser_origin(request,cfg)
    source=db.get(PiqTargetProfile,str(payload.source_profile_id))
    if not source:raise HTTPException(404,'Historical source unavailable')
    require_provision_authority(db,user,source.tenant_id)
    mapping=mapping_for(db,source.tenant_id,cfg)
    if not mapping:raise HTTPException(409,'Prepare the ProspectIQ workspace first')
    service.authorized(db,user,mapping,cfg)
    data={'version':'1','request_id':str(payload.request_id),'actor_user_id':user.id,
          'source_profile_id':source.id,'mapping_id':mapping.id,'mapping_version':mapping.mapping_version,
          'rmr_tenant_id':source.tenant_id,'piq_client_id':mapping.piq_client_id,
          'integration_instance_id':cfg.instance,
          'export':serialize_export([record(mapping)],[record(source)],cfg.issuer)}
    body=json.dumps(data,separators=(',',':')).encode()
    if len(body)>65536:raise HTTPException(413,'Historical source exceeds the copy limit')
    try:
        with httpx.Client(timeout=15,follow_redirects=False,trust_env=False,transport=transport) as client:
            with client.stream('POST',cfg.piq_origin+COPY_PATH,content=body,headers=partner_headers(cfg,COPY_PATH,body)) as response:
                if response.status_code==428:
                    raise HTTPException(409,'Open ProspectIQ through RMR once, then return here to copy. Your existing PIQ identity must be active and linked.')
                if response.status_code!=200:raise ValueError()
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>32768:raise ValueError()
        result=json.loads(raw)
        if (set(result)!={'version','request_id','mapping_id','piq_client_id','profile_id','status'}
            or result['version']!='1' or result['request_id']!=data['request_id']
            or result['mapping_id']!=mapping.id or result['piq_client_id']!=mapping.piq_client_id
            or result['status'] not in ('draft','active','archived','deleted')):raise ValueError()
        UUID(result['profile_id'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503,'Copy could not be confirmed. Retry this same action to avoid duplicates.') from None
    service.log_event('historical_profile_copied',tenant_id=source.tenant_id,mapping_id=mapping.id)
    return result
