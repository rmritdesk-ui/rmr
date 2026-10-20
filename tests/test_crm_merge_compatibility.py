"""Merge acceptance: populated legacy upgrade and unchanged public CRM contracts.

Uses disposable databases only. Set CRM_MERGE_TEST_DATABASE_URL to an empty,
disposable PostgreSQL database to exercise the identical upgrade there.
"""
import json
import os
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from test_launch1_crm_drip import app_client
from test_prospectiq_federation import federation_engine, fx
from rmr_platform.models import Account, Activity, CrmProspect, Lead, Opportunity
from rmr_platform.migrations import (
    apply_crm_prospect_conversion_schema,
    apply_crm_account_customer_lifecycle_schema,
    apply_crm_prospect_workflow_details_schema,
    apply_crm_prospect_outcome_restore_schema,
)


def test_populated_legacy_upgrade_without_future_orm_columns(tmp_path):
    url = os.environ.get("CRM_MERGE_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    engine = create_engine(url)
    # Deliberately model the old schema, not Base.metadata.create_all().
    with engine.begin() as db:
        for ddl in (
            "CREATE TABLE tenants (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36))",
            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), status VARCHAR(40))",
            "CREATE TABLE contacts (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), account_id VARCHAR(36))",
            "CREATE TABLE leads (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), assigned_user_id VARCHAR(36), status VARCHAR(40))",
            "CREATE TABLE opportunities (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), account_id VARCHAR(36), contact_id VARCHAR(36), stage VARCHAR(40), updated_at TIMESTAMP)",
            "CREATE TABLE audit_events (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(36), entity_id VARCHAR(80), entity_type VARCHAR(80), event_type VARCHAR(120), event_data TEXT)",
        ):
            db.execute(text(ddl))
        db.execute(text("INSERT INTO tenants VALUES ('tenant'), ('other')"))
        db.execute(text("INSERT INTO users VALUES ('user', 'tenant')"))
        db.execute(text("INSERT INTO accounts VALUES ('account', 'tenant', 'Inactive')"))
        db.execute(text("INSERT INTO contacts VALUES ('contact', 'tenant', 'account')"))
        db.execute(text("INSERT INTO leads VALUES ('mapped','tenant','user','Converted'), ('missing','tenant','user','Converted'), ('wrong','tenant','user','Converted')"))
        db.execute(text("INSERT INTO opportunities VALUES ('won','tenant','account','contact','Closed Won','2020-01-01'), ('legacy','tenant','account',NULL,'Prospecting','2020-01-01')"))
        for lead, tenant in (("mapped", "tenant"), ("wrong", "other")):
            db.execute(text("INSERT INTO audit_events VALUES (:id,:tenant,:lead,'lead','crm.lead.converted',:data)"),
                       dict(id=lead, tenant=tenant, lead=lead,
                            data=json.dumps({"account_id": "account", "opportunity_id": "won"})))
    for _ in range(2):
        apply_crm_prospect_conversion_schema(bind=engine)
        apply_crm_account_customer_lifecycle_schema(bind=engine)
        apply_crm_prospect_workflow_details_schema(bind=engine)
        apply_crm_prospect_outcome_restore_schema(bind=engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT status, customer_since FROM accounts")).one() == ("Inactive", None)
        assert db.execute(text("SELECT source_lead_id, stage FROM crm_prospects")).all() == [("mapped", "Customer")]
        assert db.execute(text("SELECT stage, prospect_id FROM opportunities WHERE id='legacy'")).one() == ("Prospecting", None)
        assert db.execute(text("SELECT prospect_id FROM opportunities WHERE id='won'")).scalar()
        assert db.execute(text("SELECT stage_before_opportunity_outcome FROM crm_prospects")).scalar() is None
    assert "customer_since" in {c["name"] for c in inspect(engine).get_columns("accounts")}
    engine.dispose()


def test_existing_conversion_contracts_still_return_opportunity(app_client, fx):
    for controlled in (False, True):
        lead = app_client.post(f"/api/tenants/{fx.a.id}/leads", json={
            "company_name": f"Compatibility {controlled}", "contact_name": "Test Person"}).json()["lead"]
        path = f'/api/v53/leads/{lead["id"]}/convert' if controlled else f'/api/leads/{lead["id"]}/convert'
        payload = {"account_name": "Controlled account", "create_contact": True,
                   "create_opportunity": True, "value_cents": 1200, "stage": "Prospecting"} if controlled else {}
        response = app_client.post(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["opportunity"]["id"]
        assert response.json()["contact"]["id"]
        if controlled:
            assert response.json()["opportunity"]["value_cents"] == 1200
            assert response.json()["activity"]["id"]


def test_controlled_conversion_options_remain_supported(app_client, fx):
    lead = app_client.post(f"/api/tenants/{fx.a.id}/leads", json={"company_name": "No deal"}).json()["lead"]
    response = app_client.post(f'/api/v53/leads/{lead["id"]}/convert', json={
        "account_name": "No deal", "create_contact": False, "create_opportunity": False})
    assert response.status_code == 200, response.text
    assert response.json()["contact"] is None
    assert response.json()["opportunity"] is None


@pytest.mark.parametrize("field", ["name", "stage", "value_cents", "probability_pct", "next_action", "loss_reason"])
def test_null_required_opportunity_fields_rejected(app_client, fx, field):
    row = app_client.post(f"/api/tenants/{fx.a.id}/opportunities", json={"name": "Legacy"}).json()["opportunity"]
    response = app_client.patch(f'/api/opportunities/{row["id"]}', json={field: None})
    assert response.status_code == 422, response.text
    with Session(fx.engine) as db:
        assert db.get(Opportunity, row["id"]).name == "Legacy"


def test_legacy_opportunity_can_clear_date_and_close(app_client, fx):
    row = app_client.post(f"/api/tenants/{fx.a.id}/opportunities", json={
        "name": "Legacy", "expected_close_date": "2027-01-01"}).json()["opportunity"]
    cleared = app_client.patch(f'/api/opportunities/{row["id"]}', json={"expected_close_date": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["opportunity"]["expected_close_date"] is None
    closed = app_client.post(f'/api/v531/opportunities/{row["id"]}/quick-close', json={
        "stage": "Closed Won", "expected_stage": "Prospecting", "close_date": date.today().isoformat()})
    assert closed.status_code == 200, closed.text
    assert closed.json()["opportunity"]["prospect_id"] is None


def test_custom_legacy_stage_is_not_rejected(app_client, fx):
    row = app_client.post(f"/api/tenants/{fx.a.id}/opportunities", json={
        "name": "Historical custom stage", "stage": "Legacy Review"}).json()["opportunity"]
    response = app_client.patch(f'/api/opportunities/{row["id"]}', json={
        "stage": "Legacy Review", "expected_stage": "Legacy Review", "next_action": "Keep working"})
    assert response.status_code == 200, response.text
    assert response.json()["opportunity"]["stage"] == "Legacy Review"


def test_prospect_authorization_reason_and_duplicate_guards(app_client, fx):
    lead = app_client.post(f"/api/tenants/{fx.a.id}/leads", json={"company_name": "Prospect"}).json()["lead"]
    converted = app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect')
    assert converted.status_code == 200, converted.text
    prospect = converted.json()["prospect"]
    assert app_client.post(f'/api/leads/{lead["id"]}/convert-to-prospect').status_code == 409
    assert app_client.patch(f'/api/prospects/{prospect["id"]}', json={"stage": "Not Pursuing"}).status_code == 422
    assert app_client.patch(f'/api/prospects/{prospect["id"]}', json={
        "stage": "Not Pursuing", "not_pursuing_reason": "No fit"}).status_code == 200
    assert app_client.patch(f'/api/prospects/{prospect["id"]}', json={
        "stage": "Not Pursuing", "stage_note": "Keep existing reason"}).status_code == 200
    fx.user.tenant_id = fx.b.id
    assert app_client.patch(f'/api/prospects/{prospect["id"]}', json={"stage": "Engaged"}).status_code == 403


def test_managed_owner_mywork_readonly_state(app_client, fx):
    fx.user.global_role = "RMR_OWNER"
    response = app_client.get(f"/api/v53/tenants/{fx.a.id}/crm/overview")
    assert response.json()["read_only"] is True
    fx.user._managed_tenant_id = fx.a.id
    fx.user._managed_access_type = "managed_write"
    response = app_client.get(f"/api/v53/tenants/{fx.a.id}/crm/overview")
    assert response.json()["read_only"] is False
    assert app_client.get(f"/api/tenants/{fx.a.id}/crm/my-work").json()["read_only"] is False
