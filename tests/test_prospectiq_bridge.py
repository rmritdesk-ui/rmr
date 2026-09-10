"""Phase 0: disposable databases, inert contracts, no external HTTP."""
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rmr_platform.db import Base
from rmr_platform.models import Tenant, User, utcnow
from rmr_platform.migrations import apply_prospectiq_bridge_schema
from rmr_platform.prospectiq_bridge.models import (
    ProspectiqClientMapping as Mapping, ProspectiqAuthorizationGrant as Grant,
    ProspectiqCrmReceipt as Receipt, ProspectiqReplayNonce as Nonce,
)
from rmr_platform.prospectiq_bridge import contracts as c


@pytest.fixture
def bridge_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bridge.db'}")
    yield engine
    engine.dispose()


@pytest.fixture
def db(bridge_engine):
    # Simulate an already installed core: new migration adds only its four tables.
    Base.metadata.create_all(bridge_engine, tables=[
        t for t in Base.metadata.sorted_tables if not t.name.startswith("prospectiq_")])
    apply_prospectiq_bridge_schema(bind=bridge_engine)
    apply_prospectiq_bridge_schema(bind=bridge_engine)
    with Session(bridge_engine) as db:
        db.add_all([Tenant(id="tenant-a", name="Synthetic A", slug="bridge-a"),
                    Tenant(id="tenant-b", name="Synthetic B", slug="bridge-b")])
        db.commit()
        db.add(User(id="actor", tenant_id="tenant-a", full_name="Synthetic actor",
                    email="bridge@example.invalid", password_hash="not-a-login-hash"))
        db.commit()
        yield db


def mapping(db, **extra):
    values = dict(integration_instance_id="piq-test", tenant_id="tenant-a",
                  piq_client_id=str(uuid4()), status="active")
    values.update(extra)
    row = Mapping(**values)
    db.add(row)
    db.commit()
    return row


def rejected(db, row):
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_additive_idempotent_schema(db):
    assert {Mapping.__tablename__, Grant.__tablename__, Receipt.__tablename__, Nonce.__tablename__} <= set(inspect(db.bind).get_table_names())
    assert len(list(db.scalars(select(Tenant)))) == 2
    assert list(db.scalars(select(Receipt))) == []


@pytest.mark.parametrize("conflict", ["tenant", "client"])
def test_duplicate_mapping_rejected(db, conflict):
    first = mapping(db)
    rejected(db, Mapping(integration_instance_id="piq-test",
                         tenant_id="tenant-b" if conflict == "client" else first.tenant_id,
                         piq_client_id=first.piq_client_id if conflict == "client" else str(uuid4()),
                         status="active"))


def test_separate_instance_allowed_and_bad_status_rejected(db):
    first = mapping(db)
    mapping(db, integration_instance_id="piq-other", piq_client_id=first.piq_client_id)
    rejected(db, Mapping(integration_instance_id="bad", tenant_id="tenant-b",
                         piq_client_id=str(uuid4()), status="admin"))


def grant_values(row):
    return dict(user_id="actor", tenant_id=row.tenant_id, mapping_id=row.id,
                mapping_version=1, piq_client_id=row.piq_client_id,
                integration_instance_id=row.integration_instance_id,
                code_hash=sha256(b"synthetic-transient-code").hexdigest(),
                code_expires_at=utcnow() + timedelta(seconds=60), pkce_challenge="a" * 43,
                binding_reference="server-state-hash-reference", authorization_checked_at=utcnow(),
                capabilities_json=["prospects.read"])


def test_grant_hash_only_and_context_bound(db):
    row = mapping(db)
    values = grant_values(row)
    grant = Grant(**values)
    db.add(grant)
    db.commit()
    assert grant.code_hash == values["code_hash"]
    assert not {"code", "authorization_code", "access_token", "refresh_token"} & set(Grant.__table__.columns.keys())
    assert grant.capabilities_json == ["prospects.read"]
    values.update(tenant_id="tenant-b", code_hash="b" * 64)
    rejected(db, Grant(**values))


def receipt_values(row):
    return dict(integration_instance_id=row.integration_instance_id, mapping_id=row.id,
                piq_client_id=row.piq_client_id, tenant_id=row.tenant_id,
                prospect_public_id=str(uuid4()), integration_event_id=str(uuid4()),
                payload_hash="a" * 64, provenance_json={"source": "synthetic"})


def test_receipt_uniqueness_survives_failure_or_tombstone(db):
    values = receipt_values(mapping(db))
    db.add(Receipt(**values, status="tombstoned"))
    db.commit()
    values["integration_event_id"] = str(uuid4())
    rejected(db, Receipt(**values))


def test_receipt_cannot_claim_different_tenant(db):
    values = receipt_values(mapping(db))
    values["tenant_id"] = "tenant-b"
    rejected(db, Receipt(**values))


def test_replay_rejected_across_key_rotation(db):
    values = dict(integration_instance_id="piq-test", service_identity="piq",
                  key_id="key-a", nonce_hash="c" * 64, request_timestamp=utcnow(),
                  expires_at=utcnow() + timedelta(minutes=5))
    db.add(Nonce(**values))
    db.commit()
    values["key_id"] = "key-b"
    rejected(db, Nonce(**values))


def test_empty_disabled_config_and_native_routes(monkeypatch):
    import os
    from rmr_platform.config import get_settings
    for key in os.environ:
        if key.startswith("RMR_PROSPECTIQ_"):
            monkeypatch.delenv(key)
    settings = get_settings()
    assert not settings.prospectiq_bridge_enabled
    assert settings.prospectiq_base_url == settings.prospectiq_assertion_issuer == ""
    assert settings.prospectiq_authorization_code_ttl_seconds == 60
    from rmr_platform.main import app
    paths = {route.path for route in app.routes}
    assert {"/api/auth/login", "/api/tenants/{tenant_id}/piq", "/api/piq/{opportunity_id}/move-to-crm"} <= paths
    assert not any("/api/integrations/prospectiq/v1" in path for path in paths)


def test_contracts_positive_and_fail_closed():
    uid = str(uuid4())
    assert c.LaunchRequest(mapping_id=uid, destination="prospects").version == "1"
    payload = dict(integration_instance_id="piq-test", mapping_id=uid, mapping_version=1,
                   piq_client_id=uid, prospect_public_id=uid, integration_event_id=uid,
                   actor_grant_id=uid, prospect={"company_name": "Synthetic", "evidence": []})
    assert c.CrmLeadRequest(**payload).prospect.email is None
    for extra in ({"tenant_id": uid}, {"actor_user_id": uid}, {"redirect_url": "https://example.invalid"}):
        with pytest.raises(ValidationError):
            c.CrmLeadRequest(**payload, **extra)
    with pytest.raises(ValidationError):
        c.LaunchRequest(mapping_id=uid, destination="https://example.invalid")
    with pytest.raises(ValidationError):
        c.CrmLeadRequest(**{**payload, "mapping_version": "1"})
    with pytest.raises(ValidationError):
        c.GrantContext(grant_id=uid, rmr_user_id=uid, mapping_id=uid, mapping_version=1,
                       piq_client_id=uid, integration_instance_id="piq-test",
                       capabilities=["admin"], absolute_expires_at=2000000000)
    assert len(c.ENDPOINTS) == 9


def test_all_v1_examples_and_required_fields():
    import json
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / "fixtures/prospectiq_bridge_v1.json").read_text())
    assert len(examples) == len(c.ENDPOINTS)
    for (_, _, request_type, response_type), (request, response) in zip(c.ENDPOINTS, examples):
        request_type.model_validate(request)
        response_type.model_validate(response)
        with pytest.raises(ValidationError):
            request_type.model_validate({**request, "redirect_url": "https://example.invalid"})
        for key, field in request_type.model_fields.items():
            if field.is_required():
                with pytest.raises(ValidationError):
                    request_type.model_validate({k: v for k, v in request.items() if k != key})
