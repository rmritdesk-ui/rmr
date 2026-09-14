"""Actual original PIQ UI lifecycle against disposable RMR/PIQ/PG; no live providers."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

root=Path('/proof')
assert os.environ.get('PROFILE_BROWSER_FIXTURE')=='disposable'
f=json.loads((root/'fixture.json').read_text())
final=os.environ.get('PROFILE_BROWSER_FINAL')=='true'
results={}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for mode in ['bridge','native']:
        context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1050})
        forbidden=[]
        def network(route):
            url=urlsplit(route.request.url)
            if url.hostname not in {'rmr.test','piq.test'}:
                route.abort();return
            if '/profile-pulls' in url.path and route.request.method=='POST' or '/adaptive-research/' in url.path and route.request.method=='POST':
                forbidden.append(url.path);route.abort();return
            route.continue_()
        context.route('**/*',network)
        page=context.new_page();session={}
        page.on('dialog',lambda dialog:dialog.accept())
        def response_seen(response):
            if response.url.endswith('/session/exchange') and response.status==200:session.update(response.json())
        page.on('response',response_seen)
        def enter():
            page.goto('https://rmr.test/#/prospectiq')
            page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
            expect(page.get_by_label('Current client')).to_have_value(f['clientA'],timeout=30000)
        def profiles():
            return context.request.get('https://piq.test/api/target-profiles?clientId='+f['clientA'],headers={'Authorization':'Bearer '+session['access_token']}).json()
        def new_profile(name,activate=False):
            page.get_by_role('button',name='New Profile',exact=True).click()
            sections=page.locator('.target-profile-section-toggle')
            for i in range(sections.count()):
                sections.nth(i).click()
                for field in page.locator('.target-profile-question-grid textarea').all():
                    field.fill('Synthetic B2B mortgage partners in Phoenix, Arizona; verified company contact; 10 leads')
                name_field=page.get_by_placeholder('Enter profile name')
                if name_field.count():name_field.fill(name)
            page.get_by_role('button',name='Activate' if activate else 'Save Draft',exact=True).click()
            expect(page.get_by_text('Target Profile activated.' if activate else 'Draft saved.',exact=True)).to_be_visible(timeout=15000)
        def delete_all():
            expect(page.locator('.target-profile-empty, .target-profile-list-item').first).to_be_visible(timeout=15000)
            while page.locator('.target-profile-delete').count():
                before=page.locator('.target-profile-delete').count()
                page.locator('.target-profile-delete').first.click()
                expect(page.locator('.target-profile-delete')).to_have_count(before-1)
            expect(page.locator('.target-profile-empty')).to_be_visible()
        try:
            if mode=='bridge':
                page.goto('https://rmr.test/')
                page.locator('input[name="email"]').fill(f['actors']['CLIENT_ADMIN']['email'])
                page.locator('input[name="password"]').fill(f['password'])
                page.get_by_role('button',name='Sign in',exact=True).click()
                expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
                enter()
            else:
                page.goto('https://piq.test/')
                page.get_by_label('Email',exact=True).fill(f['actors']['SALES_REP']['email'])
                page.get_by_label('Password',exact=True).fill(f['native_password'])
                page.get_by_role('button',name='Sign In',exact=True).click()
                expect(page.get_by_label('Current client')).to_be_enabled(timeout=30000)
                page.get_by_label('Current client').select_option(f['clientB'])
            page.get_by_role('button',name='Target Profiles',exact=True).click()
            expect(page.get_by_role('heading',name='Target Profiles',exact=True)).to_be_visible()
            if final:expect(page.locator('.rmr-nav-list button').first).to_have_text('Target Profiles')
            if mode=='bridge':
                expect(page.get_by_role('link',name='Back to RMR Global',exact=True)).to_be_visible()
                expect(page.get_by_role('button',name='Logout',exact=True)).to_have_count(0)
            else:expect(page.get_by_role('button',name='Logout',exact=True)).to_be_visible()
            if mode=='bridge' and not final and any(row.get('discovery_readiness',{}).get('mode')=='rmr_import' for row in profiles()):
                expect(page.get_by_text('Arizona & Colorado Referral Partners',exact=True).first).to_be_visible(timeout=15000)
                rows=profiles();assert len(rows)==1 and rows[0]['discovery_readiness']['mode']=='rmr_import'
            delete_all()
            expect(page.get_by_role('button',name='New Profile',exact=True)).to_be_enabled()
            if mode=='bridge':
                assert profiles()==[]
                page.get_by_role('link',name='Back to RMR Global',exact=True).first.click()
                enter()
                if final:expect(page.get_by_role('heading',name='Target Profiles',exact=True)).to_be_visible()
                else:page.get_by_role('button',name='Target Profiles',exact=True).click()
                assert profiles()==[]
            new_profile('Replacement '+mode)
            if mode=='bridge':
                row=profiles()[0];assert row['created_by_user_id']==f['actors']['CLIENT_ADMIN']['piq']
                assert row.get('discovery_readiness') is None
                assert row['client_id']==f['clientA']
            page.reload()
            if mode=='native':
                # Native access is in-memory; normal re-login after a full reload is unchanged.
                page.get_by_label('Email',exact=True).fill(f['actors']['SALES_REP']['email'])
                page.get_by_label('Password',exact=True).fill(f['native_password'])
                page.get_by_role('button',name='Sign In',exact=True).click()
            expect(page.get_by_label('Current client')).to_be_visible(timeout=30000)
            if mode=='native':page.get_by_label('Current client').select_option(f['clientB'])
            page.get_by_role('button',name='Target Profiles',exact=True).click()
            expect(page.get_by_text('Replacement '+mode,exact=True).first).to_be_visible(timeout=15000)
            page.get_by_role('button',name='Edit',exact=True).first.click()
            page.locator('.target-profile-section-toggle').first.click()
            page.get_by_placeholder('Enter profile name').fill('Edited '+mode)
            page.get_by_role('button',name='Save Draft',exact=True).click()
            expect(page.get_by_text('Draft saved.',exact=True)).to_be_visible()
            delete_all();new_profile('Recreated '+mode,activate=True)
            page.get_by_role('button',name='Lead Pipeline',exact=True).click()
            expect(page.get_by_role('button',name='Pull New Leads',exact=True)).to_be_disabled()
            expect(page.get_by_text('Generate Profile Intelligence before pulling leads.',exact=False)).to_be_visible()
            if final:
                page.get_by_role('button',name='Prepare Profile Intelligence',exact=True).click()
                expect(page.get_by_role('button',name='Generate Profile Summary',exact=True)).to_be_enabled()
                # AI_PROVIDER=mock; no external network. Native readiness remains genuine.
                page.get_by_role('button',name='Generate Profile Summary',exact=True).click()
                expect(page.get_by_role('button',name='Regenerate Profile Summary',exact=True)).to_be_enabled(timeout=30000)
                page.get_by_role('button',name='Lead Pipeline',exact=True).click()
                expect(page.get_by_role('button',name='Pull New Leads',exact=True)).to_be_enabled()
            assert not forbidden
            page.screenshot(path=str(root/(mode+('-final' if final else '-baseline')+'.png')),full_page=True)
            results[mode]='PASS: delete last, create, reload, edit, delete, recreate; native readiness preserved'
        except Exception:
            page.screenshot(path=str(root/'profile-lifecycle-failure.png'),full_page=True)
            print(page.locator('body').inner_text()[:3500]);raise
        finally:context.close()
    browser.close()
print(json.dumps(results))
