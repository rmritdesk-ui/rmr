"""Real frontend modules + real import APIs, synthetic CLIENT_ADMIN and temp DB.

Run in the offline browser test image; never connects to the manual runtime.
"""
import json
import re
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
            elif url.path.endswith('.css'):
                target = (PUBLIC / url.path.lstrip('/')).resolve()
                assert target.is_relative_to(PUBLIC)
                route.fulfill(content_type='text/css', body=target.read_text(encoding='utf-8'))
            else:
                route.fulfill(content_type='text/html', body='''<meta charset="utf-8"><link rel="stylesheet" href="/styles.css">
                  <link rel="stylesheet" href="/v53-experience.css">
                  <main id="page"></main><div id="modal-root"></div>
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
        assert not any('/billing' in path or '/receivables' in path for _, path in calls), calls
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


def test_client_admin_mywork_tab_renders_without_missing_action_controls(browser_page):
    page, _ = browser_page
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="mywork"]').click()
    playwright.expect(page.locator('.crm-mywork')).to_have_count(1)
    playwright.expect(page.locator('.crm-mywork-section')).to_have_count(3)


def test_client_admin_pipeline_has_one_aligned_header_per_column(browser_page):
    page, _ = browser_page
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    playwright.expect(page.locator('.v53-unified-group, .v53-unified-groups')).to_have_count(0)
    playwright.expect(page.locator('.v53-unified-columns > .v53-pipeline-column')).to_have_count(7)
    playwright.expect(page.locator('[data-pipeline-dropzone]')).to_have_count(5)
    assert page.locator('.v53-unified-stage > header strong').all_text_contents() == [
        'New Leads', 'Prospects', 'Qualified', 'Proposal', 'Verbal Commitment', 'Closed Won', 'Closed Lost',
    ]
    headers = page.locator('.v53-unified-stage > header')
    playwright.expect(headers).to_have_count(7)
    assert headers.evaluate_all('''headers => headers.every(header => {
        const h = header.getBoundingClientRect();
        const c = header.parentElement.getBoundingClientRect();
        return Math.abs(h.left - c.left) <= 2 && Math.abs(h.width - c.width) <= 2
            && Math.abs(h.top - headers[0].getBoundingClientRect().top) <= 1;
    })''')
    playwright.expect(page.locator('[data-stage="Qualified"] > header small')).to_have_text('0 · $0')
    playwright.expect(page.locator('[data-stage="Qualified"] .v53-column-empty')).to_have_text('No opportunities')
    playwright.expect(page.locator('[data-move-opportunity]')).to_have_count(0)
    playwright.expect(page.locator('[data-pipeline-view]')).to_have_count(0)
    playwright.expect(page.get_by_text('All pipeline', exact=True)).to_have_count(0)
    playwright.expect(page.get_by_text('Drag Opportunities between stages. Drag a Prospect to Qualified to create an Opportunity.', exact=True)).to_have_count(0)
    playwright.expect(page.get_by_text('Tenant Data Scope', exact=True)).to_have_count(0)
    playwright.expect(page.locator('[data-pipeline-top-scroll]')).to_have_count(0)
    playwright.expect(page.locator('#v53-crm-search')).to_have_count(0)
    playwright.expect(page.locator('#v53-crm-duplicates')).to_have_count(0)
    playwright.expect(page.locator('.v53-hero h1')).to_have_text('Relationships become revenue here.')
    playwright.expect(page.locator('.v53-hero p')).to_have_text(
        'Open any record to see its people, opportunities, messages, activity history and ProspectIQ intelligence in one connected view.'
    )
    playwright.expect(page.locator('.v53-hero #v53-crm-new')).to_be_visible()
    playwright.expect(page.locator('.v53-hero #v53-crm-import')).to_be_visible()
    tab_style = page.locator('[data-crm-tab="pipeline"]').evaluate('''e => {
        const s = getComputedStyle(e);
        return {radius:s.borderRadius, border:s.borderBottomWidth, shadow:s.boxShadow};
    }''')
    assert tab_style == {'radius': '0px', 'border': '2px', 'shadow': 'none'}
    for tab in ('accounts', 'contacts', 'activities', 'mywork'):
        page.locator(f'[data-crm-tab="{tab}"]').click()
        playwright.expect(page.locator('#v53-crm-search')).to_have_count(0)
        playwright.expect(page.locator('.v53-search')).to_have_count(0)
        playwright.expect(page.locator('#v53-crm-duplicates')).to_have_count(0)


def test_unified_pipeline_prospect_dropdown_and_opportunity_drag_keyboard_paths(
    browser_page, app_client, fx
):
    page, calls = browser_page
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Slice Five Interaction Co',
        'contact_name': 'Casey Pipeline',
        'email': 'casey@example.invalid',
    }).json()['lead']
    prospect = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()['prospect']

    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    prospect_stage = page.locator(f'[data-prospect-stage="{prospect["id"]}"]')
    prospect_stage.select_option('Engaged')
    playwright.expect(
        page.locator(f'[data-pipeline-card][data-record-type="prospect"][data-record-id="{prospect["id"]}"]')
    ).to_have_attribute('data-current-stage', 'Engaged')
    prospect_card = page.locator(
        f'[data-pipeline-card][data-record-type="prospect"][data-record-id="{prospect["id"]}"]'
    )
    playwright.expect(prospect_card.get_by_text('Engaged', exact=True)).to_have_count(1)
    playwright.expect(prospect_card.get_by_text('Edit Prospect', exact=True)).to_have_count(0)
    prospect_card.click(position={'x': 12, 'y': 55})
    playwright.expect(page.get_by_text('Edit Prospect', exact=True)).to_be_visible()
    page.get_by_text('Cancel', exact=True).click()

    prospect_card.evaluate('''card => {
      card.dispatchEvent(new DragEvent('dragstart', {
        bubbles: true, dataTransfer: new DataTransfer()
      }));
    }''')
    playwright.expect(page.locator('[data-stage="Qualified"].is-valid-drop')).to_have_count(1)
    playwright.expect(page.locator('[data-stage="Proposal"].is-invalid-drop')).to_have_count(1)
    prospect_card.dispatch_event('dragend')

    def pointer_drag(source, target):
        # Bring the destination into the scroll viewport before using coordinates.
        target.scroll_into_view_if_needed()
        source_box = source.bounding_box()
        target_box = target.bounding_box()
        assert source_box and target_box
        page.mouse.move(source_box['x'] + source_box['width'] / 2, source_box['y'] + 24)
        page.mouse.down()
        page.mouse.move(target_box['x'] + target_box['width'] / 2, target_box['y'] + 70, steps=12)
        page.mouse.up()

    pointer_drag(
        prospect_card,
        page.locator('[data-pipeline-dropzone][data-stage="Qualified"]'),
    )
    playwright.expect(page.get_by_role('heading', name='Create Opportunity')).to_be_visible()
    page.locator('#v53-promote-form input[name="name"]').fill('Slice Five opportunity')
    page.locator('#v53-create-opportunity').click()
    playwright.expect(
        page.locator(f'[data-pipeline-card][data-record-type="prospect"][data-record-id="{prospect["id"]}"]')
    ).to_have_count(0)
    handle = page.locator('[data-pipeline-drag-type="opportunity"]')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Qualified')
    playwright.expect(handle).not_to_have_attribute('draggable', 'true')
    assert handle.evaluate('(element) => element.tagName') == 'ARTICLE'
    playwright.expect(page.locator('button[data-pipeline-drag-handle]')).to_have_count(0)
    playwright.expect(handle.get_by_text('Drag card', exact=True)).to_have_count(0)
    playwright.expect(handle.get_by_text('Opportunity', exact=True)).to_have_count(0)
    # Qualified is the first Opportunity lane; ArrowLeft must not return an
    # Opportunity to the removed Prospecting stage.
    handle.focus()
    handle.press('ArrowLeft')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Qualified')
    handle.focus()
    handle.press('ArrowRight')
    handle = page.locator('[data-pipeline-drag-type="opportunity"]')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Proposal')
    assert handle.evaluate('(element) => element === document.activeElement')

    pointer_drag(handle, page.locator('[data-pipeline-dropzone][data-stage="Verbal Commitment"]'))
    handle = page.locator('[data-pipeline-drag-type="opportunity"]')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Verbal Commitment')
    playwright.expect(page.get_by_text('Opportunity detail', exact=True)).to_have_count(0)

    # A second and third physical drag after the board rerenders must continue working.
    pointer_drag(handle, page.locator('[data-pipeline-dropzone][data-stage="Proposal"]'))
    handle = page.locator('[data-pipeline-drag-type="opportunity"]')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Proposal')
    pointer_drag(handle, page.locator('[data-pipeline-dropzone][data-stage="Verbal Commitment"]'))
    handle = page.locator('[data-pipeline-drag-type="opportunity"]')
    playwright.expect(handle).to_have_attribute('data-pipeline-drag-stage', 'Verbal Commitment')

    handle.locator('[data-activity-opportunity]').click()
    playwright.expect(page.get_by_text('Add CRM Activity', exact=True)).to_be_visible()
    page.get_by_text('Cancel', exact=True).click()
    handle.focus()
    handle.press('ArrowRight')
    playwright.expect(page.get_by_text('Mark Opportunity Won', exact=True)).to_be_visible()
    page.get_by_text('Cancel', exact=True).click()

    page.evaluate('''stage => {
      const source = document.querySelector('[data-pipeline-drag-type="opportunity"]');
      const target = document.querySelector(`[data-pipeline-dropzone][data-stage="${stage}"]`);
      const transfer = new DataTransfer();
      source.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: transfer}));
      target.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: transfer}));
      target.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
      source.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: transfer}));
    }''', 'Closed Lost')
    playwright.expect(page.get_by_text('Mark Opportunity Lost', exact=True)).to_be_visible()
    page.locator('#v531-close-form select[name="loss_reason"]').select_option(label='Other')
    page.locator('#v531-confirm-close').click()
    playwright.expect(
        page.locator('[data-pipeline-card][data-current-stage="Closed Lost"]')
    ).to_contain_text('Other')
    assert any(path.endswith('/quick-close') for method, path in calls if method == 'POST')


@pytest.mark.parametrize('width', [390, 1440])
def test_unified_pipeline_narrow_viewport_contains_horizontal_board(
    browser_page, app_client, fx, width, tmp_path
):
    page, _ = browser_page
    for index in range(12):
        response = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
            'company_name': f'Long responsive account name {index:02d} for pipeline verification',
            'contact_name': f'Responsive Contact {index:02d}',
            'email': f'responsive-{index:02d}@example.invalid',
        })
        assert response.status_code == 200, response.text
    page.get_by_text('Close', exact=True).click()
    page.set_viewport_size({'width': width, 'height': 900})
    page.locator('[data-crm-tab="pipeline"]').click()
    scroll = page.locator('.v53-unified-pipeline-scroll')
    playwright.expect(scroll).to_be_visible()
    dimensions = scroll.evaluate(
        '(element) => ({clientWidth: element.clientWidth, scrollWidth: element.scrollWidth})'
    )
    assert dimensions['clientWidth'] <= width
    assert dimensions['scrollWidth'] > dimensions['clientWidth']
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    scroll.evaluate('(element) => { element.scrollLeft = 120; }')
    assert scroll.evaluate('(element) => element.scrollLeft') == 120
    scroll.dispatch_event('wheel', {'deltaY': 100, 'shiftKey': True})
    assert scroll.evaluate('(element) => element.scrollLeft') == 220
    scroll.evaluate('(element) => { element.scrollLeft = 0; }')
    lane = page.locator('.v53-pipeline-list').first
    assert lane.evaluate('(e) => e.scrollHeight > e.clientHeight')
    lane.hover()
    page.mouse.wheel(0, 240)
    page.wait_for_function('document.querySelector(".v53-pipeline-list").scrollTop > 0')
    assert scroll.evaluate('(e) => e.scrollHeight <= e.clientHeight + 1')
    board_height = page.locator('.v53-pipeline-workspace').evaluate('(e) => e.clientHeight')
    assert board_height >= (560 if width > 860 else 440)
    if width > 860:
        assert page.locator('.v53-unified-stage').first.evaluate('(e) => e.clientHeight') > 450
    # The original hero may scroll above the board. More records must not make
    # the page any taller: only their lane scroll range may grow.
    page_height = page.evaluate('document.documentElement.scrollHeight')
    lane.evaluate('''e => {
        for (let i = 0; i < 30; i++) e.append(e.firstElementChild.cloneNode(true));
    }''')
    assert page.evaluate('document.documentElement.scrollHeight') == page_height
    lane.evaluate('(e) => { while(e.children.length > 12) e.lastElementChild.remove(); }')
    page.screenshot(path=str(tmp_path / f'pipeline-{width}.png'), full_page=True)
    playwright.expect(page.locator('[data-convert-lead]')).to_have_count(12)
    playwright.expect(page.locator('#v53-crm-search')).to_have_count(0)


def test_pipeline_reminder_popup_link_and_local_timezone_survive(browser_page, app_client, fx):
    page, _ = browser_page
    response = app_client.post(f'/api/tenants/{fx.a.id}/activities', json={
        'subject': 'Pipeline follow-up reminder', 'due_at': '2020-01-01T12:00:00Z',
    })
    assert response.status_code == 200, response.text
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    playwright.expect(page.locator('[data-open-mywork]')).to_be_visible()
    page.locator('[data-open-mywork]').click()
    playwright.expect(page.locator('.crm-mywork')).to_contain_text('Pipeline follow-up reminder')
    playwright.expect(page.locator('.crm-mywork-timezone')).to_contain_text('local timezone')


def test_pipeline_touch_drag_and_stale_stage_refresh(browser_page, app_client, fx):
    page, _ = browser_page
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Touch Interaction Co', 'email': 'touch@example.invalid',
    }).json()['lead']
    prospect = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()['prospect']
    opportunity = app_client.post(f'/api/prospects/{prospect["id"]}/convert-to-opportunity', json={
        'name': 'Touch opportunity', 'value_cents': 10000,
    })
    assert opportunity.status_code == 200, opportunity.text
    opportunity = opportunity.json()['opportunity']
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    card = page.locator('[data-pipeline-drag-type="opportunity"]')
    target = page.locator('[data-pipeline-dropzone][data-stage="Proposal"]')
    target.scroll_into_view_if_needed()
    card.click(position={'x': 15, 'y': 20})
    playwright.expect(page.locator('#modal-root').get_by_text('Record Details', exact=True)).to_be_visible()
    page.get_by_text('Close', exact=True).click()
    target.scroll_into_view_if_needed()
    start, end = card.bounding_box(), target.bounding_box()
    cdp = page.context.new_cdp_session(page)
    x, y = start['x'] + 25, start['y'] + 25
    dest = end['x'] + end['width'] / 2
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
    for step in range(1, 11):
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{
            'x': x + (dest - x) * step / 10, 'y': y,
        }]})
    cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    playwright.expect(card).to_have_attribute('data-current-stage', 'Proposal')
    # Change the server behind the displayed card; a stale keyboard move must
    # refresh, not overwrite the newer stage.
    changed = app_client.patch(f'/api/opportunities/{opportunity["id"]}', json={
        'stage': 'Qualified', 'expected_stage': 'Proposal',
    })
    assert changed.status_code == 200
    card.focus()
    card.press('ArrowRight')
    playwright.expect(card).to_have_attribute('data-current-stage', 'Qualified')


def test_prospect_substatuses_stay_in_single_prospects_column(browser_page, app_client, fx):
    page, _ = browser_page
    statuses = ['Prospecting', 'Nurture', 'Engaged', 'Not Pursuing']
    ids = []
    for index, stage in enumerate(statuses):
        lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
            'company_name': f'Prospect status {stage}', 'email': f'status-{index}@example.invalid',
        }).json()['lead']
        prospect = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()['prospect']
        assert prospect['stage'] == 'Prospecting'
        if stage != 'Prospecting':
            response = app_client.patch(f'/api/prospects/{prospect["id"]}', json={
                'stage': stage, 'not_pursuing_reason': 'No current fit' if stage == 'Not Pursuing' else '',
            })
            assert response.status_code == 200, response.text
        ids.append(prospect['id'])
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    column = page.locator('.v53-unified-stage').filter(has=page.locator('.v53-prospect-column-head'))
    for prospect_id, stage in zip(ids, statuses):
        card = column.locator(f'[data-record-id="{prospect_id}"]')
        playwright.expect(card).to_have_attribute('data-current-stage', stage)
        options = card.locator('select option').all_text_contents()
        assert set(options) == set(statuses)
    playwright.expect(column.locator('[data-record-type="prospect"]')).to_have_count(4)
    for stage in statuses + ['Opportunity']:
        playwright.expect(page.locator(f'[data-pipeline-dropzone][data-stage="{stage}"]')).to_have_count(0)


def test_legacy_opportunities_remain_accessible_without_extra_lanes(browser_page, app_client, fx):
    page, calls = browser_page
    rows = []
    for stage in ('Prospecting', 'Opportunity', 'Legacy Review'):
        response = app_client.post(f'/api/tenants/{fx.a.id}/opportunities', json={
            'name': f'Legacy {stage}', 'stage': stage,
        })
        assert response.status_code == 200, response.text
        rows.append(response.json()['opportunity'])
    page.get_by_text('Close', exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    column = page.locator('.v53-unified-stage').filter(has=page.locator('.v53-prospect-column-head'))
    for row in rows:
        card = column.locator(f'[data-record-id="{row["id"]}"]')
        playwright.expect(card).to_have_attribute('data-current-stage', row['stage'])
        playwright.expect(card).to_contain_text(f'Legacy Opportunity · {row["stage"]}')
    playwright.expect(page.locator('[data-pipeline-dropzone]')).to_have_count(5)
    card = column.locator(f'[data-record-id="{rows[0]["id"]}"]')
    card.focus()
    card.press('ArrowRight')
    moved = page.locator(f'[data-record-id="{rows[0]["id"]}"]')
    playwright.expect(moved).to_have_attribute('data-current-stage', 'Qualified')
    assert any(method == 'PATCH' and path == f'/api/opportunities/{rows[0]["id"]}'
               for method, path in calls)


def test_crm_related_tabs_and_global_admin_read_only_controls(
    browser_page, app_client, fx
):
    page, _ = browser_page
    lead = app_client.post(f'/api/tenants/{fx.a.id}/leads', json={
        'company_name': 'Read Only Relationship Co',
        'contact_name': 'Robin Viewer',
        'email': 'viewer@example.invalid',
    }).json()['lead']
    converted = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').json()
    fx.user.global_role = 'RMR_OWNER'

    page.get_by_text('Close', exact=True).click()
    for tab in ('accounts', 'contacts', 'activities', 'mywork', 'pipeline'):
        page.locator(f'[data-crm-tab="{tab}"]').click()
        playwright.expect(page.locator(f'[data-crm-tab="{tab}"]')).to_have_class(
            re.compile(r'\bactive\b')
        )
    for selector in (
        '#v53-crm-new', '#v53-crm-import', '[data-convert-lead]',
        '[data-prospect-stage]', '[data-pipeline-drag-handle]',
    ):
        playwright.expect(page.locator(selector)).to_have_count(0)
    playwright.expect(page.locator('[data-pipeline-card][data-record-type="prospect"]')).to_have_count(1)
    playwright.expect(page.locator('[data-edit-prospect]')).to_have_count(0)
    page.locator('[data-crm-tab="accounts"]').click()
    page.locator(
        f'[data-open-record="account"][data-record-id="{converted["account"]["id"]}"]'
    ).click()
    playwright.expect(page.get_by_text('Read-only access', exact=True)).to_be_visible()
    playwright.expect(page.locator('[data-record-action]')).to_have_count(0)


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
