"""Three actual concurrent browser flows, original APIs/worker/outbox, fixture providers only."""
import asyncio,json,os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof');f=json.loads((root/'fixture.json').read_text());actors=json.loads((root/'multitenant-actors.json').read_text())

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  contexts=[];results=[]
  async def journey(actor):
   context=await browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1050});contexts.append(context)
   async def network(route):
    if urlsplit(route.request.url).hostname in {'rmr.test','piq.test'}:await route.continue_()
    else:await route.abort()
   await context.route('**/*',network)
   page=await context.new_page();session={};runs={}
   async def seen(response):
    path=urlsplit(response.url).path
    if response.status==200 and path.endswith('/session/exchange'):session.update(await response.json())
    if response.status==201 and path=='/api/profile-pulls':runs['pull']=await response.json()
    if response.status==202 and path=='/api/adaptive-research/runs':runs['research']=await response.json()
   page.on('response',seen)
   async def get(path):
    response=await context.request.get('https://piq.test/api'+path,headers={'Authorization':'Bearer '+session['access_token']})
    assert response.status==200,(path,response.status);return await response.json()
   try:
    await page.goto('https://rmr.test/')
    await page.locator('input[name="email"]').fill(actor['email']);await page.locator('input[name="password"]').fill(f['password'])
    await page.get_by_role('button',name='Sign in',exact=True).click()
    await expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
    await page.goto('https://rmr.test/#/prospectiq')
    await page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
    await expect(page.get_by_label('Current client')).to_be_disabled(timeout=30000)
    client=session['context']['piq_client_id'];assert session['context']['rmr_tenant_id']==actor['tenant']
    await expect(page.get_by_label('Current client')).to_have_value(client)
    if not actor['profile']:
     await expect(page.get_by_role('heading',name='Target Profiles',exact=True)).to_be_visible()
     await page.get_by_role('button',name='New Profile',exact=True).click()
     sections=page.locator('.target-profile-section-toggle')
     for i in range(await sections.count()):
      section=page.locator('.target-profile-section--collapsible').nth(i)
      if not await section.locator('.target-profile-question-grid').count():await sections.nth(i).click()
      await expect(section.locator('.target-profile-question-grid textarea').first).to_be_visible()
      for field in await section.locator('.target-profile-question-grid textarea').all():
       await field.fill('Synthetic B2B mortgage partners in Phoenix, Arizona; company contacts; 10 leads')
      name=section.get_by_placeholder('Enter profile name')
      if await name.count():await name.fill('Synthetic native replacement')
     await page.get_by_role('button',name='Activate',exact=True).click()
     await expect(page.get_by_text('Target Profile activated.',exact=True)).to_be_visible()
     await page.get_by_role('button',name='Generate Profile Summary',exact=True).click()
     await expect(page.get_by_role('button',name='Regenerate Profile Summary',exact=True)).to_be_enabled(timeout=30000)
    profiles=await get('/target-profiles?clientId='+client);assert len(profiles)==1
    profile=profiles[0];assert profile['client_id']==client
    if actor['profile']:assert profile['discovery_readiness']['mode']=='rmr_import'
    else:assert profile.get('discovery_readiness') is None
    await page.get_by_role('button',name='Lead Pipeline',exact=True).click()
    await expect(page.get_by_role('button',name='Pull New Leads',exact=True)).to_be_enabled()
    await page.get_by_role('button',name='Pull New Leads',exact=True).click()
    await page.get_by_role('button',name='Confirm & Pull Leads',exact=True).click()
    await expect(page.get_by_role('button',name='View lead',exact=True).first).to_be_visible(timeout=60000)
    pull=await get('/profile-pulls/'+runs['pull']['runId']);assert pull['status']=='completed' and pull['resultCount']==1
    leads=await get('/leads?runId='+runs['pull']['runId']);assert len(leads)==1 and leads[0]['client_id']==client
    lead=leads[0]
    await page.locator('tbody input[type="checkbox"]').first.check()
    await page.get_by_role('button',name='Run Adaptive Research',exact=True).click()
    await expect(page.get_by_role('heading',name='Confirm Adaptive Research',exact=True)).to_be_visible()
    await page.get_by_label('I understand and confirm this Adaptive Research run.').check()
    await page.get_by_role('button',name='Confirm & Run',exact=True).click()
    research_id=runs.get('research',{}).get('run_id')
    # Wait for the actual terminal UI; no timing assumptions about worker duration.
    await expect(page.get_by_text('Adaptive Research completed',exact=False).first).to_be_visible(timeout=60000)
    research=await get('/adaptive-research/runs/'+runs['research']['run_id'])
    assert research['status'] in ('completed','partial') and research['provider']=='mock'
    assert research['client_id']==client and research['selected_lead_count']==1
    await page.get_by_role('button',name='View lead',exact=True).first.click()
    await expect(page.get_by_role('heading',name=lead['company_name'],exact=True)).to_be_visible()
    await page.get_by_role('button',name='Move to RMR CRM',exact=True).click()
    await expect(page.get_by_text('Moved to RMR CRM',exact=True)).to_be_visible(timeout=45000)
    detail=await get('/leads/'+lead['id']);public=detail.get('prospectiq_id') or lead['prospectiq_id']
    endpoint='/integrations/rmr/v1/crm/handoffs'
    handoff=await get(endpoint+'/'+public);assert handoff['status']=='succeeded'
    repeat=await context.request.post('https://piq.test/api'+endpoint,headers={'Authorization':'Bearer '+session['access_token']},data={'prospect_public_id':public})
    assert repeat.status==200 and (await repeat.json())['rmr_lead_id']==handoff['rmr_lead_id']
    async with page.expect_popup() as popup:
     await page.get_by_role('link',name='View Lead',exact=True).click()
    crm=await popup.value;await expect(crm).to_have_url(handoff['crm_url'])
    await expect(crm.get_by_text(lead['company_name'],exact=True).first).to_be_visible(timeout=30000)
    record=await context.request.get('https://rmr.test/api/v53/tenants/'+actor['tenant']+'/crm/records/lead/'+handoff['rmr_lead_id'])
    assert record.status==200;await crm.close()
    await page.get_by_role('link',name='Back to RMR Global',exact=True).first.click()
    await expect(page).to_have_url('https://rmr.test/#/prospectiq')
    assert (await context.request.get('https://rmr.test/api/auth/me')).status==200
    await page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
    await expect(page.get_by_label('Current client')).to_have_value(client,timeout=30000)
    await page.reload();await expect(page.get_by_label('Current client')).to_have_value(client,timeout=30000)
    assert len(await get('/target-profiles?clientId='+client))==1
    result={**actor,'client':client,'profile_id':profile['id'],'lead_id':lead['id'],'public_id':public,
      'run_id':runs['pull']['runId'],'research_id':runs['research']['run_id'],'rmr_lead_id':handoff['rmr_lead_id'],
      'handoff_id':handoff['handoff_id'],'bridge_session_id':session['bridge_session_id']}
    results.append((result,context,session,page));print(actor['name'],'FULL FLOW PASS',flush=True)
   except Exception:
    await page.screenshot(path=str(root/('flow-failure-'+actor['tenant']+'.png')),full_page=True)
    print(actor['name'],(await page.locator('body').inner_text())[:2300],flush=True);raise
  # Independent browser contexts; all three journeys overlap in real time.
  await asyncio.gather(*(journey(a) for a in actors))
  assert len({r[0]['client'] for r in results})==3
  for own,context,session,page in results:
   headers={'Authorization':'Bearer '+session['access_token']}
   for other,_,_,_ in results:
    if other['tenant']==own['tenant']:continue
    for path in ['/target-profiles/'+other['profile_id'],'/leads/'+other['lead_id'],'/profile-pulls/'+other['run_id'],'/adaptive-research/runs/'+other['research_id']]:
     assert (await context.request.get('https://piq.test/api'+path,headers=headers)).status==403,path
    for path,data in [('/profile-pulls',{'clientId':own['client'],'targetProfileId':other['profile_id']}),
     ('/adaptive-research/estimate',{'client_id':own['client'],'lead_ids':[other['lead_id']]}),
     ('/integrations/rmr/v1/crm/handoffs',{'prospect_public_id':other['public_id']})]:
     assert (await context.request.post('https://piq.test/api'+path,headers=headers,data=data)).status in (400,403),path
    assert (await context.request.get('https://rmr.test/api/v53/tenants/'+other['tenant']+'/crm/records/lead/'+other['rmr_lead_id'])).status in (403,404)
   # Delayed idempotent retry after the other journeys finished.
   retry=await context.request.post('https://piq.test/api/integrations/rmr/v1/crm/handoffs',headers=headers,data={'prospect_public_id':own['public_id']})
   assert retry.status==200 and (await retry.json())['rmr_lead_id']==own['rmr_lead_id']
  (root/'multitenant-results.json').write_text(json.dumps([r[0] for r in results]))
  print('PASS: concurrent tenants, cross-resource denials, delayed CRM retry, reload and Back to RMR',flush=True)
  for context in contexts:await context.close()
  await browser.close()
asyncio.run(main())
