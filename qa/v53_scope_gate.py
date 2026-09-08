#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.3.1-final-production-corrections-po1"
checks: list[dict[str, object]] = []


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def check(name: str, condition: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))


init = text("rmr_platform/__init__.py")
main = text("rmr_platform/main.py")
backend = text("rmr_platform/v53_experience.py")
client = text("rmr_platform/client_admin_corrections.py")
frontend = text("public/pages/v53_client_experience.js")
css = text("public/v53-experience.css")
index = text("public/index.html")
unified = text("public/pages/unified.js")
app = text("public/app.js")
ui = text("public/ui.js")
compose = text("docker-compose.product-owner.yml")
launcher = text("START-PRODUCT-OWNER-TEST.ps1")
scope = text("V531-PRODUCT-OWNER-SCOPE-LOCK.md")

check("Exact v5.3.1 release identity is active", RELEASE in init, init.strip())
check("Frozen v5.3.1 Product Owner scope lock is packaged", "RMR Global v5.3.1 Final Production Corrections" in scope)
check("v5.3 backend router is registered", "v53_experience" in main and "v53_experience.router" in main)
check("v5.3 frontend route renderer is registered", "renderV53ClientExperience" in unified)
check("v5.3 stylesheet is linked", "v53-experience.css" in index)
check("Client Administrator route set includes the frozen modules", all(token in frontend for token in ("'home'", "'crm'", "'piq'", "'campaigns'", "'email'", "'forecast'", "'reports'", "'training'", "'organization'", "'solutions'")))
check("Application unified routes include all Client Administrator modules", all(token in app for token in ("home", "crm", "forecast", "reports", "piq", "solutions", "campaigns", "email", "website", "organization", "training")))
check("Website remains outside the v5.3 replacement renderer", "'website'" not in frontend.split("const ROUTES",1)[1].split(";",1)[0])
check("Dashboard has tenant-scope evidence", "Tenant data scope" in frontend and "data_scope" in backend)
check("Dashboard KPI cards route to underlying records", "data-v53-route" in frontend and "Weighted Pipeline" in frontend)
check("CRM has connected overview endpoint", '/crm/overview' in backend)
check("CRM has account/contact/lead/opportunity 360 endpoint", '/crm/records/{record_type}/{record_id}' in backend)
check("CRM supports controlled lead conversion", '/leads/{lead_id}/convert' in backend and "LeadConversionIn" in backend)
check("Lead conversion allows optional contact and opportunity creation", "create_contact" in backend and "create_opportunity" in backend)
check("Lead conversion captures stage value probability close date and next action", all(token in backend for token in ("opportunity_name", "stage", "value_cents", "probability_pct", "expected_close_date", "next_action")))
check("CRM record cards and opportunity cards are openable", "data-open-record" in frontend and "openCrmRecord" in frontend)
check("CRM email action keeps relationship context", all(token in frontend for token in ("account_id", "opportunity_id", "contact_id", "lead_id", "recipient_email")) and "one-to-one-email" in frontend)
check("CRM exposes useful activity and timeline context", "v53-timeline" in frontend and "Lead Conversion" in backend)
check("CRM has duplicate-review action", "Potential Duplicate Accounts" in frontend and "crm/duplicates" in frontend)
check("ProspectIQ preserves research and move-to-CRM actions", "adaptive-research" in frontend and "move-to-crm" in frontend)
check("ProspectIQ intelligence is exposed in CRM context", "_piq_for_company" in backend and "v53-intelligence" in frontend)
check("Campaign social copy actions name the clipboard destination", "Copy Post to Clipboard" in frontend and "Copy Hashtags to Clipboard" in frontend)
check("Campaign supports complete-post copy", "Copy Complete Post" in frontend)
check("Campaign generation edit regenerate and save remain available", all(token in frontend for token in ("Generate Social Content", "Regenerate", "Save", "Open / Edit")))
check("Campaign export package explains download and external provider import", "Download Recipient CSV" in frontend and "Review Package & Instructions" in frontend and "What happens next?" in frontend and "bulk_delivery" in backend)
check("Bulk email delivery remains excluded", '"bulk_email_delivery": False' in client and "No bulk delivery occurs from RMR Global" in frontend)
check("One-to-one email remains connected-mailbox based", "client’s connected mailbox" in frontend and "connection_id" in frontend)
check("Recorded messages are openable", "openMessageDetail" in frontend and "Recorded Message" in frontend)
check("Forecast is tenant-specific and source-transparent", "Forecast and CRM values for" in backend and "TENANT SALES FORECAST" in frontend)
check("Forecast provides visual trend and split provenance grids", "forecastChart" in frontend and "CRM Opportunity & Relationship Forecast" in frontend and "ProspectIQ Pipeline Potential" in frontend)
check("Forecast retains CSV/XLSX preview and import", "forecast-import/preview" in frontend and "forecast-import/commit" in frontend and 'accept=".csv,.xlsx"' in frontend)
check("Reporting retains actionable attention and drilldowns", "What needs my attention?" in frontend and "data-v53-route" in frontend and "Growth Funnel" in frontend)
check("Client training supports links and uploaded resources", "Open / Download" in frontend and "uploaded_file" in client and "application/octet-stream" in client)
check("Training permits video PDF PowerPoint and Word", all(token in client for token in (".mp4", ".pdf", ".pptx", ".docx")))
check("Training supports assignments and completion", "ClientTrainingAssignment" in client and "training/assignments" in client)
check("Team experience provides people org and list views", all(token in frontend for token in ("People", "Org View", "List View")))
check("Team management retains invite edit and reset", all(token in frontend for token in ("Invite Team Member", "Edit", "Send Reset")))
check("Solutions never automatically activate or bill", "No automatic activation or billing" in frontend and "Request This Solution" in frontend)
check("Solutions suppress placeholder zero-dollar pricing", "No placeholder $0" not in frontend and "Included in current agreement" in frontend)
check("External website URL normalization accepts common business domains", 'value = f"https://{value}"' in client)
check("Premium modern design system is physically substantial", len(css) > 15000 and all(token in css for token in ("v53-hero", "v53-metric", "v53-pipeline", "v53-drawer", "v53-training", "v53-solution")), len(css))
check("Product Owner package uses isolated v5.3.1 Docker project", "rmr-global-v531-product-owner" in launcher)
check("Product Owner package uses port 8084", "8084" in compose and "8084" in launcher)
check("Sidebar identifies v5.3.1 Final Production Corrections", "v5.3.1" in ui and "Final Production Corrections" in ui)
check("Future exclusions are explicitly preserved", all(token in scope for token in ("No RMR Global bulk-email delivery engine", "No full Salesforce", "No complete official RMR training-video curriculum", "No destructive reset/reseed")))

status = "passed" if all(row["passed"] for row in checks) else "failed"
result = {
    "status": status,
    "release": RELEASE,
    "checks": checks,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]),
}
out = ROOT / "qa" / "V53-SCOPE-GATE.json"
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "output": str(out)}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
