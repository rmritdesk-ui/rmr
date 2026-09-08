from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uuid4_str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClientServiceCommercialTerm(Base):
    """Per-client, per-service commercial terms.

    TenantService remains the authoritative subscription record. This table adds
    the commercial terms that cannot safely live as catalog-wide defaults.
    """

    __tablename__ = "v522_client_service_commercial_terms"
    __table_args__ = (
        UniqueConstraint("tenant_service_id", name="uq_v522_client_service_term"),
        UniqueConstraint("tenant_id", "service_code", name="uq_v522_tenant_service_term"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_service_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_services.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    service_code: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    rmr_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    step2_share_pct: Mapped[float] = mapped_column(Float, default=50.0)
    split_basis: Mapped[str] = mapped_column(String(30), default="gross")
    direct_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    seller_org: Mapped[str] = mapped_column(String(40), default="RMR")
    seller_name: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(60), default="explicit_client_terms")
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CommercialTermHistory(Base):
    __tablename__ = "v522_commercial_term_history"
    __table_args__ = (
        UniqueConstraint("commercial_term_id", "version_number", name="uq_v522_term_history_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    commercial_term_id: Mapped[str] = mapped_column(
        ForeignKey("v522_client_service_commercial_terms.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    service_code: Mapped[str] = mapped_column(String(80), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    changed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageDeliveryContext(Base):
    __tablename__ = "v522_message_delivery_context"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    sender_name: Mapped[str] = mapped_column(String(240), default="")
    recipient_name: Mapped[str] = mapped_column(String(240), default="")
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(50), default="RECORDED")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SocialContentRevision(Base):
    __tablename__ = "v522_social_content_revisions"
    __table_args__ = (
        UniqueConstraint("social_content_id", "revision_number", name="uq_v522_social_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    social_content_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
