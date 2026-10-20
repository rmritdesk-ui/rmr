import copy
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import select
from test_prospectiq_federation import federation_engine, fx
from test_prospectiq_crm import transfer
from rmr_platform.models import Lead
from rmr_platform.prospectiq_bridge.models import ProspectiqCrmReceipt as Receipt
from rmr_platform.prospectiq_bridge.crm_intelligence import lead_intelligence


def rich_payload(t):
    p=copy.deepcopy(t.payload)
    p["prospect"].update(company_name="Infinity Builders - Phoenix Remodeling & Construction",
        piq_score=77,address="Phoenix, Arizona",industry="Construction")
    p["prospect"]["intelligence_snapshot"]={
        "version":2,"verified":["Construction services","Phoenix address"],
        "needs_validation":["Annual revenue","Multiple locations"],
        "research_results":[{"label":"Owner","status":"confirmed","explanation":"Jane is the reported owner.",
            "sources":[{"url":"https://example.invalid/team?id=1","title":"Team"},{"url":"https://example.invalid/about","title":"About"}]},
            {"label":"Revenue","status":"not_found","explanation":"No reliable public evidence found.","sources":[]}],
        "research_runs":[{"id":str(uuid4()),"status":"partial"}],
        "why_this_matched":["Construction and Phoenix fit"],
        "recommended_next_step":"Contact the owner"}
    return p


def test_signed_rich_refresh_preserves_edits_and_old_event_cannot_revert(transfer):
    t=transfer;p=rich_payload(t)
    first=t.call(p);assert first.status_code==201,first.text
    lead_id=first.json()["rmr_lead_id"]
    with Session(t.f.engine) as db:
        lead=db.get(Lead,lead_id)
        lead.company_name="CRM edited company";lead.contact_name="CRM contact";lead.status="Contacted";lead.notes="Private CRM notes"
        db.commit()
        detail=lead_intelligence(db,t.f.a.id,lead_id)
        assert detail["source"]["piq_score"]==77
        assert len(detail["research_results"][0]["sources"])==2
        assert lead_intelligence(db,t.f.b.id,lead_id) is None
    newer=copy.deepcopy(p);newer["integration_event_id"]=str(uuid4())
    newer["prospect"]["intelligence_snapshot"]["recommended_next_step"]="Schedule a meeting"
    assert t.call(newer).status_code==200
    assert t.call(p).status_code==200
    with Session(t.f.engine) as db:
        lead=db.get(Lead,lead_id)
        assert (lead.company_name,lead.contact_name,lead.status,lead.notes)==("CRM edited company","CRM contact","Contacted","Private CRM notes")
        assert lead_intelligence(db,t.f.a.id,lead_id)["recommended_next_step"]=="Schedule a meeting"
        assert db.scalar(select(Receipt)).provenance_json["import"]["prospect"]["intelligence_snapshot"]["recommended_next_step"]=="Contact the owner"


def test_legacy_manual_and_size_boundary(transfer):
    t=transfer
    response=t.call();assert response.status_code==201
    with Session(t.f.engine) as db:
        detail=lead_intelligence(db,t.f.a.id,response.json()["rmr_lead_id"])
        assert "Legacy transfer" in detail["note"] and detail["research_results"]==[]
        assert lead_intelligence(db,t.f.a.id,str(uuid4())) is None
    oversized=copy.deepcopy(t.payload)
    oversized["prospect"]["intelligence_snapshot"]={"debug":"x"*262144}
    assert t.call(oversized).status_code==413
