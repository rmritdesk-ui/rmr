"""Phase 5: actual API/worker/SQL, mocked HTTP, isolated temporary databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from rmr_platform import piq_worker as worker
from rmr_platform.models import EconomicTransaction, User, TenantService
from rmr_platform.piq_models import PiqResearchRun, PiqProfileMatch
from rmr_platform.unified_models import PiqEvidence, ManagedTenantSession
from rmr_platform.piq_engine import research as engine, research_service as service
from rmr_platform.piq_engine.contracts import PiqProviderError
from rmr_platform.routes import unified
from rmr_platform.routes.piq_research import ResearchConfirmation
from test_piq_phase4_crm_regression import db, live, api, login, qualified, move, count, no_real_provider_network


@pytest.fixture
def cfg(monkeypatch, db, api):
    config = SimpleNamespace(piq_live_research_enabled=True, piq_research_provider='openai',
        piq_research_web_search_enabled=True, piq_research_model='gpt-4.1-mini', ai_model='gpt-5-mini',
        ai_api_key='FAKE_TEST_KEY_NEVER_REAL', ai_base_url='https://api.openai.com/v1',
        piq_research_max_cost_usd=Decimal('.20'), piq_research_timeout_seconds=120,
        piq_job_max_attempts=3, piq_live_discovery_enabled=False)
    monkeypatch.setattr(unified, 'settings', config)
    monkeypatch.setattr(worker, 'settings', config)
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False))
    return config


def url(live):
    return f'/api/piq/{live.opportunity.id}/adaptive-research'


def estimate(api, live):
    login(api, live.user)
    response = api.post(url(live)+'/estimate', json={})
    assert response.status_code == 200, response.text
    return response.json()


def payload(estimate):
    return {k: estimate[k] for k in ('run_id', 'confirmation_token')}


def queued(api, live):
    e = estimate(api, live)
    r = api.post(url(live), json=payload(e))
    assert r.status_code == 202, r.text
    return e


def claim(snapshot, **updates):
    company = snapshot['target']['company_name']
    value = dict(criterion='employees', fact=f'{company} has 60 employees in Phoenix, Arizona.',
        entity_name=company, entity_location=snapshot['target']['location'], relationship='same_entity',
        source_url='https://example.com/about', source_title=f'About {company}',
        quote=f'{company} has 60 employees in Phoenix, Arizona.', confidence=90, state='confirmed',
        relevance='supports', contradiction=False)
    value.update(updates)
    return value


def response_for(claims, **updates):
    data = {'model':'gpt-4.1-mini-2025-04-14', 'service_tier':'default', 'status':'completed',
        'usage':{'input_tokens':1000, 'input_tokens_details':{'cached_tokens':100}, 'output_tokens':100},
        'output':[{'type':'web_search_call','status':'completed','action':{'sources':[{'url':'https://example.com/about'}]}},
                  {'type':'message','content':[{'type':'output_text','text':json.dumps({'claims':claims}), 'annotations':[]}]}]}
    data.update(updates)
    return data


def pages(snapshot, claims):
    return ' '.join(c['quote'] for c in claims)+' '+snapshot['target']['location']


def mock_http(monkeypatch, response=None, status=200, error=None):
    original = httpx.Client
    calls=[]
    def handler(request):
        assert request.url == 'https://api.openai.com/v1/responses'
        calls.append(json.loads(request.content))
        if error: raise error('FAKE_SECRET_PROVIDER_ERROR', request=request)
        return httpx.Response(status, json=response or {'error':'FAKE_SECRET_PROVIDER_ERROR'})
    monkeypatch.setattr(engine.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return calls


def execute(db, api, live, cfg, monkeypatch, *, claims=None, response_changes=None, http_status=200, error=None):
    e=queued(api, live)
    run=db.get(PiqResearchRun,e['run_id']);snapshot=run.input_snapshot_json['snapshot']
    claims=[claim(snapshot)] if claims is None else claims(snapshot)
    calls=mock_http(monkeypatch,response_for(claims, **(response_changes or {})),http_status,error)
    with worker.SessionLocal() as session:
        claimed=worker.claim_next_research_run(session,worker_id='test-worker')
        assert claimed.status=='running'
    service.process_research_run(run.id,run.tenant_id,'test-worker',adapter_factory=lambda c:engine.ResponsesResearchAdapter(c,source_fetcher=lambda *_:pages(snapshot,claims)))
    db.expire_all()
    return db.get(PiqResearchRun,run.id),calls


def test_estimate_nonce_cost_and_no_provider(db, live, api, cfg):
    e=estimate(api,live)
    assert e['estimated_cost_microusd']==engine.ATTEMPT_BOUND*3 and e['maximum_cost_microusd']==200000
    assert e['task_count']>0 and e['can_confirm']
    run=db.get(PiqResearchRun,e['run_id'])
    assert run.confirmation_token_hash != e['confirmation_token'] and run.confirmation_token_hash==engine.digest(e['confirmation_token'])
    assert cfg.ai_api_key not in json.dumps(e)


@pytest.mark.parametrize('field,value',[('piq_research_max_cost_usd',Decimal('.001')),('piq_research_model','unknown'),
    ('ai_api_key',''),('piq_research_provider','demonstration'),('piq_research_web_search_enabled',False),
    ('ai_base_url','https://other.invalid/v1')])
def test_estimate_config_fails_closed(db,live,api,cfg,field,value):
    setattr(cfg,field,value);login(api,live.user)
    assert api.post(url(live)+'/estimate',json={}).status_code==409
    assert count(db,PiqResearchRun)==0


@pytest.mark.parametrize('role,allowed',[('CLIENT_ADMIN',True),('VP_SALES',False),('SALES_MANAGER',False),('SALES_REP',False),('EXECUTIVE_VIEWER',False),('MARKETING_USER',False)])
def test_spend_roles(db,live,api,cfg,role,allowed):
    live.user.tenant_role=role;db.commit()
    e=estimate(api,live);assert e['can_confirm']==allowed
    assert api.post(url(live),json=payload(e)).status_code==(202 if allowed else 403)


@pytest.mark.parametrize('mode',['valid','read_only','expired','wrong_tenant','wrong_actor','ended','missing'])
def test_managed_write(db,live,api,cfg,mode):
    admin=User(email='research-admin@example.test',password_hash='test',full_name='Admin',global_role='RMR_OWNER')
    db.add(admin);db.commit()
    e=service.estimate(db,admin,live.opportunity.id,cfg)
    other=qualified(db,'research-other')
    managed=ManagedTenantSession(admin_user_id=other.user.id if mode=='wrong_actor' else admin.id,
        tenant_id=other.tenant.id if mode=='wrong_tenant' else live.tenant.id,
        access_type='read_only' if mode=='read_only' else 'managed_write',
        status='ended' if mode=='ended' else 'active',
        expires_at=service.now()+timedelta(minutes=-1 if mode=='expired' else 10),reason='test')
    db.add(managed);db.commit()
    login(api,admin,managed.id if mode!='missing' else None)
    r=api.post(url(live),json=payload(e))
    assert r.status_code==(202 if mode=='valid' else 403),r.text


@pytest.mark.parametrize('mode',['token','user','opportunity','tenant','expired','reuse','client_cost','config'])
def test_confirmation_binding(db,live,api,cfg,mode):
    e=estimate(api,live);body=payload(e);target=url(live)
    if mode=='token':body['confirmation_token']='x'*40
    if mode in ('user','tenant','opportunity'):
        other=qualified(db,'confirm-other')
        if mode=='user':other.user.tenant_id=live.tenant.id;db.commit();login(api,other.user)
        if mode=='tenant':login(api,other.user)
        if mode=='opportunity':target=url(other)
    if mode=='expired':
        run=db.get(PiqResearchRun,e['run_id']);run.confirmation_expires_at=service.now()-timedelta(seconds=1);db.commit()
    if mode=='reuse':assert api.post(target,json=body).status_code==202
    if mode=='client_cost':body['maximum_cost_microusd']=99999999
    if mode=='config':cfg.piq_research_max_cost_usd=Decimal('.30')
    assert api.post(target,json=body).status_code in (403,404,409,422)


def test_two_estimates_only_one_active_run(db,live,api,cfg):
    first,second=estimate(api,live),estimate(api,live)
    assert api.post(url(live),json=payload(first)).status_code==202
    assert api.post(url(live),json=payload(second)).status_code==409


def test_concurrent_confirmation(db,live,api,cfg):
    e=estimate(api,live)
    def start(_):
        with worker.SessionLocal() as session:
            user=session.get(User,live.user.id)
            try:
                service.confirm(session,user,live.opportunity.id,ResearchConfirmation(**payload(e)),cfg)
                return 202
            except Exception as exc:
                return getattr(exc,'status_code',500)
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes=list(pool.map(start,range(4)))
    assert sorted(codes)==[202,409,409,409]
    assert count(db,PiqResearchRun)==1


def test_entitlement_and_cross_tenant_status(db,live,api,cfg):
    e=queued(api,live);other=qualified(db,'status-other');login(api,other.user)
    assert api.get(url(live)+'/'+e['run_id']).status_code==404
    assert api.get(url(other)+'/'+e['run_id']).status_code==404
    login(api,live.user)
    entitlement=db.scalar(select(TenantService).where(TenantService.tenant_id==live.tenant.id,TenantService.service_code=='piq_access'))
    entitlement.status='inactive';db.commit()
    assert api.get(url(live)+'/'+e['run_id']).status_code==403
    assert api.post(url(live)+'/estimate',json={}).status_code==403


def test_no_researchable_criteria(db,live,api,cfg):
    match=db.scalar(select(PiqProfileMatch).where(PiqProfileMatch.opportunity_id==live.opportunity.id))
    match.criteria_result_json={'qualified':True,'criteria':[{'criterion':'industry','state':'confirmed'}]};db.commit();login(api,live.user)
    assert api.post(url(live)+'/estimate',json={}).status_code==409


def test_success_usage_evidence_base_and_crm(db,live,api,cfg,monkeypatch):
    base=live.opportunity.base_match_score
    google=list(db.scalars(select(PiqEvidence).where(PiqEvidence.provider=='google_places')))
    prior=[(e.id,e.fact,e.evidence_hash) for e in google]
    billed=count(db,EconomicTransaction)
    run,calls=execute(db,api,live,cfg,monkeypatch)
    assert run.status=='completed',run.error_code
    assert run.adaptive_score_delta==3 and live.opportunity.base_match_score==base
    db.refresh(live.opportunity)
    assert live.opportunity.score==base+3 and live.opportunity.adaptive_score_delta==3
    evidence=db.scalar(select(PiqEvidence).where(PiqEvidence.research_run_id==run.id))
    assert evidence.verified and not evidence.is_synthesized and evidence.source_domain=='example.com'
    assert run.actual_cost_microusd==25530 and run.usage_json['complete']
    assert calls[0]['store'] is False and calls[0]['max_tool_calls']==1
    assert calls[0]['tools'][0]['type']=='web_search_preview'
    assert calls[0]['text']['format']['strict']
    assert [(e.id,e.fact,e.evidence_hash) for e in google]==prior
    before=count(db,PiqEvidence)
    service.process_research_run(run.id,run.tenant_id,'test-worker')
    assert count(db,PiqEvidence)==before and count(db,EconomicTransaction)==billed
    assert move(api,live).status_code==200
    assert move(api,live).json()['created'] is False
    assert count(db)==1
    status=api.get(url(live)+'/'+run.id).json()
    assert 'receipt' not in json.dumps(status) and 'FAKE_TEST_KEY' not in json.dumps(status)


@pytest.mark.parametrize('case,status,delta',[
    ('empty','no_evidence',0),('wrong_entity','no_evidence',0),('url','no_evidence',0),
    ('no_source','no_evidence',0),('unsupported','no_evidence',0),('contradiction','completed',-4),
    ('duplicate','partial',3),('partial','partial',3),('malformed','failed',0),('unknown_usage','partial',3)])
def test_provider_cases(db,live,api,cfg,monkeypatch,case,status,delta):
    def claims(snapshot):
        c=claim(snapshot)
        if case=='empty':return []
        if case=='wrong_entity':c['entity_name']='Another Company'
        if case=='url':c['source_url']='javascript:alert(1)'
        if case=='unsupported':c['fact']=c['quote']=snapshot['target']['company_name']+' is a successful business with many employees.'
        if case=='contradiction':c['fact']=c['quote']=snapshot['target']['company_name']+' has 900 employees in Phoenix, Arizona.'
        if case=='malformed':c['rogue_field']='unsafe'
        return [c,c] if case=='duplicate' else [c]
    changes={}
    if case=='partial':changes['status']='incomplete'
    if case=='unknown_usage':changes['usage']=None
    if case=='no_source':
        snapshot=service.snapshot_for(db,live.opportunity)
        r=response_for(claims(snapshot));r['output'][0]['action']['sources']=[];changes['output']=r['output']
    run,calls=execute(db,api,live,cfg,monkeypatch,claims=claims,response_changes=changes)
    assert (run.status,run.adaptive_score_delta)==(status,delta),(run.status,run.error_code)
    assert len(calls)==1


@pytest.mark.parametrize('status,error,retry',[(429,None,True),(500,None,True),(503,None,True),(401,None,False),
    (403,None,False),(400,None,False),(200,httpx.ReadTimeout,True),(200,httpx.ConnectError,False)])
def test_provider_errors(db,live,api,cfg,monkeypatch,status,error,retry):
    run,calls=execute(db,api,live,cfg,monkeypatch,http_status=status,error=error)
    assert run.status==('retry_wait' if retry else 'failed')
    assert run.actual_cost_microusd is None
    assert run.usage_json['exposure_microusd']==engine.ATTEMPT_BOUND
    assert 'FAKE_SECRET' not in (run.error_message or '')


def test_usage_decimal_and_pricing():
    usage=engine.usage_from(response_for([]),'gpt-4.1-mini')
    assert usage['actual_cost_microusd']==25530
    response=response_for([]);response['usage']['input_tokens']=1;response['usage']['input_tokens_details']['cached_tokens']=0;response['usage']['output_tokens']=1
    assert engine.usage_from(response,'gpt-4.1-mini')['actual_cost_microusd']==25002


@pytest.mark.parametrize('effects,expected', [([3,3,3,3],10),([-4,-4,-4],-8),([],0),([1],1),([3],3),([-4],-4)])
def test_delta_bounds(effects,expected):
    assert engine.score_delta([{'criterion':str(i),'effect':e} for i,e in enumerate(effects)])==expected
    assert engine.score_delta([{'criterion':'same','effect':3}]*4)==3
    assert engine.score_delta([{'criterion':'same','effect':3},{'criterion':'same','effect':-4}])==-4


@pytest.mark.parametrize('bad',['http://example.com','https://127.0.0.1/x','https://[::1]/','https://u:p@example.com','file:///etc/passwd','https://example.com:8080','https://a.local/x','javascript:alert(1)'])
def test_unsafe_source_url(bad):
    assert not engine.safe_url(bad)


def test_demo_unchanged(db,live,api,cfg):
    cfg.piq_live_research_enabled=False
    assert estimate(api,live)=={'provider_mode':'demonstration'}
    r=api.post(url(live),json={})
    assert r.status_code==200 and r.json()['provider_mode']=='demonstration' and len(r.json()['facts'])==3
    assert count(db,PiqResearchRun)==0


def test_restart_reservation_and_retry_no_double_delta(db,live,api,cfg,monkeypatch):
    run,calls=execute(db,api,live,cfg,monkeypatch,error=httpx.ReadTimeout)
    with worker.SessionLocal() as session:
        claimed=worker.claim_next_research_run(session,worker_id='retry',now=service.now()+timedelta(seconds=10))
    snapshot=run.input_snapshot_json['snapshot'];claims=[claim(snapshot)]
    # Replace HTTP fixture while retaining real httpx.Client (patch context undo).
    adapter=SimpleNamespace(execute=lambda *_:{'usage':engine.usage_from(response_for(claims),cfg.piq_research_model),
        'claims':engine.validate_claims(response_for(claims),snapshot,source_fetcher=lambda *_:pages(snapshot,claims))[0],
        'rejected':0,'status':'completed','error_code':None})
    service.process_research_run(run.id,run.tenant_id,'retry',adapter_factory=lambda _:adapter)
    db.expire_all();run=db.get(PiqResearchRun,run.id)
    assert run.status=='completed' and len(run.usage_json['attempts'])==2
    assert run.actual_cost_microusd is None and run.usage_json['known_cost_microusd']==25530
    assert run.usage_json['exposure_microusd']==engine.ATTEMPT_BOUND+25530
    assert count(db,PiqEvidence)==5


def test_revoked_owner_stops_before_network(db,live,api,cfg):
    e=queued(api,live)
    live.user.tenant_role='SALES_REP';db.commit()
    worker.tick(worker_id='revoked')
    db.expire_all();run=db.get(PiqResearchRun,e['run_id'])
    assert run.status=='failed' and run.error_code=='research_access_revoked' and not run.usage_json


@pytest.mark.parametrize('case',['uncited','unfetched','wrong_location','third_party','vague','unrelated_quote','parent','negation'])
def test_source_attribution_rejections(db,live,case):
    snapshot=service.snapshot_for(db,live.opportunity);c=claim(snapshot)
    if case=='wrong_location':c['entity_location']='London'
    if case=='third_party':c['source_url']='https://unrelated.com/about'
    if case=='vague':c['fact']=c['quote']=snapshot['target']['company_name']+' has many employees and is growing.'
    if case=='unrelated_quote':c['fact']='This is unquoted model prose.'
    if case=='parent':c['fact']=c['quote']=snapshot['target']['company_name']+' says its parent has 60 employees.'
    if case=='negation':c['fact']=c['quote']=snapshot['target']['company_name']+' does not have 60 employees.'
    response=response_for([c])
    if case=='uncited':response['output'][0]['action']['sources']=[]
    accepted,rejected=engine.validate_claims(response,snapshot,source_fetcher=lambda *_:'' if case=='unfetched' else pages(snapshot,[c]))
    assert not accepted and rejected==1


def test_inferred_signal_requires_literal_requested_term(db,live):
    snapshot=service.snapshot_for(db,live.opportunity)
    snapshot['tasks'].append({'criterion':'keyword:0','requested':'local lending','state':'unresolved'})
    quote=snapshot['target']['company_name']+' provides local lending for its customers.'
    c=claim(snapshot,criterion='keyword:0',quote=quote,fact=quote,state='inferred',relevance='uncertain',confidence=60)
    accepted,rejected=engine.validate_claims(response_for([c]),snapshot,source_fetcher=lambda *_:pages(snapshot,[c]))
    assert not rejected and accepted[0]['state']=='inferred' and accepted[0]['effect']==1 and not accepted[0]['verified']


@pytest.mark.parametrize('base,employees,expected',[(99,60,100),(2,900,0)])
def test_final_score_clamp(db,live,api,cfg,monkeypatch,base,employees,expected):
    live.opportunity.base_match_score=base;live.opportunity.score=base;db.commit()
    def claims(snapshot):
        quote=snapshot['target']['company_name']+f' has {employees} employees in Phoenix, Arizona.'
        return [claim(snapshot,quote=quote,fact=quote)]
    run,_=execute(db,api,live,cfg,monkeypatch,claims=claims)
    db.refresh(live.opportunity)
    assert live.opportunity.score==expected and live.opportunity.base_match_score==base


def test_usage_bound_violation_records_cost_but_accepts_nothing(db,live,api,cfg,monkeypatch):
    run,_=execute(db,api,live,cfg,monkeypatch,response_changes={'usage':{'input_tokens':999999,'output_tokens':999999}})
    assert run.status=='failed' and run.error_code=='research_cost_bound_exceeded'
    assert run.actual_cost_microusd>200000 and count(db,PiqEvidence)==4


def test_profile_change_invalidates_confirmation(db,live,api,cfg):
    e=estimate(api,live);live.profile.name='Changed';db.commit()
    assert api.post(url(live),json=payload(e)).status_code==409


def test_lease_expiry_fences_late_result_and_reserves_unknown_cost(db,live,api,cfg):
    e=queued(api,live)
    with worker.SessionLocal() as session:
        run=worker.claim_next_research_run(session,worker_id='old')
    def execute_late(snapshot,config):
        with worker.SessionLocal() as session:
            r=session.get(PiqResearchRun,run.id);r.lease_expires_at=service.now()-timedelta(seconds=1);session.commit()
            worker.recover_expired_leases(session)
        return {'usage':engine.usage_from(response_for([]),cfg.piq_research_model),'claims':[],
                'rejected':0,'status':'no_evidence','error_code':None}
    service.process_research_run(run.id,run.tenant_id,'old',adapter_factory=lambda _:SimpleNamespace(execute=execute_late))
    db.expire_all();run=db.get(PiqResearchRun,e['run_id'])
    assert run.status=='retry_wait' and run.usage_json['exposure_microusd']==engine.ATTEMPT_BOUND
    assert run.actual_cost_microusd is None and count(db,PiqEvidence)==4


def test_durable_receipt_recovery_without_provider(db,live,api,cfg):
    e=queued(api,live)
    with worker.SessionLocal() as session:
        run=worker.claim_next_research_run(session,worker_id='old')
        snapshot=run.input_snapshot_json['snapshot'];claims=[claim(snapshot)]
        usage=engine.usage_from(response_for(claims),cfg.piq_research_model)
        accepted,_=engine.validate_claims(response_for(claims),snapshot,source_fetcher=lambda *_:pages(snapshot,claims))
        service.ledger(run,{'1':{'reserved_microusd':engine.ATTEMPT_BOUND,'usage':usage}})
        run.diagnostics_json={'receipt':{'usage':usage,'claims':accepted,'rejected':0,'status':'completed','error_code':None}}
        run.lease_expires_at=service.now()-timedelta(seconds=1);session.commit()
        worker.recover_expired_leases(session)
        worker.claim_next_research_run(session,worker_id='new')
    def forbidden(_):raise AssertionError('Receipt recovery must not call provider')
    service.process_research_run(run.id,run.tenant_id,'new',adapter_factory=forbidden)
    db.expire_all();run=db.get(PiqResearchRun,e['run_id'])
    assert run.status=='completed' and run.actual_cost_microusd==25530 and len(run.usage_json['attempts'])==1
    assert count(db,PiqEvidence)==5


def test_cross_run_evidence_hash_does_not_stack(db,live,api,cfg,monkeypatch):
    first,_=execute(db,api,live,cfg,monkeypatch)
    e=queued(api,live)
    snapshot=first.input_snapshot_json['snapshot'];claims=[claim(snapshot)]
    receipt={'usage':engine.usage_from(response_for(claims),cfg.piq_research_model),
        'claims':engine.validate_claims(response_for(claims),snapshot,source_fetcher=lambda *_:pages(snapshot,claims))[0],
        'rejected':0,'status':'completed','error_code':None}
    with worker.SessionLocal() as session:worker.claim_next_research_run(session,worker_id='again')
    service.process_research_run(e['run_id'],live.tenant.id,'again',adapter_factory=lambda _:SimpleNamespace(execute=lambda *_:receipt))
    db.expire_all()
    assert count(db,PiqEvidence)==5 and db.get(PiqResearchRun,e['run_id']).adaptive_score_delta==3


@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','::1'])
def test_source_dns_private_addresses_are_never_fetched(monkeypatch,address):
    import time
    monkeypatch.setattr(socket,'getaddrinfo',lambda *_args,**_kwargs:[(None,None,None,None,(address,443))])
    assert engine.fetch_source('https://example.com/about',time.monotonic()+5)==''


@pytest.mark.parametrize('status,content_type,body,accepted',[(200,'text/html',b'<p>Source text</p>',True),
    (302,'text/html',b'redirect',False),(200,'application/pdf',b'%PDF',False),
    (200,'text/html',b'x'*262145,False)])
def test_source_fetch_pins_address_bounds_and_no_redirect(monkeypatch,status,content_type,body,accepted):
    import time
    monkeypatch.setattr(socket,'getaddrinfo',lambda *_args,**_kwargs:[(None,None,None,None,('93.184.216.34',443))])
    original=httpx.Client
    def handler(request):
        assert request.url.host=='93.184.216.34' and request.headers['host']=='example.com'
        assert request.extensions['sni_hostname']=='example.com'
        assert 'authorization' not in request.headers
        return httpx.Response(status,headers={'content-type':content_type,'location':'http://127.0.0.1/'},content=body)
    monkeypatch.setattr(engine.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    assert bool(engine.fetch_source('https://example.com/about',time.monotonic()+5))==accepted


def test_model_fallback_and_timeout_lease(db,live,api,cfg):
    cfg.piq_research_model='';cfg.ai_model='gpt-4.1-mini';cfg.piq_research_timeout_seconds=900
    e=queued(api,live)
    with worker.SessionLocal() as session:
        start=service.now();run=worker.claim_next_research_run(session,worker_id='long')
        assert run.lease_expires_at.replace(tzinfo=start.tzinfo)>=start+timedelta(seconds=989)
    assert e['model']=='gpt-4.1-mini'


def test_cap_rounds_down_not_up(cfg):
    cfg.piq_research_max_cost_usd=Decimal('0.1220399')
    with pytest.raises(PiqProviderError):engine.configuration(cfg)


def test_malformed_envelope_preserves_known_usage(db,live,api,cfg,monkeypatch):
    run,_=execute(db,api,live,cfg,monkeypatch,response_changes={'output':[{'type':'web_search_call'},
        {'type':'message','content':[None]}]})
    assert run.status=='failed' and run.actual_cost_microusd==25530
    assert run.error_code=='research_schema_invalid'


def test_citations_without_search_are_not_evidence(db,live):
    snapshot=service.snapshot_for(db,live.opportunity);c=claim(snapshot);response=response_for([c])
    response['output']=response['output'][1:]
    response['output'][0]['content'][0]['annotations']=[{'type':'url_citation','url':c['source_url']}]
    accepted,rejected=engine.validate_claims(response,snapshot,source_fetcher=lambda *_:pages(snapshot,[c]))
    assert not accepted and rejected==1


@pytest.mark.parametrize('changes',[{'model':'unexpected-model'},{'service_tier':'priority'}])
def test_response_pricing_contract_mismatch_fails_closed(db,live,api,cfg,monkeypatch,changes):
    run,_=execute(db,api,live,cfg,monkeypatch,response_changes=changes)
    assert run.status=='failed' and run.error_code=='research_provider_contract_mismatch'
    assert run.actual_cost_microusd is None and count(db,PiqEvidence)==4
