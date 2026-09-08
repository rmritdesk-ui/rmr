#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="RMR Global v5.2 browser Golden Paths")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output-dir", default="qa/screenshots-v52")
    parser.add_argument("--result", default="qa/V52-BROWSER-GOLDEN-PATHS.json")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    result_path = Path(args.result).resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    checks: list[dict] = []
    errors: list[str] = []
    started = datetime.now(timezone.utc)

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    status = "passed"
    failure = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.set_default_timeout(12000)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error" and "401" not in msg.text and "favicon" not in msg.text.lower()
            else None,
        )
        try:
            # Kerry client administrator: embedded customer product.
            page.goto(base, wait_until="domcontentloaded")
            page.fill("input[name=email]", "admin@kerry-real-estate.demo")
            page.fill("input[name=password]", "Client-Admin-2026!")
            page.click("#login-form button[type=submit]")
            page.wait_for_selector(".app-shell")
            body = page.locator("body").inner_text()
            check("Kerry Client Administrator reaches the embedded client workspace", "Kerry" in body and "Website" in body and "ProspectIQ" in body)
            page.screenshot(path=str(out / "01-kerry-dashboard.png"), full_page=True)

            for route, expected in [
                ("website", "Website Studio"),
                ("crm", "CRM & Sales Pipeline"),
                ("piq", "ProspectIQ"),
                ("campaigns", "Campaigns & Social"),
                ("email", "Email & Activities"),
                ("reports", "Growth & Management Reporting"),
                ("training", "Training"),
                ("organization", "Sales Organization"),
            ]:
                page.goto(f"{base}/#/{route}", wait_until="domcontentloaded")
                page.wait_for_selector("#page")
                page.wait_for_timeout(250)
                check(f"Customer route {route} is reachable through the normal product shell", expected.lower() in page.locator("#page").inner_text().lower(), expected)

            # Website CMS publication.
            page.goto(f"{base}/#/website", wait_until="domcontentloaded")
            page.wait_for_selector("text=Appointments")
            website_text = page.locator("#page").inner_text().lower()
            check("Website workspace exposes Studio, Media, Blog, Resources, Team Profiles, SEO and Appointments", all(term.lower() in website_text for term in ["Website Studio", "Media", "Blog", "Resources", "Team Profiles", "SEO", "Appointments"]))
            page.get_by_text("Blog", exact=True).click()
            page.click("#add-blog")
            page.fill("input[name=title]", f"Golden Path Market Update {stamp}")
            page.fill("input[name=slug]", f"golden-path-market-update-{stamp.lower()}")
            page.select_option("select[name=status]", "published")
            page.fill("textarea[name=summary]", "Created through the actual customer browser workflow.")
            page.fill("textarea[name=body]", "This article proves the embedded Website Studio can publish client content.")
            page.fill("input[name=seo_title]", f"Golden Path Market Update {stamp}")
            page.fill("textarea[name=seo_description]", "RMR Global browser Golden Path content.")
            page.click("#save-blog")
            page.wait_for_timeout(650)
            check("Website Studio creates and publishes a blog article", f"Golden Path Market Update {stamp}" in page.locator("#page").inner_text())
            page.screenshot(path=str(out / "02-website-studio.png"), full_page=True)

            # CRM opportunity.
            page.goto(f"{base}/#/crm", wait_until="domcontentloaded")
            page.wait_for_selector("#crm-new")
            page.click("#crm-new")
            page.select_option("select[name=type]", "opportunity")
            opportunity_name = f"Golden Path Opportunity {stamp}"
            page.fill("input[name=name]", opportunity_name)
            if page.locator("select[name=account_id] option").count() > 1:
                page.select_option("select[name=account_id]", index=1)
            page.fill("input[name=value]", "25000")
            page.select_option("select[name=stage]", "Qualified")
            page.fill("input[name=probability]", "60")
            page.fill("textarea[name=next_action]", "Schedule the next customer conversation.")
            page.click("#save-crm-record")
            page.wait_for_timeout(650)
            if opportunity_name not in page.locator("#page").inner_text():
                page.locator('[data-crm-tab="opportunities"]').click()
                page.wait_for_timeout(300)
            check("CRM creates a client opportunity", opportunity_name in page.locator("#page").inner_text())
            page.screenshot(path=str(out / "03-crm-opportunity.png"), full_page=True)

            # ProspectIQ discovery and evidence.
            page.goto(f"{base}/#/piq", wait_until="domcontentloaded")
            page.wait_for_selector("#run-discovery")
            before = page.locator("[data-piq-profile]").count()
            page.click("#run-discovery")
            page.wait_for_timeout(850)
            after = page.locator("[data-piq-profile]").count()
            check("ProspectIQ discovery executes from the customer UI", after >= before and after > 0, f"before={before} after={after}")
            page.locator("[data-piq-profile]").first.click()
            page.wait_for_selector(".modal")
            check("ProspectIQ profile exposes supporting evidence", "Evidence" in page.locator(".modal").inner_text())
            page.screenshot(path=str(out / "04-prospectiq.png"), full_page=True)
            page.get_by_text("Close", exact=True).click()

            # Social content.
            page.goto(f"{base}/#/campaigns", wait_until="domcontentloaded")
            page.get_by_text("Social Content", exact=True).click()
            page.click("#generate-social")
            social_title = f"Golden Path Social {stamp}"
            page.fill("input[name=title]", social_title)
            page.fill("textarea[name=message]", "Clear real estate guidance begins with understanding the client goal.")
            page.fill("input[name=call_to_action]", "Talk with Kerry")
            page.fill("input[name=hashtags]", "#RealEstate,#Arizona")
            page.click("#save-social")
            page.wait_for_timeout(750)
            social_text = page.locator("#page").inner_text()
            check("Campaigns & Social generates client content", social_title in social_text)
            check("Social workflow exposes Copy Post, Copy Hashtags and manual Mark Published controls", all(term in social_text for term in ["Copy Post", "Copy Hashtags", "Mark Published"]))
            page.screenshot(path=str(out / "05-campaigns-social.png"), full_page=True)

            # CRM email and activity history.
            page.goto(f"{base}/#/email", wait_until="domcontentloaded")
            page.wait_for_selector("#new-email")
            page.click("#new-email")
            subject = f"Golden Path follow-up {stamp}"
            page.fill("input[name=recipient_name]", "Jordan Partner")
            page.fill("input[name=recipient_email]", "jordan@example.com")
            page.fill("input[name=subject]", subject)
            page.fill("textarea[name=body]", "This safe demo message proves email and CRM activity remain connected.")
            page.fill("textarea[name=supported_facts]", "Kerry serves Arizona\nKerry serves Colorado")
            page.click("#send-crm-email")
            page.wait_for_timeout(650)
            check("Email sends in safe demo mode and appears in activity history", subject in page.locator("#page").inner_text())
            page.screenshot(path=str(out / "06-email-activities.png"), full_page=True)

            # Reporting and public website lead capture.
            page.goto(f"{base}/#/reports", wait_until="domcontentloaded")
            page.wait_for_selector("text=Growth & Management Reporting")
            report_text = page.locator("#page").inner_text().lower()
            check("Reporting connects website, PIQ, CRM, social and email", all(term in report_text for term in ["website", "piq", "opportunit", "social", "email"]))
            page.screenshot(path=str(out / "07-reporting.png"), full_page=True)

            page.goto(f"{base}/sites/kerry-real-estate", wait_until="domcontentloaded")
            page.fill("#lead-form input[name=name]", f"Golden Path Lead {stamp}")
            page.fill("#lead-form input[name=email]", f"lead-{stamp.lower()}@example.com")
            page.fill("#lead-form input[name=phone]", "602-555-0199")
            page.fill("#lead-form textarea[name=message]", "I would like to discuss selling my home.")
            page.click("#lead-form button[type=submit]")
            page.wait_for_timeout(400)
            check("Embedded Kerry website captures a lead", "received" in page.locator("#form-status").inner_text().lower())
            page.fill("#appointment-form input[name=name]", f"Golden Path Visitor {stamp}")
            page.fill("#appointment-form input[name=email]", f"visitor-{stamp.lower()}@example.com")
            page.fill("#appointment-form input[name=preferred_time]", "Friday morning")
            page.fill("#appointment-form textarea[name=message]", "Browser Golden Path appointment request.")
            page.click("#appointment-form button[type=submit]")
            page.wait_for_timeout(400)
            check("Embedded Kerry website captures an appointment request", "received" in page.locator("#appointment-status").inner_text().lower())
            page.screenshot(path=str(out / "08-kerry-public-site.png"), full_page=True)

            # RMR portfolio and managed client workspace.
            page.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'X-RMR-Request':'1'}})")
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("#login-form")
            page.fill("input[name=email]", "dave@rmr.local")
            page.fill("input[name=password]", "RMR-Owner-2026!")
            page.click("#login-form button[type=submit]")
            page.wait_for_selector(".app-shell")
            check("RMR Owner reaches Portfolio Command Center", "Portfolio Command Center" in page.locator("body").inner_text())
            page.select_option("#tenant-selector", label="Kerry Laughlin Real Estate")
            page.goto(f"{base}/#/client-360", wait_until="domcontentloaded")
            page.wait_for_selector("#open-client-workspace")
            page.click("#open-client-workspace")
            page.wait_for_timeout(500)
            if "Authorized & Audited Client Workspace" not in page.locator("body").inner_text():
                page.wait_for_selector("text=Client Workspace Preview")
                page.click("#start-managed-session")
                page.wait_for_selector(".modal")
                page.fill("#managed-reason", "Automated Golden Path managed services validation")
                page.click("#confirm-managed-session")
                page.wait_for_timeout(550)
            check("RMR can enter an authorized and audited client workspace", "Authorized & Audited Client Workspace" in page.locator("body").inner_text())
            page.goto(f"{base}/#/crm", wait_until="domcontentloaded")
            page.wait_for_selector("#crm-new")
            check("RMR managed service session can reach the real customer CRM", page.locator("#crm-new").count() == 1)
            page.screenshot(path=str(out / "09-rmr-managed-workspace.png"), full_page=True)
            if page.locator("#end-managed-session").count():
                page.click("#end-managed-session")
                page.wait_for_timeout(350)

            # CAF alternate website mode and client workflow.
            page.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'X-RMR-Request':'1'}})")
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector("#login-form")
            page.fill("input[name=email]", "admin@cactus-air-filters.demo")
            page.fill("input[name=password]", "Client-Admin-2026!")
            page.click("#login-form button[type=submit]")
            page.wait_for_selector(".app-shell")
            page.goto(f"{base}/#/website", wait_until="domcontentloaded")
            page.wait_for_selector("text=Website & Content")
            page.wait_for_function("() => document.querySelector('#page')?.innerText.toLowerCase().includes('external')")
            caf_website_text = page.locator("#page").inner_text()
            check("CAF demonstrates the external connected website tenant mode", "external" in caf_website_text.lower(), caf_website_text[:500])
            page.goto(f"{base}/#/crm", wait_until="domcontentloaded")
            page.wait_for_selector("#crm-new")
            check("CAF retains an operational CRM in the same multi-tenant product", page.locator("#crm-new").count() == 1)
            page.screenshot(path=str(out / "10-caf-client-workspace.png"), full_page=True)

            check("No browser page or console errors occurred", not errors, "; ".join(errors[:8]))
        except Exception as exc:
            status = "failed"
            failure = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            try:
                page.screenshot(path=str(out / "FAILURE.png"), full_page=True)
            except Exception:
                pass
        finally:
            browser.close()

    result = {
        "status": status,
        "release": "5.3.1-final-production-corrections-po1",
        "base_url": base,
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "passed": sum(1 for row in checks if row["passed"]),
        "failed": sum(1 for row in checks if not row["passed"]) + (1 if status == "failed" and all(row["passed"] for row in checks) else 0),
        "checks": checks,
        "browser_errors": errors,
        "failure": failure,
        "screenshots": sorted(path.name for path in out.glob("*.png")),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "passed", "failed", "failure")}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
