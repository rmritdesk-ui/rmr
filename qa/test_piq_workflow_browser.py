"""Workflow browser acceptance, fake REST only; no provider or database actions."""
import json
import pytest
from playwright.sync_api import expect
from qa.test_piq_phase3_browser import MockApp, LIVE, ORIGIN

@pytest.fixture
def app(browser):
    context=browser.new_context(viewport={"width":1440,"height":1000})
    page=context.new_page();page.set_default_timeout(6000)
    app=MockApp(context,page)
    yield app
    assert not app.errors and not app.unexpected,(app.errors,app.unexpected)
    context.close()

@pytest.mark.parametrize("role",["CLIENT_ADMIN","SALES_REP"])
def test_profile_collection_crud_and_compound_locations(app,role):
    app.start(role)
    expect(app.button).to_have_text("Pull Leads")
    app.page.locator("#piq-create-profile").click()
    form=app.page.locator("#piq-profile-form")
    form.locator('[name="name"]').fill("Second target")
    form.locator('[name="industries"]').fill("Mortgage Broker")
    form.locator('[name="locations"]').fill("Phoenix, Arizona\nTempe, Arizona")
    app.page.locator("#piq-save-profile").click()
    expect(app.page.locator("#piq-profile-select")).to_have_value("profile-2")
    assert app.profiles[1]["locations_json"]==["Phoenix, Arizona","Tempe, Arizona"]
    app.page.locator("#piq-edit-profile").click()
    expect(app.page.locator('[name="locations"]')).to_have_value("Phoenix, Arizona\nTempe, Arizona")
    app.page.locator('[name="name"]').fill("Edited second")
    app.page.locator("#piq-save-profile").click()
    expect(app.page.locator("#piq-profile-select option:checked")).to_contain_text("Edited second")
    expect(app.page.locator("#piq-profile-select option:checked")).to_contain_text("Phoenix, Arizona")
    app.page.reload(wait_until="domcontentloaded")
    expect(app.page.locator("#piq-profile-select")).to_have_value("profile-2")
    app.page.locator("#piq-view-profile").click()
    expect(app.page.locator('[name="locations"]')).to_have_attribute("readonly","")
    app.page.locator("#modal-root [data-close-modal]").last.click()
    app.page.locator("#piq-delete-profile").click()
    assert len(app.profiles)==2
    app.page.locator("#piq-confirm-delete").click()
    expect(app.page.locator("#piq-profile-select option")).to_have_count(1)
    assert app.post_calls==0

@pytest.mark.parametrize("value",["1","17","50"])
def test_custom_integer_selected_profile(app,value):
    seen=[]
    def observe(request):
        if request.url.endswith("/discover"):seen.append(request.post_data_json)
    app.page.on("request",observe)
    app.start()
    expect(app.page.locator("#piq-quantity option")).to_have_text(["10","20","30","40","50","Custom"])
    app.page.locator("#piq-quantity").select_option("custom")
    app.page.locator("#piq-custom-quantity").fill(value)
    app.click()
    assert seen==[{"count":int(value),"target_profile_id":"profile-a"}]

@pytest.mark.parametrize("value",["0","51","1.5",""])
def test_invalid_custom_never_submits(app,value):
    app.start();app.page.locator("#piq-quantity").select_option("custom")
    app.page.locator("#piq-custom-quantity").fill(value)
    app.button.click()
    expect(app.page.locator("#toast-region")).to_contain_text("whole number")
    assert app.post_calls==0

def test_profile_and_run_scope_summary(app):
    app.runs=[{**app.run("completed"),"run_id":"new-run","result_count":0,
               "diagnostics":{"provider_candidate_count":5,"evaluated_count":3,"rejected":3,"duplicates_skipped":2}}]
    app.start()
    expect(app.page.locator("#piq-run-select")).to_have_value("new-run")
    expect(app.page.locator("[data-piq-run-summary]")).to_contain_text("New discovered prospects: 0")
    assert any("/profile-a/results" in path for _,path,_ in app.calls)
    app.page.locator("#piq-run-select").select_option("all")
    expect(app.page.locator("#piq-run-select")).to_have_value("all")
    expect(app.page.locator("#page")).to_contain_text("Showing historical prospects")

@pytest.mark.parametrize("role",["CLIENT_ADMIN","SALES_REP"])
def test_no_evidence_persists_and_zero_delta_display(app,role):
    app.opportunities=[{**LIVE,"location":"Phoenix, Arizona","adaptive_score_delta":None,
        "research":{"eligible":True,"mode":"live","latest":{"status":"no_evidence"}}}]
    app.start(role)
    expect(app.page.locator("[data-research-outcome]")).to_contain_text("no accepted evidence")
    app.page.reload(wait_until="domcontentloaded")
    expect(app.page.locator("[data-research-outcome]")).to_contain_text("no accepted evidence")
    app.page.locator("[data-open-piq]" if role=="CLIENT_ADMIN" else "[data-piq-profile]").click()
    expect(app.page.locator(".modal")).to_contain_text("Base Match: 72")
    expect(app.page.locator(".modal")).to_contain_text("Research Adjustment: +0")
    expect(app.page.locator(".modal")).to_contain_text("Address: Phoenix, Arizona")

def test_eligibility_and_viewer_capabilities(app):
    app.opportunities=[{**LIVE,"research":{"eligible":False,"reason":"A public HTTPS website is required","latest":None}}]
    app.start()
    expect(app.page.locator("[data-research-piq]")).to_be_disabled()
    expect(app.page.locator("[data-research-outcome]")).to_contain_text("HTTPS")

def test_viewer_has_no_write_controls(app):
    app.read_only=True;app.start("EXECUTIVE_VIEWER")
    expect(app.page.locator("#piq-create-profile")).to_have_count(0)
    expect(app.page.locator("#piq-delete-profile")).to_have_count(0)
    expect(app.button).to_have_count(0)


@pytest.mark.parametrize('role',['CLIENT_ADMIN','SALES_REP'])
def test_pull_controls_grouped_and_custom_visibility(app,role):
    app.start(role)
    operation=app.page.locator('[data-piq-pull]')
    expect(operation.locator('#piq-pull-profile-select')).to_have_value('profile-a')
    expect(operation.locator('#piq-quantity')).to_be_visible()
    expect(operation.get_by_role('button',name='Pull Leads',exact=True)).to_have_count(1)
    expect(app.page.locator('[data-piq-management] #piq-quantity')).to_have_count(0)
    expect(app.page.get_by_role('button',name='Pull Leads',exact=True)).to_have_count(1)
    for preset in ['10','20','30','40','50']:
        app.page.locator('#piq-quantity').select_option(preset)
        expect(app.page.locator('#piq-custom-wrap')).to_be_hidden()
        expect(app.page.locator('#piq-quantity-help')).to_have_text(f'Pull up to {preset} new discovered prospects. Fewer may be available within the search limits.')
    boxes=[app.page.locator(s).bounding_box() for s in ['#piq-pull-profile-select','#piq-quantity','#v53-run-discovery' if role=='CLIENT_ADMIN' else '#run-discovery']]
    assert max(x['y'] for x in boxes)-min(x['y'] for x in boxes)<15
    app.page.locator('#piq-quantity').select_option('custom')
    expect(app.page.locator('#piq-custom-quantity')).to_be_visible()
    expect(app.page.locator('#piq-custom-quantity')).to_have_attribute('min','1')
    expect(app.page.locator('#piq-custom-quantity')).to_have_attribute('max','50')
    app.page.locator('#piq-quantity').select_option('20')
    expect(app.page.locator('#piq-custom-quantity')).to_be_hidden()
    assert app.post_calls==0
    if role=='CLIENT_ADMIN':
        expect(app.page.locator('.v53-target-profile')).to_have_count(0)
        expect(app.page.locator('[data-piq-selected-summary]')).to_have_count(1)


def test_operational_profile_selector_stays_in_sync(app):
    app.profiles.append({**app.profiles[0],'id':'profile-b','name':'Second Profile','locations_json':['Tempe, Arizona']})
    app.start()
    app.page.locator('#piq-pull-profile-select').select_option('profile-b')
    expect(app.page.locator('#piq-profile-select')).to_have_value('profile-b')
    expect(app.page.locator('[data-piq-selected-summary]')).to_contain_text('Tempe, Arizona')
    app.page.locator('#piq-profile-select').select_option('profile-a')
    expect(app.page.locator('#piq-pull-profile-select')).to_have_value('profile-a')
    assert app.post_calls==0


def test_history_shortcuts_remain_below_pull_row(app):
    app.runs=[{**app.run('completed'),'run_id':'latest','result_count':0}]
    app.start()
    expect(app.page.locator('[data-piq-pull] [data-piq-history]')).to_be_visible()
    app.page.locator('#piq-all-leads').click()
    expect(app.page.locator('#piq-run-select')).to_have_value('all')
    app.page.locator('#piq-latest-pull').click()
    expect(app.page.locator('#piq-run-select')).to_have_value('latest')
    expect(app.page.locator('[data-piq-run-summary]')).to_contain_text('New discovered prospects: 0')
    assert app.post_calls==0


def test_mobile_pull_card_stays_within_viewport(app):
    app.page.set_viewport_size({'width':390,'height':844})
    app.start()
    for selector in ['#piq-pull-profile-select','#piq-quantity','#v53-run-discovery']:
        box=app.page.locator(selector).bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=391
