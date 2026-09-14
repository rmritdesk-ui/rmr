"""Hold a real browser across app/worker restarts; interrupted launch recovery."""
import json,os,time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text());actors=json.loads((root/'multitenant-actors.json').read_text())
rows=json.loads((root/'multitenant-results.json').read_text());actor=actors[2];row=next(r for r in rows if r['tenant']==actor['tenant'])
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True);context=browser.new_context(ignore_https_errors=True)
 context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in {'rmr.test','piq.test'} else route.abort())
 page=context.new_page();session={}
 def seen(response):
  if response.url.endswith(('/session/exchange','/session/refresh')) and response.status==200:session.update(response.json())
 page.on('response',seen)
 def enter():
  page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
  expect(page.get_by_label('Current client')).to_have_value(row['client'],timeout=30000)
 def unchanged():
  headers={'Authorization':'Bearer '+session['access_token']}
  for path in ['/target-profiles?clientId='+row['client'],'/leads?runId='+row['run_id']]:
   response=context.request.get('https://piq.test/api'+path,headers=headers);assert response.status==200 and len(response.json())==1
  response=context.request.get('https://piq.test/api/integrations/rmr/v1/crm/handoffs/'+row['public_id'],headers=headers)
  assert response.status==200 and response.json()['rmr_lead_id']==row['rmr_lead_id']
 page.goto('https://rmr.test/');page.locator('input[name="email"]').fill(actor['email']);page.locator('input[name="password"]').fill(f['password'])
 page.get_by_role('button',name='Sign in',exact=True).click();expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
 enter();unchanged();old=session['bridge_session_id']
 if (root/'multitenant-restarted').exists():(root/'multitenant-restarted').unlink()
 (root/'multitenant-restart-requested').write_text('ready')
 print('READY FOR DISPOSABLE RMR/BACKEND/WORKER RESTART',flush=True)
 deadline=time.monotonic()+120
 while not (root/'multitenant-restarted').exists():
  assert time.monotonic()<deadline,'Restart not acknowledged';page.wait_for_timeout(500)
 # docker restart returns before uvicorn is ready; do not confuse startup outage with renewal failure.
 deadline=time.monotonic()+60
 while context.request.get('https://rmr.test/api/auth/me').status!=200:
  assert time.monotonic()<deadline,'RMR did not become ready';page.wait_for_timeout(500)
 page.reload();expect(page.get_by_label('Current client')).to_have_value(row['client'],timeout=30000)
 # Reload renews the existing durable bridge session, not a duplicate session.
 unchanged();assert session['bridge_session_id']==old
 assert context.request.get('https://rmr.test/api/auth/me').status==200
 print('PASS: durable session reload after all three process restarts',flush=True)
 for after in [False,True]:
  observed={}
  def interrupt(route):
   observed['body']=route.request.post_data_json
   if after:
    response=route.fetch();assert response.status==200
   route.abort()
  context.route('**/api/integrations/rmr/v1/session/exchange',interrupt)
  page.goto('https://rmr.test/#/prospectiq');page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
  expect(page.get_by_role('status')).to_have_text('Your RMR authorization has expired. Return to RMR Global to continue.',timeout=30000)
  expect(page.get_by_role('button',name='Open native ProspectIQ login',exact=True)).to_be_visible()
  assert observed
  context.unroute('**/api/integrations/rmr/v1/session/exchange',interrupt)
  if after:
   replay=context.request.post('https://piq.test/api/integrations/rmr/v1/session/exchange',headers={'Origin':'https://piq.test'},data=observed['body'])
   # Existing PIQ partner transport deliberately sanitizes upstream rejection as 503.
   assert replay.status==503 and replay.json()['error']=='RMR authorization unavailable; return through RMR'
  enter();unchanged()
  print('PASS: interrupted launch '+('after session creation; consumed code rejected' if after else 'before exchange')+'; reopen recovers without duplicates',flush=True)
 page.get_by_role('link',name='Back to RMR Global',exact=True).first.click();expect(page).to_have_url('https://rmr.test/#/prospectiq')
 context.close();browser.close()
