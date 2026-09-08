"""Contract alignment: fake Responses/source pages, real isolated persistence; never live HTTP."""
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from fastapi import HTTPException
from rmr_platform.piq_models import PiqProfileMatch
from test_piq_phase5_research import (db, live, api, cfg, no_real_provider_network,
    engine, service, claim, response_for, pages, execute)


def snapshot():
    return {'target': {'id':'one','company_name':'Example Company','website':'https://example.com',
                       'location':'Phoenix, Arizona'},
            'tasks':[{'criterion':'employees','requested':{'min':2,'max':250}}]}


def task_response(s, claims, **updates):
    task={'criterion':'employees','status':'found' if claims else 'not_found', 'searched':True,
          'findings':claims,'search_summary':'FAKE_SECRET_DO_NOT_PERSIST raw reasoning must never be stored'}
    task.update(updates)
    r=response_for([])
    r['output'][1]['content'][0]['text']=json.dumps({'task_results':[task]})
    return r


def test_planner_skips_exclusion_and_unknown_without_changing_discovery(db,live,api,cfg):
    match=db.scalar(select(PiqProfileMatch).where(PiqProfileMatch.opportunity_id==live.opportunity.id))
    criteria=[{'criterion':key,'state':'unresolved','requested':value} for key,value in [
        ('industry',['Mortgage']),('geography',['Phoenix Metro, Arizona','Northern Colorado']),
        ('exclusion:0','direct residential real estate competitors'),('unsupported','unknown'),
        ('keyword:0','relocation'),('keyword:1','home buyer'),('employees',{'min':2,'max':250}),('revenue',50000000)]]
    match.criteria_result_json={'qualified':True,'criteria':criteria};db.commit()
    before=json.dumps(match.criteria_result_json,sort_keys=True)
    selected=service.snapshot_for(db,live.opportunity)['tasks']
    assert [t['criterion'] for t in selected]==['industry','geography','keyword:0','keyword:1']
    assert len(selected)==engine.MAX_TASKS==4
    assert json.dumps(match.criteria_result_json,sort_keys=True)==before
    assert criteria[2]['state']=='unresolved'


def test_only_unsupported_tasks_are_not_researchable(db,live,api,cfg):
    match=db.scalar(select(PiqProfileMatch).where(PiqProfileMatch.opportunity_id==live.opportunity.id))
    match.criteria_result_json={'qualified':True,'criteria':[{'criterion':'exclusion:0','state':'unresolved','requested':'competitor'}]}
    db.commit()
    with pytest.raises(HTTPException,match='No researchable criteria'):
        service.snapshot_for(db,live.opportunity)


def test_prompt_schema_and_limits():
    body=engine.request_body(snapshot(),'gpt-4.1-mini')
    schema=body['text']['format']['schema']
    assert schema['required']==['task_results']
    assert body['max_tool_calls']==1 and body['max_output_tokens']==1800 and not body['store']
    for term in ['full target address','literal','hostname','independently fetches','not_found','Do not invent evidence']:
        assert term in body['instructions']


@pytest.mark.parametrize('found',[False,True])
def test_structured_outcomes_and_sanitization(found):
    s=snapshot();claims=[claim(s)] if found else [];d=engine.new_diagnostics(s);fetches=[]
    def fetch(*args):fetches.append(1);return pages(s,claims)
    accepted,rejected=engine.validate_claims(task_response(s,claims),s,source_fetcher=fetch,diagnostics=d)
    assert len(accepted)==int(found) and rejected==0
    assert d['returned']==d['entering_validation']==d['accepted']==int(found)
    assert d['tasks'][0]['provider_outcome']==('found' if found else 'not_found')
    assert d['tasks'][0]['searched'] is True
    assert len(fetches)==int(found)
    assert 'FAKE_SECRET' not in json.dumps(d) and 'search_summary' not in json.dumps(d)


@pytest.mark.parametrize('case,reason,fetches',[
    ('entity','entity_mismatch',0),('domain','domain_mismatch',0),('location','location_mismatch',0),
    ('provenance','unsupported_provenance',0),('url','missing_url',0),
    ('fetch','source_fetch_failed',1),('quote','quotation_not_found',1),
    ('numeric','unsupported_numeric_source',1),('page_location','location_mismatch',1),
    ('duplicate','duplicate',1),('state','other_validation_failure',1),
])
def test_rejection_diagnostics_preserve_safety(case,reason,fetches):
    s=snapshot();c=claim(s)
    if case=='entity':c['entity_name']='FAKE_SECRET_WRONG_ENTITY'
    if case=='domain':c['source_url']='https://different.example/about'
    if case=='location':c['entity_location']='Another location'
    if case=='url':c['source_url']='javascript:alert(1)'
    if case=='numeric':c['quote']=c['fact']='Example Company has many employees in Phoenix, Arizona.'
    if case=='page_location':c['quote']=c['fact']='Example Company has 60 employees today.'
    if case=='state':c['contradiction']=True
    claims=[c,c] if case=='duplicate' else [c]
    response=task_response(s,claims)
    response['output'][0]['action']['sources']=[{'url':c['source_url']}] if case!='provenance' else []
    d=engine.new_diagnostics(s);calls=[]
    def fetch(*args):
        calls.append(1)
        return '' if case=='fetch' else 'Phoenix, Arizona unrelated text' if case=='quote' else c['quote'].replace('Phoenix, Arizona','') if case=='page_location' else pages(s,claims)
    accepted,rejected=engine.validate_claims(response,s,source_fetcher=fetch,diagnostics=d)
    assert rejected==1 and len(accepted)==int(case=='duplicate')
    assert d['reasons']=={reason:1} and d['tasks'][0]['reasons']=={reason:1}
    assert d['returned']==len(claims) and d['rejected']==1
    assert len(calls)==fetches and d['source_fetches']==fetches
    assert 'FAKE_SECRET' not in json.dumps(d) and c['source_url'] not in json.dumps(d)


@pytest.mark.parametrize('case',['bad_claim','found_empty','not_found_claim','unknown_task','duplicate_task','omitted_task','unsearched_found','bad_json','too_many'])
def test_malformed_contract_fails_closed(case):
    s=snapshot();c=claim(s);r=task_response(s,[c]);raw=json.loads(r['output'][1]['content'][0]['text'])
    t=raw['task_results'][0]
    if case=='bad_claim':t['findings'][0]['unsafe']='SECRET'
    if case=='found_empty':t['findings']=[]
    if case=='not_found_claim':t['status']='not_found'
    if case=='unknown_task':t['criterion']='SECRET'
    if case=='duplicate_task':raw['task_results'].append(dict(t))
    if case=='omitted_task':raw['task_results']=[]
    if case=='unsearched_found':t['searched']=False
    if case=='too_many':t['findings']=[c]*5
    r['output'][1]['content'][0]['text']='SECRET-not-json' if case=='bad_json' else json.dumps(raw)
    d=engine.new_diagnostics(s)
    with pytest.raises(engine.PiqProviderError,match='safely'):
        engine.validate_claims(r,s,source_fetcher=lambda *_:pytest.fail('must not fetch'),diagnostics=d)
    assert d['accepted']==d['entering_validation']==0 and 'malformed_claim' in d['reasons']
    if case=='too_many':assert d['returned']==d['rejected']==5
    assert 'SECRET' not in json.dumps(d)


@pytest.mark.parametrize('kind',['empty','rejected','accepted','malformed'])
def test_durable_summary_api_and_legacy_compatibility(db,live,api,cfg,monkeypatch,kind):
    def claims(s):
        if kind=='empty':return []
        c=claim(s)
        if kind=='rejected':c['entity_name']='SECRET_WRONG_COMPANY'
        if kind=='malformed':c['extra']='SECRET'
        return [c]
    run,_=execute(db,api,live,cfg,monkeypatch,claims=claims)
    expected={'empty':'no_findings','rejected':'findings_rejected','accepted':'accepted','malformed':'failed'}[kind]
    for _ in range(2):
        result=api.get(f'/api/piq/{live.opportunity.id}/adaptive-research/{run.id}').json()
        assert result['summary']['outcome']==expected
        assert 'SECRET' not in json.dumps(result)
        db.expire_all()
    if kind=='empty':
        run.diagnostics_json={'receipt':{'claims':[],'rejected':0,'status':'no_evidence','error_code':None}}
        db.commit()
        summary=service.safe_run(run)['summary']
        assert summary['returned']==summary['rejected']==0 and summary['tasks_researched'] is None
        assert summary['outcome']=='no_findings'


def test_structured_summary_no_reasoning_or_untrusted_reason_fields():
    s=snapshot();d=engine.new_diagnostics(s)
    engine.validate_claims(task_response(s,[]),s,diagnostics=d)
    d['reasons']['SECRET']=1
    run=SimpleNamespace(status='no_evidence',diagnostics_json={'receipt':{'claims':[],'rejected':0,'diagnostics':d}},input_snapshot_json={'snapshot':s})
    result=service.research_summary(run)
    assert result['tasks_researched']==1 and result['tasks_not_found']==1
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('kind',['empty','accepted','rejected','malformed'])
def test_new_contract_worker_persistence_and_fresh_api_read(db,live,api,cfg,monkeypatch,kind):
    s=service.snapshot_for(db,live.opportunity)
    c=claim(s)
    if kind=='rejected':c['entity_name']='SECRET_OTHER_ENTITY'
    if kind=='malformed':c['extra']='SECRET'
    claims=[] if kind=='empty' else [c]
    tasks=[{'criterion':t['criterion'],'status':'found' if claims and t['criterion']=='employees' else 'not_found',
            'searched':True,'findings':claims if t['criterion']=='employees' else [],
            'search_summary':'SECRET raw explanation never retained'} for t in s['tasks']]
    r=response_for([])
    r['output'][1]['content'][0]['text']=json.dumps({'task_results':tasks})
    run,_=execute(db,api,live,cfg,monkeypatch,claims=lambda _:claims,response_changes={'output':r['output']})
    assert run.status=={'empty':'no_evidence','accepted':'completed','rejected':'no_evidence','malformed':'failed'}[kind]
    before=json.dumps(run.diagnostics_json,sort_keys=True)
    assert 'SECRET' not in before and 'search_summary' not in before
    db.expire_all()
    result=api.get(f'/api/piq/{live.opportunity.id}/adaptive-research/{run.id}').json()
    summary=result['summary']
    assert summary['returned']==int(kind!='empty')
    assert summary['accepted']==int(kind=='accepted')
    assert summary['rejected']==int(kind in ('rejected','malformed'))
    assert json.dumps(run.diagnostics_json,sort_keys=True)==before
    if kind!='malformed':assert summary['tasks_researched']==len(s['tasks'])


def test_legacy_unsupported_criterion_still_rejected_without_fetch():
    s=snapshot();c=claim(s,criterion='unsupported');d=engine.new_diagnostics(s)
    accepted,rejected=engine.validate_claims(response_for([c]),s,diagnostics=d,
                                            source_fetcher=lambda *_:pytest.fail('must not fetch'))
    assert accepted==[] and rejected==1 and d['reasons']=={'unsupported_criterion':1}
