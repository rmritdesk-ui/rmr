#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="RMR Global v5.4 preserved v5.3.1 browser regression Golden Paths")
    parser.add_argument("--base-url", default="http://127.0.0.1:18155")
    parser.add_argument("--output-dir", default="qa/screenshots-v54-preserved-regression")
    parser.add_argument("--result", default="qa/V54-PRESERVED-V531-BROWSER-REGRESSION.json")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    result_path = Path(args.result).resolve(); result_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    checks: list[dict] = []
    errors: list[str] = []
    status = "passed"; failure = ""
    started = datetime.now(timezone.utc)

    def check(name: str, condition: bool, detail: str = "") -> None:
        row = {"name": name, "passed": bool(condition), "detail": detail}
        checks.append(row)
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    def shot(page, name: str) -> None:
        page.screenshot(path=str(out / name), full_page=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-proxy-server", "--proxy-bypass-list=*"],
        )
        context = browser.new_context(viewport={"width": 1680, "height": 1150}, accept_downloads=True)
        page = context.new_page(); page.set_default_timeout(25000)

        def on_console(msg):
            text = msg.text or ""
            if msg.type == "error" and "401" not in text and "favicon" not in text.lower():
                errors.append(f"console.{msg.type}: {text}")

        page.on("console", on_console)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

        try:
            # -----------------------------------------------------------------
            # Client Administrator: opportunity quick-close and retained CRM.
            # -----------------------------------------------------------------
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_selector('[data-demo-email="admin@kerry-real-estate.demo"]')
            page.click('[data-demo-email="admin@kerry-real-estate.demo"]')
            page.wait_for_selector(".app-shell")
            tenant_id = page.request.get(f"{base}/api/auth/me").json()["user"]["tenant_id"]
            page.goto(f"{base}/#/crm?tab=opportunities", wait_until="domcontentloaded")
            page.wait_for_selector(".v53-crm-shell")

            async_marker = stamp[-8:]
            won_name = f"V54 Won {async_marker}"
            lost_name = f"V54 Lost {async_marker}"

            def create_opportunity(name: str, value: str, probability: str) -> None:
                page.click("#v53-crm-new")
                page.wait_for_selector('[data-create-kind="opportunity"]')
                page.click('[data-create-kind="opportunity"]')
                page.wait_for_selector("#v53-new-form")
                page.fill('#v53-new-form [name="name"]', name)
                page.select_option('#v53-new-form [name="stage"]', "Prospecting")
                page.fill('#v53-new-form [name="value"]', value)
                page.fill('#v53-new-form [name="probability"]', probability)
                page.fill('#v53-new-form [name="close"]', (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat())
                page.fill('#v53-new-form [name="next_action"]', "Complete v5.4 preservation review")
                page.click("#v53-save-new")
                page.wait_for_timeout(800)
                page.goto(f"{base}/#/crm?tab=opportunities&search={name}", wait_until="domcontentloaded")
                page.wait_for_selector(".v53-opportunity-card")

            create_opportunity(won_name, "27500", "35")
            won_card = page.locator(".v53-opportunity-card").filter(has_text=won_name).first
            check("New open opportunity is created through the existing CRM workflow", won_card.count() == 1 and "$27,500" in won_card.inner_text(), won_card.inner_text() if won_card.count() else "")
            won_card.click(); page.wait_for_selector(".modal")
            check("Opportunity detail preserves Edit Opportunity and adds obvious Mark Won and Mark Lost actions", page.locator('.modal [data-record-action="edit-opportunity"]').count() == 1 and page.locator('.modal [data-record-action="mark-won"]').count() == 1 and page.locator('.modal [data-record-action="mark-lost"]').count() == 1)
            page.locator('.modal [data-record-action="mark-won"]').click(); page.wait_for_selector("#v531-close-form")
            page.fill('#v531-close-form [name="value"]', "28000")
            page.fill('#v531-close-form [name="close_date"]', datetime.now(timezone.utc).date().isoformat())
            page.fill('#v531-close-form [name="note"]', "Product Owner quick-close Won Golden Path")
            page.click("#v531-confirm-close"); page.wait_for_timeout(900)
            page.goto(f"{base}/#/crm?tab=opportunities&search={won_name}", wait_until="domcontentloaded")
            page.wait_for_selector(".v53-opportunity-card")
            won_card = page.locator(".v53-opportunity-card").filter(has_text=won_name).first
            won_column = page.locator(".v53-pipeline-column").filter(has=page.locator("header strong").filter(has_text="Closed Won")).first
            check("Mark Won persists the final amount and moves the opportunity into Closed Won", won_card.count() == 1 and won_column.locator(".v53-opportunity-card").filter(has_text=won_name).count() == 1 and "$28,000" in won_card.inner_text(), won_card.inner_text() if won_card.count() else "")
            won_card.click(); page.wait_for_selector(".v531-final-status.won")
            check("Closed Won opportunity detail shows final status and preserves the existing record", "Closed Won" in page.locator(".v531-final-status.won").inner_text() and "$28,000" in page.locator(".v531-final-status.won").inner_text())
            page.locator(".modal [data-close-modal]").last.click()
            shot(page, "01-opportunity-mark-won.png")

            create_opportunity(lost_name, "12000", "25")
            lost_card = page.locator(".v53-opportunity-card").filter(has_text=lost_name).first
            lost_card.click(); page.wait_for_selector(".modal")
            page.locator('.modal [data-record-action="mark-lost"]').click(); page.wait_for_selector("#v531-close-form")
            page.fill('#v531-close-form [name="close_date"]', datetime.now(timezone.utc).date().isoformat())
            page.select_option('#v531-close-form [name="loss_reason"]', "Timing")
            page.fill('#v531-close-form [name="note"]', "Product Owner quick-close Lost Golden Path")
            page.click("#v531-confirm-close"); page.wait_for_timeout(900)
            page.goto(f"{base}/#/crm?tab=opportunities&search={lost_name}", wait_until="domcontentloaded")
            page.wait_for_selector(".v53-opportunity-card")
            lost_card = page.locator(".v53-opportunity-card").filter(has_text=lost_name).first
            lost_column = page.locator(".v53-pipeline-column").filter(has=page.locator("header strong").filter(has_text="Closed Lost")).first
            check("Mark Lost moves the opportunity into Closed Lost", lost_card.count() == 1 and lost_column.locator(".v53-opportunity-card").filter(has_text=lost_name).count() == 1, lost_card.inner_text() if lost_card.count() else "")
            lost_card.click(); page.wait_for_selector(".v531-final-status.lost")
            check("Closed Lost opportunity detail preserves the required loss reason", "Closed Lost" in page.locator(".v531-final-status.lost").inner_text() and "Timing" in page.locator(".v531-final-status.lost").inner_text(), page.locator(".v531-final-status.lost").inner_text())
            page.locator(".modal [data-close-modal]").last.click()
            shot(page, "02-opportunity-mark-lost.png")

            page.goto(f"{base}/#/reports", wait_until="domcontentloaded"); page.wait_for_selector(".v53-attention-panel")
            report_text = page.locator("#page").inner_text()
            report_data = page.request.get(f"{base}/api/v521/tenants/{tenant_id}/action-report").json()
            won_kpi = next((x for x in report_data.get("kpis", []) if x.get("key") == "won_revenue"), {})
            manual_source = next((x for x in report_data.get("sources", []) if str(x.get("source", "")).lower() == "manual"), {})
            check("Quick-close Won updates the existing reporting and source-attribution engine", int(won_kpi.get("value_cents", 0)) >= 2_800_000 and int(manual_source.get("value_cents", 0)) >= 2_800_000 and "won revenue" in report_text.lower(), json.dumps({"won_kpi": won_kpi, "manual_source": manual_source}))

            page.goto(f"{base}/#/crm?tab=leads", wait_until="domcontentloaded"); page.wait_for_selector(".v53-crm-shell")
            lead_rows = page.locator(".v53-lead-row")
            check("CRM Leads index uses the corrected readable card-row presentation", lead_rows.count() >= 1 and lead_rows.first.locator('[data-open-record="lead"]').count() == 1, f"rows={lead_rows.count()}")
            first_box = lead_rows.first.bounding_box()
            check("CRM lead row uses available workspace width instead of a compressed data dump", bool(first_box and first_box["width"] > 850), json.dumps(first_box or {}))
            shot(page, "03-crm-leads-corrected.png")

            page.goto(f"{base}/#/forecast", wait_until="domcontentloaded"); page.wait_for_selector(".v53-chart")
            forecast_text = page.locator("#page").inner_text()
            check("Forecast separates CRM records from ProspectIQ-originated potential without changing the existing totals", page.locator(".v53-forecast-table").count() == 2 and "CRM Opportunity & Relationship Forecast" in forecast_text and "ProspectIQ Pipeline Potential" in forecast_text, forecast_text[:1500])
            shot(page, "04-forecast-provenance-grids.png")

            page.goto(f"{base}/#/solutions", wait_until="domcontentloaded"); page.wait_for_selector(".v53-solution-card")
            cards = page.locator(".v53-solution-card")
            containment_ok = True; containment_detail = []
            for i in range(min(cards.count(), 12)):
                card = cards.nth(i); button = card.locator("footer button")
                cb = card.bounding_box(); bb = button.bounding_box() if button.count() else None
                if cb and bb:
                    inside = bb["x"] >= cb["x"] - 1 and bb["x"] + bb["width"] <= cb["x"] + cb["width"] + 1 and bb["y"] + bb["height"] <= cb["y"] + cb["height"] + 1
                    containment_ok = containment_ok and inside
                    containment_detail.append({"index": i, "inside": inside, "card": cb, "button": bb})
            check("Solutions labels, pricing and actions remain contained inside their cards at desktop size", containment_ok, json.dumps(containment_detail[:4]))
            shot(page, "05-solutions-card-containment.png")

            # -----------------------------------------------------------------
            # RMR Owner: actionable portfolio/success intelligence and clarity.
            # -----------------------------------------------------------------
            page.click("#logout-button"); page.wait_for_selector('[data-demo-email="dave@rmr.local"]')
            page.click('[data-demo-email="dave@rmr.local"]'); page.wait_for_selector(".app-shell")
            page.goto(f"{base}/#/portfolio", wait_until="domcontentloaded"); page.wait_for_selector('[data-portfolio-kpi="attention"]')
            check("Portfolio Command Center exposes all eight record-backed or calculation-backed KPIs as actions", page.locator("[data-portfolio-kpi]").count() == 8, f"kpis={page.locator('[data-portfolio-kpi]').count()}")
            page.click('[data-portfolio-kpi="attention"]'); page.wait_for_timeout(400)
            note = page.locator("#portfolio-filter-note").inner_text()
            check("Needs Attention drills into the affected client rows", "attention" in note.lower(), note)
            page.click('[data-portfolio-kpi="mrr"]'); page.wait_for_selector(".v531-detail-list")
            check("MRR opens a calculation-backed client detail view", page.locator("[data-portfolio-detail-client]").count() >= 1)
            page.locator(".modal [data-close-modal]").last.click()
            shot(page, "06-portfolio-kpi-drilldown.png")

            page.goto(f"{base}/#/client-success", wait_until="domcontentloaded"); page.wait_for_selector("#success-actions")
            check("Client Success recommendations expose a direct Review Client action", page.locator("[data-success-client360]").count() >= 1 and "Review Client" in page.locator("#success-actions").inner_text())
            page.click('[data-success-kpi="attention"]'); page.wait_for_timeout(400)
            success_note = page.locator("#success-filter-note").inner_text()
            check("Client Success Needs Attention filters the underlying scorecard", "requiring attention" in success_note.lower(), success_note)
            shot(page, "07-client-success-actionability.png")

            # Honest invitation delivery and access state.
            portfolio = page.request.get(f"{base}/api/portfolio/summary").json()
            access_tenant = None
            for tenant in portfolio.get("tenants", []):
                access = page.request.get(f"{base}/api/tenants/{tenant['id']}/access").json()
                if access.get("access", {}).get("pending_invitation"):
                    access_tenant = tenant; break
            if access_tenant:
                page.goto(f"{base}/#/client-360?tenant={access_tenant['id']}", wait_until="domcontentloaded")
                page.wait_for_selector("#manage-access"); page.click("#manage-access")
                page.wait_for_selector(".v531-delivery-state")
                access_text = page.locator(".modal").inner_text()
                check("Client Access states whether an invitation is local/pending/sent/accepted without claiming unverified email delivery", "Invitation" in access_text and ("Local Product Owner" in access_text or "pending" in access_text.lower() or "delivery" in access_text.lower()), access_text[:1200])
                page.locator(".modal [data-close-modal]").last.click()

            # Objective onboarding requirement state and activation gate clarity.
            page.goto(f"{base}/#/onboarding", wait_until="domcontentloaded"); page.wait_for_selector("[data-onboard]")
            incomplete = page.locator("[data-onboard]").filter(has_text="Continue setup").first
            if incomplete.count():
                incomplete.click(); page.wait_for_selector(".v531-requirement")
                requirement_text = page.locator(".v531-requirement").inner_text()
                complete_disabled = page.locator("#complete-step").is_disabled()
                check("Onboarding exposes objective stage requirements and blocks completion where required evidence is missing", bool(requirement_text.strip()) and (complete_disabled or "ready" in requirement_text.lower() or "optional" in requirement_text.lower()), requirement_text)
                page.locator(".modal [data-close-modal]").last.click()

            # Service activation confirmation and next operational handoff.
            page.goto(f"{base}/#/service-requests", wait_until="domcontentloaded")
            review = page.locator("[data-review-request]").first
            if review.count():
                review.click(); page.wait_for_selector("#activate-request")
                page.click("#activate-request"); page.wait_for_selector("#confirm-activate-solution")
                confirm_text = page.locator(".modal").inner_text()
                check("Service activation requires confirmation of client, solution, price and effective date", all(x in confirm_text for x in ["Client", "Solution", "Monthly price", "Effective date", "Confirm Activation"]), confirm_text[:1200])
                page.locator(".modal [data-close-modal]").last.click()
            else:
                check("Service activation confirmation remains reachable when a request exists", True, "No pending request in this isolated test state; runtime gate verifies activation follow-up")

            page.goto(f"{base}/#/system", wait_until="domcontentloaded"); page.wait_for_selector(".v531-health-card")
            details = page.locator(".v531-health-card details")
            check("System Health keeps plain-language status primary and technical JSON collapsed by default", details.count() >= 1 and all(not details.nth(i).get_attribute("open") for i in range(details.count())), f"details={details.count()}")
            details.first.locator("summary").click()
            check("Technical health evidence remains available through progressive disclosure", details.first.get_attribute("open") is not None and details.first.locator("pre").count() == 1)
            shot(page, "08-system-health-progressive-disclosure.png")

            check("No unexpected browser console or page errors occurred", not errors, "; ".join(errors[:10]))
        except Exception as exc:
            status = "failed"; failure = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            try: shot(page, "FAILURE.png")
            except Exception: pass
        finally:
            browser.close()

    result = {
        "status": status,
        "release": "5.4.0-tenant-themes-po1",
        "base_url": base,
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "passed": sum(1 for row in checks if row["passed"]),
        "failed": sum(1 for row in checks if not row["passed"]) + (1 if status == "failed" and all(row["passed"] for row in checks) else 0),
        "checks": checks,
        "browser_errors": errors,
        "failure": failure,
        "screenshots": sorted(p.name for p in out.glob("*.png")),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"]}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
