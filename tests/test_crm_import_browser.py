"""Real frontend modules + real import APIs, synthetic CLIENT_ADMIN and temp DB.

Run in the offline browser test image; never connects to the manual runtime.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy.orm import Session

from test_prospectiq_federation import federation_engine, fx
from test_launch1_crm_drip import app_client
from rmr_platform.models import Lead

playwright = pytest.importorskip('playwright.sync_api')
PUBLIC = Path(__file__).resolve().parents[1] / 'public'


@pytest.fixture
def browser_page(app_client, fx):
    calls, errors = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1200, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            request = route.request
            url = urlsplit(request.url)
            assert url.hostname == 'audit.test', 'No external requests allowed'
            if url.path.startswith('/api/'):
                calls.append((request.method, url.path))
                response = app_client.request(request.method, url.path, content=request.post_data,
                    headers={'Content-Type': 'application/json', 'X-RMR-Request': '1'})
                route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
            elif url.path.endswith('.js'):
                target = (PUBLIC / url.path.lstrip('/')).resolve()
                assert target.is_relative_to(PUBLIC)
                route.fulfill(content_type='application/javascript', body=target.read_text(encoding='utf-8'))
            else:
                route.fulfill(content_type='text/html', body='''<main id="page"></main><div id="modal-root"></div>
                  <script type="module">
                  import {state} from '/state.js';
                  import {renderV53ClientExperience} from '/pages/v53_client_experience.js';
                  window.auditState=state;
                  state.user={tenant_role:'CLIENT_ADMIN',global_role:'NONE'};
                  state.selectedTenantId=''' + json.dumps(fx.a.id) + ''';
                  const ctx={navigate:async route=>{
                    state.routeQuery=Object.fromEntries(new URLSearchParams(route.split('?')[1]||''));
                    await renderV53ClientExperience('crm',document.querySelector('#page'),ctx);
                  }};
                  await ctx.navigate('crm?tab=leads');
                  </script>''')
        page.route('**/*', serve)
        page.goto('http://audit.test/')
        page.locator('#v53-crm-import').click()
        yield page, calls
        assert not errors, errors
        assert all('/crm/' in path for _, path in calls), calls  # No AR/billing dependency.
        browser.close()


@pytest.mark.parametrize('format', ['upload_csv', 'paste_csv', 'paste_tabs'])
def test_client_admin_browser_preview_import_and_reload(browser_page, fx, format):
    page, calls = browser_page
    delimiter = '\t' if format == 'paste_tabs' else ','
    text = '\n'.join(delimiter.join(row) for row in [
        ['Business', 'Contact', 'Email', 'Phone'],
        ['Customer', 'Pat', 'pat@example.invalid', '123'],
        ['Duplicate', 'Pat', 'PAT@example.invalid', '123'],
        ['', 'Missing company', '', ''],
        ['Invalid', '', 'bad-email', ''],
    ])
    if format == 'upload_csv':
        page.locator('#crm-file').set_input_files({'name': 'customers.csv', 'mimeType': 'text/csv', 'buffer': text.encode()})
    else:
        page.locator('#crm-paste').fill(text)
    assert page.locator('#crm-commit').is_disabled()
    page.locator('#crm-map').click()
    playwright.expect(page.locator('[data-import-field="company_name"]')).to_have_value('0')
    page.locator('#crm-preview').click()
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('1 ready')
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('1 duplicates/skipped')
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('2 invalid')
    playwright.expect(page.locator('#crm-import-preview')).to_contain_text('Duplicate within this import')
    assert fx.db.query(Lead).count() == 0
    page.locator('#crm-commit').click()
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('Imported 1 lead(s)')
    assert page.locator('#crm-commit').is_disabled()
    page.get_by_text('View imported leads', exact=True).click()
    playwright.expect(page.locator('#v53-crm-content')).to_contain_text('pat@example.invalid')
    with Session(fx.engine) as db:
        lead = db.query(Lead).one()
        assert lead.tenant_id == fx.a.id and lead.company_name == 'Customer'
    assert [path.rsplit('/', 1)[-1] for method, path in calls if method == 'POST'] == ['import-preview', 'import']


def test_browser_mapping_change_invalidates_preview_and_tenant_switch_blocks(browser_page):
    page, calls = browser_page
    page.locator('#crm-paste').fill('Email,Business\npat@example.invalid,Customer')
    page.locator('#crm-map').click()
    page.locator('#crm-preview').click()
    playwright.expect(page.locator('#crm-commit')).to_be_enabled()
    page.locator('[data-import-field="email"]').select_option('')
    assert page.locator('#crm-commit').is_disabled()
    page.evaluate("window.auditState.selectedTenantId='other-tenant'")
    page.locator('#crm-preview').click()
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('Client changed')
    assert page.locator('#crm-commit').is_disabled()
    assert sum(method == 'POST' for method, _ in calls) == 1


def test_browser_invalid_only_cannot_commit(browser_page):
    page, _ = browser_page
    page.locator('#crm-paste').fill('Company,Email\nCustomer,invalid-email')
    page.locator('#crm-map').click()
    page.locator('#crm-preview').click()
    playwright.expect(page.locator('#crm-import-status')).to_contain_text('0 ready')
    assert page.locator('#crm-commit').is_disabled()
