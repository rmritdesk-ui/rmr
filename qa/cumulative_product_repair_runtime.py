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

DATA = Path(tempfile.mkdtemp(prefix="rmr-v522-runtime-"))
os.environ.update({
    "RMR_DATA_DIR": str(DATA),
    "RMR_ENVIRONMENT": "pilot",
    "RMR_BASE_URL": "http://testserver",
    "RMR_ALLOW_DEMO_CREDENTIALS": "true",
    "RMR_AUTO_MIGRATE": "true",
    "RMR_AUTO_SEED": "true",
    "RMR_INSTALL_PROFILE": "demo",
    "RMR_APP_VERSION": "5.3.1-final-production-corrections-po1",
    "RMR_SECRET_KEY": "v522-runtime-gate-secret-key-long-enough",
    "RMR_CREDENTIAL_ENCRYPTION_KEY": "0123456789abcdef0123456789abcdef",
    "RMR_INTEGRATION_ENCRYPTION_KEY": "abcdef0123456789abcdef0123456789",
    "RMR_AI_PROVIDER": "demonstration",
    "RMR_ONE_TO_ONE_EMAIL_PROVIDER": "mock",
    "RMR_SYSTEM_EMAIL_PROVIDER": "local",
    "RMR_PIQ_DISCOVERY_PROVIDER": "demonstration",
    "RMR_PIQ_RESEARCH_PROVIDER": "demonstration",
    "RMR_LOCAL_RECOVERY_MODE": "true",
})

from fastapi.testclient import TestClient  # noqa: E402
from rmr_platform.main import app  # noqa: E402

checks: list[dict[str, object]] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password}, headers={"X-RMR-Request": "1"})
    check(f"Login works for {email}", response.status_code == 200, response.text[:500])

status = "passed"
error = ""
try:
    with TestClient(app) as client:
        health = client.get("/api/health")
        check("Application starts at the exact cumulative repair release", health.status_code == 200 and health.json().get("version") == "5.3.1-final-production-corrections-po1", health.json())
        check("Latest additive migration is current", health.json().get("checks", {}).get("migrations", {}).get("current") == "005.005.000-cumulative-product-repair", health.json().get("checks", {}).get("migrations"))

        login(client, "dave@rmr.local", "RMR-Owner-2026!")
        tenants = client.get("/api/tenants").json()["tenants"]
        kerry = next(row for row in tenants if row["slug"] == "kerry-real-estate")
        terms = client.get(f"/api/v522/admin/tenants/{kerry['id']}/commercial-terms")
        check("RMR Admin commercial schedule loads", terms.status_code == 200 and bool(terms.json().get("items")), terms.text[:1000])
        item = next((row for row in terms.json()["items"] if row["tenant_service"]["status"] == "active"), terms.json()["items"][0])
        subscription = item["tenant_service"]
        payload = {
            "contract_price_cents": 98765,
            "usage_price_cents": 0,
            "cadence": "monthly",
            "status": "active",
            "quantity": 1.0,
            "effective_date": subscription.get("effective_date") or "2026-01-01",
            "rmr_share_pct": 64.0,
            "step2_share_pct": 36.0,
            "split_basis": "gross",
            "direct_cost_cents": 4321,
            "seller_org": "RMR",
            "seller_name": "Runtime Gate",
            "notes": "Runtime business-outcome validation",
        }
        changed = client.patch(f"/api/v522/admin/tenants/{kerry['id']}/commercial-terms/{subscription['id']}", json=payload, headers={"X-RMR-Request": "1"})
        check("Per-client price and per-service revenue share save", changed.status_code == 200 and changed.json()["calculation"]["reconciles"] is True, changed.text[:1200])
        reloaded = client.get(f"/api/v522/admin/tenants/{kerry['id']}/commercial-terms").json()
        saved = next(row for row in reloaded["items"] if row["tenant_service"]["id"] == subscription["id"])
        check("Commercial terms persist after reload", saved["tenant_service"]["contract_price_cents"] == 98765 and saved["commercial_term"]["rmr_share_pct"] == 64.0 and saved["commercial_term"]["step2_share_pct"] == 36.0, saved)
        economics = client.get("/api/v522/admin/partner-economics").json()
        econ = next(row for row in economics["items"] if row["tenant_service"]["id"] == subscription["id"])
        check("Partner Economics derives from and reconciles configured terms", econ["terms_source"] == "explicit_client_terms" and econ["calculation"]["reconciles"] is True and economics["summary"]["split_reconciliation_difference_cents"] == 0, {"item": econ, "summary": economics["summary"]})
        trace = client.get(f"/api/v522/admin/partner-economics/terms/{subscription['id']}").json()
        check("Partner Economics trace exposes history", bool(trace.get("history")) and trace["item"]["tenant"]["id"] == kerry["id"], trace)

        client.post("/api/auth/logout", headers={"X-RMR-Request": "1"})
        login(client, "admin@kerry-real-estate.demo", "Client-Admin-2026!")
        social = client.post(f"/api/v521/tenants/{kerry['id']}/social/generate", json={
            "objective": "Help Arizona homeowners prepare for a move to Northern Colorado",
            "audience": "Arizona homeowners planning a relocation",
            "tone": "warm, credible, locally knowledgeable",
            "call_to_action": "Schedule a relocation planning conversation",
            "keywords": ["Arizona", "Northern Colorado", "relocation"],
            "suggested_visual": "A family arriving at a Northern Colorado home",
        }, headers={"X-RMR-Request": "1"})
        check("Social generator creates four differentiated finished posts", social.status_code == 200 and len(social.json().get("items", [])) == 4 and len({row["post_text"] for row in social.json()["items"]}) >= 3, social.text[:1400])
        social_id = social.json()["items"][0]["id"]
        detail = client.get(f"/api/v522/tenants/{kerry['id']}/social/{social_id}")
        check("Generated social record is openable", detail.status_code == 200 and detail.json()["item"]["id"] == social_id, detail.text[:1000])
        update = client.patch(f"/api/v522/tenants/{kerry['id']}/social/{social_id}", json={"title": "Approved relocation post", "post_text": detail.json()["item"]["post_text"] + "\nApproved edit.", "hashtags": detail.json()["item"]["hashtags"], "status": "APPROVED"}, headers={"X-RMR-Request": "1"})
        check("Social content can be edited and approved", update.status_code == 200 and update.json()["item"]["status"] == "APPROVED", update.text[:800])
        regenerate = client.post(f"/api/v522/tenants/{kerry['id']}/social/{social_id}/regenerate", json={"tone": "direct and helpful"}, headers={"X-RMR-Request": "1"})
        check("Social content can be regenerated with revision history", regenerate.status_code == 200 and bool(regenerate.json()["item"]["post_text"]), regenerate.text[:1000])
        history = client.get(f"/api/v522/tenants/{kerry['id']}/social/{social_id}").json()["revisions"]
        check("Social revision history is preserved", len(history) >= 2, history)

        workspace = client.get(f"/api/v521/tenants/{kerry['id']}/email-workspace").json()
        connection = next((row for row in workspace["connections"] if row["provider"].upper() == "MOCK"), workspace["connections"][0])
        opps = client.get(f"/api/tenants/{kerry['id']}/opportunities").json()["opportunities"]
        message = client.post(f"/api/v521/tenants/{kerry['id']}/one-to-one-email", json={
            "connection_id": connection["id"],
            "recipient_email": "runtime-gate@example.com",
            "recipient_name": "Runtime Gate Prospect",
            "subject": "Runtime Gate one-to-one follow-up",
            "body": "This is a recorded one-to-one CRM communication.",
            "opportunity_id": opps[0]["id"] if opps else None,
        }, headers={"X-RMR-Request": "1"})
        check("One-to-one email is recorded through the client mailbox", message.status_code == 200 and message.json()["message"]["status"].startswith("RECORDED"), message.text[:1000])
        message_id = message.json()["message"]["id"]
        message_detail = client.get(f"/api/v522/tenants/{kerry['id']}/messages/{message_id}")
        detail_json = message_detail.json()
        check("Sent-message detail exposes exact body sender recipient actor status time and CRM context", message_detail.status_code == 200 and bool(detail_json["message"]["body"]) and bool(detail_json["delivery"]["sender_email"]) and bool(detail_json["message"]["recipient_email"]) and bool(detail_json["actor"]["id"]) and bool(detail_json["message"]["sent_at"]) and bool(detail_json["relationship"]["id"]), detail_json)

        environment = client.get(f"/api/v521/tenants/{kerry['id']}/environment").json()
        check("RMR Global explicitly excludes bulk email delivery", environment["bulk_email_delivery"] is False and set(environment["campaign_export_formats"]) >= {"mailchimp", "constant_contact", "hubspot", "brevo", "generic"}, environment)
except Exception as exc:
    status = "failed"
    error = f"{type(exc).__name__}: {exc}"

result = {"status": status, "release": "5.3.1-final-production-corrections-po1", "checks": checks, "passed": sum(1 for r in checks if r["passed"]), "failed": sum(1 for r in checks if not r["passed"]) + (1 if status == "failed" and all(r["passed"] for r in checks) else 0), "error": error}
out = ROOT / "qa" / "V522-CUMULATIVE-PRODUCT-REPAIR-RUNTIME.json"
out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "passed": result["passed"], "failed": result["failed"], "error": error, "output": str(out)}, indent=2))
raise SystemExit(0 if status == "passed" else 1)
