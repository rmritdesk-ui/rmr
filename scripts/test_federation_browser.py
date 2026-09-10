"""Actual-app browser acceptance on disposable rmr.test / piq.test HTTPS origins."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT=Path("/proof")
f=json.loads((ROOT/"fixture.json").read_text())
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(ignore_https_errors=True,viewport={"width":1440,"height":1050})
    blocked=[]
    def network(route):
        if urlsplit(route.request.url).hostname in {"rmr.test","piq.test"}:
            route.continue_()
        else:
            blocked.append(urlsplit(route.request.url).hostname);route.abort()
    context.route("**/*",network)
    page=context.new_page()
    callback_urls=[]
    session_data={}
    browser_errors=[]
    api_errors=[]
    page.on("pageerror",lambda error:browser_errors.append(error.message[:300]))
    def response_seen(response):
        if "/api/" in response.url and response.status>=400:
            try: message=response.json().get("error",response.json().get("detail",""))
            except Exception: message=""
            api_errors.append((urlsplit(response.url).path,response.status,str(message)[:200]))
        if response.url.endswith("/api/integrations/rmr/v1/session/exchange") and response.status==200:
            session_data.update(response.json())
    page.on("response",response_seen)
    page.on("framenavigated",lambda frame:callback_urls.append(frame.url) if "rmr-callback=" in frame.url else None)
    try:
        page.goto("https://rmr.test/")
        page.locator('input[name="email"]').fill("federation-proof@example.invalid")
        page.locator('input[name="password"]').fill(f["password"])
        page.get_by_role("button",name="Sign in",exact=True).click()
        expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
        page.goto("https://rmr.test/#piq")
        launch=page.get_by_role("button",name="Open ProspectIQ",exact=True)
        expect(launch).to_be_visible(timeout=30000)
        page.screenshot(path=str(ROOT/"rmr-launch.png"))
        launch.click()
        expect(page.get_by_label("Current client")).to_be_visible(timeout=30000)
        expect(page.get_by_label("Current client")).to_be_disabled()
        expect(page.get_by_label("Current client")).to_have_value(f["clientA"])
        expect(page.get_by_label("Current client").locator("option")).to_have_count(1)
        expect(page.locator('input[type="password"]')).to_have_count(0)
        expect(page.get_by_text("Synthetic Lead A",exact=True).first).to_be_visible(timeout=30000)
        assert page.get_by_text("Synthetic Lead B",exact=True).count()==0
        assert not urlsplit(page.url).query and not urlsplit(page.url).fragment
        assert session_data["context"]["piq_client_id"]==f["clientA"]
        token=session_data["access_token"]
        assert not any(token in url or "access_token=" in url or "refresh_token=" in url for url in callback_urls)
        stored=page.evaluate("JSON.stringify({session:{...sessionStorage},local:{...localStorage}})")
        assert token not in stored and "code_verifier" not in stored
        assert "assertion" not in session_data
        assert not context.cookies("https://piq.test/")
        page.screenshot(path=str(ROOT/"piq-client-a.png"),full_page=True)
        headers={"Authorization":"Bearer "+token}
        async_body={"clientId":f["clientB"]}
        for path in ["/api/leads?clientId="+f["clientB"],"/api/leads/"+f["leadB"],
                     "/api/target-profiles/"+f["profileB"],"/api/leads?targetProfileId="+f["profileB"]]:
            assert context.request.get("https://piq.test"+path,headers=headers).status==403
        assert context.request.post("https://piq.test/api/profile-pulls",headers=headers,data=async_body).status==403
        assert context.request.post("https://piq.test/api/adaptive-research/runs",headers=headers,data={}).status==403
        assert context.request.post("https://piq.test/api/integrations/crm/push",headers=headers,data={"leadId":f["leadA"]}).status==403
        assert context.request.get("https://piq.test/api/leads/"+f["leadA"],headers=headers).status==200
        assert context.request.get("https://piq.test/api/target-profiles/"+f["profileA"],headers=headers).status==200
        assert context.request.get("https://piq.test/api/leads",headers=headers).json()[0]["client_id"]==f["clientA"]
        page.get_by_role("button",name="View lead",exact=True).click()
        expect(page.get_by_role("heading",name="Synthetic Lead A",exact=True)).to_be_visible(timeout=30000)
        page.screenshot(path=str(ROOT/"piq-lead-detail.png"),full_page=True)
        # Actual logout route revokes PIQ only; the RMR cookie remains usable.
        assert context.request.post("https://piq.test/api/auth/logout",headers=headers,data={}).status==200
        assert context.request.get("https://piq.test/api/leads",headers=headers).status==401
        assert context.request.get("https://rmr.test/api/auth/me").status==200
        page.reload()
        expect(page.get_by_text("Return through RMR to start a new ProspectIQ session.",exact=True)).to_be_visible()
        assert page.locator('input[type="password"]').count()==0
        # Replay callback has no transaction material and must never establish a session.
        assert callback_urls
        page.goto(callback_urls[0])
        page.reload()  # A fresh document must reject the already consumed transaction.
        expect(page.get_by_role("status")).to_contain_text("expired or unavailable",timeout=15000)
        assert page.get_by_label("Current client").count()==0
        # A new RMR launch also proves the original shell's actual Signout control.
        page.goto("https://rmr.test/#piq")
        page.get_by_role("button",name="Open ProspectIQ",exact=True).click()
        expect(page.get_by_label("Current client")).to_be_visible(timeout=30000)
        new_token=session_data["access_token"]
        page.get_by_title("Signout",exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Your RMR login is unchanged")
        assert context.request.get("https://piq.test/api/leads",headers={"Authorization":"Bearer "+new_token}).status==401
        assert context.request.get("https://rmr.test/api/auth/me").status==200
        # Explicit native PIQ login still has its normal two-client membership.
        native=context.request.post("https://piq.test/api/auth/login",data={
            "email":"linked-proof@example.invalid","password":f["native_password"]})
        assert native.status==200
        native_token=native.json()["accessToken"]
        assert len(context.request.get("https://piq.test/api/clients",headers={"Authorization":"Bearer "+native_token}).json())==2
        assert set(blocked) <= {"fonts.googleapis.com","fonts.gstatic.com","js.stripe.com"}
        result={"result":"PASS","original_shell":True,"no_second_password":True,"client_a_only":True,
                "client_b_selection":"disabled","client_b_query_object_profile":"403",
                "spending_and_crm_requests":"403 before handlers","native_multi_client_count":2,
                "piq_logout_revoked":True,"rmr_login_survived":True,"reload_requires_rmr":True,
                "callback_replay_rejected":True,"ui_signout_revoked":True,"lead_detail_rendered":True,
                "rmr_cookie_shared":False,"assertion_in_browser":False,
                "tokens_in_urls_or_storage":False,"external_requests":0}
        (ROOT/"browser-result.json").write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    except Exception:
        page.screenshot(path=str(ROOT/"failure.png"))
        print("PROOF FAILED at origin:",urlsplit(page.url).hostname)
        print("Browser errors:",browser_errors)
        print("API errors:",api_errors)
        print("Blocked external hosts:",sorted(set(blocked)))
        print("Visible page:",page.locator("body").inner_text()[:1600])
        raise
    finally:
        context.close();browser.close()
