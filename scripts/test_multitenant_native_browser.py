"""Native PIQ login/logout and draft profile UI remain independent of the bridge."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
f=json.loads(Path('/proof/fixture.json').read_text())
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True);context=browser.new_context(ignore_https_errors=True)
 context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname=='piq.test' else route.abort())
 page=context.new_page();page.on('dialog',lambda dialog:dialog.accept())
 def login():
  page.get_by_label('Email',exact=True).fill(f['actors']['EXECUTIVE_VIEWER']['email']);page.get_by_label('Password',exact=True).fill(f['native_password'])
  page.get_by_role('button',name='Sign In',exact=True).click();expect(page.get_by_label('Current client')).to_be_enabled(timeout=30000)
  page.get_by_label('Current client').select_option(f['clientB'])
 page.goto('https://piq.test/');login()
 expect(page.get_by_role('button',name='Logout',exact=True)).to_be_visible();expect(page.get_by_role('link',name='Back to RMR Global',exact=True)).to_have_count(0)
 page.get_by_role('button',name='Target Profiles',exact=True).click();page.get_by_role('button',name='New Profile',exact=True).click()
 section=page.locator('.target-profile-section--collapsible').first
 if not section.locator('.target-profile-question-grid').count():section.locator('button').click()
 page.get_by_placeholder('Enter profile name').fill('Native isolated draft')
 page.get_by_role('button',name='Save Draft',exact=True).click();expect(page.get_by_text('Draft saved.',exact=True)).to_be_visible()
 page.get_by_role('button',name='Lead Pipeline',exact=True).click();expect(page.get_by_role('button',name='Pull New Leads',exact=True)).to_be_disabled()
 page.reload();login();page.get_by_role('button',name='Target Profiles',exact=True).click()
 expect(page.get_by_text('Native isolated draft',exact=True).first).to_be_visible()
 page.locator('.target-profile-delete').first.click();expect(page.get_by_text('Native isolated draft',exact=True)).to_have_count(0)
 page.get_by_role('button',name='Logout',exact=True).click();expect(page.get_by_label('Password',exact=True)).to_be_visible()
 print('PASS: native login, independent client selection, draft create/persist/delete, readiness enforced, native logout',flush=True)
 context.close();browser.close()
