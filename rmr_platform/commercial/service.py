
from __future__ import annotations
import csv,datetime as dt,io,json,os,secrets,zipfile
from pathlib import Path
from sqlalchemy import inspect,text
from .models import ActivityEvent,Campaign,Message,Suppression,ExportJob,now
SENSITIVE_FRAGMENTS=('password','secret','token','credential','api_key','session','hash','cvv','cvc','card_number')
def event(db,tenant_id,event_type,actor=None,entity_type=None,entity_id=None,**data):
    e=ActivityEvent(tenant_id=str(tenant_id),event_type=event_type,actor_user_id=str(actor) if actor else None,entity_type=entity_type,entity_id=str(entity_id) if entity_id else None,campaign_id=data.pop('campaign_id',None),message_id=data.pop('message_id',None),crm_record_id=data.pop('crm_record_id',None),piq_record_id=data.pop('piq_record_id',None),data_json=json.dumps(data,default=str))
    db.add(e); return e
def is_suppressed(db,tenant,email): return db.query(Suppression).filter_by(tenant_id=str(tenant),email=email.lower(),active=True).first() is not None
def stop_on_reply(db,message,actor=None):
    message.reply_received_at=now(); message.status='REPLIED'; message.stopped_reason='REPLY_RECEIVED'
    event(db,message.tenant_id,'EMAIL_REPLY_RECEIVED',actor,'message',message.id,message_id=message.id,campaign_id=message.campaign_id,crm_record_id=message.crm_record_id,piq_record_id=message.piq_record_id)
    for m in db.query(Message).filter(Message.campaign_id==message.campaign_id,Message.recipient_email==message.recipient_email,Message.status.in_(['DRAFT','APPROVED','SCHEDULED'])).all(): m.status='STOPPED'; m.stopped_reason='REPLY_RECEIVED'
def export_tenant(bind,tenant_id,output_dir):
    output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True); eid=secrets.token_hex(12); path=output_dir/f'tenant-{tenant_id}-export-{eid}.zip'
    insp=inspect(bind); manifest={'tenant_id':str(tenant_id),'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'tables':{},'exclusions':['RMR source code','proprietary algorithms','internal security logs','other tenant data','provider secrets']}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for table in sorted(insp.get_table_names()):
            cols=[c['name'] for c in insp.get_columns(table)]
            if 'tenant_id' not in cols: continue
            safe=[c for c in cols if not any(f in c.lower() for f in SENSITIVE_FRAGMENTS)]
            if not safe: continue
            q='SELECT '+','.join('"'+c.replace('"','')+'"' for c in safe)+' FROM "'+table.replace('"','')+'" WHERE CAST(tenant_id AS TEXT)=:tenant'
            with bind.connect() as conn: rows=[dict(r._mapping) for r in conn.execute(text(q),{'tenant':str(tenant_id)})]
            buf=io.StringIO(); w=csv.DictWriter(buf,fieldnames=safe); w.writeheader()
            for r in rows: w.writerow({k:json.dumps(v,default=str) if isinstance(v,(dict,list)) else v for k,v in r.items()})
            z.writestr(f'data/{table}.csv',buf.getvalue()); manifest['tables'][table]=len(rows)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    return path,manifest
