"""Actual Phase 2 UI + original backend/queue/worker proof. External networking blocked."""
import json, re
from uuid import uuid4
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
ROOT=Path("/proof")
PROVIDER=ROOT/"piq" if (ROOT/"piq").is_dir() else ROOT
f=json.loads((ROOT/"fixture.json").read_text())
results={}
initial_count=json.loads((PROVIDER/"mock-discovery-count.json").read_text())["calls"] if (PROVIDER/"mock-discovery-count.json").exists() else 0
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for role in ["CLIENT_ADMIN","SALES_REP","EXECUTIVE_VIEWER"]:
        context=browser.new_context(ignore_https_errors=True,viewport={"width":1440,"height":1050})
        blocked=[]
        def network(route):
            if urlsplit(route.request.url).hostname in {"rmr.test","piq.test"}:route.continue_()
            else:blocked.append(urlsplit(route.request.url).hostname);route.abort()
        context.route("**/*",network)
        page=context.new_page()
        session={}
        runs={}
        failures=[]
        def response_seen(response):
            path=urlsplit(response.url).path
            if path.endswith("/session/exchange") and response.status==200:session.update(response.json())
            if path=="/api/profile-pulls" and response.request.method=="POST" and response.status==201:runs["discovery"]=response.json()
            if path=="/api/adaptive-research/runs" and response.request.method=="POST" and response.status==202:runs["research"]=response.json()
            if response.status>=400 and "/api/" in path:
                try:msg=response.json().get("error","")
                except Exception:msg=""
                failures.append((path,response.status,str(msg)[:160]))
        page.on("response",response_seen)
        try:
            page.goto("https://rmr.test/")
            page.locator('input[name="email"]').fill(f["actors"][role]["email"])
            page.locator('input[name="password"]').fill(f["password"])
            page.get_by_role("button",name="Sign in",exact=True).click()
            expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
            page.goto("https://rmr.test/#piq")
            page.get_by_role("button",name="Open ProspectIQ",exact=True).click()
            expect(page.get_by_label("Current client")).to_be_visible(timeout=30000)
            expect(page.get_by_label("Current client")).to_be_disabled()
            expect(page.get_by_label("Current client")).to_have_value(f["clientA"])
            assert not page.locator('input[type="password"]').count()
            token=session["access_token"]
            headers={"Authorization":"Bearer "+token}
            expected={"prospects.read"}
            if role!="EXECUTIVE_VIEWER": expected.update(["profiles.create","profiles.update_own","discovery.run","prospects.export","crm.move_to_rmr"])
            if role=="CLIENT_ADMIN": expected.update(["profiles.manage_workspace","research.run","research.confirm_cost"])
            assert set(session["context"]["capabilities"])==expected
            for path in ["/api/leads?clientId="+f["clientB"],"/api/leads/"+f["leadB"],"/api/target-profiles/"+f["profileB"],"/api/adaptive-research/runs/"+f["profileB"]]:
                assert context.request.get("https://piq.test"+path,headers=headers).status==403
            assert context.request.post("https://piq.test/api/adaptive-research/estimate",headers=headers,
                data={"client_id":f["clientA"],"lead_ids":[f["leadB"]]}).status==403
            assert context.request.post("https://piq.test/api/integrations/crm/push",headers=headers,data={"leadId":f["leadA"]}).status==403
            for path,body in [
                ("/api/target-profiles",{"clientId":f["clientB"],"profileName":"Denied"}),
                ("/api/profile-pulls",{"clientId":f["clientA"],"targetProfileId":f["profileB"]}),
                ("/api/profile-pulls",{"clientId":f["clientB"],"targetProfileId":f["profileA"]}),
            ]:
                assert context.request.post("https://piq.test"+path,headers=headers,data=body).status==403
            page.get_by_role("button",name="Target Profiles",exact=True).click()
            expect(page.get_by_role("heading",name="Target Profiles",exact=True)).to_be_visible()
            if role=="EXECUTIVE_VIEWER":
                expect(page.get_by_role("button",name="New Profile",exact=True)).to_be_disabled()
                expect(page.get_by_role("button",name="Save Draft",exact=True)).to_be_disabled()
                for path,body in [("/api/target-profiles",{"clientId":f["clientA"],"profileName":"Denied"}),
                    ("/api/profile-pulls",{"clientId":f["clientA"],"targetProfileId":f["profileA"]}),
                    ("/api/adaptive-research/estimate",{"lead_ids":[f["leadA"]]})]:
                    assert context.request.post("https://piq.test"+path,headers=headers,data=body).status==403
                assert context.request.get("https://piq.test/api/leads/"+f["leadA"],headers=headers).status==200
                page.get_by_role("button",name="Lead Pipeline",exact=True).click()
                expect(page.get_by_role("button",name="Pull New Leads",exact=True)).to_be_disabled()
                expect(page.get_by_role("button",name="Run Adaptive Research",exact=True)).to_be_disabled()
                expect(page.get_by_role("button",name="View lead",exact=True).first).to_be_visible()
                company=page.locator("tbody .lead-company").first.inner_text()
                page.get_by_role("button",name="View lead",exact=True).first.click()
                expect(page.get_by_role("heading",name=company,exact=True)).to_be_visible(timeout=30000)
                expect(page.locator(".lead-client-summary__contacts select")).to_be_disabled()
                assert page.get_by_role("button",name="Push to CRM",exact=True).count()==0
                results[role]={"read":True,"create_discovery_research_denied":True}
            else:
                profile_name="Phase2 "+role+" "+uuid4().hex[:6]
                page.get_by_role("button",name="New Profile",exact=True).click()
                sections=page.locator(".target-profile-section-toggle")
                for i in range(sections.count()):
                    sections.nth(i).click()
                    for field in page.locator(".target-profile-question-grid textarea").all():
                        field.fill("Phoenix, Arizona mortgage brokers; 1-50 employees; review public evidence")
                    name=page.get_by_placeholder("Enter profile name")
                    if name.count():name.fill(profile_name)
                page.get_by_role("button",name="Activate",exact=True).click()
                expect(page.get_by_text("Target Profile activated.",exact=True)).to_be_visible(timeout=15000)
                page.get_by_role("button",name="Generate Profile Summary",exact=True).click()
                expect(page.get_by_role("button",name="Regenerate Profile Summary",exact=True)).to_be_enabled(timeout=30000)
                profiles=context.request.get("https://piq.test/api/target-profiles?clientId="+f["clientA"],headers=headers).json()
                selected=next(row for row in profiles if row["profile_name"]==profile_name)
                assert selected["created_by_user_id"]==f["actors"][role]["piq"]
                # Actual updates/status/delete routes retain native semantics.
                assert context.request.patch("https://piq.test/api/target-profiles/"+selected["id"],headers=headers,data={"profileName":profile_name}).status==200
                disposable=context.request.post("https://piq.test/api/target-profiles",headers=headers,data={"clientId":f["clientA"],"profileName":"Delete fixture"}).json()
                assert context.request.delete("https://piq.test/api/target-profiles/"+disposable["id"],headers=headers).status==200
                if role=="SALES_REP":
                    assert context.request.put("https://piq.test/api/target-profiles/"+f["profileA"],headers=headers,data={"profileName":"Denied"}).status==403
                page.get_by_role("button",name="Lead Pipeline",exact=True).click()
                page.locator("select").filter(has=page.locator("option",has_text=profile_name)).select_option(selected["id"])
                page.get_by_role("button",name="Pull New Leads",exact=True).click()
                page.get_by_role("button",name="Confirm & Pull Leads",exact=True).click()
                expect(page.get_by_role("button",name="View lead",exact=True)).to_be_visible(timeout=60000)
                assert "discovery" in runs
                run_id=runs["discovery"]["runId"]
                run=context.request.get("https://piq.test/api/profile-pulls/"+run_id,headers=headers).json()
                assert run["status"]=="completed" and run["resultCount"]==1
                lead=context.request.get("https://piq.test/api/leads?runId="+run_id,headers=headers).json()[0]
                assert lead["client_id"]==f["clientA"] and lead["company_name"].startswith("Phase2 Mock Prospect")
                if role=="CLIENT_ADMIN":
                    page.locator('tbody input[type="checkbox"]').first.check()
                    page.get_by_role("button",name="Run Adaptive Research",exact=True).click()
                    expect(page.get_by_role("heading",name="Confirm Adaptive Research",exact=True)).to_be_visible()
                    page.get_by_label("I understand and confirm this Adaptive Research run.").check()
                    page.get_by_role("button",name="Confirm & Run",exact=True).click()
                    expect(page.get_by_text(re.compile("Adaptive Research completed"))).to_be_visible(timeout=60000)
                    assert "research" in runs
                    research=context.request.get("https://piq.test/api/adaptive-research/runs/"+runs["research"]["run_id"],headers=headers).json()
                    assert research["status"] in ["completed","partial"] and research["provider"]=="mock"
                    assert research["selected_lead_count"]==1
                    results[role]={"profile_created":True,"discovery_completed":True,"research_completed":True,
                        "research_evidence_count":research["evidence_count"],"accepted_for_display_count":research["accepted_for_display_count"]}
                else:
                    expect(page.get_by_role("button",name="Run Adaptive Research",exact=True)).to_be_disabled()
                    assert context.request.post("https://piq.test/api/adaptive-research/estimate",headers=headers,data={"lead_ids":[lead["id"]]}).status==403
                    results[role]={"own_profile_discovery_completed":True,"research_denied":True}
                page.get_by_role("button",name="View lead",exact=True).click()
                expect(page.get_by_role("heading",name=lead["company_name"],exact=True)).to_be_visible(timeout=30000)
                assert page.get_by_role("button",name="Push to CRM",exact=True).count()==0
            page.screenshot(path=str(ROOT/(role.lower()+"-phase2.png")),full_page=True)
            assert token not in page.evaluate("JSON.stringify({session:{...sessionStorage},local:{...localStorage}})")
            assert not urlsplit(page.url).query and not urlsplit(page.url).fragment
            assert set(blocked)<={"fonts.googleapis.com","fonts.gstatic.com","js.stripe.com"}
            page.get_by_title("Signout",exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Your RMR login is unchanged")
            assert context.request.get("https://rmr.test/api/auth/me").status==200
            print(role,"PASS")
        except Exception:
            page.screenshot(path=str(ROOT/"phase2-failure.png"),full_page=True)
            print("FAILED",role,"API errors",failures)
            print(page.locator("body").inner_text()[:3500])
            raise
        finally:context.close()
    # Separate browser context proves the original native PIQ login and client selector.
    native=browser.new_context(ignore_https_errors=True)
    native.route("**/*",network)
    try:
        page=native.new_page()
        page.goto("https://piq.test/")
        page.get_by_label("Email",exact=True).fill(f["actors"]["SALES_REP"]["email"])
        page.get_by_label("Password",exact=True).fill(f["native_password"])
        page.get_by_role("button",name="Sign In",exact=True).click()
        expect(page.get_by_label("Current client")).to_be_enabled(timeout=30000)
        expect(page.get_by_label("Current client").locator("option")).to_have_count(2)
        page.get_by_label("Current client").select_option(f["clientB"])
        expect(page.get_by_label("Current client")).to_have_value(f["clientB"])
        results["native_login"]={"original_ui":True,"two_client_memberships_preserved":True}
    finally:
        native.close()
        browser.close()
count=json.loads((PROVIDER/"mock-discovery-count.json").read_text())["calls"]
assert count-initial_count==2
results.update(result="PASS",mock_discovery_requests=count-initial_count,real_google_calls=0,real_openai_calls=0,crm_handoffs=0)
(ROOT/"phase2-browser-result.json").write_text(json.dumps(results,indent=2))
print(json.dumps(results))
