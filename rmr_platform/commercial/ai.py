
from __future__ import annotations
import json, os, urllib.request
from .policy import scan_text
class AIMessageService:
    def __init__(self): self.mode=os.getenv('RMR_AI_MODE','safe-template')
    def generate(self,client,prospect,facts,research,purpose,tone='professional',cta='Would you be open to a brief conversation?'):
        facts=[str(x).strip() for x in (facts or []) if str(x).strip()]
        research=[str(x).strip() for x in (research or []) if str(x).strip()]
        context={'client':client,'prospect':prospect,'verified_facts':facts,'adaptive_research':research,'purpose':purpose,'tone':tone,'cta':cta}
        if self.mode=='openai-compatible' and os.getenv('RMR_AI_API_KEY'):
            return self._remote(context)
        name=prospect.get('contact_name') or 'there'; company=prospect.get('company_name') or 'your organization'
        support=(' I noticed '+facts[0].rstrip('.')+'.') if facts else ''
        subject=f"A quick idea for {company}"
        body=f"Hi {name},\n\n{client.get('company_name','Our team')} works with organizations like {company} to {purpose.strip().rstrip('.')}.{support}\n\n{cta}\n\nBest,\n{client.get('sender_name',client.get('company_name',''))}"
        return {'subject':subject,'body':body,'context':context,'human_review_required':True,'unsupported_claims_added':False,'provider':'safe-template'}
    def _remote(self,context):
        url=os.getenv('RMR_AI_BASE_URL','https://api.openai.com/v1')+'/chat/completions'
        prompt='Write one concise B2B email. Use only the supplied verified facts/research. Never invent a claim. Return JSON with subject and body. Context: '+json.dumps(context)
        payload=json.dumps({'model':os.getenv('RMR_AI_MODEL','gpt-5-mini'),'messages':[{'role':'system','content':'You produce factual, human-review-required outreach. Do not invent facts.'},{'role':'user','content':prompt}],'response_format':{'type':'json_object'}}).encode()
        req=urllib.request.Request(url,data=payload,headers={'Authorization':'Bearer '+os.environ['RMR_AI_API_KEY'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=45) as r: data=json.load(r)
        parsed=json.loads(data['choices'][0]['message']['content'])
        return {'subject':parsed['subject'],'body':parsed['body'],'context':context,'human_review_required':True,'unsupported_claims_added':False,'provider':'openai-compatible'}
