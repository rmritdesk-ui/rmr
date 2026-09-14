"""Real collision UI -> native admin explicit approval -> existing user SSO -> revoke."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text())
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 user=browser.new_context(ignore_https_errors=True);admin=browser.new_context(ignore_https_errors=True)
 for context in [user,admin]:context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in {'rmr.test','piq.test'} else route.abort())
 page=user.new_page();review=admin.new_page();session={}
 def seen(response):
  if response.url.endswith('/session/exchange') and response.status==200:session.update(response.json())
 page.on('response',seen);review.on('dialog',lambda dialog:dialog.accept())
 page.goto('https://rmr.test/');page.locator('input[name="email"]').fill(f['actors']['SALES_REP']['email']);page.locator('input[name="password"]').fill(f['password'])
 page.get_by_role('button',name='Sign in',exact=True).click();expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
 page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
 expect(page.get_by_text('An existing PIQ account needs explicit identity approval.',exact=False)).to_be_visible(timeout=30000)
 assert not session
 review.goto('https://piq.test/');review.get_by_label('Email',exact=True).fill(f['actors']['EXECUTIVE_VIEWER']['email']);review.get_by_label('Password',exact=True).fill(f['native_password'])
 review.get_by_role('button',name='Sign In',exact=True).click();expect(review.get_by_label('Current client')).to_be_enabled(timeout=30000)
 expect(review.get_by_role('button',name='Logout',exact=True)).to_be_visible()
 expect(review.get_by_role('link',name='Back to RMR Global',exact=True)).to_have_count(0)
 review.get_by_role('button',name='Users & Access',exact=True).click()
 section=review.get_by_role('region',name='RMR identity links')
 expect(section.get_by_text(f['actors']['SALES_REP']['rmr'],exact=False)).to_be_visible()
 expect(section.get_by_text(f['actors']['SALES_REP']['piq'],exact=False)).to_be_visible()
 section.get_by_role('button',name='Approve identity link',exact=True).click()
 expect(section.get_by_text('approved',exact=False)).to_be_visible()
 page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
 expect(page.get_by_label('Current client')).to_have_value(f['clientA'],timeout=30000)
 assert session['context']['rmr_user_id']==f['actors']['SALES_REP']['rmr']
 expect(page.get_by_role('link',name='Back to RMR Global',exact=True)).to_be_visible()
 expect(page.get_by_role('button',name='Logout',exact=True)).to_have_count(0)
 section.get_by_role('button',name='Revoke identity link',exact=True).click();expect(section.get_by_text('revoked',exact=False)).to_be_visible()
 assert user.request.get('https://piq.test/api/clients',headers={'Authorization':'Bearer '+session['access_token']}).status in (401,403)
 review.get_by_role('button',name='Logout',exact=True).click();expect(review.get_by_label('Password',exact=True)).to_be_visible()
 print('PASS: collision denied, immutable IDs reviewed, native administrator approval, SSO, bridge-only revocation, native logout',flush=True)
 user.close();admin.close();browser.close()
