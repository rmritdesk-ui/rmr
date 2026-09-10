"""Actual Phase 4 browser renewal/reload/tab proof; only disposable PG/TLS fixtures."""
import json,sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
from sqlalchemy import create_engine,text
ROOT=Path("/proof");f=json.loads((ROOT/"fixture.json").read_text())
URL="postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test?options=-csearch_path%3Drmr_operations_proof"
mode=sys.argv[1] if len(sys.argv)>1 else "before"
result={"mode":mode,"result":"PASS"}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(ignore_https_errors=True,viewport={"width":1440,"height":1050},
        **({"storage_state":str(ROOT/"phase4-private-browser.json")} if mode!="before" else {}))
    context.route("**/*",lambda route:route.continue_() if urlsplit(route.request.url).hostname in {"rmr.test","piq.test"} else route.abort())
    if mode!="before":
        state=json.loads((ROOT/"phase4-private-tab.json").read_text())
        context.add_init_script("if(location.origin==='https://piq.test'){sessionStorage.setItem('rmr-bridge-session',"+json.dumps(json.dumps({"id":state["id"]}))+");}")
    page=context.new_page();seen=[]
    def observed(response):
        if "/session/" in urlsplit(response.url).path:
            seen.append((urlsplit(response.url).path,response.status,response.json() if response.status==200 else {}))
    page.on("response",observed)
    def latest():
        return next(data for path,status,data in reversed(seen) if status==200 and data.get("access_token"))
    def launch(tab):
        tab.goto("https://rmr.test/#piq")
        tab.get_by_role("button",name="Open ProspectIQ",exact=True).click()
        expect(tab.get_by_label("Current client")).to_be_disabled(timeout=30000)
    def save(tab,s):
        context.storage_state(path=str(ROOT/"phase4-private-browser.json"))
        (ROOT/"phase4-private-tab.json").write_text(json.dumps({"id":s["bridge_session_id"]}))
    try:
        if mode=="before":
            for host,prefix in [("rmr.test","prospectiq"),("piq.test","rmr")]:
                ready=context.request.get("https://"+host+"/api/integrations/"+prefix+"/v1/health")
                assert ready.status==200 and ready.json()["status"]=="ready"
            page.goto("https://rmr.test/")
            page.locator('input[name="email"]').fill(f["actors"]["CLIENT_ADMIN"]["email"])
            page.locator('input[name="password"]').fill(f["password"])
            page.get_by_role("button",name="Sign in",exact=True).click()
            expect(page.locator('input[name="password"]')).to_have_count(0,timeout=30000)
            launch(page);first=latest();id1=first["bridge_session_id"]
            cookies=[c for c in context.cookies("https://piq.test/") if c["name"].startswith("__Host-rmr-refresh-")]
            assert len(cookies)==1 and all(c["httpOnly"] and c["secure"] and c["sameSite"]=="Strict" and c["path"]=="/" and c["domain"]=="piq.test" for c in cookies)
            refresh="https://piq.test/api/integrations/rmr/v1/session/refresh"
            assert context.request.post(refresh,data={"bridge_session_id":id1}).status==403
            assert context.request.post(refresh,headers={"Origin":"https://rmr.test","X-RMR-Bridge-Request":"1"},data={"bridge_session_id":id1}).status==403
            assert context.request.post(refresh,headers={"Origin":"https://piq.test","X-RMR-Bridge-Request":"1"},
                data={"bridge_session_id":id1,"capabilities":["research.run"]}).status==400
            page.reload();expect(page.get_by_label("Current client")).to_be_disabled(timeout=30000)
            assert latest()["bridge_session_id"]==id1 and latest()["refresh_token"] is None
            generation=len([x for x in seen if x[0].endswith("/refresh") and x[1]==200])
            page.evaluate("window.originalClock=Date.now;Date.now=()=>window.originalClock()+300000")
            with page.expect_response(lambda r:r.url.endswith('/session/refresh') and r.status==200):
                page.get_by_role("button",name="Target Profiles",exact=True).click()
            expect(page.get_by_role("heading",name="Target Profiles",exact=True)).to_be_visible(timeout=15000)
            page.wait_for_function("!!document.querySelector('select')")
            page.evaluate("Date.now=window.originalClock")
            assert len([x for x in seen if x[0].endswith("/refresh") and x[1]==200])>generation
            assert latest()["bridge_session_id"]==id1
            second=context.new_page();second.on("response",observed);launch(second);s=latest()
            assert s["bridge_session_id"]!=id1
            page.get_by_title("Signout",exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("Your RMR login is unchanged")
            second.reload();expect(second.get_by_label("Current client")).to_be_disabled(timeout=30000)
            assert latest()["bridge_session_id"]==s["bridge_session_id"]
            engine=create_engine(URL)
            with engine.begin() as db:db.execute(text("UPDATE users SET tenant_role='SALES_REP' WHERE id=:id"),{"id":f["user"]})
            second.get_by_role("button",name="Lead Pipeline",exact=True).click()
            expect(second.get_by_role("button",name="Run Adaptive Research",exact=True)).to_be_disabled(timeout=15000)
            # Native Pull also requires a completed profile summary; do not bypass that prerequisite.
            second.reload();expect(second.get_by_label("Current client")).to_be_disabled(timeout=30000)
            reduced=latest();caps=reduced["context"]["capabilities"]
            assert "research.run" not in caps and "discovery.run" in caps and "crm.move_to_rmr" in caps
            assert reduced["bridge_session_id"]==s["bridge_session_id"]
            with engine.begin() as db:db.execute(text("UPDATE users SET tenant_role='CLIENT_ADMIN' WHERE id=:id"),{"id":f["user"]})
            engine.dispose()
            page=second
            second.reload();expect(second.get_by_label("Current client")).to_be_disabled(timeout=30000)
            assert "research.run" not in latest()["context"]["capabilities"]
            storage=second.evaluate("JSON.stringify({session:{...sessionStorage},local:{...localStorage}})")
            assert latest()["access_token"] not in storage and all(c["value"] not in storage for c in cookies)
            expect(second.get_by_role("button",name="View lead",exact=True).first).to_be_visible(timeout=30000)
            expect(second.get_by_role("button",name="Run Adaptive Research",exact=True)).to_be_disabled()
            second.screenshot(path=str(ROOT/"phase4-downgrade.png"),full_page=True)
            save(second,latest())
            result.update(reload_same_session=True,transparent_short_token_renewal=True,cookie_security=True,
                csrf_and_browser_capability_injection_denied=True,independent_tab_logout=True,
                downgrade_in_place=True,no_privilege_resurrection=True,no_token_in_web_storage=True)
        elif mode=="outage":
            page.goto("https://piq.test/")
            expect(page.get_by_role("status")).to_be_visible(timeout=30000)
            assert any(path.endswith("/refresh") and status==503 for path,status,data in seen),[(x[0],x[1]) for x in seen]
            assert not page.get_by_label("Current client").count()
            result.update(renewal_failed_closed=True,old_browser_credential_retained=True)
        elif mode=="after":
            page.goto("https://piq.test/")
            expect(page.get_by_label("Current client")).to_be_disabled(timeout=30000)
            assert latest()["bridge_session_id"]==state["id"]
            assert "research.run" not in latest()["context"]["capabilities"]
            h=json.loads((ROOT/"phase3-browser-result.json").read_text())
            resp=context.request.get("https://piq.test/api/integrations/rmr/v1/crm/handoffs/"+f["publicA"],
                headers={"Authorization":"Bearer "+latest()["access_token"]})
            assert resp.status==200 and resp.json()["rmr_lead_id"]==h["rmr_lead_id"] and resp.json()["status"]=="succeeded"
            expect(page.get_by_role("button",name="View lead",exact=True).first).to_be_visible(timeout=30000)
            page.screenshot(path=str(ROOT/"phase4-recovered.png"),full_page=True)
            result.update(same_session_after_outage_and_restart=True,same_committed_lead=True,
                reduced_capabilities_durable=True)
            save(page,latest())
        else:raise AssertionError("Unknown proof mode")
    except Exception:
        page.screenshot(path=str(ROOT/"phase4-failure.png"),full_page=True)
        print("Phase 4 browser failed",mode,[(x[0],x[1]) for x in seen])
        print(page.locator("body").inner_text()[:2000])
        raise
    finally:context.close();browser.close()
(ROOT/("phase4-browser-"+mode+".json")).write_text(json.dumps(result,indent=2))
print(json.dumps(result))
