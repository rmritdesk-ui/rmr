#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.async_api import BrowserContext, Route, async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "screenshots-v51rc3"
REPORT = ROOT / "qa" / "V51RC3-BROWSER-RESULTS.json"
ORIGIN = "https://rmr.test"
checks: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")



def module_source(path: Path, exports: list[str] | None = None) -> str:
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"^import .*?;\s*$", "", source, flags=re.MULTILINE)
    source = re.sub(r"\bexport\s+(?=(const|let|var|function|async\s+function|class)\b)", "", source)
    assign = ""
    if exports:
        assign = "\nObject.assign(window,{" + ",".join(exports) + "});"
    return "(function(){\n" + source + assign + "\n})();"


async def load_app(page, initial_hash: str = "") -> None:
    css = (ROOT / "public/styles.css").read_text(encoding="utf-8")
    html = f"""<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><base href=\"{ORIGIN}/\"><style>{css}</style></head><body><div id=\"app\"><div class=\"boot-screen\"><div class=\"brand-mark\">R</div><p>Loading RMR Platform...</p></div></div><div id=\"toast-region\" aria-live=\"polite\"></div><div id=\"modal-root\"></div></body></html>"""
    await page.set_content(html, wait_until="domcontentloaded")
    await page.evaluate("""(initialHash) => {
      const store = new Map();
      const storage = {
        get length(){ return store.size; },
        key(index){ return [...store.keys()][index] ?? null; },
        getItem(key){ key=String(key); return store.has(key) ? store.get(key) : null; },
        setItem(key,value){ store.set(String(key),String(value)); },
        removeItem(key){ store.delete(String(key)); },
        clear(){ store.clear(); }
      };
      Object.defineProperty(window, 'localStorage', {value: storage, configurable: true});
      const nativeReplaceState = history.replaceState.bind(history);
      history.replaceState = (stateValue, titleValue, urlValue) => {
        if (typeof urlValue === 'string' && urlValue.startsWith('#')) {
          location.hash = urlValue;
          return;
        }
        try { nativeReplaceState(stateValue, titleValue, urlValue); } catch (_) {}
      };
      if (initialHash) location.hash = initialHash;
    }""", initial_hash)
    scripts = [
        (ROOT / "public/api.js", ["ApiError", "api"]),
        (ROOT / "public/state.js", ["state", "isGlobalAdmin", "selectedTenant"]),
        (ROOT / "public/ui.js", [
            "$", "$$", "esc", "money", "number", "pct", "dateFmt", "acronym", "badge",
            "statusTone", "toast", "clearFieldErrors", "applyFieldErrors", "modal", "pageHead",
            "breadcrumb", "readonlyBanner", "loading", "empty", "navItems", "renderShell",
            "bindGlobalUI", "updateBackButton", "bindBreadcrumbs", "setActiveNav", "installTooltips"
        ]),
        (ROOT / "public/pages/admin.js", ["renderAdminPage"]),
        (ROOT / "public/pages/client.js", ["renderClientPage"]),
        (ROOT / "public/pages/unified.js", ["renderUnifiedPage"]),
        (ROOT / "public/app.js", []),
    ]
    for path, exports in scripts:
        await page.add_script_tag(content=module_source(path, exports))

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def install_proxy(
    context: BrowserContext,
    backend: str,
    client: httpx.AsyncClient,
    errors: list[str],
    calls: list[dict[str, object]],
) -> None:
    async def proxy(route: Route) -> None:
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.hostname != "rmr.test":
            await route.abort("blockedbyclient")
            return
        target = backend + parsed.path + (("?" + parsed.query) if parsed.query else "")
        headers = dict(request.headers)
        for name in [
            "host",
            "content-length",
            "accept-encoding",
            "connection",
            "origin",
            "referer",
            "cookie",
        ]:
            headers.pop(name, None)
        headers["accept-encoding"] = "identity"
        try:
            response = await client.request(
                request.method,
                target,
                headers=headers,
                content=request.post_data_buffer,
            )
            calls.append({"method": request.method, "path": parsed.path, "status": response.status_code})
            out_headers: dict[str, str] = {}
            for key, value in response.headers.items():
                if key.lower() in {
                    "content-length",
                    "content-encoding",
                    "transfer-encoding",
                    "connection",
                    "set-cookie",
                    "x-frame-options",
                    "content-security-policy",
                }:
                    continue
                out_headers[key] = value
            await route.fulfill(status=response.status_code, headers=out_headers, body=response.content)
        except Exception as exc:  # pragma: no cover - diagnostic path
            errors.append(f"proxy {request.method} {request.url}: {exc}")
            await route.abort("failed")

    await context.route("**/*", proxy)


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    started = time.time()
    work = Path(tempfile.mkdtemp(prefix="rmr-v51-browser-"))
    data = work / "data"
    data.mkdir()
    token = "browser-token-" + uuid.uuid4().hex
    (data / "INITIAL-SETUP.txt").write_text(f"Setup token: {token}\n", encoding="utf-8")
    port = free_port()
    backend = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "RMR_DATA_DIR": str(data),
            "RMR_PORT": str(port),
            "RMR_BASE_URL": ORIGIN,
            "RMR_SETUP_TOKEN": token,
            "RMR_SECRET_KEY": "browser-secret-" + uuid.uuid4().hex + uuid.uuid4().hex,
            "RMR_AUTO_SEED": "false",
            "RMR_ALLOW_DEMO_CREDENTIALS": "false",
            "RMR_LOCAL_RECOVERY_MODE": "true",
            "RMR_INSTALL_PROFILE": "empty",
            "RMR_ENVIRONMENT": "pilot",
            "PYTHONUNBUFFERED": "1",
        }
    )
    log_path = work / "server.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "rmr_platform.server"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    errors: list[str] = []
    proxy_calls: list[dict[str, object]] = []
    try:
        for _ in range(150):
            try:
                if httpx.get(backend + "/api/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace")[-5000:])

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            admin_http = httpx.AsyncClient(follow_redirects=False, timeout=45)
            client_http = httpx.AsyncClient(follow_redirects=False, timeout=45)
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1050}, ignore_https_errors=True
                )
                context.set_default_timeout(12000)
                print("browser: admin context ready", flush=True)
                await context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ORIGIN)
                await install_proxy(context, backend, admin_http, errors, proxy_calls)
                page = await context.new_page()
                page.on(
                    "console",
                    lambda msg: errors.append(f"admin console {msg.type}: {msg.text}")
                    if msg.type == "error"
                    else None,
                )
                page.on("pageerror", lambda exc: errors.append(f"admin pageerror: {exc}"))
                await load_app(page)
                print("browser: app loaded", flush=True)
                await page.wait_for_selector("#setup-form")
                setup_box = await page.locator("#setup-form").bounding_box()
                check(
                    "first-run setup uses readable desktop width",
                    bool(setup_box and setup_box["width"] >= 560),
                    setup_box,
                )
                await page.screenshot(path=OUT / "v51-first-run-setup.png", full_page=True)
                await page.set_viewport_size({"width": 1920, "height": 1080})
                setup_box_1920 = await page.locator("#setup-form").bounding_box()
                setup_overflow_1920 = await page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
                )
                check(
                    "first-run setup remains readable at 1920x1080",
                    bool(setup_box_1920 and setup_box_1920["width"] >= 600 and setup_overflow_1920),
                    {"box": setup_box_1920, "no_overflow": setup_overflow_1920},
                )
                await page.screenshot(path=OUT / "v51-first-run-setup-1920.png", full_page=True)
                await page.set_viewport_size({"width": 1440, "height": 1050})
                await page.locator('[name="setup_token"]').fill(token)
                await page.locator('[name="owner_name"]').fill("RMR Browser Owner")
                await page.locator('[name="owner_email"]').fill("browser-owner@rmr.test")
                await page.locator('[name="owner_password"]').fill("Browser-Owner-Password-V51!")
                await page.locator('[name="owner_confirm"]').fill("Browser-Owner-Password-V51!")
                print("browser: submitting setup", flush=True)
                await page.get_by_role("button", name="Complete setup").click()
                await page.wait_for_selector('#page h1:has-text("Portfolio Command Center")')
                check(
                    "first-run setup signs owner in",
                    await page.locator('#page h1:has-text("Portfolio Command Center")').count() == 1,
                )
                check(
                    "one-time setup file is removed after setup",
                    not (data / "INITIAL-SETUP.txt").exists(),
                    str(data / "INITIAL-SETUP.txt"),
                )
                await page.screenshot(path=OUT / "v51-portfolio-empty.png", full_page=True)

                print("browser: setup complete", flush=True)
                await page.locator("#add-client").click()
                await page.wait_for_selector("#add-client-form")
                form = page.locator("#add-client-form")
                await form.locator('[name="name"]').fill("CAF Browser Acceptance")
                await form.locator('[name="industry"]').fill("Air Filtration")
                await form.locator('[name="seller_name"]').fill("RMR Sales")
                await form.locator('[name="primary_contact_name"]').fill("CAF Browser Admin")
                await form.locator('[name="primary_contact_email"]').fill("browser-owner@rmr.test")
                await page.locator("#save-client").click()
                await page.wait_for_selector('[data-field-error="primary_contact_email"]')
                duplicate_text = await page.locator(
                    '[data-field-error="primary_contact_email"]'
                ).inner_text()
                check("duplicate email error is inline", "already" in duplicate_text.lower(), duplicate_text)
                check("add-client form stays open after validation", await page.locator("#add-client-form").count() == 1)
                check(
                    "add-client form preserves company data",
                    await form.locator('[name="name"]').input_value() == "CAF Browser Acceptance",
                )
                await page.screenshot(path=OUT / "v51-add-client-inline-validation.png")
                unique_email = "caf-browser-admin@rmr.test"
                await form.locator('[name="primary_contact_email"]').fill(unique_email)
                await page.locator("#save-client").click()
                await page.wait_for_selector('text="Client created"')
                activation_url = await page.locator(".secure-link code").inner_text()
                check(
                    "client creation returns explicit activation link",
                    activation_url.startswith(ORIGIN + "/#/activate/"),
                    activation_url,
                )
                await page.screenshot(path=OUT / "v51-client-created-invitation.png")
                print("browser: client created; opening onboarding", flush=True)
                await page.get_by_role("button", name="Continue onboarding").click()
                await page.wait_for_selector('.modal h2:has-text("Client setup")')

                details = page.locator('.modal textarea[name="details"]')
                clipboard_text = "Cross-step clipboard acceptance text"
                await details.fill(clipboard_text)
                await details.focus()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Control+C")
                await page.get_by_role("button", name="Complete & continue").click()
                print("browser: onboarding step 1 loaded", flush=True)
                await page.wait_for_selector(
                    '.modal h2:has-text("Tenant provisioning & client access")'
                )
                next_notes = page.locator('.modal textarea[name="notes"]')
                print("browser: onboarding step 2 loaded; pasting", flush=True)
                await next_notes.focus()
                await page.keyboard.press("Control+V")
                pasted = await next_notes.input_value()
                check("clipboard paste works across onboarding steps", pasted == clipboard_text, pasted)
                print("browser: clipboard check done", flush=True)
                await page.locator(".modal [data-close-modal]").click()

                await page.wait_for_selector('#page h1:has-text("Client Onboarding")')
                await page.locator("#app-back").click()
                await page.wait_for_selector('#page h1:has-text("Portfolio Command Center")')
                options = await page.locator("#tenant-selector option").all_inner_texts()
                check(
                    "new client appears immediately in tenant selector",
                    any("CAF Browser Acceptance" in item for item in options),
                    options,
                )
                tenant_id = await page.locator('#tenant-selector option', has_text="CAF Browser Acceptance").get_attribute("value")
                check("new client has canonical tenant selector id", bool(tenant_id), tenant_id)
                await page.select_option("#tenant-selector", label="CAF Browser Acceptance")
                await page.wait_for_selector('#page h1:has-text("CAF Browser Acceptance — Client 360")')
                check(
                    "Client 360 breadcrumb has Portfolio",
                    await page.locator('.breadcrumbs button:has-text("Portfolio")').count() == 1,
                )
                check(
                    "Client 360 has manage access action",
                    await page.get_by_role("button", name="Manage Client Access").count() == 1,
                )
                check(
                    "Client 360 exposes website action",
                    await page.locator("#page").get_by_text("Website & platform").count() == 1,
                )
                await page.screenshot(path=OUT / "v51-client360-actions.png", full_page=True)
                await page.locator("#app-back").click()
                await page.wait_for_selector('#page h1:has-text("Portfolio Command Center")')
                check(
                    "in-app Back returns to portfolio",
                    await page.locator('#page h1:has-text("Portfolio Command Center")').count() == 1,
                )

                print("browser: client360/back checks done", flush=True)
                client_context = await browser.new_context(
                    viewport={"width": 1440, "height": 1050}, ignore_https_errors=True
                )
                client_context.set_default_timeout(12000)
                await install_proxy(client_context, backend, client_http, errors, proxy_calls)
                client_page = await client_context.new_page()
                client_page.on(
                    "console",
                    lambda msg: errors.append(f"client console {msg.type}: {msg.text}")
                    if msg.type == "error"
                    else None,
                )
                client_page.on("pageerror", lambda exc: errors.append(f"client pageerror: {exc}"))
                activation_hash = "#" + activation_url.split("#", 1)[1]
                await load_app(client_page, activation_hash)
                await client_page.wait_for_selector("#activation-form")
                await client_page.locator('[name="password"]').fill("CAF-Browser-Password-V51!")
                await client_page.locator('[name="confirm"]').fill("CAF-Browser-Password-V51!")
                print("browser: activation page loaded", flush=True)
                await client_page.get_by_role("button", name="Activate account").click()
                await client_page.wait_for_selector('#page h1:has-text("Welcome")')
                check(
                    "client activation opens separate client portal",
                    await client_page.locator("text=Client operations").count() >= 1,
                )
                check(
                    "client portal hides Portfolio Command Center",
                    await client_page.locator("text=Portfolio Command Center").count() == 0,
                )
                await client_page.screenshot(path=OUT / "v51-client-portal-home.png", full_page=True)

                await client_page.locator('[data-nav="crm"]').click()
                await client_page.wait_for_selector('#page h1:has-text("CRM Workspace")')
                check(
                    "client CRM is editable",
                    await client_page.locator("#crm-new").count() == 1,
                )
                check(
                    "client cannot see Partner Economics",
                    await client_page.locator('[data-nav="partner-economics"]').count() == 0,
                )
                await client_page.screenshot(path=OUT / "v51-client-crm.png", full_page=True)

                # Activation notification must deep-link the administrator to the client and return cleanly.
                await page.locator("#notifications-button").click()
                await page.wait_for_selector('.modal h2:has-text("Notifications")')
                activation_notice = page.locator('[data-notification][data-action-route*="client-360"]', has_text="CAF Browser Acceptance").first
                check("client activation creates actionable admin notification", await activation_notice.count() == 1)
                await activation_notice.click()
                await page.wait_for_selector('#page h1:has-text("CAF Browser Acceptance — Client 360")')
                check("notification deep-links to client 360", await page.locator('#page h1:has-text("CAF Browser Acceptance — Client 360")').count() == 1)
                await page.locator("#app-back").click()
                await page.wait_for_selector('#page h1:has-text("Portfolio Command Center")')

                # Finish onboarding through the actual UI now that the Client Administrator is active.
                await page.evaluate("tenantId => { location.hash = '#/onboarding?tenant=' + tenantId; window.dispatchEvent(new HashChangeEvent('hashchange')); }", tenant_id)
                await page.wait_for_selector('.modal h2:has-text("Tenant provisioning & client access")')
                for stage_number in range(2, 9):
                    await page.wait_for_function(
                        """expected => {
                            const el = document.querySelector('.modal .step-button.current .step-number');
                            if (!el) return false;
                            const value = (el.textContent || '').trim();
                            return value === String(expected) || value === '✓';
                        }""",
                        arg=stage_number,
                    )
                    current = page.locator('.modal .step-button.current .step-number')
                    check(f"onboarding UI reached stage {stage_number}", (await current.inner_text()).strip() in {str(stage_number), "✓"})
                    if stage_number < 8:
                        await page.get_by_role("button", name="Complete & continue").click()
                    else:
                        await page.get_by_role("button", name="Complete go-live").click()
                        await page.wait_for_selector('.completion-state:has-text("is live")')
                check("final onboarding offers Return to Onboarding", await page.get_by_role("button", name="Return to Onboarding").count() == 1)
                check("final onboarding offers Return to Portfolio", await page.get_by_role("button", name="Return to Portfolio").count() == 1)
                check("final onboarding offers Open Client 360", await page.get_by_role("button", name="Open Client 360").count() == 1)
                await page.screenshot(path=OUT / "v51-onboarding-complete.png")
                await page.get_by_role("button", name="Return to Onboarding").click()
                await page.wait_for_selector('#page h1:has-text("Client Onboarding")')
                completed_card = page.locator('[data-onboard]', has_text="Review onboarding").first.locator('xpath=..')
                check("onboarding dashboard refreshes immediately to 100%", "100%" in await completed_card.inner_text(), await completed_card.inner_text())

                print("browser: client portal and crm checked", flush=True)
                await client_page.locator("#logout-button").click()
                await client_page.wait_for_selector("#login-form")
                await client_page.get_by_role("button", name="Forgot password?").click()
                await client_page.wait_for_selector("#forgot-form")
                check(
                    "forgot password UI exists",
                    await client_page.locator("text=Reset your password").count() == 1,
                )
                await client_page.screenshot(path=OUT / "v51-forgot-password.png")

                print("browser: forgot password checked", flush=True)
                await page.locator('[data-nav="service-requests"]').click()
                await page.wait_for_selector('#page h1:has-text("Service Requests")')
                check(
                    "Service Requests has Back to Portfolio",
                    await page.get_by_role("button", name="Back to Portfolio").count() == 1,
                )
                check("Service Requests has breadcrumb", await page.locator(".breadcrumbs").count() == 1)

                await page.locator('[data-nav="system"]').click()
                await page.wait_for_selector('#page h1:has-text("System Health")')
                check(
                    "System Health has plain-language headline",
                    await page.locator("text=Core platform services are operating normally.").count() == 1,
                )
                check(
                    "System Health has recommended action",
                    await page.locator("text=Recommended action:").count() == 1,
                )
                await page.screenshot(path=OUT / "v51-system-health.png", full_page=True)

                print("browser: admin final screens checked", flush=True)
                await client_page.set_viewport_size({"width": 390, "height": 844})
                await load_app(client_page)
                await client_page.wait_for_selector("#login-form")
                overflow = await client_page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
                )
                check(
                    "mobile auth/application has no horizontal overflow",
                    overflow,
                    await client_page.evaluate(
                        "[document.documentElement.scrollWidth,document.documentElement.clientWidth]"
                    ),
                )
                await client_page.screenshot(path=OUT / "v51-mobile-login.png", full_page=True)

                await client_context.close()
                await context.close()
            finally:
                await admin_http.aclose()
                await client_http.aclose()
                await browser.close()

        significant = [
            e
            for e in errors
            if "favicon" not in e.lower()
            and "blockedbyclient" not in e.lower()
            and "status of 401 (unauthorized)" not in e.lower()
            and "status of 409 (conflict)" not in e.lower()
        ]
        check("no browser console or page errors", not significant, significant)
        unauthorized = [
            c for c in proxy_calls if c["status"] == 401 and c["path"] not in {"/api/auth/me"}
        ]
        check("no unexpected unauthorized API calls", not unauthorized, unauthorized)
        result = {
            "status": "passed",
            "release": "5.3.1-final-production-corrections-po1",
            "passed": sum(1 for x in checks if x["ok"]),
            "failed": sum(1 for x in checks if not x["ok"]),
            "duration_seconds": round(time.time() - started, 2),
            "checks": checks,
            "screenshots": [str(p) for p in sorted(OUT.glob("*.png"))],
            "errors": significant,
            "proxy_calls": proxy_calls,
        }
        REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ["status", "passed", "failed", "duration_seconds"]}, indent=2))
        return 0
    except Exception as exc:
        result = {
            "status": "failed",
            "error": str(exc),
            "passed": sum(1 for x in checks if x["ok"]),
            "failed": sum(1 for x in checks if not x["ok"]),
            "checks": checks,
            "errors": errors,
            "server_log": log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
            if log_path.exists()
            else "",
        }
        REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ["status", "error", "passed", "failed"]}, indent=2))
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
