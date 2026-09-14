"""Brand-new RMR tenant -> real provision -> HMAC bootstrap -> SSO, entirely offline."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('PROFILE_BROWSER_FIXTURE')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text())
actors=json.loads((root/'new-onboarding.json').read_text())
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for actor in actors:
        context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1050})
        context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in {'rmr.test','piq.test'} else route.abort())
        page=context.new_page();observed={}
        def response_seen(response):
            path=urlsplit(response.url).path
            if path.endswith('/provision') and response.status==200:observed['provision']=response.json()
            if path.endswith('/profiles/bootstrap') and response.status==200:observed['bootstrap']=response.json()
            if path.endswith('/session/exchange') and response.status==200:observed['session']=response.json()
        page.on('response',response_seen)
        try:
            page.goto('https://rmr.test/')
            page.locator('input[name="email"]').fill(actor['email'])
            page.locator('input[name="password"]').fill(f['password'])
            page.get_by_role('button',name='Sign in',exact=True).click()
            expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
            page.goto('https://rmr.test/#/prospectiq')
            page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
            expect(page.get_by_label('Current client')).to_be_visible(timeout=30000)
            assert observed['bootstrap']['status']=='completed'
            session=observed['session'];assert session['context']['rmr_tenant_id']==actor['tenant']
            assert session['context']['mapping_id']==observed['provision']['mapping_id']
            client=session['context']['piq_client_id'];assert client not in [f['clientA'],f['clientB']]
            rows=context.request.get('https://piq.test/api/target-profiles?clientId='+client,headers={'Authorization':'Bearer '+session['access_token']}).json()
            assert len(rows)==actor['count']
            assert all(row['client_id']==client for row in rows)
            if actor['count']:
                assert rows[0]['discovery_readiness']['mode']=='rmr_import'
                expect(page.get_by_role('heading',name='Leads / Opportunity List',exact=True)).to_be_visible()
            else:
                expect(page.get_by_role('heading',name='Target Profiles',exact=True)).to_be_visible()
                expect(page.get_by_role('button',name='New Profile',exact=True)).to_be_enabled()
                page.get_by_role('button',name='New Profile',exact=True).click()
                page.locator('.target-profile-section-toggle').first.click()
                page.get_by_placeholder('Enter profile name').fill('First native draft')
                page.get_by_role('button',name='Save Draft',exact=True).click()
                expect(page.get_by_text('Draft saved.',exact=True)).to_be_visible()
                native=context.request.get('https://piq.test/api/target-profiles?clientId='+client,headers={'Authorization':'Bearer '+session['access_token']}).json()
                assert len(native)==1 and native[0]['client_id']==client and native[0].get('discovery_readiness') is None
            expect(page.locator('.rmr-nav-list button').first).to_have_text('Target Profiles')
            print('Fresh tenant with',actor['count'],'active profiles: PASS; automatic mapping/bootstrap/SSO, archived excluded')
        finally:context.close()
    browser.close()
