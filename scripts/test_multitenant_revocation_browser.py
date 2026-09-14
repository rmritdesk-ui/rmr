"""Actual session rechecks after authoritative fixture revocations; no provider calls."""
import json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text());actors=json.loads((root/'multitenant-actors.json').read_text())
results=json.loads((root/'multitenant-results.json').read_text());actor=actors[0]
record=next(row for row in results if row['tenant']==actor['tenant'])
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for disable,restore in [('disable','enable'),('user-disable','user-enable'),('access-disable','restore-services'),
  ('enhancement-disable','restore-services'),('downgrade','restore-role'),('membership-remove','membership-restore'),('mapping-suspend','mapping-restore')]:
  context=browser.new_context(ignore_https_errors=True)
  context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in {'rmr.test','piq.test'} else route.abort())
  page=context.new_page();session={}
  def seen(response):
   if response.url.endswith('/session/exchange') and response.status==200:session.update(response.json())
  page.on('response',seen)
  def control(action):
   response=context.request.post('http://control-fixture:9100/control',data={'action':action,'index':0});assert response.status==200
  try:
   page.goto('https://rmr.test/');page.locator('input[name="email"]').fill(actor['email']);page.locator('input[name="password"]').fill(f['password'])
   page.get_by_role('button',name='Sign in',exact=True).click();expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
   page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
   expect(page.get_by_label('Current client')).to_have_value(record['client'],timeout=30000)
   headers={'Authorization':'Bearer '+session['access_token']}
   control(disable)
   denied=context.request.post('https://piq.test/api/integrations/rmr/v1/crm/handoffs',headers=headers,data={'prospect_public_id':record['public_id']})
   assert denied.status in (401,403), (disable,denied.status)
   for path,data in [('/profile-pulls',{'clientId':record['client'],'targetProfileId':record['profile_id']}),
     ('/adaptive-research/estimate',{'client_id':record['client'],'lead_ids':[record['lead_id']]})]:
    assert context.request.post('https://piq.test/api'+path,headers=headers,data=data).status in (401,403)
   control(restore)
   # Effective capabilities never grow inside an old downgraded grant; revoked grants stay revoked.
   assert context.request.post('https://piq.test/api/integrations/rmr/v1/crm/handoffs',headers=headers,data={'prospect_public_id':record['public_id']}).status in (401,403)
   page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
   expect(page.get_by_label('Current client')).to_have_value(record['client'],timeout=30000)
   fresh={'Authorization':'Bearer '+session['access_token']}
   assert context.request.get('https://piq.test/api/leads/'+record['lead_id'],headers=fresh).status==200
   print(disable,'PASS: protected actions denied; old grant remains restricted; new launch recovers',flush=True)
  finally:
   control(restore);context.close()
 browser.close()
