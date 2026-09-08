from __future__ import annotations
from datetime import timedelta
import json, os, smtplib, threading, time
from email.message import EmailMessage
from sqlalchemy import select
from .db import SessionLocal
from . import cb1_models as m
from .cb1_services import decrypt, dumps, loads, utcnow

_stop=threading.Event(); _thread=None

def _send(connection,message):
    provider=connection.provider.upper()
    if provider=='MOCK': return 'mock-'+message.id
    cfg=loads(connection.config_json,{}) or {}
    if provider in {'SMTP','IMAP','SMTP_IMAP'}:
        cred=loads(decrypt(connection.credential_encrypted),{}) or {}
        host=cfg.get('smtp_host') or cred.get('smtp_host'); port=int(cfg.get('smtp_port') or cred.get('smtp_port') or 587)
        user=cred.get('username'); password=cred.get('password')
        if not host: raise RuntimeError('SMTP host is not configured.')
        msg=EmailMessage(); msg['From']=connection.sender_email; msg['To']=message.recipient_email; msg['Subject']=message.subject; msg.set_content(message.body_approved)
        with smtplib.SMTP(host,port,timeout=20) as smtp:
            if cfg.get('starttls',True): smtp.starttls()
            if user: smtp.login(user,password)
            smtp.send_message(msg)
        return msg.get('Message-ID') or 'smtp-'+message.id
    if provider in {'MICROSOFT','MICROSOFT365','OUTLOOK'}:
        import httpx
        token=decrypt(connection.token_encrypted)
        if not token: raise RuntimeError('Microsoft OAuth token is not configured.')
        payload={'message':{'subject':message.subject,'body':{'contentType':'Text','content':message.body_approved},'toRecipients':[{'emailAddress':{'address':message.recipient_email}}]},'saveToSentItems':True}
        r=httpx.post('https://graph.microsoft.com/v1.0/me/sendMail',headers={'Authorization':'Bearer '+token},json=payload,timeout=30); r.raise_for_status(); return 'ms-'+message.id
    if provider in {'GOOGLE','GMAIL','GOOGLE_WORKSPACE'}:
        import base64, httpx
        token=decrypt(connection.token_encrypted)
        if not token: raise RuntimeError('Google OAuth token is not configured.')
        raw=f'From: {connection.sender_email}\r\nTo: {message.recipient_email}\r\nSubject: {message.subject}\r\n\r\n{message.body_approved}'.encode()
        r=httpx.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',headers={'Authorization':'Bearer '+token},json={'raw':base64.urlsafe_b64encode(raw).decode().rstrip('=')},timeout=30); r.raise_for_status(); return r.json().get('id')
    raise RuntimeError('Unsupported provider: '+provider)

def tick():
    db=SessionLocal()
    try:
        now=utcnow(); state=db.get(m.CB1WorkerState,'drip-worker')
        if not state: state=m.CB1WorkerState(worker_name='drip-worker',status='HEALTHY',heartbeat_at=now); db.add(state)
        state.status='HEALTHY'; state.heartbeat_at=now; state.detail_json=dumps({'pid':os.getpid()}); db.commit()
        jobs=db.scalars(select(m.CB1DripJob).where(m.CB1DripJob.status=='QUEUED',m.CB1DripJob.due_at<=now).limit(25)).all()
        for job in jobs:
            try:
                message=db.get(m.CB1Message,job.message_id); campaign=db.get(m.CB1Campaign,job.campaign_id)
                if not message or not campaign or campaign.status not in {'ACTIVE','RUNNING'}: job.status='STOPPED'; job.last_error='Campaign inactive or message missing.'; continue
                if message.status not in {'APPROVED','SCHEDULED'}: job.status='STOPPED'; job.last_error='Message not approved.'; continue
                suppressed=db.scalar(select(m.CB1Suppression).where(m.CB1Suppression.tenant_id==message.tenant_id,m.CB1Suppression.email==message.recipient_email.lower()))
                if suppressed: message.status='SUPPRESSED'; message.stop_reason=suppressed.reason; job.status='STOPPED'; continue
                recent=db.scalar(select(m.CB1Message).where(m.CB1Message.tenant_id==message.tenant_id,m.CB1Message.recipient_email==message.recipient_email,m.CB1Message.sent_at>=now-timedelta(hours=campaign.frequency_hours),m.CB1Message.id!=message.id))
                if recent: job.due_at=recent.sent_at+timedelta(hours=campaign.frequency_hours); job.last_error='Frequency cap deferred send.'; continue
                conn=db.get(m.CB1ProviderConnection,campaign.provider_connection_id)
                if not conn or conn.status!='ACTIVE': job.last_error='Provider connection is not active.'; job.attempts+=1; job.due_at=now+timedelta(minutes=15); continue
                provider_id=_send(conn,message); message.provider_message_id=provider_id; message.sent_at=now; message.status='SENT'; job.status='COMPLETE'; job.updated_at=now
                db.add(m.CB1AuditEvent(tenant_id=message.tenant_id,event_type='EMAIL_SENT',object_type='message',object_id=message.id,detail_json=dumps({'crm_record_id':message.crm_record_id,'piq_record_id':message.piq_record_id,'recipient':message.recipient_email})))
            except Exception as exc:
                job.attempts+=1; job.last_error=str(exc); job.due_at=now+timedelta(minutes=min(60,5*max(1,job.attempts))); job.status='FAILED' if job.attempts>=5 else 'QUEUED'
            db.commit()
    finally: db.close()

def _loop():
    while not _stop.wait(5):
        try: tick()
        except Exception: pass

def start():
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear(); _thread=threading.Thread(target=_loop,name='rmr-cb1-drip-worker',daemon=True); _thread.start()
def stop(): _stop.set()
