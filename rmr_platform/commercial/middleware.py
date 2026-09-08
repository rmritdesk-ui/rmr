
from fastapi import Request
from fastapi.responses import JSONResponse
from .policy import scan_text
async def restricted_data_middleware(request:Request,call_next):
    if request.method in ('POST','PUT','PATCH') and any(x in request.url.path for x in ('/api/commercial','/api/crm','/api/leads','/api/contacts','/api/accounts')):
        try:
            body=await request.body(); text=body.decode('utf-8','ignore'); findings=scan_text(text)
            async def receive(): return {'type':'http.request','body':body,'more_body':False}
            request._receive=receive
            blockers=[x for x in findings if x['severity']=='BLOCK']
            if blockers: return JSONResponse(status_code=422,content={'detail':'Prohibited or restricted data detected. Do not submit full card data, credentials, or secrets in general-purpose fields.','findings':blockers})
        except Exception: pass
    return await call_next(request)
