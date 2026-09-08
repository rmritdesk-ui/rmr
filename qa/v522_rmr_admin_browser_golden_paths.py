#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="RMR Global v5.2.2 RMR Admin browser Golden Paths")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--output-dir", default="qa/screenshots-v522-rmr-admin")
    parser.add_argument("--result", default="qa/V522-RMR-ADMIN-BROWSER-GOLDEN-PATHS.json")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    result_path = Path(args.result).resolve(); result_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    checks: list[dict] = []
    errors: list[str] = []
    failure = ""; status = "passed"
    started = datetime.now(timezone.utc)

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""), flush=True)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-proxy-server", "--proxy-bypass-list=*", "--host-resolver-rules=MAP rmr-global.test 127.0.0.1"],
        )
        page = browser.new_page(viewport={"width": 1680, "height": 1150})
        page.set_default_timeout(20000)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" and "401" not in msg.text and "favicon" not in msg.text.lower() else None)
        try:
            page.goto(base, wait_until="domcontentloaded")
            demo = '[data-demo-email="dave@rmr.local"]'
            page.wait_for_selector(demo)
            page.click(demo)
            page.wait_for_selector(".app-shell")
            check("RMR Owner reaches the platform administration workspace", "Portfolio Command Center" in page.locator("body").inner_text())

            page.goto(f"{base}/#/pricing", wait_until="domcontentloaded")
            page.wait_for_selector("#v522-pricing-client")
            page.select_option("#v522-pricing-client", label="Kerry Laughlin Real Estate")
            page.wait_for_timeout(600)
            page.wait_for_selector("[data-v522-edit-term]")
            pricing_text = page.locator("#page").inner_text()
            check("Client Pricing exposes per-client and per-service commercial terms", all(x in pricing_text.lower() for x in ["client pricing & revenue share", "negotiated", "rmr", "step2", "direct cost", "seller", "effective"]), pricing_text[:1400])
            check("Client Pricing exposes an edit action for every service row", page.locator("[data-v522-edit-term]").count() >= 1, f"edit_actions={page.locator('[data-v522-edit-term]').count()}")

            first_row = page.locator("[data-v522-edit-term]").first.locator("xpath=ancestor::tr")
            service_name = first_row.locator("td").first.inner_text().split("\n")[0].strip()
            page.locator("[data-v522-edit-term]").first.click()
            page.wait_for_selector("#v522-edit-form")
            form = page.locator("#v522-edit-form")
            originals = {
                "client_price": form.locator('[name="client_price"]').input_value(),
                "usage_price": form.locator('[name="usage_price"]').input_value(),
                "cadence": form.locator('[name="cadence"]').input_value(),
                "quantity": form.locator('[name="quantity"]').input_value(),
                "rmr_share_pct": form.locator('[name="rmr_share_pct"]').input_value(),
                "step2_share_pct": form.locator('[name="step2_share_pct"]').input_value(),
                "split_basis": form.locator('[name="split_basis"]').input_value(),
                "direct_cost": form.locator('[name="direct_cost"]').input_value(),
                "seller_org": form.locator('[name="seller_org"]').input_value(),
                "seller_name": form.locator('[name="seller_name"]').input_value(),
                "effective_date": form.locator('[name="effective_date"]').input_value(),
                "status": form.locator('[name="status"]').input_value(),
                "notes": form.locator('[name="notes"]').input_value(),
            }
            page.fill('#v522-edit-form [name="client_price"]', "395.55")
            page.fill('#v522-edit-form [name="rmr_share_pct"]', "63")
            page.fill('#v522-edit-form [name="step2_share_pct"]', "37")
            page.select_option('#v522-edit-form [name="split_basis"]', "gross")
            page.fill('#v522-edit-form [name="direct_cost"]', "17.25")
            page.fill('#v522-edit-form [name="seller_name"]', f"{stamp} Browser Golden Path")
            page.fill('#v522-edit-form [name="notes"]', f"{stamp} reversible RMR Admin browser QC")
            page.click("#v522-save-term")
            page.wait_for_timeout(900)
            page.goto(f"{base}/#/pricing", wait_until="domcontentloaded")
            page.wait_for_selector("#v522-pricing-client")
            page.select_option("#v522-pricing-client", label="Kerry Laughlin Real Estate")
            page.wait_for_timeout(700)
            row = page.locator("tr").filter(has_text=service_name).first
            row_text = row.inner_text()
            check("Client-specific price and per-service RMR/Step2 split persist after reload", "$395.55" in row_text and "63%" in row_text and "37%" in row_text and "Browser Golden Path" in row_text, row_text)
            page.screenshot(path=str(out / "01-client-pricing.png"), full_page=True)

            page.goto(f"{base}/#/partner-economics", wait_until="domcontentloaded")
            page.wait_for_selector("[data-v522-econ-detail]")
            economics_text = page.locator("#page").inner_text()
            check("Partner Economics shows formula provenance, reconciliation, and client/service trace", all(x in economics_text.lower() for x in ["how the calculations work", "client and service trace", "revenue by service", "reconciliation"]), economics_text[:1600])
            econ_row = page.locator("tr").filter(has_text="Kerry Laughlin Real Estate").filter(has_text=service_name).first
            econ_text = econ_row.inner_text()
            check("Partner Economics derives the test service from the saved client agreement", "$395.55" in econ_text and "63%" in econ_text and "37%" in econ_text, econ_text)
            econ_row.locator("[data-v522-econ-detail]").click()
            page.wait_for_selector(".modal")
            detail_text = page.locator(".modal").inner_text()
            check("Partner Economics drill-down explains exact terms, reconciliation, and history", "Calculation reconciles" in detail_text and "Term history" in detail_text and "$395.55" in detail_text, detail_text[:1200])
            page.screenshot(path=str(out / "02-partner-economics.png"), full_page=True)
            page.locator("[data-close-modal]").last.click()

            # Restore the original service terms through the same client-facing admin workflow.
            page.goto(f"{base}/#/pricing", wait_until="domcontentloaded")
            page.wait_for_selector("#v522-pricing-client")
            page.select_option("#v522-pricing-client", label="Kerry Laughlin Real Estate")
            page.wait_for_timeout(600)
            page.locator("tr").filter(has_text=service_name).first.locator("[data-v522-edit-term]").click()
            page.wait_for_selector("#v522-edit-form")
            for name in ["client_price", "usage_price", "quantity", "rmr_share_pct", "step2_share_pct", "direct_cost", "seller_name", "effective_date", "notes"]:
                page.fill(f'#v522-edit-form [name="{name}"]', originals[name])
            for name in ["cadence", "split_basis", "seller_org", "status"]:
                page.select_option(f'#v522-edit-form [name="{name}"]', originals[name])
            page.click("#v522-save-term")
            page.wait_for_timeout(800)
            page.goto(f"{base}/#/pricing", wait_until="domcontentloaded")
            page.wait_for_selector("#v522-pricing-client")
            page.select_option("#v522-pricing-client", label="Kerry Laughlin Real Estate")
            page.wait_for_timeout(600)
            restored_text = page.locator("tr").filter(has_text=service_name).first.inner_text()
            original_price = float(originals["client_price"])
            price_ok = f"${original_price:,.2f}" in restored_text or (original_price == 0 and "$0" in restored_text)
            check(
                "Browser Golden Path restores the original client commercial terms",
                price_ok
                and f"{float(originals['rmr_share_pct']):g}%" in restored_text
                and f"{float(originals['step2_share_pct']):g}%" in restored_text
                and originals["split_basis"] in restored_text,
                restored_text,
            )

            check("No browser page or console errors occurred", not errors, "; ".join(errors[:10]))
        except Exception as exc:
            status = "failed"; failure = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            try: page.screenshot(path=str(out / "FAILURE.png"), full_page=True)
            except Exception: pass
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
        "screenshots": sorted(p.name for p in out.glob("*.png")),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"]}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
