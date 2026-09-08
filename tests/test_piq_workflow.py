"""PIQ acceptance workflow: real HTTP/SQL with isolated data, no provider network."""
from types import SimpleNamespace
from datetime import timedelta, datetime, timezone
import pytest
from sqlalchemy import select, func, text, inspect
from rmr_platform.models import PiqOpportunity, TenantService, User, AuditEvent
from rmr_platform.unified_models import PiqTargetProfile, ManagedTenantSession, PiqEvidence
from rmr_platform.piq_models import PiqDiscoveryRun, PiqProfileMatch, PiqResearchRun
from rmr_platform.routes import unified
from rmr_platform.migrations import apply_piq_profile_collection
from rmr_platform.piq_engine.discovery import persist_candidates
from test_piq_phase4_crm_regression import db, api, login, live, no_real_provider_network
from test_piq_phase1_discovery import seed_tenant, live_settings, discovery_run
from test_piq_phase2_matching import strong, result_for

def body(**kw):
    return {"name":"Phoenix lenders","industries":["Mortgage Broker"],"locations":["Phoenix, Arizona"],
            "keywords":[],"exclusions":[],"employee_min":0,"employee_max":0,"revenue_min_cents":0,**kw}
def base(live):return f"/api/tenants/{live.tenant.id}/piq/target-profiles"
def configure(monkeypatch):
    monkeypatch.setattr(unified,"settings",live_settings(piq_max_results_per_run=50,piq_max_candidates_per_run=100,
                                                       piq_live_research_enabled=False))

def test_profile_crud_archive_preserves_history(api,db,live,monkeypatch):
    configure(monkeypatch);login(api,live.user)
    before=db.scalar(select(func.count()).select_from(PiqDiscoveryRun))
    a=api.post(base(live),json=body());b=api.post(base(live),json=body(name="Scottsdale",locations=["Scottsdale, Arizona"]))
    assert a.status_code==b.status_code==201
    aid=a.json()["profile"]["id"]
    assert len(api.get(base(live)).json()["profiles"])==3
    assert api.get(base(live)+"/"+aid).json()["profile"]["locations_json"]==["Phoenix, Arizona"]
    edited=api.put(base(live)+"/"+aid,json=body(name="Edited",locations=["Phoenix, Arizona","Tempe, Arizona"]))
    assert edited.status_code==200 and edited.json()["profile"]["locations_json"]==["Phoenix, Arizona","Tempe, Arizona"]
    assert db.scalar(select(func.count()).select_from(PiqDiscoveryRun))==before
    old_ids=(live.run.id,live.opportunity.id)
    assert api.delete(base(live)+"/"+live.profile.id).status_code==200
    assert live.profile.id not in {p["id"] for p in api.get(base(live)).json()["profiles"]}
    assert api.get(base(live)+"/"+live.profile.id+"/runs").status_code==200
    assert api.get(base(live)+"/"+live.profile.id+"/results").json()["opportunities"][0]["id"]==live.opportunity.id
    assert api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":1,"target_profile_id":live.profile.id}).status_code==400
    assert db.get(PiqDiscoveryRun,old_ids[0]) and db.get(PiqOpportunity,old_ids[1])
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.event_type=="piq.target.archived"))

@pytest.mark.parametrize("change",[
    {"name":""},{"name":" "},{"name":"x"*181},{"industries":[]},{"locations":[]},
    {"industries":["x"*81]},{"locations":["x"]*26},{"keywords":["x"]*26},{"exclusions":["x"]*26},
    {"employee_min":-1},{"employee_max":-1},{"employee_min":20,"employee_max":10},
    {"employee_min":1.2},{"employee_min":True},{"revenue_min_cents":-1},{"revenue_min_cents":1.5},
])
def test_profile_validation(api,live,change):
    login(api,live.user)
    assert api.post(base(live),json=body(**change)).status_code==422

@pytest.mark.parametrize("count,status",[(1,202),(50,202),(0,422),(51,422),(1.5,422),("5",422),(True,422)])
def test_selected_profile_and_counts(api,db,live,monkeypatch,count,status):
    configure(monkeypatch);login(api,live.user)
    created=api.post(base(live),json=body(name="Second")).json()["profile"]
    response=api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":count,"target_profile_id":created["id"]})
    assert response.status_code==status,response.text
    if status==202:
        run=db.get(PiqDiscoveryRun,response.json()["run_id"])
        assert run.target_profile_id==created["id"] and run.requested_count==count
        assert run.profile_snapshot_json["locations"]==["Phoenix, Arizona"]

def test_cross_tenant_and_entitlement(api,db,live,monkeypatch):
    configure(monkeypatch);login(api,live.user)
    other,user,profile=seed_tenant(db,"workflow-other")
    assert api.get(base(live)+"/"+profile.id).status_code==404
    assert api.put(base(live)+"/"+profile.id,json=body()).status_code==404
    assert api.delete(base(live)+"/"+profile.id).status_code==404
    assert api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":1,"target_profile_id":profile.id}).status_code==404
    login(api,user)
    assert api.get(base(live)).status_code==403
    login(api,live.user)
    service=db.scalar(select(TenantService).where(TenantService.tenant_id==live.tenant.id,TenantService.service_code=="piq_access"))
    service.status="inactive";db.commit()
    assert api.get(base(live)).status_code==403
    assert api.get(f"/api/piq/{live.opportunity.id}/profile").status_code==403
    assert api.get(base(live)+"/"+live.profile.id+"/results").status_code==403

@pytest.mark.parametrize("role,write",[("CLIENT_ADMIN",True),("SALES_REP",True),("EXECUTIVE_VIEWER",False),("MARKETING_USER",False)])
def test_capabilities(api,db,live,monkeypatch,role,write):
    configure(monkeypatch);live.user.tenant_role=role;db.commit();login(api,live.user)
    assert api.get(base(live)).json()["can_write"]==write
    assert api.get(f"/api/piq/{live.opportunity.id}/profile").json()["research"]["can_move"]==write
    assert api.post(base(live),json=body()).status_code==(201 if write else 403)

def test_managed_admin_requires_valid_session(api,db,live,monkeypatch):
    configure(monkeypatch)
    admin=User(email="workflow-owner@example.test",full_name="Owner",password_hash="test",global_role="RMR_OWNER",active=True)
    db.add(admin);db.commit();login(api,admin)
    assert api.get(base(live)).json()["can_write"] is False
    assert api.post(base(live),json=body()).status_code==403
    session=ManagedTenantSession(tenant_id=live.tenant.id,admin_user_id=admin.id,access_type="managed_write",status="active",reason="Isolated workflow regression",
                                expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    db.add(session);db.commit();login(api,admin,session.id)
    assert api.post(base(live),json=body()).status_code==201

def test_repeated_runs_dedupe_and_scoped_reads(api,db,live,monkeypatch):
    configure(monkeypatch);login(api,live.user)
    endpoint=f"/api/tenants/{live.tenant.id}/piq/discover"
    payload={"count":1,"target_profile_id":live.profile.id}
    one=api.post(endpoint,json=payload,headers={"Idempotency-Key":"workflow-one"}).json()["run_id"]
    assert api.post(endpoint,json=payload,headers={"Idempotency-Key":"workflow-one"}).json()["run_id"]==one
    two=api.post(endpoint,json=payload,headers={"Idempotency-Key":"workflow-two"}).json()["run_id"]
    assert one!=two
    from qa.piq_phase4_fixture import canonical_candidate
    run=db.get(PiqDiscoveryRun,one)
    assert persist_candidates(db,run,result_for(run.profile_snapshot_json,[canonical_candidate()]))==(0,1)
    run.status="completed";run.result_count=0;db.commit()
    result=api.get(base(live)+"/"+live.profile.id+"/results",params={"run_id":one})
    assert result.json()["opportunities"]==[]
    assert len(api.get(base(live)+"/"+live.profile.id+"/results").json()["opportunities"])==1
    assert len(api.get(base(live)+"/"+live.profile.id+"/runs").json()["runs"])==3
    assert run.diagnostics_json["duplicates_skipped"]==1 and run.diagnostics_json["evaluated_count"]==0

def test_extra_candidates_can_fill_retained_target(db,live):
    from dataclasses import replace
    run=discovery_run(db,live.tenant,live.user,live.profile,"refill");run.requested_count=1
    rejected=replace(strong(),external_id="closed",business_status="CLOSED_PERMANENTLY",website="https://closed.example",company_name="Closed Mortgage Company")
    accepted=replace(strong(),external_id="new-accepted",website="https://new-company.example",company_name="New mortgage company")
    result=result_for(run.profile_snapshot_json,[rejected,accepted])
    assert persist_candidates(db,run,result)==(1,0)
    assert run.diagnostics_json["evaluated_count"]==2 and run.diagnostics_json["rejected"]==1

def test_profile_migration_preserves_data_and_repeats(db,live):
    bind=db.get_bind();before=(live.profile.id,live.run.id,live.opportunity.id)
    db.commit()
    with bind.begin() as conn:
        conn.execute(text("DROP INDEX ix_piq_target_profiles_tenant_id"))
        conn.execute(text("CREATE UNIQUE INDEX ix_piq_target_profiles_tenant_id ON piq_target_profiles (tenant_id)"))
    apply_piq_profile_collection(bind=bind);apply_piq_profile_collection(bind=bind)
    db.add(PiqTargetProfile(tenant_id=live.tenant.id,name="Second profile",locations_json=["Phoenix, Arizona"]))
    db.commit()
    assert db.get(PiqTargetProfile,before[0]) and db.get(PiqDiscoveryRun,before[1]) and db.get(PiqOpportunity,before[2])
    assert not any(i["unique"] and i["column_names"]==["tenant_id"] for i in inspect(bind).get_indexes("piq_target_profiles"))

def test_research_state_no_evidence_is_server_backed(api,db,live,monkeypatch):
    configure(monkeypatch);login(api,live.user)
    run=PiqResearchRun(tenant_id=live.tenant.id,opportunity_id=live.opportunity.id,requested_by=live.user.id,
                       provider="openai",model="gpt-4.1-mini",status="no_evidence",idempotency_key="workflow-research")
    db.add(run);db.commit()
    for _ in range(2):
        info=api.get(f"/api/piq/{live.opportunity.id}/research-state").json()
        assert info["latest"]["status"]=="no_evidence"
    assert api.get(base(live)+"/"+live.profile.id+"/results").json()["opportunities"][0]["research"]["latest"]["status"]=="no_evidence"

def test_no_silent_config_clamping(api,db,live,monkeypatch):
    configure(monkeypatch);login(api,live.user)
    unified.settings.piq_max_results_per_run=3
    r=api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":50,"target_profile_id":live.profile.id})
    assert r.status_code==422

def test_demo_results_remain_visible_in_selected_profile(api,db,live,monkeypatch):
    configure(monkeypatch);unified.settings.piq_live_discovery_enabled=False;login(api,live.user)
    response=api.post(f"/api/tenants/{live.tenant.id}/piq/discover",json={"count":1,"target_profile_id":live.profile.id})
    assert response.status_code==200 and response.json()["provider_mode"]=="demonstration"
    created=response.json()["created"][0]
    assert created["target_profile_id"]==live.profile.id and created["provider"]=="demonstration"
    rows=api.get(base(live)+"/"+live.profile.id+"/results").json()["opportunities"]
    assert created["id"] in {r["id"] for r in rows}
