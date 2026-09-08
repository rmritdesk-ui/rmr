from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import json
import logging
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from rmr_platform.migrations import apply_piq_phase0_schema
from rmr_platform.models import PiqOpportunity, ServiceCatalog, Tenant, TenantService, User
from rmr_platform.piq_engine.contracts import (
    DiscoveryExecutionResult,
    NormalizedCandidate,
    PiqProviderError,
    ProviderSearchResult,
)
from rmr_platform.piq_engine.discovery import execute_google_discovery, persist_candidates
from rmr_platform.piq_engine.google_places import (
    DETAIL_FIELDS,
    GooglePlacesAdapter,
    normalize_place,
)
from rmr_platform.piq_engine.profile import plan_profile_queries
from rmr_platform.piq_models import PiqDiscoveryRun
from rmr_platform import piq_worker
from rmr_platform.routes import unified as unified_routes
from rmr_platform.unified_models import ManagedTenantSession, PiqTargetProfile


@pytest.fixture(autouse=True)
def no_real_provider_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Automated Phase 1 tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture()
def db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase1.db'}", future=True)
    apply_piq_phase0_schema(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session
    engine.dispose()


def profile_snapshot(**overrides):
    snapshot = {
        "id": "profile-1",
        "name": "Target",
        "industries": ["Mortgage Broker"],
        "locations": ["Phoenix, Arizona"],
        "employee_min": 25,
        "employee_max": 250,
        "revenue_min_cents": 5_000_000,
        "keywords": [],
        "exclusions": ["Competitor"],
        "active": True,
    }
    snapshot.update(overrides)
    return snapshot


def candidate(
    external_id: str,
    *,
    name: str = "Example Company",
    website: str | None = "https://www.example.com/about",
    address: str | None = "100 Main St, Phoenix, AZ",
) -> NormalizedCandidate:
    return NormalizedCandidate(
        external_provider="google_places",
        external_id=external_id,
        company_name=name,
        formatted_address=address,
        city="Phoenix",
        state="Arizona",
        country="United States",
        latitude=33.4,
        longitude=-112.1,
        categories=("mortgage_broker", "finance"),
        business_status="OPERATIONAL",
        phone=None,
        website=website,
        rating=4.7,
        review_count=32,
        source_url="https://maps.google.test/place",
        source_metadata={"api": "places_web_service_legacy"},
        raw_metadata={"place_id": external_id},
        retrieved_at=datetime.now(timezone.utc),
    )


def seed_tenant(db: Session, suffix: str, *, role: str = "CLIENT_ADMIN", entitled: bool = True):
    tenant = Tenant(name=f"Tenant {suffix}", slug=f"phase1-{suffix}")
    db.add(tenant)
    db.flush()
    user = User(
        email=f"{suffix}@example.test",
        password_hash="test-only",
        full_name=f"User {suffix}",
        tenant_id=tenant.id,
        tenant_role=role,
    )
    db.add(user)
    db.flush()
    profile = PiqTargetProfile(
        tenant_id=tenant.id,
        created_by=user.id,
        industries_json=["Mortgage Broker"],
        locations_json=["Phoenix, Arizona"],
        keywords_json=["local"],
        active=True,
    )
    db.add(profile)
    if entitled:
        if not db.get(ServiceCatalog, "piq-access-catalog"):
            db.add(ServiceCatalog(id="piq-access-catalog", code="piq_access", name="ProspectIQ"))
        db.add(TenantService(tenant_id=tenant.id, service_code="piq_access", status="active"))
    db.commit()
    return tenant, user, profile


def discovery_run(db: Session, tenant: Tenant, user: User, profile: PiqTargetProfile, suffix: str):
    run = PiqDiscoveryRun(
        tenant_id=tenant.id,
        target_profile_id=profile.id,
        requested_by=user.id,
        provider="google_places",
        status="queued",
        idempotency_key=f"run-{suffix}",
        requested_count=10,
        profile_snapshot_json=profile_snapshot(id=profile.id),
    )
    db.add(run)
    db.commit()
    return run


def request(method: str, *, idempotency_key: str = "") -> Request:
    headers = [(b"x-rmr-request", b"1")]
    if idempotency_key:
        headers.append((b"idempotency-key", idempotency_key.encode()))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/phase1-test",
        "raw_path": b"/phase1-test",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    })


def live_settings(**overrides):
    values = {
        "piq_live_discovery_enabled": True,
        "piq_discovery_provider": "google_places",
        "google_places_api_key": "test-key",
        "piq_max_queries_per_run": 8,
        "piq_max_results_per_run": 25,
        "piq_discovery_timeout_seconds": 30,
        "piq_job_max_attempts": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_query_plan_one_industry_and_location():
    plan = plan_profile_queries(profile_snapshot(), max_queries=8)
    assert [item.text for item in plan.queries] == ["Mortgage Broker in Phoenix, Arizona"]


def test_query_plan_multiple_industries_locations_is_deterministic_and_capped():
    snapshot = profile_snapshot(
        industries=["Mortgage Broker", "Title Company", "Home Builder"],
        locations=["Phoenix", "Mesa"],
    )
    plan = plan_profile_queries(snapshot, max_queries=4)
    assert [item.text for item in plan.queries] == [
        "Mortgage Broker in Phoenix",
        "Mortgage Broker in Mesa",
        "Title Company in Phoenix",
        "Title Company in Mesa",
    ]


def test_query_keywords_are_bounded_and_employee_revenue_are_not_filters():
    snapshot = profile_snapshot(keywords=["family owned", "local", "ignored"], employee_min=999, revenue_min_cents=999999)
    plan = plan_profile_queries(snapshot, max_queries=2)
    assert plan.queries[0].text == "Mortgage Broker family owned local in Phoenix, Arizona"
    assert "999" not in plan.queries[0].text
    assert plan.ignored_provider_filters == ("employee_min", "employee_max", "revenue_min_cents")
    assert plan.exclusions == ("Competitor",)


@pytest.mark.parametrize("snapshot", [
    profile_snapshot(active=False),
    profile_snapshot(industries=[]),
    profile_snapshot(locations=[]),
])
def test_query_plan_rejects_inactive_or_incomplete_profile(snapshot):
    with pytest.raises(PiqProviderError) as caught:
        plan_profile_queries(snapshot, max_queries=8)
    assert caught.value.code == "invalid_profile"
    assert caught.value.retryable is False


def test_google_success_details_and_normalization():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if "textsearch" in req.url.path:
            return httpx.Response(200, json={"status": "OK", "results": [{"place_id": "p1", "name": "Fallback"}]})
        return httpx.Response(200, json={"status": "OK", "result": {
            "place_id": "p1",
            "name": "Real Company",
            "formatted_address": "100 Main St, Phoenix, AZ, USA",
            "address_components": [
                {"long_name": "Phoenix", "types": ["locality"]},
                {"long_name": "Arizona", "types": ["administrative_area_level_1"]},
                {"long_name": "United States", "types": ["country"]},
            ],
            "formatted_phone_number": "(602) 555-0100",
            "website": "https://real.example",
            "types": ["mortgage_broker", "finance"],
            "rating": 4.8,
            "user_ratings_total": 91,
            "business_status": "OPERATIONAL",
            "url": "https://maps.google.test/p1",
            "geometry": {"location": {"lat": 33.45, "lng": -112.07}},
        }})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = GooglePlacesAdapter(api_key="test-key", timeout_seconds=10, client=client, page_delay_seconds=0).search(
        "Mortgage Broker in Phoenix", max_results=5
    )
    item = result.candidates[0]
    assert item.external_id == "p1"
    assert item.company_name == "Real Company"
    assert (item.city, item.state, item.country) == ("Phoenix", "Arizona", "United States")
    assert (item.latitude, item.longitude) == (33.45, -112.07)
    assert item.categories == ("mortgage_broker", "finance")
    assert item.phone == "(602) 555-0100"
    assert item.website == "https://real.example"
    assert item.rating == 4.8 and item.review_count == 91
    assert "email" not in {field.name for field in fields(item)}
    assert seen[0].url.params["query"] == "Mortgage Broker in Phoenix"
    assert seen[1].url.params["fields"] == DETAIL_FIELDS


def test_google_zero_results_and_result_cap():
    calls = 0

    def handler(req: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

    adapter = GooglePlacesAdapter(
        api_key="test-key",
        timeout_seconds=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        page_delay_seconds=0,
    )
    result = adapter.search("Nothing in Nowhere", max_results=2)
    assert result.candidates == []
    assert result.page_count == 1
    assert calls == 1


def test_google_pagination_and_global_result_cap():
    text_calls = 0

    def handler(req: httpx.Request):
        nonlocal text_calls
        if "textsearch" in req.url.path:
            text_calls += 1
            if text_calls == 1:
                return httpx.Response(200, json={
                    "status": "OK",
                    "results": [{"place_id": "p1", "name": "One"}],
                    "next_page_token": "next-token",
                })
            assert req.url.params["pagetoken"] == "next-token"
            return httpx.Response(200, json={
                "status": "OK",
                "results": [{"place_id": "p2", "name": "Two"}, {"place_id": "p3", "name": "Three"}],
            })
        place_id = req.url.params["place_id"]
        return httpx.Response(200, json={"status": "OK", "result": {"place_id": place_id, "name": place_id}})

    adapter = GooglePlacesAdapter(
        api_key="test-key",
        timeout_seconds=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        page_delay_seconds=0,
    )
    result = adapter.search("Businesses in Phoenix", max_results=2)
    assert [item.external_id for item in result.candidates] == ["p1", "p2"]
    assert text_calls == 2
    assert result.page_count == 2


@pytest.mark.parametrize(("response", "expected_code", "retryable"), [
    (httpx.Response(429, json={}), "provider_rate_limit", True),
    (httpx.Response(401, json={}), "provider_auth", False),
    (httpx.Response(403, json={}), "provider_auth", False),
    (httpx.Response(503, json={}), "provider_5xx", True),
    (httpx.Response(200, json={"status": "REQUEST_DENIED"}), "provider_auth", False),
    (httpx.Response(200, json={"status": "OVER_QUERY_LIMIT"}), "provider_rate_limit", True),
])
def test_google_error_classification(response, expected_code, retryable):
    adapter = GooglePlacesAdapter(
        api_key="test-key",
        timeout_seconds=10,
        client=httpx.Client(transport=httpx.MockTransport(lambda _req: response)),
        page_delay_seconds=0,
    )
    with pytest.raises(PiqProviderError) as caught:
        adapter.search("Query", max_results=1)
    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert "test-key" not in caught.value.public_message


def test_google_malformed_timeout_and_missing_key():
    malformed = GooglePlacesAdapter(
        api_key="test-key",
        timeout_seconds=10,
        client=httpx.Client(transport=httpx.MockTransport(lambda _req: httpx.Response(200, text="not-json"))),
    )
    with pytest.raises(PiqProviderError, match="malformed") as malformed_error:
        malformed.search("Query", max_results=1)
    assert malformed_error.value.code == "malformed_response"

    def timeout(req: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=req)

    timed = GooglePlacesAdapter(
        api_key="test-key",
        timeout_seconds=10,
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )
    with pytest.raises(PiqProviderError) as timeout_error:
        timed.search("Query", max_results=1)
    assert timeout_error.value.code == "provider_timeout"
    assert timeout_error.value.retryable is True

    missing = GooglePlacesAdapter(api_key="", timeout_seconds=10)
    with pytest.raises(PiqProviderError) as missing_error:
        missing.search("Query", max_results=1)
    assert missing_error.value.code == "invalid_configuration"
    assert missing_error.value.retryable is False


def test_normalization_preserves_unknowns_closed_status_and_never_synthesizes_email():
    item = normalize_place(
        {},
        {"place_id": "closed-1", "name": "Closed Co", "business_status": "CLOSED_PERMANENTLY", "types": ["store"]},
    )
    assert item is not None
    assert item.website is None and item.phone is None and item.formatted_address is None
    assert item.business_status == "CLOSED_PERMANENTLY"
    assert item.categories == ("store",)
    assert "email" not in {field.name for field in fields(item)}
    assert all("@" not in str(value) for value in item.raw_metadata.values())


def test_persistence_deduplicates_within_tenant_and_allows_cross_tenant_and_demo_coexistence(db: Session):
    tenant_a, user_a, profile_a = seed_tenant(db, "dedupe-a")
    tenant_b, user_b, profile_b = seed_tenant(db, "dedupe-b")
    run_a = discovery_run(db, tenant_a, user_a, profile_a, "a")
    run_b = discovery_run(db, tenant_b, user_b, profile_b, "b")
    db.refresh(tenant_a)
    original_tenant_timestamp = tenant_a.updated_at
    demo = PiqOpportunity(
        tenant_id=tenant_a.id,
        company_name="Example Company",
        provider="demonstration",
        website="https://example.com",
        location="100 Main St, Phoenix, AZ",
        score=91,
    )
    db.add(demo)
    db.commit()
    result = DiscoveryExecutionResult(
        plan=plan_profile_queries(profile_snapshot(), max_queries=1),
        candidates=[candidate("place-1")],
        status="completed",
        diagnostics={},
    )
    assert persist_candidates(db, run_a, result) == (1, 0)
    db.commit()
    assert persist_candidates(db, run_a, result) == (0, 1)

    same_domain_new_place = DiscoveryExecutionResult(
        plan=result.plan,
        candidates=[candidate("place-2", name="Renamed", website="https://example.com/contact")],
        status="completed",
        diagnostics={},
    )
    assert persist_candidates(db, run_a, same_domain_new_place) == (0, 1)
    assert persist_candidates(db, run_b, result) == (1, 0)
    db.commit()
    rows_a = list(db.scalars(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant_a.id)))
    rows_b = list(db.scalars(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant_b.id)))
    assert len(rows_a) == 2
    assert {row.provider for row in rows_a} == {"demonstration", "google_places"}
    assert len(rows_b) == 1 and rows_b[0].source_external_id == "place-1"
    google = next(row for row in rows_a if row.provider == "google_places")
    # Phase 2 now qualifies live candidates; legacy/demo assertions stay intact.
    assert google.score == google.base_match_score > 0 and google.evidence_count > 0 and google.estimated_value_cents == 0
    db.refresh(tenant_a)
    assert tenant_a.updated_at == original_tenant_timestamp


class FakeAdapter:
    def __init__(self, *, result: ProviderSearchResult | None = None, error: PiqProviderError | None = None):
        self.result = result or ProviderSearchResult()
        self.error = error
        self.called = 0
        self.closed = False

    def search(self, _query: str, *, max_results: int):
        self.called += 1
        if self.error:
            raise self.error
        self.result.candidates = self.result.candidates[:max_results]
        return self.result

    def close(self):
        self.closed = True


def test_worker_live_off_does_not_claim_or_call_provider(db: Session, monkeypatch: pytest.MonkeyPatch):
    tenant, user, profile = seed_tenant(db, "worker-off")
    run = discovery_run(db, tenant, user, profile, "off")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    called = []
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings(piq_live_discovery_enabled=False))
    monkeypatch.setattr(piq_worker, "process_discovery_run", lambda *_args, **_kwargs: called.append(True))
    piq_worker.tick(worker_id="off-worker")
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == "queued"
    assert called == []


def test_worker_live_handler_completes_and_persists_candidate(db: Session, monkeypatch: pytest.MonkeyPatch):
    tenant, user, profile = seed_tenant(db, "worker-live")
    run = discovery_run(db, tenant, user, profile, "live")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    with factory() as claim_db:
        piq_worker.claim_next_discovery_run(claim_db, worker_id="live-worker")
    adapter = FakeAdapter(result=ProviderSearchResult(candidates=[candidate("worker-place")], page_count=1))
    piq_worker.process_discovery_run(run.id, tenant.id, "live-worker", adapter_factory=lambda: adapter)
    db.expire_all()
    completed = db.get(PiqDiscoveryRun, run.id)
    assert completed.status == "completed"
    assert completed.result_count == 1
    stored = db.scalar(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant.id))
    assert stored.provider == "google_places" and stored.score == stored.base_match_score > 0
    assert adapter.called == 1 and adapter.closed is True


@pytest.mark.parametrize(("error", "attempt_count", "expected_status"), [
    (PiqProviderError("provider_timeout", "Timed out", retryable=True), 1, "retry_wait"),
    (PiqProviderError("provider_auth", "Rejected", retryable=False), 1, "failed"),
    (PiqProviderError("provider_5xx", "Unavailable", retryable=True), 3, "failed"),
])
def test_worker_transient_permanent_and_max_attempt_behavior(db: Session, monkeypatch, error, attempt_count, expected_status):
    tenant, user, profile = seed_tenant(db, f"worker-error-{expected_status}-{attempt_count}")
    run = discovery_run(db, tenant, user, profile, f"error-{expected_status}-{attempt_count}")
    run.status = "running"
    run.attempt_count = attempt_count
    run.lease_owner = "error-worker"
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings(piq_job_max_attempts=3))
    adapter = FakeAdapter(error=error)
    piq_worker.process_discovery_run(run.id, tenant.id, "error-worker", adapter_factory=lambda: adapter)
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == expected_status


def test_live_route_queues_idempotently_and_status_is_tenant_scoped(db: Session, monkeypatch: pytest.MonkeyPatch):
    tenant_a, admin_a, _profile_a = seed_tenant(db, "route-a")
    tenant_b, admin_b, _profile_b = seed_tenant(db, "route-b")
    monkeypatch.setattr(unified_routes, "settings", live_settings())
    first = unified_routes.discover(
        tenant_a.id,
        unified_routes.DiscoverIn(count=7),
        request("POST", idempotency_key="stable-key"),
        admin_a,
        db,
    )
    second = unified_routes.discover(
        tenant_a.id,
        unified_routes.DiscoverIn(count=7),
        request("POST", idempotency_key="stable-key"),
        admin_a,
        db,
    )
    first_body = json.loads(first.body)
    second_body = json.loads(second.body)
    assert first.status_code == 202 and first_body["status"] == "queued"
    assert first_body["provider_mode"] == "google_places"
    assert first_body["requested_count"] == 7
    assert first_body["run_id"] == second_body["run_id"]
    status = unified_routes.discovery_run_status(tenant_a.id, first_body["run_id"], admin_a, db)
    assert status["run_id"] == first_body["run_id"]
    with pytest.raises(HTTPException) as denied:
        unified_routes.discovery_run_status(tenant_a.id, first_body["run_id"], admin_b, db)
    assert denied.value.status_code == 403
    assert db.scalar(select(PiqDiscoveryRun).where(PiqDiscoveryRun.tenant_id == tenant_b.id)) is None


def test_live_route_follows_sales_role_entitlement_profile_and_managed_session_rules(db: Session, monkeypatch):
    tenant, sales_rep, profile = seed_tenant(db, "sales-rep", role="SALES_REP")
    monkeypatch.setattr(unified_routes, "settings", live_settings())
    response = unified_routes.discover(
        tenant.id,
        unified_routes.DiscoverIn(count=1),
        request("POST"),
        sales_rep,
        db,
    )
    assert response.status_code == 202

    profile.active = False
    db.commit()
    with pytest.raises(HTTPException) as inactive:
        unified_routes.discover(tenant.id, unified_routes.DiscoverIn(count=1), request("POST"), sales_rep, db)
    assert inactive.value.status_code == 400

    no_service_tenant, no_service_user, _ = seed_tenant(db, "no-service", entitled=False)
    with pytest.raises(HTTPException) as no_service:
        unified_routes.discover(
            no_service_tenant.id,
            unified_routes.DiscoverIn(count=1),
            request("POST"),
            no_service_user,
            db,
        )
    assert no_service.value.status_code == 403

    global_admin = User(
        email="global-phase1@example.test",
        password_hash="test-only",
        full_name="Global Admin",
        global_role="RMR_OWNER",
    )
    db.add(global_admin)
    db.commit()
    profile.active = True
    db.commit()
    with pytest.raises(HTTPException) as unmanaged:
        unified_routes.discover(tenant.id, unified_routes.DiscoverIn(count=1), request("POST"), global_admin, db)
    assert unmanaged.value.status_code == 403

    managed = ManagedTenantSession(
        admin_user_id=global_admin.id,
        tenant_id=tenant.id,
        reason="Phase 1 test",
        access_type="managed_write",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(managed)
    db.commit()
    global_admin._managed_tenant_id = tenant.id
    global_admin._managed_session_id = managed.id
    global_admin._managed_access_type = "managed_write"
    managed_response = unified_routes.discover(
        tenant.id,
        unified_routes.DiscoverIn(count=1),
        request("POST"),
        global_admin,
        db,
    )
    managed_run = db.get(PiqDiscoveryRun, json.loads(managed_response.body)["run_id"])
    assert managed_run.managed_session_id == managed.id


def test_http_client_logs_do_not_expose_key(caplog):
    caplog.set_level(logging.DEBUG)
    adapter = GooglePlacesAdapter(
        api_key="private-test-key",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"status": "ZERO_RESULTS"})
        )),
    )
    assert adapter.search("Query", max_results=1).candidates == []
    assert "private-test-key" not in caplog.text
    logging.getLogger("httpx").info("Unrelated RMR request")
    assert "Unrelated RMR request" in caplog.text


@pytest.mark.parametrize("payload", [[], {"status": "OK", "results": {}},
                                         {"status": "OK", "results": ["invalid"]},
                                         {"status": "OK", "results": [{"name": "No identity"}]}])
def test_malformed_shapes_fail_explicitly(payload):
    adapter = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))))
    with pytest.raises(PiqProviderError) as error:
        adapter.search("Query", max_results=1)
    assert error.value.code == "malformed_response"


def test_page_bound_and_duplicate_ids_limit_detail_calls():
    searches, details = [], []
    def handler(req):
        if "textsearch" in req.url.path:
            searches.append(req)
            return httpx.Response(200, json={"status": "OK", "next_page_token": "more",
                "results": [{"place_id": "same", "name": "Same"}]})
        details.append(req)
        return httpx.Response(200, json={"status": "OK", "result": {"place_id": "same", "name": "Same"}})
    adapter = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5, page_delay_seconds=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = adapter.search("Query", max_results=10)
    assert len(searches) == 3 and len(details) == 1 and len(result.candidates) == 1


def test_deadline_shared_across_queries_and_large_response_rejected():
    now = [0.0]
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"status": "ZERO_RESULTS"})
    adapter = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5, clock=lambda: now[0],
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    adapter.search("One", max_results=1)
    now[0] = 6.0
    with pytest.raises(PiqProviderError) as expired:
        adapter.search("Two", max_results=1)
    assert expired.value.code == "provider_timeout" and len(calls) == 1
    huge = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 1_000_001))))
    with pytest.raises(PiqProviderError) as oversized:
        huge.search("Query", max_results=1)
    assert oversized.value.code == "malformed_response"


def test_details_partial_failure_preserves_only_observed_search_data():
    def handler(req):
        if "textsearch" in req.url.path:
            return httpx.Response(200, json={"status": "OK", "results": [{"place_id": "p1", "name": "Observed"}]})
        return httpx.Response(200, text="bad-details")
    adapter = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = execute_google_discovery(profile_snapshot(), adapter=adapter, max_queries=1, max_results=1)
    assert result.status == "partial"
    assert result.candidates[0].website is None
    assert result.candidates[0].source_metadata["details_enriched"] is False
    assert result.diagnostics["issues"][0]["code"] == "malformed_response"


def test_details_rate_limit_retries_instead_of_silent_success():
    def handler(req):
        if "textsearch" in req.url.path:
            return httpx.Response(200, json={"status": "OK", "results": [{"place_id": "p1", "name": "Observed"}]})
        return httpx.Response(429, json={})
    adapter = GooglePlacesAdapter(api_key="test-key", timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PiqProviderError) as limited:
        execute_google_discovery(profile_snapshot(), adapter=adapter, max_queries=1, max_results=1)
    assert limited.value.code == "provider_rate_limit" and limited.value.retryable


def test_normalization_rejects_unsafe_urls_and_unbounded_metadata():
    item = normalize_place({}, {"place_id": "p", "name": "Observed",
        "website": "javascript:alert(1)", "url": "https://maps.example/a?key=secret#token",
        "geometry": {"location": {"lat": float("nan"), "lng": {"junk": "x" * 10000}}},
        "rating": {}, "types": [{"junk": "x" * 10000}, "finance"], "extra": "x" * 10000})
    assert item.website is None and item.source_url == "https://maps.example/a"
    assert item.latitude is None and item.longitude is None and item.rating is None
    assert len(json.dumps(item.raw_metadata)) < 1000
    mapped = normalize_place({}, {"place_id": "p", "name": "Observed",
        "url": "https://maps.google.com/?cid=123456&key=private"})
    assert mapped.source_url == "https://maps.google.com/?cid=123456"
    requested_fields = set(DETAIL_FIELDS.split(","))
    assert "type" in requested_fields and "address_components" in requested_fields
    assert "types" not in requested_fields and "address_component" not in requested_fields


def test_phase1_uses_portable_postgresql_schema_and_lease_sql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable
    from rmr_platform.piq_models import PiqProfileMatch, PiqResearchRun
    for model in (PiqDiscoveryRun, PiqProfileMatch, PiqResearchRun, PiqOpportunity):
        ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
    claim = update(PiqDiscoveryRun).where(PiqDiscoveryRun.lease_expires_at > datetime.now(timezone.utc)).values(status="running")
    assert "UPDATE piq_discovery_runs" in str(claim.compile(dialect=postgresql.dialect()))


def test_name_location_fallback_is_tenant_scoped(db):
    tenant, user, profile = seed_tenant(db, "fallback")
    run = discovery_run(db, tenant, user, profile, "fallback")
    result = DiscoveryExecutionResult(plan_profile_queries(profile_snapshot(), max_queries=1),
        [candidate("p1", website=None), candidate("p2", website=None)], "completed", {})
    assert persist_candidates(db, run, result) == (1, 1)
    db.commit()


def test_retry_due_time_then_success_uses_original_snapshot(db, monkeypatch):
    tenant, user, profile = seed_tenant(db, "retry-cycle")
    run = discovery_run(db, tenant, user, profile, "retry-cycle")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    transient = FakeAdapter(error=PiqProviderError("provider_timeout", "Timed out", retryable=True))
    monkeypatch.setattr(piq_worker, "_adapter", lambda: transient)
    piq_worker.tick(worker_id="first")
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == "retry_wait"
    with factory() as session:
        assert piq_worker.claim_next_discovery_run(session, worker_id="too-early") is None
        session.execute(update(PiqDiscoveryRun).where(PiqDiscoveryRun.id == run.id).values(next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        session.commit()
    profile.industries_json = ["Changed after queue"]
    db.commit()
    class SnapshotAdapter(FakeAdapter):
        def search(self, query, *, max_results):
            assert query == "Mortgage Broker in Phoenix, Arizona"
            # A separate connection can write while HTTP executes.
            with factory() as session:
                session.execute(update(Tenant).where(Tenant.id == tenant.id).values(name="Concurrent write"))
                session.commit()
            return super().search(query, max_results=max_results)
    successful = SnapshotAdapter(result=ProviderSearchResult(candidates=[candidate("retry-p")]))
    monkeypatch.setattr(piq_worker, "_adapter", lambda: successful)
    piq_worker.tick(worker_id="second")
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == "completed"
    assert db.get(PiqDiscoveryRun, run.id).attempt_count == 2


def test_late_worker_result_cannot_persist_after_lease_recovery(db, monkeypatch):
    tenant, user, profile = seed_tenant(db, "late")
    run = discovery_run(db, tenant, user, profile, "late")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    with factory() as session:
        piq_worker.claim_next_discovery_run(session, worker_id="same-worker")
    class LateAdapter(FakeAdapter):
        def search(self, query, *, max_results):
            with factory() as session:
                session.execute(update(PiqDiscoveryRun).where(PiqDiscoveryRun.id == run.id).values(lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
                session.commit()
                piq_worker.recover_expired_leases(session)
                piq_worker.claim_next_discovery_run(session, worker_id="same-worker")
            return super().search(query, max_results=max_results)
    piq_worker.process_discovery_run(run.id, tenant.id, "same-worker",
        adapter_factory=lambda: LateAdapter(result=ProviderSearchResult(candidates=[candidate("late-p")])) )
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).attempt_count == 2
    assert db.get(PiqDiscoveryRun, run.id).status == "running"
    assert db.scalar(select(PiqOpportunity.id).where(PiqOpportunity.tenant_id == tenant.id)) is None


@pytest.mark.parametrize("fault", ["wrong_provider", "wrong_profile_tenant", "expired_managed", "no_entitlement"])
def test_worker_rejects_invalid_run_ownership_before_provider(db, monkeypatch, fault):
    tenant, user, profile = seed_tenant(db, fault)
    run = discovery_run(db, tenant, user, profile, fault)
    if fault == "wrong_provider":
        run.provider = "demonstration"
    elif fault == "wrong_profile_tenant":
        _, _, other_profile = seed_tenant(db, "other-profile")
        run.target_profile_id = other_profile.id
    elif fault == "expired_managed":
        user.global_role = "RMR_OWNER"
        managed = ManagedTenantSession(tenant_id=tenant.id, admin_user_id=user.id, reason="test",
            expires_at=datetime.now(timezone.utc)-timedelta(minutes=1))
        db.add(managed); db.flush()
        run.managed_session_id = managed.id
    else:
        db.scalar(select(TenantService).where(TenantService.tenant_id == tenant.id)).status = "inactive"
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    adapter = FakeAdapter()
    monkeypatch.setattr(piq_worker, "_adapter", lambda: adapter)
    piq_worker.tick(worker_id="ownership")
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == "failed"
    assert adapter.called == 0


def test_cookie_authenticated_routes_and_no_demo_fallback(db, monkeypatch):
    from rmr_platform.db import get_db
    from rmr_platform.security import COOKIE_NAME, create_token
    tenant, admin, profile = seed_tenant(db, "http-admin")
    other_tenant, other, _ = seed_tenant(db, "http-other")
    global_user = User(email="http-global@example.test", password_hash="test-only", full_name="Global", global_role="RMR_OWNER")
    db.add(global_user); db.commit()
    managed = ManagedTenantSession(tenant_id=tenant.id, admin_user_id=global_user.id, reason="test",
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    db.add(managed); db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    def isolated_db():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(unified_routes.router)
    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(unified_routes, "settings", live_settings())
    url = f"/api/tenants/{tenant.id}/piq/discover"
    with TestClient(app) as client:
        assert client.post(url, json={"count": 1}).status_code == 401
        client.cookies.set(COOKIE_NAME, create_token(admin))
        assert client.post(url, json={"count": 1}).status_code == 400
        headers = {"X-RMR-Request": "1", "Idempotency-Key": "http-key"}
        assert client.post(url, json={"count": 0}, headers=headers).status_code == 422
        queued = client.post(url, json={"count": 1}, headers=headers)
        assert queued.status_code == 202
        run_id = queued.json()["run_id"]
        assert client.post(url, json={"count": 2}, headers=headers).status_code == 409
        client.cookies.set(COOKIE_NAME, create_token(other))
        assert client.get(f"/api/tenants/{tenant.id}/piq/discovery-runs/{run_id}").status_code == 403
        assert client.get(f"/api/tenants/{other_tenant.id}/piq/discovery-runs/{run_id}").status_code == 404
        client.cookies.set(COOKIE_NAME, create_token(global_user))
        assert client.post(url, json={"count": 1}, headers={"X-RMR-Request": "1"}).status_code == 403
        assert client.post(url, json={"count": 1}, headers={"X-RMR-Request": "1", "X-RMR-Managed-Session": managed.id}).status_code == 202
        monkeypatch.setattr(unified_routes, "settings", live_settings(piq_discovery_provider="invalid"))
        client.cookies.set(COOKIE_NAME, create_token(admin))
        assert client.post(url, json={"count": 1}, headers=headers).status_code == 503
    assert db.scalar(select(PiqOpportunity.id).where(PiqOpportunity.tenant_id == tenant.id)) is None


@pytest.mark.parametrize("condition,expected", [("no_profile", 400), ("missing_key", 503), ("read_only_role", 403)])
def test_live_queue_rejects_incomplete_setup_and_read_only_role(db, monkeypatch, condition, expected):
    tenant, user, profile = seed_tenant(db, condition)
    monkeypatch.setattr(unified_routes, "settings", live_settings(
        google_places_api_key="" if condition == "missing_key" else "test-key"))
    if condition == "no_profile":
        db.delete(profile)
    if condition == "read_only_role":
        user.tenant_role = "EXECUTIVE_VIEWER"
    db.commit()
    with pytest.raises(HTTPException) as error:
        unified_routes.discover(tenant.id, unified_routes.DiscoverIn(count=1), request("POST"), user, db)
    assert error.value.status_code == expected
    assert db.scalar(select(PiqDiscoveryRun.id).where(PiqDiscoveryRun.tenant_id == tenant.id)) is None
    assert db.scalar(select(PiqOpportunity.id).where(PiqOpportunity.tenant_id == tenant.id)) is None
