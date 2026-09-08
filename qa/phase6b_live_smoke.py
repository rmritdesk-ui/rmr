"""One-shot, explicitly authorized Phase 6B harness. Never reuse a database.

No provider mocks or production changes. All business actions use the running
application HTTP API; the real lifespan worker performs provider requests.
Run only in the isolated container with /data bound to a new smoke directory.
"""
import json
import logging
import os
from decimal import Decimal
from pathlib import Path
import secrets
import threading
import time

import httpx
import uvicorn

REPORT = {"stage": "preflight", "google_http": 0, "google_search_http": 0,
          "google_details_http": 0, "openai_http": 0, "source_http": 0,
          "discovery_submissions": 0, "research_confirmations": 0,
          "move_requests": 0, "verdict": "E. CONFIGURATION BLOCKED"}
logging.disable(logging.CRITICAL)


class StopSmoke(Exception):
    pass


def require(condition, code):
    if not condition:
        REPORT["blocker"] = code
        raise StopSmoke()


def emit(event, **data):
    # Only allowlisted summaries, never environment, headers, or exceptions.
    print(json.dumps({"event": event, **data}, default=str), flush=True)


original_send = httpx.Client.send


def observed_send(client, request, **kwargs):
    # Observation only: forward the identical request to the original transport.
    # Do not retain provider headers, query strings, or response bodies.
    host, path = request.url.host, request.url.path
    if host == "maps.googleapis.com":
        REPORT["google_http"] += 1
        key = "google_search_http" if path.endswith("textsearch/json") else "google_details_http"
        REPORT[key] += 1
    elif host == "api.openai.com":
        REPORT["openai_http"] += 1
    elif host not in ("127.0.0.1", "localhost"):
        REPORT["source_http"] += 1
    response = original_send(client, request, **kwargs)
    if host in ("maps.googleapis.com", "api.openai.com"):
        REPORT.setdefault("provider_http_statuses", []).append({"provider": "google" if host == "maps.googleapis.com" else "openai", "status": response.status_code})
    return response


def request(client, method, path, *, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.status_code != expected:
        REPORT["api_failure"] = {"path": path, "status": response.status_code}
        # Local API errors are not blindly echoed; record known safe codes only.
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                REPORT["api_failure"]["code"] = detail["code"]
            elif detail == "No researchable criteria":
                REPORT["api_failure"]["code"] = "no_researchable_criteria"
        except (ValueError, AttributeError):
            pass
        require(False, "application_api_rejected_request")
    return response.json()


def poll(client, path, kind, timeout):
    deadline = time.monotonic() + timeout
    statuses = REPORT.setdefault(kind + "_observed_states", ["queued"])
    while time.monotonic() < deadline:
        result = request(client, "GET", path)
        status = result["status"]
        if statuses[-1] != status:
            statuses.append(status)
            emit(kind + "_status", status=status)
        if status not in ("queued", "running", "retry_wait"):
            return result
        time.sleep(0.5)
    require(False, kind + "_observation_timeout")


def main():
    server = None
    server_thread = None
    initialized = False
    try:
        require(os.environ.get("RMR_DATA_DIR") == "/data", "data_directory_mismatch")
        require(os.environ.get("RMR_DATABASE_URL") == "sqlite:////data/phase6b.db", "database_url_mismatch")
        require(not Path("/data/phase6b.db").exists(), "database_already_exists")
        from rmr_platform.config import settings as cfg
        require(bool(cfg.google_places_api_key) and bool(cfg.ai_api_key), "missing_credentials")
        require(cfg.piq_worker_enabled and cfg.piq_job_max_attempts == 1, "worker_limits")
        require(cfg.piq_live_discovery_enabled and cfg.piq_discovery_provider == "google_places", "discovery_provider")
        require(cfg.piq_max_queries_per_run == 1 and cfg.piq_max_results_per_run == 3
                and cfg.piq_discovery_timeout_seconds <= 30, "discovery_limits")
        require(cfg.piq_live_research_enabled and cfg.piq_research_provider == "openai"
                and cfg.piq_research_web_search_enabled, "research_provider")
        require(cfg.piq_research_model == "gpt-4.1-mini-2025-04-14"
                and cfg.ai_base_url == "https://api.openai.com/v1", "research_model_or_endpoint")
        require(0 < cfg.piq_research_max_cost_usd <= Decimal("0.05") and cfg.piq_research_timeout_seconds <= 60, "research_limits")
        require(not cfg.auto_seed and not cfg.auto_migrate and not cfg.allow_demo_credentials
                and cfg.install_profile == "empty" and cfg.payment_provider == "mock", "isolation_settings")
        REPORT["effective_settings_verified"] = True
        from sqlalchemy import select, func, inspect, text
        from rmr_platform.db import SessionLocal, engine
        from rmr_platform.migrations import migrate
        from rmr_platform.seed import seed_reference_data
        from rmr_platform.models import Tenant, User, ServiceCatalog, TenantService, PiqOpportunity, Lead, AuditEvent, EconomicTransaction
        from rmr_platform.unified_models import PiqTargetProfile, PiqEvidence
        from rmr_platform.piq_models import PiqDiscoveryRun, PiqResearchRun, PiqProfileMatch
        from rmr_platform.security import hash_password
        from rmr_platform.piq_engine.profile import snapshot_target_profile, plan_profile_queries
        REPORT["stage"] = "initialize_isolated_database"
        migrate()
        initialized = True
        password = secrets.token_urlsafe(36)
        with SessionLocal() as db:
            require(db.scalar(select(func.count()).select_from(Tenant)) == 0, "database_not_empty")
            seed_reference_data(db)
            tenant = Tenant(name="Phase 6B Isolated Smoke", slug="phase6b-isolated-smoke", status="active")
            db.add(tenant); db.flush()
            user = User(email="phase6b-admin@example.test", full_name="Phase 6B Smoke Admin",
                        tenant_id=tenant.id, tenant_role="CLIENT_ADMIN", password_hash=hash_password(password),
                        active=True, must_change_password=False)
            db.add(user); db.flush()
            # Existing PIQ list/Move API requires both service entitlements.
            # This creates entitlements only, not paid Enhance actions/charges.
            for code in ("piq_access", "piq_enhancement"):
                if not db.scalar(select(ServiceCatalog).where(ServiceCatalog.code == code)):
                    db.add(ServiceCatalog(code=code, name=code)); db.flush()
                db.add(TenantService(tenant_id=tenant.id, service_code=code, status="active"))
            db.commit()
            tenant_id, user_id, email = tenant.id, user.id, user.email
        from rmr_platform.main import app
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000,
                                              log_config=None, access_log=False, log_level="critical"))
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 30
        while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        require(server.started, "server_start_failed")
        from rmr_platform import piq_worker
        require(piq_worker.is_running(), "worker_not_running")
        REPORT.update(tenant_id=tenant_id, user_id=user_id, runtime_started=True)
        httpx.Client.send = observed_send
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False,
                          headers={"X-RMR-Request": "1"}) as client:
            REPORT["stage"] = "local_login_and_profile"
            auth = request(client, "POST", "/api/auth/login", json={"email": email, "password": password})
            del password
            require(auth["user"]["tenant_id"] == tenant_id and auth["user"]["tenant_role"] == "CLIENT_ADMIN", "actor_mismatch")
            profile_payload = {"name": "Phase 6B Mortgage Phoenix", "industries": ["Mortgage Broker"],
                               "locations": ["Phoenix, Arizona"], "keywords": [], "exclusions": []}
            profile_result = request(client, "PUT", f"/api/tenants/{tenant_id}/piq/target-profile", json=profile_payload)
            with SessionLocal() as db:
                profile = db.get(PiqTargetProfile, profile_result["profile"]["id"])
                snapshot = snapshot_target_profile(profile)
                plan = plan_profile_queries(snapshot, max_queries=cfg.piq_max_queries_per_run)
                require(len(plan.queries) == 1 and profile.active, "profile_query_limit")
                REPORT["profile"] = snapshot
                REPORT["planned_query"] = plan.queries[0].text
            emit("google_preflight", query=REPORT["planned_query"], maximum_results=3, maximum_attempts=1,
                 provider="google_places", demo_fallback=False)
            REPORT["stage"] = "google_discovery"
            REPORT["verdict"] = "B. GOOGLE PROVIDER BLOCKED"
            REPORT["discovery_submissions"] += 1
            queued = request(client, "POST", f"/api/tenants/{tenant_id}/piq/discover", expected=202,
                             json={"count": 3}, headers={"Idempotency-Key": "phase6b-single-discovery"})
            REPORT["discovery_run_id"] = queued["run_id"]
            result = poll(client, f"/api/tenants/{tenant_id}/piq/discovery-runs/{queued['run_id']}", "discovery", 90)
            REPORT["discovery"] = result
            require(result["attempt_count"] <= 1, "discovery_attempt_limit_exceeded")
            require(result["status"] in ("completed", "partial"), "google_discovery_failed")
            require(not result.get("error_code"), "google_discovery_partial_provider_failure")
            REPORT["legacy_compatible"] = True
            rows = request(client, "GET", f"/api/tenants/{tenant_id}/piq")["opportunities"]
            fields = ("id", "company_name", "provider", "source_external_id", "location", "website", "phone",
                      "base_match_score", "confidence_score", "evidence_completeness_pct", "score", "estimated_value_cents")
            REPORT["candidates"] = [{k: row.get(k) for k in fields} for row in rows]
            require(len(rows) <= 3 and all(x["provider"] == "google_places" and x["estimated_value_cents"] == 0 for x in rows), "discovery_data_integrity")
            require(bool(rows), "zero_qualified_candidates")
            REPORT["verdict"] = "C. ADAPTIVE RESEARCH BLOCKED"
            eligible = [r for r in rows if (r.get("website") or "").startswith("https://") and "phoenix" in (r.get("location") or "").lower()]
            require(bool(eligible), "no_unambiguous_https_phoenix_candidate")
            selected = eligible[0]
            oid = selected["id"]
            REPORT["selected"] = {k: selected.get(k) for k in fields}
            profile_ui = request(client, "GET", f"/api/piq/{oid}/profile")
            REPORT["piq_profile_api_verified"] = profile_ui["opportunity"]["id"] == oid
            base_before = selected["base_match_score"]
            REPORT["stage"] = "adaptive_research_estimate"
            estimate = request(client, "POST", f"/api/piq/{oid}/adaptive-research/estimate", json={})
            REPORT["estimate"] = {k: v for k, v in estimate.items() if k != "confirmation_token"}
            require(estimate["provider"] == "openai" and estimate["model"] == cfg.piq_research_model
                    and estimate["estimated_cost_microusd"] <= 50000 and estimate["maximum_cost_microusd"] <= 50000
                    and estimate["can_confirm"], "research_estimate_guard")
            with SessionLocal() as db:
                rr = db.get(PiqResearchRun, estimate["run_id"])
                require(rr.tenant_id == tenant_id and rr.requested_by == user_id and rr.opportunity_id == oid, "research_estimate_identity")
            REPORT["stage"] = "adaptive_research"
            REPORT["research_confirmations"] += 1
            request(client, "POST", f"/api/piq/{oid}/adaptive-research", expected=202,
                    json={"run_id": estimate["run_id"], "confirmation_token": estimate["confirmation_token"]})
            estimate.pop("confirmation_token", None)
            research_result = poll(client, f"/api/piq/{oid}/adaptive-research/{estimate['run_id']}", "research", 120)
            REPORT["research"] = research_result
            with SessionLocal() as db:
                rr = db.get(PiqResearchRun, estimate["run_id"])
                REPORT["research_usage"] = rr.usage_json
                receipt = (rr.diagnostics_json or {}).get("receipt", {})
                REPORT["accepted_evidence_count"] = len(receipt.get("claims", []))
                REPORT["rejected_evidence"] = receipt.get("rejected", [])
                row = db.get(PiqOpportunity, oid)
                delta = row.adaptive_score_delta or 0
                REPORT["scores"] = {"base_before": base_before, "base_after": row.base_match_score, "delta": delta, "final": row.score}
                REPORT["score_valid"] = row.base_match_score == base_before and -8 <= delta <= 10 and row.score == max(0, min(100, base_before + delta))
                require((rr.usage_json or {}).get("exposure_microusd", 0) <= 50000, "research_cost_exceeded")
                REPORT["research_evidence"] = [{k: getattr(e, k) for k in ("fact", "source_url", "source_domain", "evidence_state", "verified", "is_synthesized", "profile_criterion", "raw_json")}
                    for e in db.scalars(select(PiqEvidence).where(PiqEvidence.research_run_id == rr.id))]
            require(research_result["status"] in ("completed", "no_evidence", "partial") and not research_result.get("error_code"), "openai_research_failed")
            require(REPORT["score_valid"], "score_integrity")
            REPORT["stage"] = "move_to_crm"
            REPORT["verdict"] = "D. IMPLEMENTATION DEFECT FOUND"
            first = request(client, "POST", f"/api/piq/{oid}/move-to-crm")
            REPORT["move_requests"] += 1
            second = request(client, "POST", f"/api/piq/{oid}/move-to-crm")
            REPORT["move_requests"] += 1
            with SessionLocal() as db:
                leads = list(db.scalars(select(Lead).where(Lead.tenant_id == tenant_id)))
                audits = list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "piq.moved_to_crm")))
                REPORT["crm"] = {"lead_count": len(leads), "audit_count": len(audits), "source": leads[0].source if leads else None, "repeat_created": second.get("created")}
                require(len(leads) == len(audits) == 1 and leads[0].source == "ProspectIQ" and second.get("created") is False, "crm_integrity")
            REPORT["verdict"] = "A. LIVE PIQ CYCLE VALIDATED"
            REPORT["stage"] = "complete"
    except StopSmoke:
        pass
    except Exception as exc:
        REPORT["unexpected_exception_type"] = type(exc).__name__
        REPORT["blocker"] = "harness_or_runtime_exception_inspect_before_any_further_action"
    finally:
        if server:
            server.should_exit = True
        if server_thread:
            server_thread.join(timeout=20)
        REPORT["runtime_stopped"] = server_thread is None or not server_thread.is_alive()
        if initialized:
            try:
                with SessionLocal() as db:
                    REPORT["stored_discovery_runs"] = db.scalar(select(func.count()).select_from(PiqDiscoveryRun))
                    REPORT["stored_research_runs"] = db.scalar(select(func.count()).select_from(PiqResearchRun))
                    REPORT["economic_transactions"] = db.scalar(select(func.count()).select_from(EconomicTransaction))
                    REPORT["invoice_table_counts"] = {name: db.execute(text('SELECT COUNT(*) FROM "' + name + '"')).scalar()
                        for name in inspect(engine).get_table_names() if "invoice" in name.lower()}
            except Exception as exc:
                REPORT["accounting_inspection_error_type"] = type(exc).__name__
        emit("phase6b_final", **REPORT)


if __name__ == "__main__":
    main()
