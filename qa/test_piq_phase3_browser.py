"""Phase 3 release gate: actual ES modules/renderers, fully intercepted HTTP.

Run: python -B -m pytest qa/test_piq_phase3_browser.py -q -p no:cacheprovider
No server, login, seed data, or real provider is used. Historical gates stay frozen.
"""
from pathlib import Path
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='http://127.0.0.1:9876'
DEMO={'id':'demo-1','company_name':'Demo Prospect','provider':'demonstration','score':84,'evidence_count':2,
      'estimated_value_cents':500000,'signal':'Demo signal','status':'Priority','enhanced':False,'moved_to_crm':False}
LIVE={**DEMO,'id':'live-1','company_name':'Google Qualified Prospect','provider':'google_places','score':72,
      'base_match_score':72,'confidence_score':81,'evidence_completeness_pct':67,
      'estimated_value_cents':0,'phone':None,'website':None,'signal':'Observed Google signal'}


class MockApp:
    def __init__(self, context, page):
        self.context=context;self.page=page;self.role='CLIENT_ADMIN';self.mode='live';self.read_only=False
        self.calls=[];self.errors=[];self.unexpected=[];self.states=['queued','running','completed']
        self.active=False;self.failure_code='worker_error';self.post_error=0;self.poll_errors=[]
        self.opportunities=[dict(DEMO)];self.status_calls=0;self.list_calls=0;self.post_calls=0
        self.held=None;self.hold_status=False;self.evidence_state='confirmed';self.move_calls=0
        self.held_post=None;self.hold_post=False
        self.profiles=[{'id':'profile-a','name':'Saved Target','industries_json':['Mortgage Broker'],
                       'locations_json':['Phoenix, Arizona'],'keywords_json':['local'],'exclusions_json':[],
                       'employee_min':0,'employee_max':0,'revenue_min_cents':0,'active':True}]
        self.runs=[]
        context.route('**/*',self.route)
        page.on('pageerror',lambda error:self.errors.append(str(error)))

    @property
    def button(self):
        return self.page.locator('#v53-run-discovery' if self.role=='CLIENT_ADMIN' else '#run-discovery')

    def run(self,status='queued'):
        return {'run_id':'run-a','status':status,'provider_mode':'google_places','requested_count':6,
                'result_count':1 if status in ('completed','partial') else 0,'error_code':self.failure_code,
                'error_message':'SECRET_PROVIDER_BODY_DO_NOT_RENDER'}

    def html(self):
        user={'id':'mock-user','tenant_id':'tenant-a','tenant_role':self.role,'full_name':'Test User'}
        if self.role=='MANAGED':user.update(tenant_role=None,global_role='RMR_OWNER')
        styles=''.join(f'<link rel="stylesheet" href="/static/{name}">' for name in
                       ('styles.css','client-admin-correction.css','cumulative-product-repair.css','v53-experience.css','tenant-themes.css'))
        return f'''<!doctype html><html><head>{styles}</head><body>
        <div id="app"><main class="main-area"><div id="page"></div></main></div><div id="toast-region"></div><div id="modal-root"></div>
        <script type="module">
        import {{state}} from '/static/state.js';
        import {{renderUnifiedPage}} from '/static/pages/unified.js';
        window.state=state;state.user={json.dumps(user)};window.navigations=[];
        if({json.dumps(self.role)}==='MANAGED')sessionStorage.setItem('rmr_managed_session','managed-test-session');
        window.mount=async(tenant='tenant-a')=>{{state.route='piq';state.selectedTenantId=tenant;
          await renderUnifiedPage('piq',window.ctx,{str(self.read_only).lower()});window.ready=true;}};
        window.ctx={{navigate:route=>{{window.navigations.push(route);if(route==='piq')window.mount(state.selectedTenantId);
          else{{state.route=route;document.querySelector('#page').textContent='Other workspace';}}}}}};
        await window.mount();
        </script></body></html>'''

    def route(self, route):
        request=route.request;url=urlsplit(request.url);path=url.path
        if not request.url.startswith(ORIGIN+'/'):
            self.unexpected.append(request.url);route.abort();return
        if path=='/':route.fulfill(status=200,content_type='text/html',body=self.html());return
        if path.startswith('/static/'):
            file=(ROOT/'public'/path.removeprefix('/static/')).resolve()
            if not file.is_relative_to((ROOT/'public').resolve()) or not file.is_file():
                self.unexpected.append(path);route.abort();return
            kind='text/javascript' if file.suffix=='.js' else 'text/css' if file.suffix=='.css' else 'image/jpeg'
            route.fulfill(status=200,content_type=kind,body=file.read_bytes());return
        self.calls.append((request.method,path,request.headers))
        def reply(data,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(data))
        if '/target-profiles' in path:
            parts=path.split('/target-profiles',1)[1].strip('/').split('/')
            if parts==[''] and request.method=='GET':
                reply({'profiles':self.profiles,'can_write':not self.read_only and self.role not in ('EXECUTIVE_VIEWER','MARKETING_USER'),
                       'max_requested_count':50,'discovery_live':self.mode=='live','research_live':not getattr(self,'research_demo',False)})
            elif parts==[''] and request.method=='POST':
                payload=request.post_data_json
                profile={'id':'profile-'+str(len(self.profiles)+1),'active':True,
                         **{k+'_json' if k in ('industries','locations','keywords','exclusions') else k:v for k,v in payload.items()}}
                self.profiles.append(profile);reply({'profile':profile},201)
            elif parts[-1]=='runs':
                reply({'runs':self.runs})
            elif parts[-1]=='results':
                self.list_calls+=1
                reply({'opportunities':self.opportunities if '/tenant-a/' in path else []})
            else:
                profile=next(p for p in self.profiles if p['id']==parts[0])
                if request.method=='DELETE':
                    profile['active']=False;self.profiles.remove(profile);reply({'profile':profile,'archived':True})
                elif request.method=='PUT':
                    profile.update({k+'_json' if k in ('industries','locations','keywords','exclusions') else k:v for k,v in request.post_data_json.items()});reply({'profile':profile})
                else:reply({'profile':profile})
        elif path.endswith('/environment'):
            reply({'external_pi_q_dependency':{'discovery_provider':'demonstration'}})
        elif path.endswith('/target-profile'):
            reply({'profile':{'id':'profile-a','name':'Saved Target','industries_json':['Mortgage Broker'],
                              'locations_json':['Phoenix, Arizona'],'keywords_json':['local'],'active':True}})
        elif path.endswith('/discovery-runs/active'):
            reply({'run':self.run() if self.active and '/tenant-a/' in path else None})
        elif '/discovery-runs/' in path:
            self.status_calls+=1
            if self.hold_status:self.held=route;return
            if self.poll_errors:
                status=self.poll_errors.pop(0)
                if status==0:route.abort('connectionfailed');return
                reply({'detail':'SECRET_PROVIDER_BODY_DO_NOT_RENDER'},status);return
            status=self.states.pop(0) if len(self.states)>1 else self.states[0]
            if status in ('completed','partial','failed','cancelled'):self.active=False
            if status in ('completed','partial') and not any(row['id']=='live-1' for row in self.opportunities):
                self.opportunities.append(dict(LIVE))
            reply(self.run(status))
        elif path.endswith('/discover'):
            self.post_calls+=1
            if self.hold_post:self.held_post=route;return
            if self.post_error:reply({'detail':'SECRET_PROVIDER_BODY_DO_NOT_RENDER'},self.post_error);return
            if self.mode=='demo':
                self.opportunities.append({**DEMO,'id':'demo-2','company_name':'New Demo Prospect'})
                reply({'created':[self.opportunities[-1]],'provider_mode':'demonstration'});return
            self.active=True;reply(self.run(),202)
        elif path.endswith('/piq'):
            self.list_calls+=1;reply({'opportunities':self.opportunities if '/tenant-a/' in path else [],'read_only':False})
        elif path.endswith('/profile'):
            item=next(row for row in self.opportunities if row['id']==path.split('/')[-2])
            reply({'opportunity':item,'evidence':[{'provider':item['provider'],'evidence_type':'profile_criterion',
                   'fact':'Observed provider fact','source_name':'Google Places' if item['provider']=='google_places' else 'RMR Demo Provider',
                   'confidence_pct':90,'verified':True,'evidence_state':self.evidence_state,
                   'source_url':'https://maps.google.com/?cid=123','raw_json':{'secret':'RAW_JSON_DO_NOT_RENDER'}}]})
        elif path.endswith('/move-to-crm'):
            self.move_calls+=1
            item=next(row for row in self.opportunities if row['id']==path.split('/')[-2]);created=not item['moved_to_crm'];item['moved_to_crm']=True
            reply({'created':created,'opportunity':item})
        else:self.unexpected.append(path);reply({'detail':'Unexpected mocked request'},500)

    def start(self,role='CLIENT_ADMIN'):
        self.role=role;self.page.clock.install();self.page.goto(ORIGIN+'/#/piq',wait_until='domcontentloaded')
        self.page.wait_for_function('window.ready === true')
        if not self.read_only:expect(self.button).to_be_enabled() if not self.active else expect(self.button).to_be_disabled()

    def click(self):
        self.button.click();expect(self.page.locator('[data-piq-discovery-status]')).to_have_attribute('data-piq-discovery-status','queued')

    def step(self,state):
        self.page.clock.run_for(3100)
        if state in ('completed','partial'):
            expect(self.page.locator('#page')).to_contain_text('Google Qualified Prospect')
        else:expect(self.page.locator('[data-piq-discovery-status]')).to_have_attribute('data-piq-discovery-status',state)


@pytest.fixture
def app(browser):
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page();page.set_default_timeout(8000)
    app=MockApp(context,page)
    yield app
    assert not app.errors,app.errors
    assert not app.unexpected,app.unexpected
    context.close()


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP','MANAGED'])
def test_demo_synchronous_compatibility(app,role):
    app.mode='demo';app.start(role);app.button.click()
    expect(app.page.locator('#page')).to_contain_text('New Demo Prospect')
    expect(app.button).to_be_enabled()
    expected='1 prospects discovered using demonstration mode' if role=='CLIENT_ADMIN' else '1 prospects discovered'
    expect(app.page.locator('#toast-region')).to_contain_text(expected)
    assert app.post_calls==1 and app.status_calls==0 and app.list_calls==2


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP','VP_SALES','MANAGED'])
def test_live_happy_path_and_headers(app,role):
    app.start(role);app.click();expect(app.button).to_be_disabled()
    for status in ['queued','running','completed']:app.step(status)
    expect(app.button).to_be_enabled()
    assert app.post_calls==1 and app.list_calls==2 and app.status_calls==3
    post=next(row for row in app.calls if row[0]=='POST')
    assert post[2]['x-rmr-request']=='1' and post[2]['idempotency-key']
    if role=='MANAGED':assert post[2]['x-rmr-managed-session']=='managed-test-session'
    calls=app.status_calls;app.page.clock.run_for(15000);assert app.status_calls==calls
    expect(app.page.locator('#page')).to_contain_text('Saved Target')


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
def test_partial_results_are_retained_and_explicit(app,role):
    app.states=['running','partial'];app.start(role);app.click();app.step('running');app.step('partial')
    expect(app.page.locator('#toast-region')).to_contain_text('partial results')
    expect(app.button).to_be_enabled();assert app.list_calls==2


def test_retry_wait_then_completion(app):
    app.states=['retry_wait','running','completed'];app.start();app.click()
    app.step('retry_wait');expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('Retrying')
    app.step('running');app.step('completed')


@pytest.mark.parametrize(('code','message'),[
    ('invalid_configuration','not configured'),('provider_auth','authentication failed'),
    ('provider_timeout','timed out'),('provider_rate_limit','temporarily unavailable'),
    ('provider_5xx','temporarily unavailable'),('worker_error','could not be completed'),
])
def test_failure_stops_reenables_and_never_falls_back(app,code,message):
    app.failure_code=code;app.states=['failed'];app.start();app.click();app.step('failed')
    expect(app.button).to_be_enabled();expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text(message)
    expect(app.page.locator('body')).not_to_contain_text('SECRET_PROVIDER_BODY')
    assert app.post_calls==1 and app.list_calls==1 and len(app.opportunities)==1
    calls=app.status_calls;app.page.clock.run_for(15000);assert app.status_calls==calls


def test_cancelled_run_is_terminal(app):
    app.states=['cancelled'];app.start();app.click();app.step('cancelled')
    expect(app.button).to_be_enabled();assert app.list_calls==1


@pytest.mark.parametrize('status',[400,401,403,422,503])
def test_submission_error_is_safe_and_not_retried(app,status):
    app.post_error=status;app.start('SALES_REP');app.button.click()
    expect(app.button).to_be_enabled();expect(app.page.locator('#toast-region')).not_to_be_empty()
    expect(app.page.locator('body')).not_to_contain_text('SECRET_PROVIDER_BODY')
    assert app.post_calls==1 and app.status_calls==0


def test_duplicate_click_and_nonoverlapping_poll(app):
    app.start();app.button.evaluate('(button)=>{button.click();button.click();button.click();}')
    expect(app.button).to_be_disabled();app.page.wait_for_function("document.querySelector('[data-piq-discovery-status]').dataset.piqDiscoveryStatus==='queued'")
    assert app.post_calls==1
    app.hold_status=True;app.page.clock.run_for(3100);app.page.wait_for_timeout(50)
    assert app.status_calls==1
    app.page.clock.run_for(6000);assert app.status_calls==1
    app.held.fulfill(status=200,content_type='application/json',body=json.dumps(app.run('running')))
    expect(app.page.locator('[data-piq-discovery-status]')).to_have_attribute('data-piq-discovery-status','running')


def test_temporary_poll_failure_tolerated(app):
    app.poll_errors=[0];app.states=['completed'];app.start();app.click()
    app.page.clock.run_for(3100);expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('Connection interrupted')
    app.step('completed');assert app.status_calls==2


def test_three_poll_failures_stop_and_preserve_run(app):
    app.poll_errors=[503,503,503];app.start();app.click()
    for index in range(3):
        app.page.clock.run_for(3100)
        expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('temporarily unavailable' if index==2 else 'Connection interrupted')
    calls=app.status_calls;app.page.clock.run_for(15000);assert app.status_calls==calls
    expect(app.button).to_be_disabled();expect(app.page.get_by_role('button',name='Check discovery status')).to_be_visible()


def test_poll_403_is_not_retried(app):
    app.poll_errors=[403];app.start();app.click();app.page.clock.run_for(3100)
    expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('permission')
    app.page.clock.run_for(15000);assert app.status_calls==1


def test_missing_restored_run_clears_stale_session_record(app):
    app.poll_errors=[404];app.start();app.click();app.page.clock.run_for(3100)
    expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('no longer available')
    expect(app.button).to_be_enabled()
    assert app.page.evaluate("sessionStorage.getItem('rmr_piq_discovery:mock-user:tenant-a')") is None


def test_navigation_cleanup_and_return(app):
    app.start();app.click();app.page.evaluate("window.ctx.navigate('home')")
    calls=app.status_calls;app.page.clock.run_for(10000);assert app.status_calls==calls
    app.states=['running','completed'];app.page.evaluate('window.mount()')
    expect(app.button).to_be_disabled();expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('Finding matching')
    app.step('completed');assert app.post_calls==1


def test_reload_restores_run_without_resubmitting(app):
    app.start();app.click();app.states=['running','completed'];app.page.reload(wait_until='domcontentloaded')
    expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('Finding matching')
    app.step('completed');assert app.post_calls==1


def test_active_endpoint_restores_without_session_storage(app):
    app.active=True;app.states=['completed'];app.start();expect(app.button).to_be_disabled();app.step('completed')
    assert app.post_calls==0


def test_tenant_switch_does_not_poll_old_tenant(app):
    app.start();app.click();app.page.evaluate("window.mount('tenant-b')")
    expect(app.button).to_be_enabled();calls=app.status_calls;app.page.clock.run_for(15000)
    assert app.status_calls==calls
    expect(app.page.locator('#page')).not_to_contain_text('Google Qualified Prospect')


def test_ui_timeout_is_not_backend_failure(app):
    app.start();app.click();app.page.clock.fast_forward(300001)
    expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('still processing')
    expect(app.button).to_be_disabled();assert app.active
    calls=app.status_calls;app.page.clock.run_for(15000);assert app.status_calls==calls


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
@pytest.mark.parametrize('evidence_state',['confirmed','inferred','unresolved','contradicted'])
def test_real_prospect_display_and_safe_evidence(app,role,evidence_state):
    app.opportunities=[dict(LIVE)];app.evidence_state=evidence_state;app.start(role)
    expect(app.page.locator('#page')).to_contain_text('Google Places')
    expect(app.page.locator('#page')).to_contain_text('Not estimated')
    app.page.locator('[data-open-piq]' if role=='CLIENT_ADMIN' else '[data-piq-profile]').click()
    detail=app.page.locator('.modal');expect(detail).to_be_visible()
    for value in ['72','Confidence: 81%','Evidence completeness: 67%','Phone: Unknown','Website: Unknown',evidence_state.capitalize()]:
        expect(detail).to_contain_text(value)
    expect(detail).not_to_contain_text('RAW_JSON_DO_NOT_RENDER')
    expect(detail).not_to_contain_text('$0')
    if evidence_state in ('inferred','unresolved'):expect(detail).to_contain_text('not verified')
    source=detail.get_by_role('link',name='Source');expect(source).to_have_attribute('rel','noopener noreferrer')


def test_unsafe_website_is_not_linked(app):
    app.opportunities=[{**LIVE,'website':'javascript:alert(1)'}];app.start();app.page.locator('[data-open-piq]').click()
    expect(app.page.locator('.modal')).to_contain_text('Website: Unknown')
    assert app.page.locator('a[href^="javascript:"]').count()==0


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
def test_existing_move_to_crm_action_remains_connected(app,role):
    app.opportunities=[dict(LIVE)];app.start(role)
    app.page.locator('[data-move-piq]' if role=='CLIENT_ADMIN' else '[data-piq-crm]').click()
    expect(app.page.locator('#page')).to_contain_text('In CRM' if role=='CLIENT_ADMIN' else 'Google Qualified Prospect')
    assert app.move_calls==1 and app.opportunities[0]['moved_to_crm']


def test_managed_read_only_view_has_no_discovery_write_button(app):
    app.read_only=True;app.start('MANAGED');expect(app.button).to_have_count(0);assert app.post_calls==0


def test_uncertain_submission_retry_reuses_idempotency_key(app):
    app.post_error=503;app.start();app.button.click()
    expect(app.button).to_be_enabled();app.post_error=0;app.click()
    keys=[headers['idempotency-key'] for method,path,headers in app.calls if path.endswith('/discover')]
    assert len(keys)==2 and keys[0]==keys[1]


def test_conflicting_submission_reconciles_active_run(app):
    app.post_error=409;app.start();app.active=True;app.button.click()
    expect(app.page.locator('[data-piq-discovery-status]')).to_have_attribute('data-piq-discovery-status','queued')
    expect(app.button).to_be_disabled();assert app.post_calls==1


def test_conflicting_finished_request_does_not_lock_future_submissions(app):
    app.post_error=409;app.start();app.button.click()
    expect(app.button).to_be_enabled()
    app.post_error=0;app.click()
    keys=[headers['idempotency-key'] for method,path,headers in app.calls if path.endswith('/discover')]
    assert len(keys)==2 and keys[0]!=keys[1]


def test_leave_return_during_submission_captures_run_once(app):
    app.hold_post=True;app.start();app.button.click();app.page.wait_for_timeout(50)
    assert app.held_post is not None
    app.page.evaluate("window.ctx.navigate('home'); window.mount()")
    expect(app.button).to_be_disabled()
    app.active=True;app.states=['running','completed']
    app.held_post.fulfill(status=202,content_type='application/json',body=json.dumps(app.run()))
    expect(app.page.locator('[data-piq-discovery-status]')).to_contain_text('Finding matching')
    app.step('completed');assert app.post_calls==1


def test_stale_poll_response_cannot_update_another_tenant(app):
    app.hold_status=True;app.start();app.click();app.page.clock.run_for(3100);app.page.wait_for_timeout(50)
    assert app.held is not None
    app.page.evaluate("window.mount('tenant-b')")
    expect(app.button).to_be_enabled()
    app.held.fulfill(status=200,content_type='application/json',body=json.dumps(app.run('completed')))
    expect(app.page.locator('#page')).not_to_contain_text('Google Qualified Prospect')
    assert app.page.evaluate('state.selectedTenantId')=='tenant-b'
    assert app.page.evaluate('window.navigations.length')==0


@pytest.mark.parametrize('score',[0,100])
def test_live_score_extremes_and_missing_optional_metrics(app,score):
    app.opportunities=[{**LIVE,'score':score,'confidence_score':None,'evidence_completeness_pct':None}]
    app.start();app.page.locator('[data-open-piq]').click()
    expect(app.page.locator('.v53-score-large strong')).to_have_text(str(score))
    expect(app.page.locator('.modal')).to_contain_text('Confidence: Unknown')
    expect(app.page.locator('.modal')).to_contain_text('Evidence completeness: Unknown')


@pytest.mark.parametrize(('provider','status','label'),[(None,'Priority','Source not recorded'),(None,'Imported','Imported'),('demonstration','Priority','Demonstration')])
def test_legacy_provenance_is_not_invented(app,provider,status,label):
    app.opportunities=[{**DEMO,'provider':provider,'status':status}];app.start('SALES_REP')
    expect(app.page.locator('td small')).to_have_text(label)


def test_request_key_supports_browsers_without_random_uuid(app):
    app.start();app.page.evaluate("Object.defineProperty(crypto,'randomUUID',{value:undefined})")
    app.click()
    post=next(row for row in app.calls if row[0]=='POST')
    assert len(post[2]['idempotency-key'])==32
