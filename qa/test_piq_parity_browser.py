"""Parity UI checks; all HTTP intercepted, including real app.js boot dispatch."""
import json
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from qa.test_piq_phase3_browser import MockApp, LIVE, ORIGIN


class ParityApp(MockApp):
    full_boot=False

    def html(self):
        if not self.full_boot:return super().html()
        return '<!doctype html><div id="app"></div><div id="toast-region"></div><div id="modal-root"></div><script type="module" src="/static/app.js"></script>'

    def route(self, route):
        path=urlsplit(route.request.url).path
        def reply(data):route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        if not route.request.url.startswith(ORIGIN+'/'):return super().route(route)
        if self.full_boot:
            if path=='/api/setup/status':reply({'setup_required':False});return
            if path=='/api/auth/me':
                reply({'user':{'id':'pilot','tenant_id':'tenant-a','tenant_role':'CLIENT_ADMIN','full_name':'Kerry Client Administrator','email':'admin@kerry-real-estate.demo'}});return
            if path=='/api/tenants':reply({'tenants':[{'id':'tenant-a','name':'Kerry Real Estate'}]});return
            if path.endswith('/modules'):reply({'modules':[{'key':'piq','label':'ProspectIQ','enabled':True,'icon':'P'}],'services':[]});return
            if path.endswith('/theme'):reply({'theme':{'enabled':False}});return
        if path.endswith('/profile'):
            item=self.opportunities[0]
            reply({'opportunity':item,'research':item.get('research'),
                   'match':{'explanation':'Eligible deterministic match','scoring_version':'test-version',
                            'criteria_result_json':{'criteria':[{'criterion':'employees','requested':{'min':10},'observed':None,'state':'unresolved','score_effect':0,'reason':'Not available from Google'}]}},
                   'evidence':[{'provider':'openai_research','evidence_type':'adaptive_research','fact':'Source-backed team information',
                                'source_name':'First-party website','source_domain':'example.test','source_url':'https://example.test/team',
                                'profile_criterion':'employees','score_effect':3,'confidence_pct':80,'evidence_state':'inferred','verified':False,
                                'raw_json':{'reasoning':'RAW_REASONING_MUST_NOT_RENDER'}}]})
            return
        return super().route(route)


@pytest.fixture
def app(browser):
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page();page.set_default_timeout(6000)
    app=ParityApp(context,page)
    app.opportunities=[{**LIVE,'source_external_id':'ChIJ-parity-test','source_url':'https://maps.google.com/?cid=123',
        'research':{'eligible':True,'can_move':True,'mode':'live','latest':{'status':'no_evidence'}}}]
    yield app
    assert not app.errors and not app.unexpected,(app.errors,app.unexpected)
    context.close()


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
@pytest.mark.parametrize('enhanced',[False,True])
def test_lead_intelligence_criteria_provenance_and_accepted_evidence(app,role,enhanced):
    app.opportunities[0]['enhanced']=enhanced
    app.start(role)
    app.page.locator('[data-open-piq]' if role=='CLIENT_ADMIN' else '[data-piq-profile]').click()
    detail=app.page.locator('#modal-root')
    for text in ['ChIJ-parity-test','employees · unresolved','Unresolved discovery criteria: employees',
                 'Criterion: employees','example.test','Criterion effect: +3','Inferred · not verified',
                 'Base Match: 72','Research Adjustment: +0','Final Match: 72','Not estimated','no accepted evidence']:
        expect(detail).to_contain_text(text)
    expect(detail).not_to_contain_text('RAW_REASONING_MUST_NOT_RENDER')
    expect(detail.locator('a[href="https://example.test/team"]')).to_have_attribute('rel','noopener noreferrer')
    expect(detail.get_by_role('button',name='Run Adaptive Research')).to_be_visible()


def test_no_evidence_has_no_conflicting_available_label(app):
    app.start()
    expect(app.page.locator('[data-piq-research-summary]')).to_contain_text('no accepted evidence')
    app.page.reload(wait_until='domcontentloaded')
    expect(app.page.locator('[data-piq-research-summary]')).not_to_contain_text('Available')
    app.page.locator('[data-open-piq]').click()
    expect(app.page.locator('#modal-root')).not_to_contain_text('Available')


@pytest.mark.parametrize('role',['MARKETING_USER','EXECUTIVE_VIEWER','SALES_MANAGER','SALES_REP'])
def test_role_capability_rendering(app,role):
    app.read_only=role in ('MARKETING_USER','EXECUTIVE_VIEWER')
    app.start(role)
    expect(app.page.locator('#piq-create-profile')).to_have_count(0 if app.read_only else 1)
    expect(app.page.locator('[data-piq-crm]')).to_have_count(0 if app.read_only else 1)


def test_actual_app_boot_dispatches_client_admin_to_current_workflow(app):
    app.full_boot=True
    app.page.goto(ORIGIN+'/#/piq',wait_until='networkidle')
    expect(app.page.locator('#page')).to_have_class('main-content v53-client-page')
    expect(app.page.locator('#piq-create-profile')).to_be_visible()
    expect(app.page.locator('#v53-run-discovery')).to_have_text('Pull Leads')
    expect(app.page.locator('#piq-quantity option')).to_have_text(['10','20','30','40','50','Custom'])
    expect(app.page.locator('.v53-provider-banner')).to_contain_text('Live Google Places · Live OpenAI Adaptive Research')
    expect(app.page.get_by_role('button',name='Run Discovery',exact=True)).to_have_count(0)
    expect(app.page.get_by_role('button',name='Enhance',exact=True)).to_have_count(0)
    expect(app.page.locator('[data-open-piq]')).to_be_visible()
    assert app.post_calls==app.move_calls==0
