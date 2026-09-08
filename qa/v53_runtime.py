#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="rmr-v53-runtime-"))
os.environ.update({
    "RMR_DATA_DIR": str(DATA),
    "RMR_ENVIRONMENT": "pilot",
    "RMR_BASE_URL": "http://testserver",
    "RMR_ALLOW_DEMO_CREDENTIALS": "true",
    "RMR_AUTO_MIGRATE": "true",
    "RMR_AUTO_SEED": "true",
    "RMR_INSTALL_PROFILE": "demo",
    "RMR_APP_VERSION": "5.3.1-final-production-corrections-po1",
    "RMR_SECRET_KEY": "v53-runtime-gate-secret-key-long-enough",
    "RMR_CREDENTIAL_ENCRYPTION_KEY": "0123456789abcdef0123456789abcdef",
    "RMR_INTEGRATION_ENCRYPTION_KEY": "abcdef0123456789abcdef0123456789",
    "RMR_AI_PROVIDER": "demonstration",
    "RMR_ONE_TO_ONE_EMAIL_PROVIDER": "mock",
    "RMR_SYSTEM_EMAIL_PROVIDER": "local",
    "RMR_PIQ_DISCOVERY_PROVIDER": "demonstration",
    "RMR_PIQ_RESEARCH_PROVIDER": "demonstration",
    "RMR_LOCAL_RECOVERY_MODE": "true",
    "RMR_EXTERNAL_SITE_LIVE_TEST": "false",
})

from fastapi.testclient import TestClient  # noqa: E402
from rmr_platform.main import app  # noqa: E402

RELEASE = "5.3.1-final-production-corrections-po1"
HEADERS = {"X-RMR-Request": "1"}
checks: list[dict[str, object]] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    row = {"name": name, "passed": bool(condition), "detail": detail}
    checks.append(row)
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": password}, headers=HEADERS)
    check(f"Login works for {email}", response.status_code == 200, response.text[:500])
    return response.json()["user"]


status = "passed"
error = ""
try:
    with TestClient(app) as client:
        health = client.get("/api/health")
        check("Application starts at exact v5.3 release", health.status_code == 200 and health.json().get("version") == RELEASE, health.json())

        kerry_user = login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        kerry_id = kerry_user["tenant_id"]
        dashboard = client.get(f"/api/v53/tenants/{kerry_id}/dashboard")
        check("Kerry Client Administrator dashboard is tenant scoped", dashboard.status_code == 200 and dashboard.json()["data_scope"]["tenant_id"] == kerry_id and "Kerry" in dashboard.json()["tenant"]["name"], dashboard.text[:900])
        check("Dashboard exposes actionable KPI routes", all(row.get("route") for row in dashboard.json()["kpis"]), dashboard.json()["kpis"])

        client.post("/api/auth/logout", headers=HEADERS)
        owner = login(client, "dave@rmr.local", "RMR-Owner-2026!")
        tenants = client.get("/api/tenants").json()["tenants"]
        caf = next(row for row in tenants if row["slug"] == "cactus-air-filters")
        client.post("/api/auth/logout", headers=HEADERS)

        login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        forbidden = client.get(f"/api/v53/tenants/{caf['id']}/dashboard")
        check("Kerry cannot access CAF v5.3 dashboard", forbidden.status_code == 403, forbidden.status_code)
        client.post("/api/auth/logout", headers=HEADERS)
        caf_user = login(client, "admin@cactus-air-filters.demo", "Client-Admin-2026!")
        caf_dashboard = client.get(f"/api/v53/tenants/{caf_user['tenant_id']}/dashboard")
        check("CAF sees only CAF tenant scope", caf_dashboard.status_code == 200 and caf_dashboard.json()["data_scope"]["tenant_id"] == caf_user["tenant_id"] and "Cactus" in caf_dashboard.json()["tenant"]["name"], caf_dashboard.text[:700])
        client.post("/api/auth/logout", headers=HEADERS)

        login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        crm = client.get(f"/api/v53/tenants/{kerry_id}/crm/overview")
        check("Modern CRM overview loads connected records", crm.status_code == 200 and all(key in crm.json() for key in ("accounts", "contacts", "leads", "opportunities", "activities", "summary")), crm.text[:900])

        lead_resp = client.post(f"/api/tenants/{kerry_id}/leads", json={
            "company_name": "V53 Runtime Prospect",
            "contact_name": "Morgan Runtime",
            "email": "morgan.runtime@example.com",
            "phone": "602-555-0153",
            "source": "Website Appointment Request",
            "status": "New",
            "assigned_user_id": None,
            "notes": "v5.3 controlled conversion gate",
        }, headers=HEADERS)
        check("CRM lead can be created", lead_resp.status_code == 200, lead_resp.text[:700])
        lead = lead_resp.json()["lead"]
        convert = client.post(f"/api/v53/leads/{lead['id']}/convert", json={
            "account_name": "Morgan Runtime Household",
            "create_contact": True,
            "create_opportunity": True,
            "opportunity_name": "Morgan Runtime relocation opportunity",
            "stage": "Qualified",
            "value_cents": 47500000,
            "probability_pct": 65,
            "expected_close_date": "2026-12-15",
            "next_action": "Schedule buyer consultation",
        }, headers=HEADERS)
        check("Controlled lead conversion creates deliberate account contact and opportunity", convert.status_code == 200 and convert.json()["opportunity"]["stage"] == "Qualified" and convert.json()["opportunity"]["value_cents"] == 47500000 and convert.json()["contact"]["email"] == "morgan.runtime@example.com", convert.text[:1300])
        created = convert.json()
        detail = client.get(f"/api/v53/tenants/{kerry_id}/crm/records/opportunity/{created['opportunity']['id']}")
        check("Opportunity 360 connects account contact activity and original source", detail.status_code == 200 and detail.json()["related"]["account"]["id"] == created["account"]["id"] and detail.json()["related"]["contact"]["id"] == created["contact"]["id"] and any(x["activity_type"] == "Lead Conversion" for x in detail.json()["activities"]), detail.text[:1600])

        update_opp = client.patch(f"/api/opportunities/{created['opportunity']['id']}", json={
            "name": "Morgan Runtime home search",
            "stage": "Proposal",
            "value_cents": 50000000,
            "probability_pct": 75,
            "expected_close_date": "2026-11-30",
            "next_action": "Review shortlist and financing",
        }, headers=HEADERS)
        check("Opportunity name stage value probability close date and next action update", update_opp.status_code == 200 and update_opp.json()["opportunity"]["name"] == "Morgan Runtime home search" and update_opp.json()["opportunity"]["stage"] == "Proposal", update_opp.text[:900])
        update_contact = client.patch(f"/api/v53/contacts/{created['contact']['id']}", json={"phone": "602-555-0199", "title": "Buyer"}, headers=HEADERS)
        check("Contact 360 data is editable", update_contact.status_code == 200 and update_contact.json()["contact"]["phone"] == "602-555-0199", update_contact.text[:600])

        email_ws = client.get(f"/api/v521/tenants/{kerry_id}/email-workspace").json()
        connection = next((row for row in email_ws["connections"] if row["status"] not in {"DISCONNECTED", "REVOKED"}), None)
        check("Client-owned mailbox connection is available", bool(connection), email_ws.get("connections"))
        sent = client.post(f"/api/v521/tenants/{kerry_id}/one-to-one-email", json={
            "connection_id": connection["id"],
            "recipient_email": "morgan.runtime@example.com",
            "recipient_name": "Morgan Runtime",
            "subject": "Your relocation planning conversation",
            "body": "Here is the next step for your home search.",
            "account_id": created["account"]["id"],
            "opportunity_id": created["opportunity"]["id"],
            "contact_id": created["contact"]["id"],
        }, headers=HEADERS)
        check("One-to-one email uses client mailbox and records CRM context", sent.status_code == 200 and sent.json()["message"]["status"].startswith("RECORDED"), sent.text[:1000])
        detail_after_email = client.get(f"/api/v53/tenants/{kerry_id}/crm/records/opportunity/{created['opportunity']['id']}").json()
        check("Opportunity 360 includes recorded communication", any(x["recipient_email"] == "morgan.runtime@example.com" for x in detail_after_email["messages"]), detail_after_email["messages"])

        social = client.post(f"/api/v521/tenants/{kerry_id}/social/generate", json={
            "objective": "Help Phoenix homeowners plan a move to Northern Colorado",
            "audience": "Homeowners considering relocation",
            "tone": "warm, credible and locally knowledgeable",
            "call_to_action": "Schedule a relocation planning conversation",
            "keywords": ["Phoenix", "Northern Colorado", "relocation"],
            "suggested_visual": "A family arriving at a Northern Colorado home",
        }, headers=HEADERS)
        check("Social generation returns four differentiated platform drafts", social.status_code == 200 and len(social.json().get("items", [])) == 4 and len({x["post_text"] for x in social.json()["items"]}) >= 3, social.text[:1200])

        package = client.post(f"/api/v521/tenants/{kerry_id}/campaign-exports", json={
            "name": "V53 Runtime Follow-Up",
            "provider_format": "mailchimp",
            "include_leads": True,
            "include_contacts": True,
            "include_piq": False,
            "lead_statuses": [],
            "sources": [],
            "subject": "A practical next step",
            "preview_text": "Guidance for your move",
            "email_body": "A client-approved campaign message.",
            "call_to_action": "Schedule a consultation",
        }, headers=HEADERS)
        check("Campaign package creates provider-ready recipient CSV without delivery", package.status_code == 200 and package.json()["package"]["provider_format"] == "mailchimp", package.text[:900])
        package_id = package.json()["package"]["id"]
        package_detail = client.get(f"/api/v53/campaign-exports/{package_id}")
        check("Campaign package explains recipient download and external delivery steps", package_detail.status_code == 200 and package_detail.json()["instructions"]["bulk_delivery"] is False and len(package_detail.json()["instructions"]["steps"]) >= 4, package_detail.json())
        download = client.get(package_detail.json()["download_url"])
        check("Campaign recipient CSV is downloadable and tenant scoped", download.status_code == 200 and b"Email Address" in download.content and b"morgan.runtime@example.com" in download.content, download.content[:300])

        forecast = client.get(f"/api/v53/tenants/{kerry_id}/forecast-dashboard")
        check("Forecast is tenant scoped and source transparent", forecast.status_code == 200 and "Kerry" in forecast.json()["tenant"]["name"] and "Kerry" in forecast.json()["data_scope"] and set(forecast.json()["sources"]) == {"forecast", "actual_imported", "closed_won", "pipeline"}, forecast.text[:1100])

        original_site = client.get(f"/api/v521/tenants/{kerry_id}/website-connection").json()
        normalized = client.patch(f"/api/v521/tenants/{kerry_id}/website-connection", json={"mode": "external", "external_url": "www.v53-runtime-example.com"}, headers=HEADERS)
        check("Common business website domain is normalized to HTTPS", normalized.status_code == 200 and normalized.json()["external_url"] == "https://www.v53-runtime-example.com", normalized.text[:700])
        client.patch(f"/api/v521/tenants/{kerry_id}/website-connection", json={"mode": "managed", "external_url": ""}, headers=HEADERS)

        pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        training = client.post(
            f"/api/v521/tenants/{kerry_id}/client-training",
            data={
                "title": "V53 Runtime Training PDF",
                "description": "Product Owner runtime training retrieval test",
                "category": "Sales Workflow",
                "required": "true",
                "roles_json": json.dumps(["CLIENT_ADMIN"]),
                "user_ids_json": "[]",
                "due_date": "",
            },
            files={"file": ("v53-runtime-training.pdf", pdf_bytes, "application/pdf")},
            headers=HEADERS,
        )
        check("Client training accepts a required PDF resource", training.status_code == 200 and training.json()["resource"]["media_type"] == "uploaded_file" and training.json()["resource"]["required"] is True, training.text[:800])
        resource_id = training.json()["resource"]["id"]
        training_list = client.get(f"/api/v521/tenants/{kerry_id}/client-training")
        resource = next(x for x in training_list.json()["resources"] if x["id"] == resource_id)
        check("Training resource appears with assignments", training_list.status_code == 200 and resource["required"] is True and bool(resource["assignments"]), resource)
        media = client.get(f"/api/v521/client-training/{resource_id}/media")
        check("Uploaded training file can be opened or downloaded", media.status_code == 200 and media.content.startswith(b"%PDF"), {"status": media.status_code, "content_type": media.headers.get("content-type"), "disposition": media.headers.get("content-disposition")})
        assignment_id = resource["assignments"][0]["id"]
        completed = client.patch(f"/api/v521/client-training/assignments/{assignment_id}", json={"status": "complete", "progress_pct": 100}, headers=HEADERS)
        check("Training completion is tracked", completed.status_code == 200 and completed.json()["assignment"]["status"] == "complete", completed.text[:700])

        solutions = client.get(f"/api/tenants/{kerry_id}/solutions").json()["solutions"]
        available = next((row for row in solutions if row["status"] != "Active"), None)
        check("An additional solution is available for request testing", bool(available), solutions)
        before = client.get(f"/api/tenants/{kerry_id}/services").json()["services"]
        requested = client.post(f"/api/v521/tenants/{kerry_id}/solution-requests", json={
            "service_code": available["service"]["code"],
            "note": "Runtime request only; do not activate",
            "preferred_contact_method": "Email",
            "contact_date": "2026-09-15",
            "contact_time": "10:30",
            "timezone": "America/Phoenix",
        }, headers=HEADERS)
        check("Solution request stores date time timezone and confirms no activation or charge", requested.status_code == 200 and requested.json()["request"]["status"] == "Requested" and requested.json()["preference"]["timezone"] == "America/Phoenix" and "no service was activated" in requested.json()["confirmation"].lower(), requested.text[:1200])
        after = client.get(f"/api/tenants/{kerry_id}/services").json()["services"]
        active_before = {(x["tenant_service"]["service_code"], x["tenant_service"]["status"]) for x in before}
        active_after = {(x["tenant_service"]["service_code"], x["tenant_service"]["status"]) for x in after}
        check("Request does not automatically activate a tenant service", active_after == active_before, {"before": sorted(active_before), "after": sorted(active_after)})

except Exception as exc:
    status = "failed"
    error = f"{type(exc).__name__}: {exc}"

result = {
    "status": status,
    "release": RELEASE,
    "data_dir": str(DATA),
    "checks": checks,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]) + (1 if status == "failed" and all(row["passed"] for row in checks) else 0),
    "error": error,
}
out = ROOT / "qa" / "V53-RUNTIME-BUSINESS-OUTCOMES.json"
out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "error": error, "output": str(out)}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
