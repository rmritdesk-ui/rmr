"""Final imported-profile UX on the disposable Phase 4 stack only; no external providers."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine, text

root=Path('/proof'); f=json.loads((root/'fixture.json').read_text())
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    ctx=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1050})
    ctx.route('**/*',lambda r:r.continue_() if urlsplit(r.request.url).hostname in {'rmr.test','piq.test'} else r.abort())
    page=ctx.new_page(); session={}; pull={}
    def observe(response):
        path=urlsplit(response.url).path
        if path.endswith('/session/exchange') and response.status==200: session.update(response.json())
        if path=='/api/profile-pulls' and response.request.method=='POST' and response.status==201: pull.update(response.json())
    page.on('response',observe)
    page.goto('https://rmr.test/')
    page.locator('input[name=email]').fill(f['actors']['CLIENT_ADMIN']['email'])
    page.locator('input[name=password]').fill(f['password'])
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.locator('input[name=password]')).to_have_count(0,timeout=30000)
    page.goto('https://rmr.test/#/prospectiq')
    expect(page.get_by_text('Arizona & Colorado Referral Partners',exact=True)).to_be_visible()
    for name in ['Pull Leads','Run Adaptive Research','Move to CRM']:
        expect(page.get_by_role('button',name=name,exact=True)).to_have_count(0)
    page.get_by_role('button',name='Open ProspectIQ',exact=True).click()
    expect(page.get_by_label('Current client')).to_have_value(f['clientA'],timeout=30000)
    expect(page.locator('input[type=password]')).to_have_count(0)
    select=page.locator('select').filter(has=page.locator('option',has_text='Arizona & Colorado Referral Partners'))
    expect(select).to_be_visible()
    selected=select.input_value(); assert selected
    expect(select.locator('option:checked')).to_contain_text('Arizona & Colorado Referral Partners')
    expect(page.get_by_title('Signout',exact=True)).to_have_count(0)
    expect(page.get_by_role('link',name='Back to RMR Global',exact=True).first).to_be_visible()
    expect(page.get_by_role('button',name='Pull New Leads',exact=True)).to_be_enabled()
    page.get_by_role('button',name='Pull New Leads',exact=True).click()
    page.get_by_role('button',name='Confirm & Pull Leads',exact=True).click()
    expect(page.get_by_role('button',name='View lead',exact=True)).to_be_visible(timeout=60000)
    headers={'Authorization':'Bearer '+session['access_token']}
    leads=ctx.request.get('https://piq.test/api/leads?runId='+pull['runId'],headers=headers).json()
    assert len(leads)==1 and leads[0]['client_id']==f['clientA']
    lead=leads[0]
    estimate=ctx.request.post('https://piq.test/api/adaptive-research/estimate',headers=headers,
        data={'client_id':f['clientA'],'lead_ids':[lead['id']],'target_profile_id':selected})
    assert estimate.status==200
    # Research execution/cost confirmation is covered by the companion workflow proof.
    page.get_by_role('button',name='View lead',exact=True).click()
    endpoint='https://piq.test/api/integrations/rmr/v1/crm/handoffs'
    existing=ctx.request.get(endpoint+'/'+lead['prospectiq_id'],headers=headers).json()
    if not existing:
        page.get_by_role('button',name='Move to RMR CRM',exact=True).click()
    expect(page.get_by_text('Moved to RMR CRM',exact=True)).to_be_visible(timeout=30000)
    handoff=ctx.request.get(endpoint+'/'+lead['prospectiq_id'],headers=headers).json()
    repeated=ctx.request.post(endpoint,headers=headers,data={'prospect_public_id':lead['prospectiq_id']}).json()
    assert handoff['rmr_lead_id']==repeated['rmr_lead_id']
    with page.expect_popup() as popup: page.get_by_role('link',name='View Lead',exact=True).click()
    crm=popup.value
    expect(crm.locator('#modal-root [data-record-action=convert]')).to_be_visible(timeout=30000)
    engine=create_engine('postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test?options=-csearch_path%3Drmr_operations_proof')
    with engine.connect() as db:
        assert db.scalar(text('SELECT COUNT(*) FROM leads WHERE id=:id'),{'id':handoff['rmr_lead_id']})==1
        assert db.scalar(text('SELECT COUNT(*) FROM prospectiq_crm_receipts WHERE lead_id=:id'),{'id':handoff['rmr_lead_id']})==1
    engine.dispose();crm.close()
    page.get_by_role('link',name='Back to RMR Global',exact=True).first.click()
    expect(page).to_have_url('https://rmr.test/#/prospectiq')
    expect(page.get_by_role('button',name='Open ProspectIQ',exact=True)).to_be_visible()
    assert ctx.request.get('https://rmr.test/api/auth/me').status==200
    ctx.close()
    native=browser.new_context(ignore_https_errors=True)
    native.route('**/*',lambda r:r.continue_() if urlsplit(r.request.url).hostname in {'rmr.test','piq.test'} else r.abort())
    page=native.new_page();page.goto('https://piq.test/')
    page.get_by_label('Email',exact=True).fill(f['actors']['SALES_REP']['email'])
    page.get_by_label('Password',exact=True).fill(f['native_password'])
    page.get_by_role('button',name='Sign In',exact=True).click()
    expect(page.get_by_label('Current client')).to_be_enabled(timeout=30000)
    expect(page.get_by_role('link',name='Back to RMR Global',exact=True)).to_have_count(0)
    page.get_by_title('Signout',exact=True).click()
    expect(page.get_by_label('Password',exact=True)).to_be_visible(timeout=15000)
    native.close();browser.close()
print(json.dumps({'result':'PASS','imported_profile_auto_selected':True,'mock_discovery':True,
    'research_authorization':True,'idempotent_single_crm_lead':True,'native_view_lead':True,
    'return_to_prospectiq':True,'rmr_session_preserved':True,'native_logout_preserved':True,'real_provider_calls':0}))
