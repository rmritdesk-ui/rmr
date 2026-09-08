
from __future__ import annotations
import base64,email,imaplib,json,os,smtplib,ssl,urllib.parse,urllib.request,uuid
from email.message import EmailMessage
class ProviderError(RuntimeError): pass
class BaseAdapter:
    def __init__(self,credentials): self.c=credentials or {}
    def send(self,message): raise NotImplementedError
    def sync(self,since=None): return []
class MockAdapter(BaseAdapter):
    def send(self,message): return {'provider_message_id':'mock-'+str(uuid.uuid4()),'status':'sent'}
    def sync(self,since=None): return []
class MicrosoftGraphAdapter(BaseAdapter):
    AUTH='https://login.microsoftonline.com/common/oauth2/v2.0/authorize'; TOKEN='https://login.microsoftonline.com/common/oauth2/v2.0/token'; API='https://graph.microsoft.com/v1.0'
    @classmethod
    def auth_url(cls,client_id,redirect_uri,state):
        q={'client_id':client_id,'response_type':'code','redirect_uri':redirect_uri,'response_mode':'query','scope':'offline_access openid profile email Mail.Send Mail.Read','state':state}
        return cls.AUTH+'?'+urllib.parse.urlencode(q)
    def send(self,m):
        if os.getenv('RMR_PROVIDER_MODE','mock')=='mock': return MockAdapter(self.c).send(m)
        token=self.c['access_token']; payload={'message':{'subject':m['subject'],'body':{'contentType':'Text','content':m['body']},'toRecipients':[{'emailAddress':{'address':m['recipient_email']}}], 'internetMessageHeaders':[{'name':'X-RMR-Message-ID','value':m['id']}]},'saveToSentItems':True}
        req=urllib.request.Request(self.API+'/me/sendMail',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=30) as r: return {'provider_message_id':r.headers.get('request-id') or str(uuid.uuid4()),'status':'sent'}
class GoogleGmailAdapter(BaseAdapter):
    AUTH='https://accounts.google.com/o/oauth2/v2/auth'; TOKEN='https://oauth2.googleapis.com/token'; API='https://gmail.googleapis.com/gmail/v1'
    @classmethod
    def auth_url(cls,client_id,redirect_uri,state):
        q={'client_id':client_id,'response_type':'code','redirect_uri':redirect_uri,'scope':'openid email https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly','access_type':'offline','prompt':'consent','state':state}
        return cls.AUTH+'?'+urllib.parse.urlencode(q)
    def send(self,m):
        if os.getenv('RMR_PROVIDER_MODE','mock')=='mock': return MockAdapter(self.c).send(m)
        em=EmailMessage(); em['To']=m['recipient_email']; em['Subject']=m['subject']; em['X-RMR-Message-ID']=m['id']; em.set_content(m['body'])
        raw=base64.urlsafe_b64encode(em.as_bytes()).decode().rstrip('=')
        req=urllib.request.Request(self.API+'/users/me/messages/send',data=json.dumps({'raw':raw}).encode(),headers={'Authorization':'Bearer '+self.c['access_token'],'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=30) as r: d=json.load(r); return {'provider_message_id':d.get('id'), 'status':'sent'}
class SMTPIMAPAdapter(BaseAdapter):
    def send(self,m):
        if os.getenv('RMR_PROVIDER_MODE','mock')=='mock': return MockAdapter(self.c).send(m)
        msg=EmailMessage(); msg['From']=self.c['from_email']; msg['To']=m['recipient_email']; msg['Subject']=m['subject']; msg['X-RMR-Message-ID']=m['id']; msg.set_content(m['body'])
        host=self.c['smtp_host']; port=int(self.c.get('smtp_port',587)); ctx=ssl.create_default_context()
        if self.c.get('smtp_ssl'):
            s=smtplib.SMTP_SSL(host,port,context=ctx,timeout=30)
        else:
            s=smtplib.SMTP(host,port,timeout=30); s.ehlo(); s.starttls(context=ctx); s.ehlo()
        try: s.login(self.c['username'],self.c['password']); s.send_message(msg)
        finally: s.quit()
        return {'provider_message_id':msg['Message-ID'] or 'smtp-'+str(uuid.uuid4()),'status':'sent'}
    def sync(self,since=None):
        if os.getenv('RMR_PROVIDER_MODE','mock')=='mock': return []
        M=imaplib.IMAP4_SSL(self.c['imap_host'],int(self.c.get('imap_port',993))); M.login(self.c['username'],self.c['password']); M.select('INBOX')
        typ,data=M.search(None,'UNSEEN'); out=[]
        for num in (data[0].split() if data and data[0] else []):
            typ,msgdata=M.fetch(num,'(RFC822)'); raw=msgdata[0][1]; em=email.message_from_bytes(raw)
            out.append({'message_id':em.get('Message-ID'),'in_reply_to':em.get('In-Reply-To'),'from':em.get('From'),'subject':em.get('Subject'),'body':''})
        M.logout(); return out
ADAPTERS={'MICROSOFT':MicrosoftGraphAdapter,'GOOGLE':GoogleGmailAdapter,'SMTP_IMAP':SMTPIMAPAdapter,'MOCK':MockAdapter}
def adapter(provider,credentials):
    try: return ADAPTERS[provider.upper()](credentials)
    except KeyError: raise ProviderError('Unsupported provider')
