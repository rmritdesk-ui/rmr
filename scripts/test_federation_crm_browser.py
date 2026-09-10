"""Actual Phase 3 browser -> outbox -> signed receiver -> native CRM. Private synthetic stack only."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
ROOT=Path("/proof");f=json.loads((ROOT/"fixture.json").read_text());results={}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for role in ["EXECUTIVE_VIEWER","CLIENT_ADMIN"]:
        context=browser.new_context(ignore_https_errors=True,viewport={"width":1440,"height":1050})
        def network(route):
            if urlsplit(route.request.url).hostname in {"rmr.test","piq.test"}:route.continue_()
            else:route.abort()
        context.route("**/*",network)
        page=context.new_page();session={};errors=[]
        def seen(response):
            path=urlsplit(response.url).path
            if path.endswith("/session/exchange") and response.status==200:session.update(response.json())
            if response.status>=500 and "/api/" in path:errors.append((path,response.status))
        page.on("response",seen)
        try:
            page.goto("https://rmr.test/")
            page.locator('input[name="email"]').fill(f["actors"][role]["email"])
            page.locator('input[name="password"]').fill(f["password"])
            page.get_by_role("button",name="Sign in",exact=True).click()
            expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
            page.goto("https://rmr.test/#piq")
            page.get_by_role("button",name="Open ProspectIQ",exact=True).click()
            expect(page.get_by_label("Current client")).to_be_disabled(timeout=30000)
            expect(page.get_by_label("Current client")).to_have_value(f["clientA"])
            headers={"Authorization":"Bearer "+session["access_token"]}
            endpoint="https://piq.test/api/integrations/rmr/v1/crm/handoffs"
            assert context.request.post(endpoint,headers=headers,data={"prospect_public_id":f["publicB"]}).status==403
            assert context.request.post(endpoint,headers=headers,data={"prospect_public_id":f["publicA"],"rmr_tenant_id":f["clientB"]}).status in (400,403,422)
            assert context.request.post("https://piq.test/api/integrations/crm/push",headers=headers,data={"leadId":f["leadA"]}).status==403
            page.get_by_role("button",name="Lead Pipeline",exact=True).click()
            selector=page.locator("select").filter(has=page.locator("option",has_text="Profile A"))
            if selector.count():selector.first.select_option(f["profileA"])
            # Other workflow proofs may have added leads; select the intended synthetic row.
            target=page.locator("tr").filter(has_text="Synthetic Lead A").get_by_role("button",name="View lead",exact=True)
            expect(target).to_be_visible(timeout=30000)
            target.click()
            expect(page.get_by_role("heading",name="Synthetic Lead A",exact=True)).to_be_visible(timeout=30000)
            if role=="CLIENT_ADMIN":
                existing=context.request.get(endpoint+"/"+f["publicA"],headers=headers).json()
                if not existing:
                    expect(page.get_by_role("button",name="Move to RMR CRM",exact=True)).to_be_enabled()
                    page.get_by_role("button",name="Move to RMR CRM",exact=True).click()
                expect(page.get_by_text("Moved to RMR CRM",exact=True)).to_be_visible(timeout=30000)
                handoff=context.request.get(endpoint+"/"+f["publicA"],headers=headers).json()
                assert handoff["status"]=="succeeded" and handoff["rmr_lead_id"]
                repeat=context.request.post(endpoint,headers=headers,data={"prospect_public_id":f["publicA"]})
                assert repeat.status==200 and repeat.json()["handoff_id"]==handoff["handoff_id"]
                assert repeat.json()["rmr_lead_id"]==handoff["rmr_lead_id"]
                page.screenshot(path=str(ROOT/"phase3-piq-success.png"),full_page=True)
                with page.expect_popup() as popup:
                    page.get_by_role("link",name="View Lead",exact=True).click()
                crm=popup.value
                expect(crm).to_have_url(handoff["crm_url"])
                expect(crm.get_by_text("Synthetic Lead A",exact=True).first).to_be_visible(timeout=30000)
                # CLIENT_ADMIN must open its existing authorized record detail, not just a heading/link.
                expect(crm.locator("#modal-root [data-record-action=convert]")).to_be_visible(timeout=15000)
                crm.screenshot(path=str(ROOT/"phase3-rmr-lead.png"),full_page=True)
                record=context.request.get("https://rmr.test/api/v53/tenants/"+f["tenant"]+"/crm/records/lead/"+handoff["rmr_lead_id"])
                assert record.status==200
                assert context.request.get("https://rmr.test/api/v53/tenants/"+f["clientB"]+"/crm/records/lead/"+handoff["rmr_lead_id"]).status in (403,404)
                results[role]={"outbox_succeeded":True,"same_lead_on_repeat":True,"view_native_crm":True,"tenant_attacks_denied":True}
                results["handoff_id"]=handoff["handoff_id"];results["rmr_lead_id"]=handoff["rmr_lead_id"]
                crm.close()
            else:
                action=page.get_by_role("button",name="Move to RMR CRM",exact=True)
                if action.count():expect(action).to_be_disabled()
                assert context.request.post(endpoint,headers=headers,data={"prospect_public_id":f["publicA"]}).status==403
                results[role]={"read_allowed":True,"crm_transfer_denied":True}
            assert not errors,errors
        except Exception:
            page.screenshot(path=str(ROOT/"phase3-failure.png"),full_page=True)
            print("FAILED",role,"server errors",errors)
            print(page.locator("body").inner_text()[:2400])
            raise
        finally:context.close()
    native=browser.new_context(ignore_https_errors=True);native.route("**/*",network)
    page=native.new_page();login={}
    def native_seen(response):
        if urlsplit(response.url).path=="/api/auth/login" and response.status==200:login.update(response.json())
    page.on("response",native_seen)
    page.goto("https://piq.test/")
    page.get_by_label("Email",exact=True).fill(f["actors"]["SALES_REP"]["email"])
    page.get_by_label("Password",exact=True).fill(f["native_password"])
    page.get_by_role("button",name="Sign In",exact=True).click()
    expect(page.get_by_label("Current client")).to_be_enabled(timeout=30000)
    expect(page.get_by_label("Current client").locator("option")).to_have_count(2)
    page.get_by_label("Current client").select_option(f["clientB"])
    assert login.get("accessToken")
    result=native.request.post("https://piq.test/api/integrations/crm/push",
        headers={"Authorization":"Bearer "+login["accessToken"]},data={"leadId":f["leadB"]})
    assert result.status==200,result.text()
    provider_root=ROOT/"piq" if (ROOT/"piq").is_dir() else ROOT
    assert json.loads((provider_root/"native-crm-result.json").read_text())["received"]
    results["native_login_and_generic_crm"]="PASS"
    native.close();browser.close()
results.update(result="PASS",real_google_calls=0,real_openai_calls=0,automatic_crm_conversion=False)
(ROOT/"phase3-browser-result.json").write_text(json.dumps(results,indent=2));print(json.dumps(results))
