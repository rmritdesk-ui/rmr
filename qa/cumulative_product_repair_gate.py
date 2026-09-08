#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.3.1-final-production-corrections-po1"
checks: list[dict[str, object]] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")

init = text("rmr_platform/__init__.py")
main = text("rmr_platform/main.py")
migrations = text("rmr_platform/migrations.py")
repair = text("rmr_platform/cumulative_product_repair.py")
models = text("rmr_platform/cumulative_product_models.py")
client = text("rmr_platform/client_admin_corrections.py")
admin_js = text("public/pages/cumulative_admin.js")
client_js = text("public/pages/client_admin_correction.js")
index = text("public/index.html")
css = text("public/cumulative-product-repair.css")
launcher = text("START-PRODUCT-OWNER-TEST.ps1")
dockerfile = text("Dockerfile")

check("Exact cumulative repair release identity is active", RELEASE in init and RELEASE in launcher, RELEASE)
check("v5.2.2 migration is the required current migration", '005.005.000-cumulative-product-repair' in migrations and 'MIGRATION_VERSION = "005.005.000-cumulative-product-repair"' in migrations)
check("Cumulative repair router is registered", "cumulative_product_repair.router" in main)
check("Per-client commercial-term model exists", "class ClientServiceCommercialTerm" in models)
check("Commercial change-history model exists", "class CommercialTermHistory" in models)
check("Message delivery provenance model exists", "class MessageDeliveryContext" in models)
check("Social revision-history model exists", "class SocialContentRevision" in models)
check("Client-specific commercial-term list endpoint exists", '/admin/tenants/{tenant_id}/commercial-terms' in repair)
check("Per-service commercial terms validate a 100 percent split", "RMR and Step2 shares must total 100%" in repair)
check("Partner Economics derives from service agreements", '/admin/partner-economics' in repair and "data_provenance" in repair)
check("Partner Economics exposes traceable detail and history", '/admin/partner-economics/terms/{tenant_service_id}' in repair and "CommercialTermHistory" in repair)
check("Sent-message detail endpoint exists", '/tenants/{tenant_id}/messages/{message_id}' in repair)
check("Social edit and regenerate endpoints exist", '/tenants/{tenant_id}/social/{social_id}' in repair and '/tenants/{tenant_id}/social/{social_id}/regenerate' in repair)
check("AI provider integration uses the OpenAI Responses API path", 'f"{base_url}/responses"' in client and '"store": False' in client)
check("Demo social generation is explicitly labeled", '"demonstration": provider in {"demonstration", "mock", "local"}' in client)
check("Mass-email delivery remains excluded", '"bulk_email_delivery": False' in client)
check("Campaign export formats include dedicated email platforms", all(value in client for value in ('mailchimp', 'constant_contact', 'hubspot', 'brevo', 'generic')))
check("One-to-one email captures client mailbox and CRM context", "MessageDeliveryContext" in client and 'one-to-one-email' in client)
check("Forecast CSV and XLSX upload remains supported", "openpyxl" in client and "forecast-import/preview" in client)
check("Forecast provenance remains explicit", "forecast-provenance" in client and "actual_source" in client)
check("Actionable reporting remains implemented", "action-report" in client and "What Needs My Attention" in client_js)
check("Client-managed training remains implemented", "client-training" in client and ("Upload a training file or provide a hosted training URL" in client or "Upload a video or provide a hosted video URL" in client))
check("Secure password-reset workflow remains implemented", "send-password-reset" in client and "expires_at" in client)
check("Solutions requests retain date time and timezone", "contact_date" in client and "contact_time" in client and "timezone" in client)
check("RMR Admin pricing and Partner Economics use the corrected UI", "renderCumulativeAdmin" in text("public/pages/admin.js") and "Client Pricing & Revenue Share" in admin_js)
check("Admin pricing UI exposes client price and RMR Step2 split", all(value in admin_js for value in ("Client Price", "RMR", "Step2", "Effective", "Direct Cost")))
check("Partner Economics UI exposes trace and reconciliation", "Client and Service Trace" in admin_js and "Reconciliation" in admin_js)
check("Sent messages are openable from Email and Activities", "data-message-detail" in client_js and "Sent message detail" in client_js)
check("Social content is openable editable and regenerable", "data-open-social" in client_js and "Regenerate" in client_js)
check("Premium cumulative repair stylesheet is physically linked", "cumulative-product-repair.css" in index and "premium" in css.lower())
check("Docker image includes required static assets", "COPY static ./static" in dockerfile)
check("One-click Product Owner launcher is present", (ROOT / "START-PRODUCT-OWNER-TEST.bat").is_file() and "product_owner_qc" in launcher)

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {"status": status, "release": RELEASE, "checks": checks, "passed": sum(1 for r in checks if r["passed"]), "failed": sum(1 for r in checks if not r["passed"])}
out = ROOT / "qa" / "V522-CUMULATIVE-PRODUCT-REPAIR-GATE.json"
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "output": str(out)}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
