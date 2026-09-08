#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "qa" / "V51RC3-ACCEPTANCE-RESULTS.json"
checks: list[dict[str, object]] = []


def record(name: str, ok: bool, detail: object = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def api(client: httpx.Client, method: str, base: str, path: str, *, body=None, data=None, files=None, expected=200):
    headers = {"X-RMR-Request": "1"} if method.upper() not in {"GET", "HEAD"} else {}
    response = client.request(method, base + path, json=body, data=data, files=files, headers=headers)
    try:
        parsed: object = response.json()
    except Exception:
        parsed = response.text
    record(f"{method} {path}", response.status_code == expected, {"status": response.status_code, "body": parsed})
    return parsed


def login(base: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(timeout=30, follow_redirects=False)
    payload = api(client, "POST", base, "/api/auth/login", body={"email": email, "password": password})
    record(f"login exact credentials {email}", payload["user"]["email"] == email.lower(), payload)
    return client


def token_from_url(value: str) -> str:
    fragment = urlparse(value).fragment
    return fragment.rsplit("/", 1)[-1]


def wait_for_server(base: str, log_path: Path) -> None:
    for _ in range(120):
        try:
            response = httpx.get(base + "/api/health", timeout=1)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server did not start. Log:\n{log_path.read_text(encoding='utf-8', errors='replace')[-6000:]}")


def complete_step(owner: httpx.Client, base: str, step_id: str, expected=200):
    return api(owner, "POST", base, f"/api/onboarding/steps/{step_id}/complete", body={}, expected=expected)


def main() -> int:
    started = time.time()
    work = Path(tempfile.mkdtemp(prefix="rmr-v51-acceptance-"))
    data_dir = work / "data"
    data_dir.mkdir(parents=True)
    setup_token = "v51-setup-token-" + uuid.uuid4().hex
    setup_file = data_dir / "INITIAL-SETUP.txt"
    setup_file.write_text(f"Setup token: {setup_token}\n", encoding="utf-8")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({
        "RMR_DATA_DIR": str(data_dir),
        "RMR_PORT": str(port),
        "RMR_BASE_URL": base,
        "RMR_SETUP_TOKEN": setup_token,
        "RMR_SECRET_KEY": "v51-test-secret-" + uuid.uuid4().hex + uuid.uuid4().hex,
        "RMR_AUTO_SEED": "false",
        "RMR_ALLOW_DEMO_CREDENTIALS": "false",
        "RMR_LOCAL_RECOVERY_MODE": "true",
        "RMR_INSTALL_PROFILE": "empty",
        "RMR_ENVIRONMENT": "pilot",
        "PYTHONUNBUFFERED": "1",
    })
    log_path = work / "server.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "rmr_platform.server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_for_server(base, log_path)
        anon = httpx.Client(timeout=30, follow_redirects=False)
        health = api(anon, "GET", base, "/api/health")
        record("plain-language health headline", bool(health["business_status"]["headline"]), health["business_status"])
        status = api(anon, "GET", base, "/api/setup/status")
        record("empty install requires setup", status["setup_required"] is True, status)

        owner_email = "owner@v51.test"
        owner_password = "Owner-V51-Exact-Password!"
        step2_email = "operator@step2.test"
        step2_password = "Step2-V51-Exact-Password!"
        setup = api(anon, "POST", base, "/api/setup/complete", body={
            "setup_token": setup_token,
            "owner_name": "RMR Product Owner",
            "owner_email": owner_email,
            "owner_password": owner_password,
            "create_step2_admin": True,
            "step2_name": "Step2 Platform Administrator",
            "step2_email": step2_email,
            "step2_password": step2_password,
        })
        record("setup auto-authenticates exact owner", setup["authenticated"] is True and setup["user"]["email"] == owner_email, setup)
        me = api(anon, "GET", base, "/api/auth/me")
        record("setup session cookie usable", me["user"]["global_role"] == "RMR_OWNER", me)
        record("setup token plaintext file removed or neutralized", (not setup_file.exists()) or (setup_token not in setup_file.read_text(encoding="utf-8")), str(setup_file))
        api(anon, "POST", base, "/api/auth/logout", body={})
        owner = login(base, owner_email, owner_password)
        step2 = login(base, step2_email, step2_password)

        catalog = api(owner, "GET", base, "/api/service-catalog")
        codes = {row["code"] for row in catalog["services"]}
        record("governed service catalog seeded", {"platform_core", "crm", "managed_website", "campaigns"}.issubset(codes), sorted(codes))

        # Training resource used to prove activation sync.
        training = api(owner, "POST", base, "/api/training", data={
            "title": "Campaigns & Content Activation Training",
            "description": "Required after activation.",
            "module": "Campaigns & Content",
            "media_type": "external_link",
            "media_url": "https://example.invalid/training",
            "required": "true",
            "roles": "CLIENT_ADMIN",
            "duration_minutes": "8",
        })
        training_id = training["resource"]["id"]

        suffix = uuid.uuid4().hex[:8]
        first_email = f"client-admin-{suffix}@v51.test"
        first = api(owner, "POST", base, "/api/tenants", body={
            "name": f"CAF Acceptance {suffix}",
            "slug": f"caf-acceptance-{suffix}",
            "industry": "Air Filtration",
            "country": "United States",
            "timezone": "America/Phoenix",
            "seller_org": "RMR",
            "seller_name": "RMR Sales",
            "website_mode": "managed",
            "website_url": "",
            "primary_contact_name": "CAF Client Administrator",
            "primary_contact_email": first_email,
            "invite_primary_admin": True,
            "services": [
                {"service_code": "platform_core", "contract_price_cents": 29500},
                {"service_code": "crm", "contract_price_cents": 17500},
                {"service_code": "managed_website", "contract_price_cents": 14500},
            ],
        })
        tenant1 = first["tenant"]["id"]
        record("no opaque tenant credential or temporary password returned", "temporary_client_admin_password" not in first and "key" not in first, first.keys())
        invitation_url = first["invitation"].get("activation_url")
        record("primary admin invitation created", bool(invitation_url), first["invitation"])

        # Structured duplicate-email validation preserves a field-specific error contract.
        duplicate = api(owner, "POST", base, "/api/tenants", body={
            "name": "Duplicate Email Test",
            "slug": f"duplicate-{suffix}",
            "industry": "Consulting",
            "country": "United States",
            "timezone": "America/Phoenix",
            "seller_org": "RMR",
            "seller_name": "RMR Sales",
            "website_mode": "managed",
            "website_url": "",
            "primary_contact_name": "Duplicate",
            "primary_contact_email": first_email,
            "invite_primary_admin": True,
            "services": [],
        }, expected=409)
        record("duplicate email is field-specific", "primary_contact_email" in duplicate["detail"]["field_errors"], duplicate)

        portfolio = api(owner, "GET", base, "/api/portfolio/summary")
        tenants = api(owner, "GET", base, "/api/tenants")
        onboarding = api(owner, "GET", base, "/api/onboarding")
        pricing = api(owner, "GET", base, f"/api/tenants/{tenant1}/services")
        client360 = api(owner, "GET", base, f"/api/tenants/{tenant1}/client360")
        record("new client appears in portfolio", any(row["id"] == tenant1 for row in portfolio["tenants"]), portfolio["tenants"])
        record("new client appears in canonical selector source", any(row["id"] == tenant1 for row in tenants["tenants"]), tenants)
        record("new client appears in onboarding", any(row["tenant"]["id"] == tenant1 for row in onboarding["projects"]), onboarding)
        record("new client pricing persisted", len(pricing["services"]) == 3, pricing)
        record("Client 360 has relationship actions", {"return_route", "onboarding_route", "pricing_route", "crm_route", "website_route", "access_route"}.issubset(client360["actions"]), client360["actions"])
        record("Client 360 website has usable preview", bool(client360["website"]["open_url"]), client360["website"])

        # Step2 sees RMR-created client.
        step2_tenants = api(step2, "GET", base, "/api/tenants")
        record("Step2 shares full client visibility", any(row["id"] == tenant1 for row in step2_tenants["tenants"]), step2_tenants)

        project_data = api(owner, "GET", base, f"/api/tenants/{tenant1}/onboarding")
        steps = project_data["steps"]
        record("eight onboarding stages created", len(steps) == 8, steps)
        record("tenant provisioning stage includes client access", "client access" in steps[1]["name"].lower(), steps[1]["name"])
        progress_expected = [13, 25, 38, 50, 63, 75, 88]
        for index, step in enumerate(steps[:7]):
            updated = complete_step(owner, base, step["id"])
            record(f"onboarding progress immediate after stage {index+1}", updated["project"]["readiness_pct"] == progress_expected[index], updated["project"])
        gate = complete_step(owner, base, steps[7]["id"], expected=409)
        record("go-live blocked before active Client Administrator", gate["detail"]["gate"] == "client_admin_access", gate)

        # Activate client invitation and auto-login as real tenant user.
        token = token_from_url(invitation_url)
        client1 = httpx.Client(timeout=30, follow_redirects=False)
        invite_details = api(client1, "GET", base, f"/api/auth/invitations/{token}")
        record("invitation identifies correct tenant", invite_details["tenant"]["id"] == tenant1, invite_details)
        client_password = "CAF-Client-Password-V51!"
        accepted = api(client1, "POST", base, "/api/auth/invitations/accept", body={"token": token, "password": client_password})
        record("client invitation activation auto-authenticates", accepted["user"]["tenant_id"] == tenant1, accepted)
        client_me = api(client1, "GET", base, "/api/auth/me")
        record("real Client Administrator session", client_me["user"]["tenant_role"] == "CLIENT_ADMIN", client_me)

        final = complete_step(owner, base, steps[7]["id"])
        record("onboarding reaches immediate 100 percent", final["project"]["readiness_pct"] == 100 and final["project"]["status"] == "complete", final["project"])
        record("go-live completion exposes Client 360 destination", final["next_route"] == "client-360", final)
        refreshed = api(owner, "GET", base, f"/api/tenants/{tenant1}/onboarding")
        record("onboarding persisted after refetch", refreshed["project"]["readiness_pct"] == 100 and all(step["status"] == "complete" for step in refreshed["steps"]), refreshed)
        client360 = api(owner, "GET", base, f"/api/tenants/{tenant1}/client360")
        record("Client 360 reflects active client access", client360["access"]["access_state"] == "active" and client360["tenant"]["status"] == "live", client360)

        # Second tenant for isolation.
        second = api(owner, "POST", base, "/api/tenants", body={
            "name": f"Second Tenant {suffix}", "slug": f"second-{suffix}", "industry": "Consulting",
            "country": "United States", "timezone": "America/Phoenix", "seller_org": "Step2",
            "seller_name": "Step2 Sales", "website_mode": "managed", "website_url": "",
            "primary_contact_name": "Second Admin", "primary_contact_email": f"second-{suffix}@v51.test",
            "invite_primary_admin": False, "services": [{"service_code": "platform_core", "contract_price_cents": 29500}],
        })
        tenant2 = second["tenant"]["id"]
        client_tenants = api(client1, "GET", base, "/api/tenants")
        record("client selector contains only own tenant", [row["id"] for row in client_tenants["tenants"]] == [tenant1], client_tenants)
        api(client1, "GET", base, f"/api/tenants/{tenant2}/client360", expected=403)
        api(client1, "GET", base, f"/api/tenants/{tenant2}/accounts", expected=403)

        # Client uses its tenant. RMR remains read-only for client business data.
        api(owner, "POST", base, f"/api/tenants/{tenant1}/accounts", body={"name": "Forbidden Admin Account"}, expected=403)
        account = api(client1, "POST", base, f"/api/tenants/{tenant1}/accounts", body={
            "name": "CAF First Customer", "status": "Active", "annual_value_cents": 1250000,
            "source": "Manual", "risk": "Low", "notes": "Created by Client Administrator acceptance journey."
        })["account"]
        contact = api(client1, "POST", base, f"/api/tenants/{tenant1}/contacts", body={
            "account_id": account["id"], "first_name": "Pat", "last_name": "Customer", "title": "Owner",
            "email": f"customer-{suffix}@example.test", "phone": "555-0101", "primary_contact": True,
        })["contact"]
        opportunity = api(client1, "POST", base, f"/api/tenants/{tenant1}/opportunities", body={
            "account_id": account["id"], "contact_id": contact["id"], "name": "CAF Annual Service",
            "stage": "Qualified", "value_cents": 950000, "probability_pct": 35,
            "source": "Manual", "next_action": "Prepare proposal",
        })["opportunity"]
        api(client1, "POST", base, f"/api/tenants/{tenant1}/activities", body={
            "account_id": account["id"], "opportunity_id": opportunity["id"], "activity_type": "Meeting",
            "subject": "Discovery call", "body": "Client-owned activity."
        })
        version = api(client1, "POST", base, f"/api/tenants/{tenant1}/forecast/versions", body={
            "fiscal_year": 2027, "name": "CAF FY2027 Operating Forecast", "annual_goal_cents": 2000000,
        })["version"]
        forecast = api(client1, "GET", base, f"/api/tenants/{tenant1}/forecast?fiscal_year=2027")
        month = forecast["months"][0]
        api(client1, "PATCH", base, f"/api/forecast/months/{month['id']}", body={"forecast_cents": 125000, "notes": "Client forecast entry"})
        owner_accounts = api(owner, "GET", base, f"/api/tenants/{tenant1}/accounts")
        record("RMR can inspect client operations read-only", owner_accounts["read_only"] is True and any(row["id"] == account["id"] for row in owner_accounts["accounts"]), owner_accounts)
        owner_forecast = api(owner, "GET", base, f"/api/tenants/{tenant1}/forecast?fiscal_year=2027")
        record("RMR forecast support view is read-only", owner_forecast["read_only"] is True, owner_forecast)
        api(owner, "PATCH", base, f"/api/forecast/months/{month['id']}", body={"forecast_cents": 999999}, expected=403)

        # Website can be opened from Client 360 and client can manage it.
        website = api(client1, "GET", base, f"/api/tenants/{tenant1}/website")
        api(client1, "PATCH", base, f"/api/tenants/{tenant1}/website", body={"company_name": f"CAF Acceptance {suffix}", "status": "published"})
        public = anon.get(base + website["preview_url"])
        record("managed website preview opens", public.status_code == 200 and "CAF" in public.text, {"status": public.status_code})

        # Client requests a solution; admin receives a deep-linked request and activation synchronizes entitlements/training.
        solutions = api(client1, "GET", base, f"/api/tenants/{tenant1}/solutions")
        campaigns = next(row for row in solutions["solutions"] if row["service"]["code"] == "campaigns")
        record("Campaigns is available before request", campaigns["status"] == "Available", campaigns)
        api(client1, "POST", base, f"/api/tenants/{tenant1}/solution-interest", body={"service_code": "campaigns", "event_type": "pricing_view"})
        request_row = api(client1, "POST", base, f"/api/tenants/{tenant1}/solution-requests", body={
            "service_code": "campaigns", "note": "CAF would like to discuss daily content support.",
            "preferred_contact_method": "Email", "best_time": "Morning",
        })["request"]
        notifications = api(owner, "GET", base, "/api/notifications")
        matching = next(row for row in notifications["notifications"] if row["entity_id"] == request_row["id"])
        record("solution request notification has deep link", matching["action_route"] == "service-requests", matching)
        queue = api(owner, "GET", base, "/api/solution-requests")
        record("solution request reaches admin queue", any(row["request"]["id"] == request_row["id"] for row in queue["requests"]), queue)
        activated = api(owner, "PATCH", base, f"/api/solution-requests/{request_row['id']}", body={
            "status": "Active", "review_note": "Approved for acceptance testing", "contract_price_cents": 29500,
            "usage_price_cents": 0,
        })
        record("service request activates entitlement", activated["request"]["status"] == "Active", activated)
        services_after = api(client1, "GET", base, f"/api/tenants/{tenant1}/services")
        record("activated solution appears in client service schedule", any(row["tenant_service"]["service_code"] == "campaigns" and row["tenant_service"]["status"] == "active" for row in services_after["services"]), services_after)
        training_after = api(client1, "GET", base, "/api/training")
        assigned = next(row for row in training_after["resources"] if row["id"] == training_id)
        record("required activation training assigned", assigned["progress"] is not None and assigned["progress"]["status"] == "not_started", assigned)

        # Password recovery: one-time token, exact new credential, token cannot be reused.
        api(client1, "POST", base, "/api/auth/logout", body={})
        reset = api(anon, "POST", base, "/api/auth/password-reset/request", body={"email": first_email})
        reset_token = token_from_url(reset["reset_url"])
        new_client_password = "CAF-Reset-Password-V51!"
        reset_done = api(anon, "POST", base, "/api/auth/password-reset/complete", body={"token": reset_token, "new_password": new_client_password})
        record("password reset auto-authenticates", reset_done["user"]["email"] == first_email, reset_done)
        api(anon, "POST", base, "/api/auth/password-reset/complete", body={"token": reset_token, "new_password": "Another-Password-V51!"}, expected=400)
        client1 = login(base, first_email, new_client_password)

        # Partner Economics cost capability: direct, allocated, and policy-pending are distinct.
        service_row = next(row["tenant_service"] for row in services_after["services"] if row["tenant_service"]["service_code"] == "campaigns")
        api(owner, "POST", base, f"/api/tenant-services/{service_row['id']}/generate-transaction", body={"quantity": 1})
        period = time.strftime("%Y-%m")
        api(owner, "POST", base, "/api/partner-economics/costs", body={
            "period": period, "category_code": "client_support", "tenant_id": tenant1, "service_code": "campaigns",
            "amount_cents": 5000, "allocation_scope": "direct_tenant_service", "allocation_basis": "direct",
            "partner_settlement_treatment": "pending_policy", "description": "Acceptance direct support cost",
            "evidence_reference": "TEST-DIRECT-001",
        })
        api(owner, "POST", base, "/api/partner-economics/costs", body={
            "period": period, "category_code": "hosting_infrastructure", "tenant_id": None, "service_code": None,
            "amount_cents": 10000, "allocation_scope": "portfolio", "allocation_basis": "equal_client",
            "partner_settlement_treatment": "pending_policy", "description": "Acceptance allocated hosting cost",
            "evidence_reference": "TEST-SHARED-001",
        })
        api(owner, "POST", base, "/api/partner-economics/costs", body={
            "period": period, "category_code": "general_operating", "tenant_id": None, "service_code": None,
            "amount_cents": 7000, "allocation_scope": "portfolio", "allocation_basis": "pending_policy",
            "partner_settlement_treatment": "management_only", "description": "Acceptance unallocated policy cost",
            "evidence_reference": "TEST-POLICY-001",
        })
        economics = api(owner, "GET", base, "/api/partner-economics")
        record("direct cost captured separately", economics["summary"]["additional_direct_costs_cents"] >= 5000, economics["summary"])
        record("shared operating cost allocated", economics["summary"]["allocated_shared_operating_costs_cents"] == 10000, economics["summary"])
        record("policy-pending cost not silently settled", economics["summary"]["unallocated_policy_pending_cents"] == 7000, economics["summary"])

        # Support view audit and deep-link notifications.
        api(owner, "POST", base, f"/api/tenants/{tenant1}/support-access", body={"area": "CRM", "purpose": "Acceptance read-only support verification"})
        support = api(owner, "GET", base, "/api/support-access")
        record("read-only support access audited", any(row["access"]["tenant_id"] == tenant1 for row in support["events"]), support)

        # Server state persisted and exact journey completed.
        final_portfolio = api(owner, "GET", base, "/api/portfolio/summary")
        final_tenant = next(row for row in final_portfolio["tenants"] if row["id"] == tenant1)
        record("full RMR-to-client journey ends live", final_tenant["status"] == "live" and final_tenant["access_state"] == "active", final_tenant)

        result = {
            "status": "passed",
            "release": "5.3.1-final-production-corrections-po1",
            "passed": sum(1 for item in checks if item["ok"]),
            "failed": sum(1 for item in checks if not item["ok"]),
            "duration_seconds": round(time.time() - started, 2),
            "checks": checks,
            "server_log_tail": log_path.read_text(encoding="utf-8", errors="replace")[-4000:],
        }
        REPORT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(json.dumps({key: result[key] for key in ["status", "release", "passed", "failed", "duration_seconds"]}, indent=2))
        return 0
    except Exception as exc:
        result = {
            "status": "failed",
            "release": "5.3.1-final-production-corrections-po1",
            "error": str(exc),
            "passed": sum(1 for item in checks if item["ok"]),
            "failed": sum(1 for item in checks if not item["ok"]),
            "checks": checks,
            "server_log_tail": log_path.read_text(encoding="utf-8", errors="replace")[-8000:] if log_path.exists() else "",
        }
        REPORT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(json.dumps({key: result[key] for key in ["status", "error", "passed", "failed"]}, indent=2))
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
    raise SystemExit(main())
