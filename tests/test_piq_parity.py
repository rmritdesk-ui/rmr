"""Persisted lead intelligence and profile-derived context, isolated SQL only."""
from sqlalchemy import select
from test_piq_workflow import db, api, live, no_real_provider_network, body, base, configure, login
from rmr_platform.piq_models import PiqDiscoveryRun, PiqProfileMatch
from rmr_platform.unified_models import PiqEvidence
from rmr_platform.piq_engine.profile import plan_profile_queries


def test_detail_exposes_persisted_match_and_research_effect(api, db, live):
    login(api, live.user)
    db.add(PiqEvidence(tenant_id=live.tenant.id, opportunity_id=live.opportunity.id,
        provider="openai_research", evidence_type="adaptive_research", profile_criterion="employees",
        fact="Source-backed employee evidence", source_domain="example.test", source_url="https://example.test/team",
        evidence_state="inferred", confidence_pct=70, raw_json={"effect":3,"private_reasoning":"DO_NOT_DISPLAY"}))
    db.commit()
    result=api.get(f"/api/piq/{live.opportunity.id}/profile")
    assert result.status_code==200
    data=result.json()
    match=db.scalar(select(PiqProfileMatch).where(PiqProfileMatch.opportunity_id==live.opportunity.id))
    assert data["match"]["id"]==match.id
    assert data["match"]["criteria_result_json"]==match.criteria_result_json
    assert data["opportunity"]["source_external_id"]==live.opportunity.source_external_id
    research=next(e for e in data["evidence"] if e["provider"]=="openai_research")
    assert research["score_effect"]==3 and research["profile_criterion"]=="employees"
    assert all(e["score_effect"] is None for e in data["evidence"] if e["provider"]=="google_places")


def test_saved_profile_derives_queries_and_run_snapshot_survives_edit(api, db, live, monkeypatch):
    configure(monkeypatch);login(api, live.user)
    profile=api.post(base(live),json=body(name="Context parity")).json()["profile"]
    response=api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":10,"target_profile_id":profile["id"]})
    assert response.status_code==202
    run=db.get(PiqDiscoveryRun,response.json()["run_id"])
    snapshot=dict(run.profile_snapshot_json)
    plan=plan_profile_queries(snapshot,max_queries=1)
    assert len(plan.queries)==1 and "Phoenix, Arizona" in plan.queries[0].text
    assert api.put(base(live)+"/"+profile["id"],json=body(locations=["Tempe, Arizona"])).status_code==200
    db.expire_all()
    assert db.get(PiqDiscoveryRun,run.id).profile_snapshot_json==snapshot
