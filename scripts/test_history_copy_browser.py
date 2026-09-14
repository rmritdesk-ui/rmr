"""Focused real UI proof on the retained disposable OLD/MANUAL stack; no providers."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text())
legacy=json.loads((root/'piq/manual-upgrade.json').read_text())
actor=json.loads((root/'multitenant-actors.json').read_text())[0]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True);context=browser.new_context(ignore_https_errors=True)
 def network(route):
  url=urlsplit(route.request.url)
  if url.hostname not in {'rmr.test','piq.test'} or (route.request.method=='POST' and url.path.startswith(('/api/profile-pulls','/api/adaptive-research','/api/integrations/rmr/v1/crm'))):route.abort()
  else:route.continue_()
 context.route('**/*',network)
 page=context.new_page();session={};copies=[]
 def seen(response):
  if response.status==200 and urlsplit(response.url).path.endswith('/session/exchange'):session.update(response.json())
 page.on('response',seen)
 page.goto('https://rmr.test/');page.locator('input[name="email"]').fill(actor['email']);page.locator('input[name="password"]').fill(f['password'])
 page.get_by_role('button',name='Sign in',exact=True).click();expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
 page.goto('https://rmr.test/#/prospectiq');expect(page.get_by_role('button',name='Open ProspectIQ',exact=True)).to_be_visible(timeout=30000)
 expect(page.locator('[data-piq-source-profile]')).to_have_count(0)
 # Existing SSO creates/recovers ownership normally, without changing federation.
 page.get_by_role('button',name='Open ProspectIQ',exact=True).click();expect(page.get_by_label('Current client')).to_have_value(legacy['client'],timeout=30000)
 page.get_by_role('link',name='Back to RMR Global',exact=True).click();expect(page.get_by_role('button',name='Previous RMR Profiles',exact=True)).to_be_visible(timeout=30000)
 source_url='https://rmr.test/api/tenants/'+actor['tenant']+'/piq/target-profiles?include_archived=true'
 before=context.request.get(source_url).json()
 page.get_by_role('button',name='Previous RMR Profiles',exact=True).click();card=page.locator('[data-piq-source-profile]').first
 expect(card).to_be_visible();expect(card.get_by_text('Historical RMR source.',exact=False)).to_be_visible()
 def lost_response(route):
  response=route.fetch();assert response.status==200
  copies.append((route.request.post_data_json,response.json()))
  if len(copies)==1:route.abort()
  else:route.fulfill(response=response)
 context.route('**/api/integrations/prospectiq/v1/profiles/history-copy',lost_response)
 button=card.get_by_role('button',name='Create New PIQ Profile From This',exact=True)
 button.click();expect(button).to_be_enabled(timeout=30000)
 button.click();expect(card.get_by_text('New PIQ profile created.',exact=False)).to_be_visible(timeout=30000)
 assert len(copies)==2 and copies[0][0]['request_id']==copies[1][0]['request_id']
 assert copies[0][1]['profile_id']==copies[1][1]['profile_id']!=legacy['deleted_profile']
 assert context.request.get(source_url).json()==before
 card.get_by_role('button',name='Open PIQ Target Profiles',exact=True).click()
 expect(page.get_by_role('heading',name='Target Profiles',exact=True)).to_be_visible(timeout=30000)
 expect(page.get_by_label('Current client')).to_have_value(legacy['client'])
 def profiles():
  r=context.request.get('https://piq.test/api/target-profiles?clientId='+legacy['client'],headers={'Authorization':'Bearer '+session['access_token']});assert r.status==200;return r.json()
 rows=profiles();new=next(row for row in rows if row['id']==copies[1][1]['profile_id'])
 assert new['status']=='draft' and new['created_by_user_id']
 assert not any(row['id']==legacy['deleted_profile'] for row in rows)
 expect(page.get_by_text(new['profile_name'],exact=True).first).to_be_visible()
 page.get_by_role('link',name='Back to RMR Global',exact=True).click();expect(page.get_by_role('button',name='Open ProspectIQ',exact=True)).to_be_visible(timeout=30000)
 expect(page.locator('[data-piq-source-profile]')).to_have_count(0)
 page.reload();expect(page.get_by_role('button',name='Open ProspectIQ',exact=True)).to_be_visible(timeout=30000)
 assert len(copies)==2 and len(profiles())==len(rows)
 print('PASS: hidden default history, explicit copy with lost-response retry, new owned draft, tombstone/source preserved, existing SSO Target Profiles, reopen creates nothing',flush=True)
 context.close();browser.close()
