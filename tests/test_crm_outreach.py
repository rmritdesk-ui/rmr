from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from test_prospectiq_federation import federation_engine, fx
from test_launch1_crm_drip import app_client
from rmr_platform.models import Activity, Contact, CrmProspect, Lead


@pytest.fixture
def prospect(app_client, fx):
    lead=app_client.post(f"/api/tenants/{fx.a.id}/leads",json={
        "company_name":"Example Construction","contact_name":"Alex Example",
        "email":"alex@example.invalid","phone":"+1 602 555 0100"}).json()["lead"]
    result=app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect')
    assert result.status_code==200,result.text
    with Session(fx.engine) as db:
        return db.scalar(select(CrmProspect)).id


@pytest.mark.parametrize("method",["Email","Phone"])
def test_draft_and_manual_confirmation(app_client,fx,prospect,method):
    url=f"/api/prospects/{prospect}"
    draft=app_client.get(url+"/outreach")
    assert draft.status_code==200,draft.text
    assert fx.a.name in draft.json()["body"]
    assert "Example Construction" in draft.json()["body"]
    assert "Alex Example" in draft.json()["body"]
    assert draft.json()["phone"]=="+1 602 555 0100"
    with Session(fx.engine) as db:
        before=db.scalar(select(func.count()).select_from(Activity))
    payload={"request_id":str(uuid4()),"method":method,"confirmed":True,"note":"Contacted manually"}
    first=app_client.post(url+"/contacted",json=payload)
    assert first.status_code==200,first.text
    assert first.json()["activity"]["completed_at"]
    assert first.json()["activity"]["activity_type"]=="Contact Confirmed"
    assert prospect in first.json()["activity"]["body"]
    assert app_client.post(url+"/contacted",json=payload).json()==first.json()
    # Older confirmations remain retry-safe after the display-label change.
    with Session(fx.engine) as db:
        db.get(Activity,payload["request_id"]).activity_type="Outreach Confirmed";db.commit()
    assert app_client.post(url+"/contacted",json=payload).status_code==200
    assert app_client.post(url+"/contacted",json={**payload,"note":"different"}).status_code==409
    assert app_client.post(url+"/contacted",json={**payload,"request_id":str(uuid4()),"confirmed":False}).status_code==422
    with Session(fx.engine) as db:
        assert db.scalar(select(func.count()).select_from(Activity))==before+1
        assert db.get(CrmProspect,prospect).stage=="Prospecting"


@pytest.mark.parametrize("stage",["Nurture","Engaged","Not Pursuing","Customer"])
def test_ineligible_stages(app_client,fx,prospect,stage):
    with Session(fx.engine) as db:
        db.get(CrmProspect,prospect).stage=stage;db.commit()
    assert app_client.get(f"/api/prospects/{prospect}/outreach").status_code==409
    assert app_client.post(f"/api/prospects/{prospect}/contacted",json={
        "request_id":str(uuid4()),"method":"Phone","confirmed":True}).status_code==409


def test_contacts_fallback_and_authorization(app_client,fx,prospect):
    with Session(fx.engine) as db:
        p=db.get(CrmProspect,prospect);c=db.get(Contact,p.contact_id)
        c.phone="";c.email="invalid";db.commit()
    draft=app_client.get(f"/api/prospects/{prospect}/outreach").json()
    assert draft["email"]=="" and draft["invalid_email"]
    assert draft["phone"]=="+1 602 555 0100"
    overview=app_client.get(f"/api/v53/tenants/{fx.a.id}/crm/overview").json()
    assert overview["prospects"][0]["contact_phone"]==draft["phone"]
    old_tenant=fx.user.tenant_id
    fx.user.tenant_id=fx.b.id
    assert app_client.get(f"/api/prospects/{prospect}/outreach").status_code==403
    assert app_client.post(f"/api/prospects/{prospect}/contacted",json={
        "request_id":str(uuid4()),"method":"Email","confirmed":True}).status_code==403
    fx.user.tenant_id=old_tenant;fx.user.tenant_role="EXECUTIVE_VIEWER"
    assert app_client.get(f"/api/prospects/{prospect}/outreach").status_code==403
    assert app_client.post(f"/api/prospects/{prospect}/contacted",json={
        "request_id":str(uuid4()),"method":"Phone","confirmed":True}).status_code==403


def test_promoted_prospect_cannot_start_intro(app_client,fx,prospect):
    result=app_client.post(f"/api/prospects/{prospect}/convert-to-opportunity",json={
        "name":"Example deal","stage":"Qualified","value_cents":10000})
    assert result.status_code==200,result.text
    assert app_client.get(f"/api/prospects/{prospect}/outreach").status_code==409


@pytest.mark.parametrize("email",["wrong","a@bad?.invalid","a..b@example.invalid","a@example.invalid\r\nBcc:other@example.invalid"])
def test_invalid_email_never_used(app_client,fx,prospect,email):
    with Session(fx.engine) as db:
        p=db.get(CrmProspect,prospect)
        db.get(Contact,p.contact_id).email=email
        db.commit()
    result=app_client.get(f"/api/prospects/{prospect}/outreach").json()
    assert result["email"]=="" and result["invalid_email"]
