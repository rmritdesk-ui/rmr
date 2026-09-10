"""Durable federation records. CRM receipt/delivery remains inactive."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import utcnow, uuid4_str


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UpdatedRecord(Record):
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ProspectiqClientMapping(UpdatedRecord, Base):
    __tablename__ = "prospectiq_client_mappings"
    __table_args__ = (
        UniqueConstraint("integration_instance_id", "piq_client_id", name="uq_bridge_instance_client"),
        # One durable mapping per tenant/instance, including suspended mappings.
        UniqueConstraint("integration_instance_id", "tenant_id", name="uq_bridge_instance_tenant"),
        UniqueConstraint("id", "integration_instance_id", "tenant_id", "piq_client_id", name="uq_bridge_mapping_context"),
        CheckConstraint("status IN ('pending','active','suspended')", name="ck_bridge_mapping_status"),
        CheckConstraint("mapping_version >= 1", name="ck_bridge_mapping_version"),
    )
    integration_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    piq_client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProspectiqAuthorizationGrant(Record, Base):
    __tablename__ = "prospectiq_authorization_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mapping_id", "integration_instance_id", "tenant_id", "piq_client_id"],
            ["prospectiq_client_mappings.id", "prospectiq_client_mappings.integration_instance_id",
             "prospectiq_client_mappings.tenant_id", "prospectiq_client_mappings.piq_client_id"],
            ondelete="RESTRICT", name="fk_bridge_grant_context"),
        CheckConstraint("status IN ('pending','consumed','revoked','expired')", name="ck_bridge_grant_status"),
        CheckConstraint("length(code_hash) = 64", name="ck_bridge_code_hash_length"),
        CheckConstraint("mapping_version >= 1", name="ck_bridge_grant_mapping_version"),
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(36), nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    integration_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    piq_client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    pkce_challenge: Mapped[str] = mapped_column(String(43), nullable=False)
    # Opaque reference to server-held hashed state/nonce; never a browser URL.
    binding_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    authorization_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    managed_session_id: Mapped[str | None] = mapped_column(ForeignKey("managed_tenant_sessions.id", ondelete="SET NULL"))
    managed_session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    browser_session_hash: Mapped[str | None] = mapped_column(String(64))
    state_hash: Mapped[str | None] = mapped_column(String(64))
    nonce_hash: Mapped[str | None] = mapped_column(String(64))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    destination: Mapped[str | None] = mapped_column(String(30))


class ProspectiqCrmReceipt(UpdatedRecord, Base):
    __tablename__ = "prospectiq_crm_receipts"
    __table_args__ = (
        UniqueConstraint("integration_instance_id", "prospect_public_id", name="uq_bridge_receipt_prospect"),
        UniqueConstraint("integration_instance_id", "integration_event_id", name="uq_bridge_receipt_event"),
        ForeignKeyConstraint(
            ["mapping_id", "integration_instance_id", "tenant_id", "piq_client_id"],
            ["prospectiq_client_mappings.id", "prospectiq_client_mappings.integration_instance_id",
             "prospectiq_client_mappings.tenant_id", "prospectiq_client_mappings.piq_client_id"],
            ondelete="RESTRICT", name="fk_bridge_receipt_context"),
        CheckConstraint("status IN ('pending','accepted','failed','tombstoned')", name="ck_bridge_receipt_status"),
        CheckConstraint("length(payload_hash) = 64", name="ck_bridge_payload_hash_length"),
    )
    integration_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(36), nullable=False)
    piq_client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prospect_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    integration_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Receipt survives CRM deletion; later service must mark it tombstoned.
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ProspectiqReplayNonce(Record, Base):
    __tablename__ = "prospectiq_replay_nonces"
    __table_args__ = (
        # Nonce reuse remains forbidden across key rotation.
        UniqueConstraint("integration_instance_id", "service_identity", "nonce_hash", name="uq_bridge_service_nonce"),
        CheckConstraint("length(nonce_hash) = 64", name="ck_bridge_nonce_hash_length"),
        CheckConstraint("expires_at > request_timestamp", name="ck_bridge_nonce_expiry"),
    )
    integration_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    service_identity: Mapped[str] = mapped_column(String(120), nullable=False)
    key_id: Mapped[str] = mapped_column(String(120), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
