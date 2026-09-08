#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="rmr-v531-runtime-"))
RELEASE = "5.3.1-final-production-corrections-po1"
os.environ.update({
    "RMR_DATA_DIR": str(DATA),
    "RMR_ENVIRONMENT": "pilot",
    "RMR_BASE_URL": "http://testserver",
    "RMR_ALLOW_DEMO_CREDENTIALS": "true",
    "RMR_AUTO_MIGRATE": "true",
    "RMR_AUTO_SEED": "true",
    "RMR_INSTALL_PROFILE": "demo",
    "RMR_APP_VERSION": RELEASE,
    "RMR_SECRET_KEY": "v531-runtime-gate-secret-key-long-enough",
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
        check("Application starts at exact v5.3.1 release", health.status_code == 200 and health.json().get("version") == RELEASE, health.json())

        owner = login(client, "dave@rmr.local", "RMR-Owner-2026!")
        tenants = client.get("/api/tenants").json()["tenants"]
        kerry = next(row for row in tenants if row["slug"] == "kerry-real-estate")
        client.post("/api/auth/logout", headers=HEADERS)
        kerry_user = login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        check("Kerry Client Administrator remains tenant scoped", kerry_user.get("tenant_id") == kerry["id"], kerry_user)

        # Mark Won convenience action.
        created = client.post(
            f"/api/tenants/{kerry['id']}/opportunities",
            json={"account_id": None, "name": "v5.3.1 Runtime Won", "stage": "Proposal", "value_cents": 400000, "probability_pct": 70, "expected_close_date": None, "source": "Runtime Gate", "next_action": "Confirm win"},
            headers=HEADERS,
        )
        check("Open opportunity can be created for quick close", created.status_code == 200, created.text[:500])
        opp = created.json()["opportunity"]
        won = client.post(
            f"/api/v531/opportunities/{opp['id']}/quick-close",
            json={"stage": "Closed Won", "close_date": datetime.now(timezone.utc).date().isoformat(), "final_value_cents": 425000, "note": "Runtime gate won", "loss_reason": ""},
            headers=HEADERS,
        )
        check("Mark Won preserves the existing opportunity and updates summary", won.status_code == 200 and won.json()["opportunity"]["id"] == opp["id"] and won.json()["opportunity"]["stage"] == "Closed Won" and won.json()["opportunity"]["probability_pct"] == 100 and won.json()["summary"]["won_revenue_cents"] >= 425000, won.text[:1000])
        check("Mark Won records an activity event", won.json()["activity"]["activity_type"] == "Opportunity Closed Won", won.json()["activity"])

        # Mark Lost convenience action and required loss reason.
        lost_created = client.post(
            f"/api/tenants/{kerry['id']}/opportunities",
            json={"account_id": None, "name": "v5.3.1 Runtime Lost", "stage": "Qualified", "value_cents": 275000, "probability_pct": 45, "expected_close_date": None, "source": "Runtime Gate", "next_action": "Capture loss"},
            headers=HEADERS,
        ).json()["opportunity"]
        missing_reason = client.post(
            f"/api/v531/opportunities/{lost_created['id']}/quick-close",
            json={"stage": "Closed Lost", "close_date": datetime.now(timezone.utc).date().isoformat(), "final_value_cents": 275000, "note": "", "loss_reason": ""},
            headers=HEADERS,
        )
        check("Mark Lost requires a loss reason", missing_reason.status_code == 422, missing_reason.text[:500])
        lost = client.post(
            f"/api/v531/opportunities/{lost_created['id']}/quick-close",
            json={"stage": "Closed Lost", "close_date": datetime.now(timezone.utc).date().isoformat(), "final_value_cents": 275000, "note": "Runtime gate lost", "loss_reason": "Timing"},
            headers=HEADERS,
        )
        check("Mark Lost preserves the existing opportunity and records the reason", lost.status_code == 200 and lost.json()["opportunity"]["id"] == lost_created["id"] and lost.json()["opportunity"]["stage"] == "Closed Lost" and lost.json()["opportunity"]["loss_reason"] == "Timing" and lost.json()["opportunity"]["probability_pct"] == 0, lost.text[:1000])

        client.post("/api/auth/logout", headers=HEADERS)
        login(client, "dave@rmr.local", "RMR-Owner-2026!")

        # Invitation delivery clarity and onboarding objective validation.
        stamp = uuid.uuid4().hex[:8]
        tenant_resp = client.post(
            "/api/tenants",
            json={
                "name": f"v531 Runtime {stamp}",
                "slug": f"v531-runtime-{stamp}",
                "industry": "Professional Services",
                "country": "United States",
                "timezone": "America/Phoenix",
                "seller_org": "RMR",
                "seller_name": "Dave Laughlin",
                "website_mode": "managed",
                "website_url": "",
                "primary_contact_name": "Runtime Client Admin",
                "primary_contact_email": f"v531-runtime-{stamp}@example.com",
                "invite_primary_admin": True,
                "services": [{"service_code": "platform_core", "contract_price_cents": 12500, "usage_price_cents": 0}],
            },
            headers=HEADERS,
        )
        check("New tenant with Client Administrator invitation can be created", tenant_resp.status_code == 200, tenant_resp.text[:1000])
        tenant_result = tenant_resp.json()
        tenant_id = tenant_result["tenant"]["id"]
        invitation = tenant_result["invitation"]
        check("Local invitation status never claims email delivery", invitation.get("delivery_status") == "Created / local delivery required" and bool(invitation.get("activation_url")), invitation)
        access = client.get(f"/api/tenants/{tenant_id}/access")
        check("Client Access explains local delivery and pending acceptance", access.status_code == 200 and access.json()["delivery_environment"]["mode"] == "local_link" and "No email is claimed as sent" in access.json()["delivery_environment"]["description"] and access.json()["invitations"][0]["delivery_status"] == "Created / local delivery required", access.text[:1200])

        onboarding = client.get(f"/api/tenants/{tenant_id}/onboarding").json()
        step1 = next(row for row in onboarding["steps"] if row["stage_number"] == 1)
        # Remove required primary-contact evidence and prove the stage is blocked.
        patched = client.patch(f"/api/tenants/{tenant_id}", json={"primary_contact_name": "", "primary_contact_email": ""}, headers=HEADERS)
        check("Tenant details can be put into a controlled missing-evidence state for validation", patched.status_code == 200, patched.text[:500])
        blocked = client.post(f"/api/onboarding/steps/{step1['id']}/complete", headers=HEADERS)
        detail = blocked.json().get("detail", {}) if blocked.status_code == 422 else {}
        check("Onboarding blocks completion when required evidence is missing", blocked.status_code == 422 and detail.get("gate") == "stage_requirements" and "Primary contact name" in detail.get("missing", []), blocked.text[:1000])

        # Service activation creates a visible operational follow-up notification.
        client.post("/api/auth/logout", headers=HEADERS)
        login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        solutions = client.get(f"/api/tenants/{kerry['id']}/solutions").json()["solutions"]
        available = next(row for row in solutions if row["status"] == "Available")
        request_response = client.post(
            f"/api/v521/tenants/{kerry['id']}/solution-requests",
            json={
                "service_code": available["service"]["code"],
                "note": "v5.3.1 operational follow-up validation",
                "preferred_contact_method": "Email",
                "contact_date": (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(),
                "contact_time": "10:30",
                "timezone": "America/Phoenix",
            },
            headers=HEADERS,
        )
        check("Client can create a service request without automatic activation", request_response.status_code == 200 and request_response.json()["request"]["status"] == "Requested", request_response.text[:1000])
        request_id = request_response.json()["request"]["id"]
        client.post("/api/auth/logout", headers=HEADERS)
        login(client, "dave@rmr.local", "RMR-Owner-2026!")
        activated = client.patch(
            f"/api/solution-requests/{request_id}",
            json={"status": "Active", "review_note": "Approved by runtime gate", "contract_price_cents": 15000, "usage_price_cents": 0},
            headers=HEADERS,
        )
        check("RMR can activate a reviewed service request with confirmed terms", activated.status_code == 200 and activated.json()["request"]["status"] == "Active", activated.text[:1000])
        notifications = client.get("/api/notifications")
        rows = notifications.json()["notifications"] if notifications.status_code == 200 else []
        follow_up = next((row for row in rows if row.get("notification_type") == "solution_activation_follow_up" and row.get("entity_id") == request_id), None)
        check("Service activation creates an RMR operational follow-up path", bool(follow_up) and follow_up.get("action_route") == f"client-360?tenant={kerry['id']}", follow_up or notifications.text[:1000])
except Exception as exc:
    status = "failed"
    error = f"{type(exc).__name__}: {exc}"

result = {
    "status": status,
    "release": RELEASE,
    "passed": sum(1 for row in checks if row["passed"]),
    "failed": sum(1 for row in checks if not row["passed"]) + (1 if status == "failed" and all(row["passed"] for row in checks) else 0),
    "checks": checks,
    "error": error,
}
out = ROOT / "qa" / "V531-RUNTIME-BUSINESS-OUTCOMES.json"
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "error": error, "output": str(out)}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
