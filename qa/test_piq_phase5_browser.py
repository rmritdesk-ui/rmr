"""Actual browser modules; all API/provider traffic intercepted, no app DB."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from qa.test_piq_phase3_browser import MockApp, ORIGIN, LIVE


def test_server_backed_active_research_restores_without_session_storage(app):
    app.opportunities[0]["research"]={"eligible":False,"reason":"Research is already in progress",
                                    "latest":app.research("running")}
    app.research_states=["running","completed"]
    app.start()
    expect(app.page.locator("[data-piq-research-status]")).to_have_attribute("data-piq-research-status","queued")
    app.page.clock.run_for(3100)
    expect(app.page.locator("[data-piq-research-status]")).to_have_attribute("data-piq-research-status","running")
    app.opportunities[0]["research"]["latest"]=app.research("completed")
    app.page.clock.run_for(3100)
    expect(app.page.locator("[data-research-outcome]")).to_contain_text("Adaptive Research completed")
    assert app.estimates==app.confirmations==0
    calls=app.research_polls;app.page.clock.run_for(10000)
    assert app.research_polls==calls


class ResearchApp(MockApp):
    def __init__(self, context, page):
        super().__init__(context,page)
        self.opportunities=[dict(LIVE)]
        self.research_states=['queued','running','completed']
        self.estimates=0;self.confirmations=0;self.research_polls=0
        self.research_demo=False;self.can_confirm=True;self.confirm_error=0;self.research_poll_error=0
        self.extra_evidence=[];self.lost_response=False

    def research(self,status):
        return {'run_id':'research-a','opportunity_id':'live-1','status':status,'provider':'openai',
            'provider_mode':'live','model':'gpt-4.1-mini','estimated_cost_microusd':122040,
            'maximum_cost_microusd':200000,'task_count':3,'confirmation_token':'test-nonce-not-for-storage',
            'can_confirm':self.can_confirm,'error_message':'DO_NOT_RENDER_PROVIDER_SECRET'}

    def route(self,route):
        path=urlsplit(route.request.url).path
        def reply(data,status=200):route.fulfill(status=status,content_type='application/json',body=json.dumps(data))
        if not route.request.url.startswith(ORIGIN+'/'):return super().route(route)
        if '/adaptive-research' in path:
            self.calls.append((route.request.method,path,route.request.headers))
            if path.endswith('/estimate'):
                self.estimates+=1
                reply({'provider_mode':'demonstration'} if self.research_demo else self.research('awaiting_confirmation'));return
            if path.endswith('/adaptive-research'):
                self.confirmations+=1
                if self.confirm_error:reply({'detail':'DO_NOT_RENDER_PROVIDER_SECRET'},self.confirm_error);return
                if self.research_demo:
                    self.opportunities[0]['enhanced']=True;reply({'provider_mode':'demonstration'});return
                assert route.request.post_data_json=={'run_id':'research-a','confirmation_token':'test-nonce-not-for-storage'}
                if self.lost_response:route.abort('connectionfailed');return
                reply(self.research('queued'),202);return
            self.research_polls+=1
            if self.research_poll_error:reply({'detail':'DO_NOT_RENDER_PROVIDER_SECRET'},self.research_poll_error);return
            status=self.research_states.pop(0) if len(self.research_states)>1 else self.research_states[0]
            if status in ('completed','partial'):
                self.opportunities[0].update(score=75,adaptive_score_delta=3,enhanced=True)
                self.extra_evidence=[{'provider':'openai_research','evidence_type':'adaptive_research','fact':'Sourced research evidence',
                    'source_name':'First-party public website / OpenAI research','confidence_pct':90,'verified':True,
                    'evidence_state':'confirmed','source_url':'https://example.com/about'}]
            reply(self.research(status));return
        if path.endswith('/profile') and self.extra_evidence:
            reply({'opportunity':self.opportunities[0],'evidence':self.extra_evidence});return
        return super().route(route)

    def open_research(self):
        if self.role=='CLIENT_ADMIN':self.page.locator('[data-research-piq="live-1"]').click()
        else:
            self.page.locator('[data-piq-profile="live-1"]').click()
            self.page.locator('#adaptive-research').click()

    def confirm(self):
        self.page.locator('#confirm-adaptive-research').click()
        expect(self.page.locator('[data-piq-research-status]')).to_have_attribute('data-piq-research-status','queued')


@pytest.fixture
def app(browser):
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page();page.set_default_timeout(8000)
    app=ResearchApp(context,page)
    yield app
    assert not app.errors,app.errors
    assert not app.unexpected,app.unexpected
    context.close()


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP','MANAGED'])
def test_estimate_and_cancel(app,role):
    app.start(role);app.open_research()
    expect(app.page.locator('#modal-root')).to_contain_text('Estimated provider usage cost')
    expect(app.page.locator('#modal-root')).to_contain_text('$0.122040')
    expect(app.page.locator('#modal-root')).to_contain_text('not a customer charge')
    app.page.locator('#modal-root button[data-close-modal]').last.click()
    assert app.estimates==1 and app.confirmations==0


@pytest.mark.parametrize('terminal',['completed','no_evidence','partial','failed','expired','cancelled'])
def test_queued_running_terminal(app,terminal):
    app.research_states=['running',terminal]
    app.start();app.open_research();app.confirm()
    app.page.clock.run_for(3100)
    expect(app.page.locator('[data-piq-research-status]')).to_have_attribute('data-piq-research-status','running')
    app.page.clock.run_for(3100)
    expected={'completed':'Adaptive Research completed.','no_evidence':'Research completed with no accepted evidence. Detailed outcome counts are unavailable.',
        'partial':'Research completed with partial results.','failed':'Adaptive Research could not be completed.',
        'expired':'Research confirmation expired.','cancelled':'Adaptive Research was cancelled.'}[terminal]
    expect(app.page.locator('#toast-region')).to_contain_text(expected)
    assert app.confirmations==1
    expect(app.page.locator('body')).not_to_contain_text('DO_NOT_RENDER_PROVIDER_SECRET')


def test_refresh_components_and_evidence(app):
    app.research_states=['completed'];app.start();app.open_research();app.confirm();app.page.clock.run_for(3100)
    expect(app.page.locator('.v53-prospect-score')).to_contain_text('75')
    app.page.locator('[data-open-piq="live-1"]').click()
    expect(app.page.locator('#modal-root')).to_contain_text('Base Match: 72')
    expect(app.page.locator('#modal-root')).to_contain_text('Research Adjustment: +3')
    expect(app.page.locator('#modal-root')).to_contain_text('Final Match: 75')
    expect(app.page.locator('#modal-root')).to_contain_text('Adaptive Research evidence')
    expect(app.page.locator('#modal-root a[href="https://example.com/about"]')).to_have_attribute('rel','noopener noreferrer')


def test_sales_cannot_confirm(app):
    app.can_confirm=False;app.start('SALES_REP');app.open_research()
    expect(app.page.locator('#confirm-adaptive-research')).to_be_disabled()
    assert app.confirmations==0


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
def test_demo_research(app,role):
    app.research_demo=True;app.start(role);app.open_research()
    expect(app.page.locator('#toast-region')).to_contain_text('Research completed in demonstration mode')
    assert app.confirmations==1 and app.research_polls==0


def test_retry_wait(app):
    app.research_states=['retry_wait','completed'];app.start();app.open_research();app.confirm()
    app.page.clock.run_for(3100)
    expect(app.page.locator('[data-piq-research-status]')).to_contain_text('Retrying')
    app.page.clock.run_for(3100)
    expect(app.page.locator('#toast-region')).to_contain_text('Adaptive Research completed.')


def test_navigation_restore_no_respend(app):
    app.research_states=['running'];app.start();app.open_research();app.confirm()
    app.page.evaluate("ctx.navigate('crm')");app.page.clock.run_for(3100)
    assert app.research_polls==0
    app.page.evaluate('window.mount()')
    expect(app.page.locator('[data-piq-research-status]')).to_be_visible()
    app.page.clock.run_for(3100)
    expect(app.page.locator('[data-piq-research-status]')).to_have_attribute('data-piq-research-status','running')
    assert app.confirmations==1
    assert 'test-nonce' not in app.page.evaluate('JSON.stringify(sessionStorage)')


def test_lost_start_response_reconciles(app):
    app.lost_response=True;app.research_states=['completed'];app.start();app.open_research();app.confirm()
    app.page.clock.run_for(3100)
    expect(app.page.locator('#toast-region')).to_contain_text('Adaptive Research completed.')
    assert app.confirmations==1


@pytest.mark.parametrize('status',[401,403,404,500])
def test_safe_poll_errors(app,status):
    app.research_poll_error=status;app.start();app.open_research();app.confirm()
    for index in range(3 if status==500 else 1):
        app.page.clock.run_for(3100)
        app.page.wait_for_function('true')
        if status==500:
            app.page.wait_for_timeout(50)
    if status==500:
        expect(app.page.locator('[data-piq-research-status]')).to_contain_text('could not be refreshed')
    expect(app.page.locator('body')).not_to_contain_text('DO_NOT_RENDER_PROVIDER_SECRET')
    assert app.research_polls==(3 if status==500 else 1)


def test_expired_confirmation(app):
    app.confirm_error=409;app.start();app.open_research();app.page.locator('#confirm-adaptive-research').click()
    expect(app.page.locator('#toast-region')).to_contain_text('Research confirmation expired or changed')
    assert app.research_polls==0
