from sqlalchemy.orm import Session
from test_prospectiq_federation import federation_engine, fx
from test_launch1_crm_drip import app_client
from test_crm_import_browser import browser_page, playwright
from test_crm_outreach import prospect
from rmr_platform.models import Contact, CrmProspect, Lead


def test_drafts_do_not_send_or_record(browser_page,prospect):
    page,calls=browser_page
    page.get_by_text("Close",exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    icon=page.get_by_role("button",name="Email",exact=True)
    playwright.expect(icon).to_have_class("v53-card-action")
    playwright.expect(icon).to_have_text("✉")
    icon.click()
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    playwright.expect(page.locator("#outreach-record")).to_be_disabled()
    assert "outreach" not in page.locator('[role="dialog"]').inner_text().lower()
    page.locator("#outreach-subject").fill("Hello & welcome?")
    page.locator("#outreach-body").fill("Line 1\nLine 2 & details")
    page.evaluate("window.opened=[]; window.open=()=>({opener:null,location:{set href(v){window.opened.push(v)}}})")
    for label in ("Open in Gmail","Outlook"):
        page.get_by_role("button",name=label,exact=True).click()
    urls=page.evaluate("window.opened")
    assert "mail.google.com" in urls[0] and "outlook.office.com" in urls[1]
    assert all("Hello%20%26%20welcome%3F" in u and "Line%201%0ALine%202%20%26%20details" in u for u in urls)
    mailto=page.evaluate("""async()=>{const m=await import('/pages/crm_outreach.js');return m.composeUrl('mailto','alex@example.invalid','Hello & welcome?','Line 1\\nLine 2 & details')}""")
    assert mailto.startswith("mailto:alex%40example.invalid?subject=Hello%20%26")
    assert not any(method=="POST" for method,_ in calls)
    playwright.expect(page.get_by_text("Did you send this email?",exact=True)).to_be_visible()
    page.get_by_role("button",name="Not Yet",exact=True).click()
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    playwright.expect(page.locator("#outreach-body")).to_have_value("Line 1\nLine 2 & details")
    assert not any(method=="POST" for method,_ in calls)
    page.evaluate("window.open=()=>null")
    page.get_by_role("button",name="Open in Gmail",exact=True).click()
    playwright.expect(page.locator("#outreach-status")).to_contain_text("Popup blocked")
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    page.locator("#outreach-body").fill("x"*2000)
    page.get_by_role("button",name="Open in Gmail",exact=True).click()
    playwright.expect(page.locator("#outreach-status")).to_contain_text("too long")
    page.locator("#outreach-body").fill("Ready to send")
    page.evaluate("window.open=()=>({opener:null,location:{}})")
    page.get_by_role("button",name="Open in Gmail",exact=True).click()
    page.locator("#outreach-record").evaluate("b=>{b.click();b.click()}")
    playwright.expect(page.locator("#outreach-status")).to_contain_text("Email recorded based on your confirmation")
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    assert sum(method=="POST" and path.endswith("/contacted") for method,path in calls)==1
    assert not any("one-to-one-email" in path for _,path in calls)


def test_phone_missing_and_stage_visibility(browser_page,app_client,fx,prospect):
    page,calls=browser_page
    with Session(fx.engine) as db:
        p=db.get(CrmProspect,prospect)
        db.get(Contact,p.contact_id).email="";db.get(Lead,p.source_lead_id).email="";db.commit()
    page.get_by_text("Close",exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    page.get_by_role("button",name="Email",exact=True).click()
    playwright.expect(page.get_by_text("Phone Contact Required",exact=True)).to_be_visible()
    playwright.expect(page.locator('a[href="tel:+16025550100"]')).to_be_visible()
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    page.locator("#outreach-call").evaluate("a=>a.addEventListener('click',e=>e.preventDefault())")
    page.get_by_role("link",name="Call Prospect").click()
    playwright.expect(page.get_by_text("Did you make the call?",exact=True)).to_be_visible()
    assert not any(method=="POST" for method,_ in calls)
    page.get_by_role("button",name="Not Yet",exact=True).click()
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    page.get_by_role("link",name="Call Prospect").click()
    page.get_by_role("button",name="Yes, I've Made the Call").click()
    playwright.expect(page.locator("#outreach-status")).to_contain_text("Phone contact recorded")
    with Session(fx.engine) as db:
        from sqlalchemy import select
        from rmr_platform.models import Activity
        activity=db.scalar(select(Activity).where(Activity.activity_type=="Contact Confirmed"))
        assert activity.completed_at and "Method: Phone" in activity.body
        assert db.get(CrmProspect,prospect).stage=="Prospecting"
    page.get_by_text("Close",exact=True).click()
    with Session(fx.engine) as db:
        p=db.get(CrmProspect,prospect)
        db.get(Contact,p.contact_id).phone="";db.get(Lead,p.source_lead_id).phone="";db.commit()
    page.get_by_role("button",name="Email",exact=True).click()
    playwright.expect(page.get_by_text("Contact Information Needed",exact=True)).to_be_visible()
    playwright.expect(page.get_by_role("button",name="Edit Contact Information")).to_be_visible()
    playwright.expect(page.locator("[data-compose],#outreach-call")).to_have_count(0)
    playwright.expect(page.locator("#outreach-confirmation")).to_be_hidden()
    playwright.expect(page.locator("#outreach-record")).to_be_disabled()
    page.get_by_text("Close",exact=True).click()
    for stage in ("Nurture","Engaged","Not Pursuing"):
        with Session(fx.engine) as db:
            db.get(CrmProspect,prospect).stage=stage;db.commit()
        page.locator('[data-crm-tab="pipeline"]').click()
        playwright.expect(page.locator("[data-email-prospect]")).to_have_count(0)


def test_opportunity_email_composer_unchanged(browser_page,app_client,prospect):
    page,calls=browser_page
    result=app_client.post(f"/api/prospects/{prospect}/convert-to-opportunity",json={"name":"Existing opportunity"})
    assert result.status_code==200,result.text
    page.get_by_text("Close",exact=True).click()
    page.locator('[data-crm-tab="pipeline"]').click()
    playwright.expect(page.locator("[data-email-prospect]")).to_have_count(0)
    page.locator("[data-email-opportunity]").click()
    playwright.expect(page.get_by_text("Send One-to-One Email",exact=True)).to_be_visible()
    playwright.expect(page.get_by_role("button",name="Send & Record")).to_be_visible()
    assert not any(method=="POST" and "one-to-one-email" in path for method,path in calls)


def test_email_modal_mobile_and_keyboard(browser_page,prospect):
    page,calls=browser_page
    page.get_by_text("Close",exact=True).click()
    page.set_viewport_size({"width":390,"height":844})
    page.locator('[data-crm-tab="pipeline"]').click()
    page.get_by_role("button",name="Email",exact=True).click()
    playwright.expect(page.locator("#outreach-subject")).to_be_focused()
    assert page.locator('[role="dialog"]').evaluate("el=>el.scrollWidth<=el.clientWidth+1")
    assert page.locator('[role="dialog"]').bounding_box()["height"]<=824
    for button in page.locator("[data-compose]").all():
        assert button.bounding_box()["width"]>280
    # Focus stays in the modal; hidden confirmation cannot be reached by Tab.
    page.locator(".modal-foot [data-close-modal]").focus()
    page.keyboard.press("Tab")
    playwright.expect(page.locator(".modal-head [data-close-modal]")).to_be_focused()
    page.keyboard.press("Escape")
    playwright.expect(page.locator('[role="dialog"]')).to_have_count(0)
    assert not any(method=="POST" for method,_ in calls)
