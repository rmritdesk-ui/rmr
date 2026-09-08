from dataclasses import replace
from datetime import timedelta
import json

import pytest
from sqlalchemy import select, func, delete
from sqlalchemy.orm import sessionmaker

from rmr_platform.models import PiqOpportunity
from rmr_platform.piq_models import PiqDiscoveryRun, PiqProfileMatch
from rmr_platform.unified_models import PiqEvidence
from rmr_platform.piq_engine.contracts import DiscoveryExecutionResult, ProviderSearchResult, ProviderIssue, PiqProviderError
from rmr_platform.piq_engine.discovery import persist_candidates, execute_google_discovery
from rmr_platform.piq_engine.evidence import persist_match
from rmr_platform.piq_engine.matching import match_candidate, SCORING_VERSION
from rmr_platform.piq_engine.profile import plan_profile_queries
from rmr_platform import piq_worker
from rmr_platform.routes import unified as unified_routes
from rmr_platform.piq_engine import discovery as discovery_service
from test_piq_phase1_discovery import (
    db, no_real_provider_network, candidate, profile_snapshot, seed_tenant,
    discovery_run, FakeAdapter, live_settings,
)


def profile(**overrides):
    return profile_snapshot(employee_min=0, employee_max=0, revenue_min_cents=0, exclusions=[], **overrides)


def strong(**overrides):
    return replace(candidate("phase2-place", name="Local Mortgage Broker Company"), phone="+1 555 0100", **overrides)


def criterion(match, key):
    return next(item for item in match.criteria if item.criterion == key)


@pytest.mark.parametrize(("categories", "state", "points", "qualified"), [
    (("mortgage_broker",), "confirmed", 25, True),
    (("Mortgage Brokers",), "confirmed", 25, True),
    (("finance",), "inferred", 15, True),
    (("restaurant",), "contradicted", 0, False),
    ((), "unresolved", 0, True),
    (("establishment", "point_of_interest"), "unresolved", 0, True),
    (("unclassified_service",), "unresolved", 0, True),
])
def test_industry_rules(categories, state, points, qualified):
    result = match_candidate(profile(), strong(categories=categories))
    assert criterion(result, "industry").state == state
    assert criterion(result, "industry").score_effect == points
    assert result.qualified == qualified


def test_explicit_category_equivalence():
    result = match_candidate(profile(industries=["Real Estate Agents"]), strong(categories=("real_estate_agency",)))
    assert criterion(result, "industry").state == "confirmed"


@pytest.mark.parametrize(("locations", "changes", "state"), [
    (["Phoenix, Arizona"], {}, "confirmed"),
    (["Phoenix, AZ"], {}, "confirmed"),
    (["Arizona"], {}, "confirmed"),
    (["USA"], {}, "confirmed"),
    (["Phoenix, Arizona"], {"city": "Tucson", "formatted_address": "100 Main, Tucson, AZ"}, "contradicted"),
    (["Phoenix, Arizona"], {"state": "Nevada"}, "contradicted"),
    (["Phoenix, Arizona", "Tucson, Arizona"], {"city": "Tucson"}, "confirmed"),
    (["Phoenix, Arizona"], {"city": None, "state": None, "country": None, "formatted_address": "100 Main, Phoenix, AZ 85001"}, "confirmed"),
    (["Unknown Territory"], {}, "unresolved"),
])
def test_geography_rules(locations, changes, state):
    result = match_candidate(profile(locations=locations), strong(**changes))
    assert criterion(result, "geography").state == state


def sparse():
    return replace(strong(), formatted_address=None, city=None, state=None, country=None,
                   categories=(), phone=None, website=None, business_status=None, rating=None, review_count=None,
                   source_metadata={"discovery_query": {"location": "Phoenix, Arizona", "text": "mortgage broker in Phoenix, Arizona"}})


def test_search_area_inferred_only_when_no_observed_location():
    result = match_candidate(profile(), sparse())
    assert criterion(result, "geography").state == "inferred"
    assert result.base_match_score == 6 and result.confidence_score < 10
    observed = replace(sparse(), formatted_address="Unresolved address")
    assert criterion(match_candidate(profile(), observed), "geography").state == "unresolved"
    no_query = replace(sparse(), source_metadata={})
    assert criterion(match_candidate(profile(), no_query), "geography").state == "unresolved"


@pytest.mark.parametrize(("exclusions", "qualified"), [
    (["mortgage brokers"], False),
    (["category: Mortgage Broker"], False),
    (["Phoenix, Arizona"], False),
    (["geography: Arizona"], False),
    (["large competitors"], True),
    (["franchises"], True),
    (["restaurant"], True),
    (["outside Phoenix"], True),
    (["location: Mortgage Broker"], True),
    (["uncertain: mortgage broker"], True),
])
def test_only_source_proven_exclusions_reject(exclusions, qualified):
    snapshot = profile()
    snapshot["exclusions"] = exclusions
    result = match_candidate(snapshot, strong())
    assert result.qualified is qualified
    assert criterion(result, "exclusion:0").state == ("unresolved" if qualified else "contradicted")


@pytest.mark.parametrize("status", ["CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY", "INACTIVE"])
def test_closed_business_rejected(status):
    result = match_candidate(profile(), strong(business_status=status))
    assert not result.qualified and result.base_match_score == 0
    assert "closed/inactive" in result.explanation


def test_employee_and_revenue_unresolved_no_fit_points_or_rejection():
    before = match_candidate(profile(), strong())
    snapshot = profile()
    snapshot.update(employee_min=10000, employee_max=20000, revenue_min_cents=10**12)
    after = match_candidate(snapshot, strong())
    assert after.qualified and after.base_match_score == before.base_match_score
    for key in ("employees", "revenue"):
        item = criterion(after, key)
        assert item.state == "unresolved" and item.observed is None and item.score_effect == 0
        assert not item.assessable and not item.evidence_refs
    assert after.evidence_completeness_pct == before.evidence_completeness_pct == 100
    assert after.confidence_score == 80 and before.confidence_score == 90


def test_keywords_require_provider_fields_not_query():
    snapshot = profile(keywords=["local", "exclusive"])
    item = strong(source_metadata={"discovery_query": {"text": "local exclusive Mortgage Broker in Phoenix", "location": "Phoenix, Arizona"}})
    result = match_candidate(snapshot, item)
    assert criterion(result, "keyword:0").score_effect == 5
    assert criterion(result, "keyword:1").state == "unresolved"
    assert result.qualified


def test_keyword_phrase_cannot_be_assembled_across_unrelated_fields():
    result = match_candidate(profile(keywords=["company finance"]), strong(categories=("finance",)))
    assert criterion(result, "keyword:0").state == "unresolved"


@pytest.mark.parametrize(("phone", "website", "points"), [
    ("+1 555 0100", "https://example.test", 15),
    (None, "https://example.test", 8),
    ("+1 555 0100", None, 8),
    (None, None, 0),
])
def test_contactability(phone, website, points):
    item = replace(strong(), phone=phone, website=website)
    result = match_candidate(profile(), item)
    assert criterion(result, "contactability").score_effect == points
    assert not hasattr(item, "email")


def test_exact_weights_clamping_and_deterministic_replay():
    snapshot = profile(keywords=["Local", "Mortgage", "Broker", "Company", "Local Mortgage"])
    result = match_candidate(snapshot, strong())
    assert result.base_match_score == 100
    assert result.score_breakdown["components"] == {
        "industry": 25, "geography": 20, "contactability": 15, "source_quality": 20,
        "keyword:0": 5, "keyword:1": 5, "keyword:2": 5, "keyword:3": 5, "keyword:4": 0,
    }
    assert result == match_candidate(snapshot, strong())
    assert result.scoring_version == SCORING_VERSION == "piq-match-v1"
    assert "adaptive" not in json.dumps(result.as_dict())


@pytest.mark.parametrize(("changes", "cap"), [
    ({"categories": ()}, 40),
    ({"categories": ("finance",)}, 65),
    ({"city": None, "state": None, "country": None, "formatted_address": None}, 55),
    ({"business_status": None}, 65),
    ({"phone": None, "website": None}, 60),
])
def test_evidence_guardrails(changes, cap):
    result = match_candidate(profile(keywords=["Local", "Mortgage", "Broker", "Company"]), replace(strong(), **changes))
    assert 0 <= result.base_match_score <= cap
    assert any(guard["cap"] == cap and guard["reason"] and guard["criterion_refs"] for guard in result.score_breakdown["guardrails"])
    assert sum(result.score_breakdown["components"].values()) + result.score_breakdown["guardrail_adjustment"] == result.base_match_score


def test_confidence_is_evidence_strength_not_business_fit():
    accepted = match_candidate(profile(), strong())
    rejected = match_candidate(profile(), strong(categories=("restaurant",)))
    weak = match_candidate(profile(), sparse())
    assert rejected.base_match_score == 0 and rejected.confidence_score == accepted.confidence_score == 90
    assert weak.confidence_score < accepted.confidence_score


def test_completeness_assessable_denominator_partial_and_missing():
    assert match_candidate(profile(), strong()).evidence_completeness_pct == 100
    assert match_candidate(profile(), strong(categories=("finance",))).evidence_completeness_pct == 75
    assert match_candidate(profile(), sparse()).evidence_completeness_pct == 25
    result = match_candidate(profile(keywords=["not observed"]), strong())
    assert result.evidence_completeness_pct == 67
    assert result.score_breakdown["assessable_profile_count"] == 3


def result_for(snapshot, candidates):
    return DiscoveryExecutionResult(plan_profile_queries(snapshot, max_queries=8), candidates, "completed", {})


def test_evidence_match_summary_retry_idempotency_and_tenant_isolation(db):
    tenant, user, saved_profile = seed_tenant(db, "phase2")
    run = discovery_run(db, tenant, user, saved_profile, "phase2")
    item = strong()
    output = result_for(run.profile_snapshot_json, [item])
    assert persist_candidates(db, run, output) == (1, 0)
    db.commit()
    opportunity = db.scalar(select(PiqOpportunity).where(PiqOpportunity.tenant_id == tenant.id))
    match = db.scalar(select(PiqProfileMatch))
    evidence = list(db.scalars(select(PiqEvidence)))
    assert len(evidence) == opportunity.evidence_count > 0
    assert opportunity.score == opportunity.base_match_score == match.base_match_score > 0
    assert opportunity.confidence_score == match.confidence_score
    assert opportunity.evidence_completeness_pct == match.evidence_completeness_pct
    assert opportunity.adaptive_score_delta is None and opportunity.estimated_value_cents == 0
    for row in evidence:
        assert row.provider == "google_places" and row.source_url == item.source_url
        assert row.source_domain == "maps.google.test" and row.tenant_id == tenant.id
        assert row.discovery_run_id == run.id and row.verified and not row.is_synthesized
        assert row.observed_at is not None and "score_effect" in row.raw_json
    hashes = {row.evidence_hash for row in evidence}
    for row in match.criteria_result_json["criteria"]:
        if row["score_effect"]:
            assert row["evidence_refs"] and set(row["evidence_refs"]) <= hashes
    # Existing rows remain skip-only, preserving Phase 1 conservative identity policy.
    assert persist_candidates(db, run, output) == (0, 1)
    persist_match(db, run, opportunity, replace(item, retrieved_at=item.retrieved_at + timedelta(days=1)), match_candidate(run.profile_snapshot_json, item))
    db.commit()
    assert db.scalar(select(func.count()).select_from(PiqProfileMatch)) == 1
    assert db.scalar(select(func.count()).select_from(PiqEvidence)) == len(evidence)
    # Existing evidence hashes also protect recovery if a match row is absent.
    db.execute(delete(PiqProfileMatch).where(PiqProfileMatch.id == match.id))
    db.flush()
    persist_match(db, run, opportunity, item, match_candidate(run.profile_snapshot_json, item))
    db.commit()
    assert db.scalar(select(func.count()).select_from(PiqEvidence)) == len(evidence)
    other, other_user, other_profile = seed_tenant(db, "phase2-other")
    other_run = discovery_run(db, other, other_user, other_profile, "phase2-other")
    assert persist_candidates(db, other_run, result_for(other_run.profile_snapshot_json, [item])) == (1, 0)
    db.commit()
    assert db.scalar(select(func.count()).select_from(PiqProfileMatch)) == 2
    assert db.scalar(select(func.count()).select_from(PiqEvidence)) == 2 * len(evidence)


def test_inferred_evidence_not_verified_or_synthesized(db):
    tenant, user, saved_profile = seed_tenant(db, "inference")
    run = discovery_run(db, tenant, user, saved_profile, "inference")
    assert persist_candidates(db, run, result_for(run.profile_snapshot_json, [sparse()])) == (1, 0)
    db.commit()
    evidence = list(db.scalars(select(PiqEvidence)))
    assert len(evidence) == 1
    assert evidence[0].evidence_state == "inferred" and not evidence[0].verified and not evidence[0].is_synthesized
    assert evidence[0].profile_criterion == "geography" and evidence[0].raw_json["score_effect"] == 6


def test_rejected_candidates_not_visible_and_demo_untouched(db):
    tenant, user, saved_profile = seed_tenant(db, "rejections")
    run = discovery_run(db, tenant, user, saved_profile, "rejections")
    demo = PiqOpportunity(tenant_id=tenant.id, provider="demonstration", company_name="Demo", score=91, evidence_count=4)
    db.add(demo)
    db.commit()
    rejected = strong(business_status="CLOSED_PERMANENTLY")
    output = result_for(run.profile_snapshot_json, [rejected])
    assert persist_candidates(db, run, output) == (0, 0)
    db.commit()
    assert db.scalar(select(func.count()).select_from(PiqOpportunity)) == 1
    assert db.scalar(select(func.count()).select_from(PiqProfileMatch)) == 0
    assert db.scalar(select(func.count()).select_from(PiqEvidence)) == 0
    assert demo.score == 91 and demo.evidence_count == 4
    assert run.diagnostics_json["rejected"] == 1
    assert run.diagnostics_json["rejected_candidates"][0]["match"]["qualified"] is False


def test_worker_counts_partial_and_replay(db, monkeypatch):
    tenant, user, saved_profile = seed_tenant(db, "counts")
    run = discovery_run(db, tenant, user, saved_profile, "counts")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    with factory() as session:
        piq_worker.claim_next_discovery_run(session, worker_id="phase2-worker")
    adapter = FakeAdapter(result=ProviderSearchResult(
        candidates=[strong(), strong(), strong(external_id="closed", business_status="CLOSED_PERMANENTLY", website=None, formatted_address="200 Main, Phoenix, AZ")],
        issues=[ProviderIssue("malformed_response", "Optional details unavailable", False, "details")], page_count=1))
    piq_worker.process_discovery_run(run.id, tenant.id, "phase2-worker", adapter_factory=lambda: adapter)
    db.expire_all()
    saved = db.get(PiqDiscoveryRun, run.id)
    assert saved.status == "partial" and saved.result_count == 1
    assert {key: saved.diagnostics_json[key] for key in ("candidates_received", "duplicates_skipped", "rejected", "qualified", "persisted", "provider_errors")} == {
        "candidates_received": 3, "duplicates_skipped": 1, "rejected": 1, "qualified": 1, "persisted": 1, "provider_errors": 1,
    }
    count = db.scalar(select(func.count()).select_from(PiqEvidence))
    piq_worker.process_discovery_run(run.id, tenant.id, "phase2-worker", adapter_factory=lambda: adapter)
    assert db.scalar(select(func.count()).select_from(PiqProfileMatch)) == 1
    assert db.scalar(select(func.count()).select_from(PiqEvidence)) == count


def test_orchestration_records_actual_query_for_inference():
    adapter = FakeAdapter(result=ProviderSearchResult(candidates=[replace(sparse(), source_metadata={})]))
    output = execute_google_discovery(profile(), adapter=adapter, max_queries=1, max_results=1)
    assert output.candidates[0].source_metadata["discovery_query"]["location"] == "Phoenix, Arizona"
    assert criterion(match_candidate(profile(), output.candidates[0]), "geography").state == "inferred"


@pytest.mark.parametrize("changes", [{"active": False}, {"industries": []}, {"locations": []}])
def test_invalid_snapshot_fails_safely(changes):
    snapshot = profile()
    snapshot.update(changes)
    with pytest.raises(PiqProviderError):
        match_candidate(snapshot, strong())


@pytest.mark.parametrize("fault", ["foreign_profile", "wrong_snapshot", "demo_provider"])
def test_persistence_rejects_incorrect_tenant_profile_binding(db, fault):
    tenant, user, saved_profile = seed_tenant(db, "owner")
    _, _, foreign_profile = seed_tenant(db, "foreign")
    run = discovery_run(db, tenant, user, saved_profile, "owner")
    if fault == "foreign_profile":
        run.target_profile_id = foreign_profile.id
    elif fault == "wrong_snapshot":
        run.profile_snapshot_json = {**run.profile_snapshot_json, "id": foreign_profile.id}
    else:
        run.provider = "demonstration"
    with pytest.raises(PiqProviderError):
        persist_candidates(db, run, result_for(run.profile_snapshot_json, [strong()]))
    db.rollback()
    assert db.scalar(select(func.count()).select_from(PiqOpportunity)) == 0


def test_worker_persistence_failure_rolls_back_all_three_tables(db, monkeypatch):
    tenant, user, saved_profile = seed_tenant(db, "atomic")
    run = discovery_run(db, tenant, user, saved_profile, "atomic")
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    monkeypatch.setattr(piq_worker, "SessionLocal", factory)
    monkeypatch.setattr(piq_worker, "settings", live_settings())
    original = discovery_service.persist_match
    def fail_after_match(*args, **kwargs):
        original(*args, **kwargs)
        args[0].flush()
        raise RuntimeError("test-only failure after opportunity/evidence/match writes")
    monkeypatch.setattr(discovery_service, "persist_match", fail_after_match)
    with factory() as session:
        piq_worker.claim_next_discovery_run(session, worker_id="atomic-worker")
    adapter = FakeAdapter(result=ProviderSearchResult(candidates=[strong()]))
    piq_worker.process_discovery_run(run.id, tenant.id, "atomic-worker", adapter_factory=lambda: adapter)
    db.expire_all()
    assert db.get(PiqDiscoveryRun, run.id).status == "failed"
    for model in (PiqOpportunity, PiqEvidence, PiqProfileMatch):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_status_exposes_rejection_reason_without_raw_provider_metadata(db):
    tenant, user, saved_profile = seed_tenant(db, "status-reject")
    run = discovery_run(db, tenant, user, saved_profile, "status-reject")
    output = result_for(run.profile_snapshot_json, [strong(business_status="CLOSED_PERMANENTLY")])
    persist_candidates(db, run, output)
    db.commit()
    response = unified_routes.discovery_run_status(tenant.id, run.id, user, db)
    assert response["diagnostics"]["rejected"] == 1
    assert "closed/inactive" in response["diagnostics"]["rejection_summary"][0]["reason"]
    assert "rejected_candidates" not in response["diagnostics"]


@pytest.mark.parametrize(("status", "rating", "reviews", "points"), [
    ("OPERATIONAL", 4.7, 20, 20), ("OPERATIONAL", None, None, 10),
    ("OPERATIONAL", 0, 10, 10), ("OPERATIONAL", 6, 10, 10),
    ("OPERATIONAL", 4.7, 0, 10), (None, 4.7, 20, 0),
])
def test_listing_quality_does_not_invent_active_status_or_meaningful_reviews(status, rating, reviews, points):
    result = match_candidate(profile(), strong(business_status=status, rating=rating, review_count=reviews))
    assert criterion(result, "source_quality").score_effect == points
