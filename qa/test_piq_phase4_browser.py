"""Actual renderer regression with fixture-only HTTP; NOT DB concurrency proof.

The simulated ledger deliberately models sequential committed responses only.
The companion backend gate tests real SQLite concurrent row counts.
"""
import json
import sys

import pytest
from playwright.sync_api import expect
from test_piq_phase3_browser import MockApp, DEMO, ROOT

sys.path.insert(0, str(ROOT))
from piq_phase4_fixture import browser_payload

LIVE, LIVE_EVIDENCE = browser_payload()


class CrmMockApp(MockApp):
    def __init__(self, context, page):
        self.leads = []
        self.lose_response = False
        self.hold_moves = False
        self.pending_moves = []
        super().__init__(context, page)

    def route(self, route):
        if route.request.url.endswith('/profile') and self.opportunities[0]['provider'] == 'google_places':
            route.fulfill(status=200, content_type='application/json', body=json.dumps({
                'opportunity': self.opportunities[0], 'evidence': LIVE_EVIDENCE}))
            return
        if route.request.url.endswith('/move-to-crm'):
            self.move_calls += 1
            if self.hold_moves:
                self.pending_moves.append(route)
                return
            self.finish_move(route)
            return
        super().route(route)

    def finish_move(self, route):
        item = self.opportunities[0]
        created = not item['moved_to_crm']
        if created:
            self.leads.append({'company_name': item['company_name'], 'source': 'ProspectIQ', 'email': ''})
            item['moved_to_crm'] = True
        if self.lose_response:
            self.lose_response = False
            route.abort('connectionfailed')
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'created': created, 'opportunity': item}))

    @property
    def move_button(self):
        return self.page.locator('[data-move-piq]' if self.role == 'CLIENT_ADMIN' else '[data-piq-crm]')


@pytest.fixture
def app(browser):
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page(); page.set_default_timeout(8000)
    app = CrmMockApp(context, page)
    yield app
    assert not app.errors and not app.unexpected
    context.close()


@pytest.mark.parametrize('role', ['CLIENT_ADMIN', 'SALES_REP'])
@pytest.mark.parametrize('kind,label', [('live', 'Google Places'), ('demo', 'Demonstration'), ('legacy', 'Source not recorded'), ('import', 'Imported')])
def test_render_move_reload_and_no_second_action(app, role, kind, label):
    item = dict(LIVE if kind == 'live' else DEMO)
    if kind in ('legacy', 'import'):
        item['provider'] = None
    if kind == 'import':
        item['status'] = 'Imported'
    app.opportunities = [item]; app.start(role)
    expect(app.page.locator('#page')).to_contain_text(label)
    app.move_button.click()
    expect(app.move_button).to_have_count(0)
    assert app.move_calls == len(app.leads) == 1
    app.page.reload(wait_until='domcontentloaded')
    expect(app.page.locator('#page')).to_contain_text(item['company_name'])
    expect(app.page.locator('#page')).to_contain_text(label)
    expect(app.move_button).to_have_count(0)
    assert app.move_calls == len(app.leads) == 1


@pytest.mark.parametrize('role', ['CLIENT_ADMIN', 'SALES_REP'])
def test_live_detail_remains_honest_before_and_after_move(app, role):
    app.opportunities = [dict(LIVE)]; app.start(role)
    opener = app.page.locator('[data-open-piq]' if role == 'CLIENT_ADMIN' else '[data-piq-profile]')
    for moved in (False, True):
        opener.click()
        detail = app.page.locator('.modal')
        for value in ('Google Places', str(LIVE['score']), f"Confidence: {LIVE['confidence_score']}%",
                      f"Evidence completeness: {LIVE['evidence_completeness_pct']}%", 'Not estimated', LIVE_EVIDENCE[0]['fact']):
            expect(detail).to_contain_text(value)
        expect(detail).not_to_contain_text('$0')
        expect(detail).not_to_contain_text('@')
        expect(detail).not_to_contain_text('RAW_JSON_DO_NOT_RENDER')
        detail.locator('button[aria-label="Close"]').click()
        if not moved:
            app.move_button.click(); expect(app.move_button).to_have_count(0)
    assert app.move_calls == len(app.leads) == 1


@pytest.mark.parametrize('role', ['CLIENT_ADMIN', 'SALES_REP'])
def test_double_action_dispatch_and_sequential_response_handling(app, role):
    app.opportunities = [dict(LIVE)]; app.hold_moves = True; app.start(role)
    app.move_button.evaluate('(button) => {button.click(); button.click();}')
    # Flush browser event processing while the two requests remain held.
    app.page.wait_for_timeout(200)
    assert app.move_calls == len(app.pending_moves) == 1
    expect(app.move_button).to_be_disabled()
    # UI suppression complements (but does not replace) the real concurrency gate.
    for route in app.pending_moves:
        app.finish_move(route)
    expect(app.move_button).to_have_count(0)
    assert len(app.leads) == 1  # Simulated sequential ledger, not real DB.


@pytest.mark.parametrize('role', ['CLIENT_ADMIN', 'SALES_REP'])
def test_retry_after_committed_response_loss(app, role):
    app.opportunities = [dict(LIVE)]; app.lose_response = True; app.start(role)
    app.move_button.click()
    expect(app.page.locator('#toast-region')).not_to_be_empty()
    expect(app.move_button).to_have_count(1)
    assert len(app.leads) == app.move_calls == 1
    app.move_button.click(); expect(app.move_button).to_have_count(0)
    assert len(app.leads) == 1 and app.move_calls == 2
