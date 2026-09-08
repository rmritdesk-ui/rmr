from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uuid4_str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SocialGenerationMetadata(Base):
    __tablename__ = "v521_social_generation_metadata"
    social_content_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(80), default="demonstration")
    objective: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(80), default="professional")
    hook: Mapped[str] = mapped_column(Text, default="")
    call_to_action: Mapped[str] = mapped_column(Text, default="")
    keywords_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_visual: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CampaignExportPackage(Base):
    __tablename__ = "v521_campaign_export_packages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    provider_format: Mapped[str] = mapped_column(String(40), default="generic")
    segment_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    subject: Mapped[str] = mapped_column(String(300), default="")
    preview_text: Mapped[str] = mapped_column(String(500), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    call_to_action: Mapped[str] = mapped_column(String(300), default="")
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(600), default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastImportBatch(Base):
    __tablename__ = "v521_forecast_import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    version_id: Mapped[str] = mapped_column(String(36), index=True)
    file_name: Mapped[str] = mapped_column(String(260), default="")
    status: Mapped[str] = mapped_column(String(40), default="preview")
    rows_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    exceptions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientTrainingResource(Base):
    __tablename__ = "v521_client_training_resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    owner_scope: Mapped[str] = mapped_column(String(30), default="client")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="Sales Workflow")
    media_type: Mapped[str] = mapped_column(String(40), default="external_link")
    media_url: Mapped[str] = mapped_column(String(1000), default="")
    file_path: Mapped[str] = mapped_column(String(600), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    roles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ClientTrainingAssignment(Base):
    __tablename__ = "v521_client_training_assignments"
    __table_args__ = (UniqueConstraint("resource_id", "user_id", name="uq_v521_training_assignment"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("v521_client_training_resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="not_started")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SolutionRequestPreference(Base):
    __tablename__ = "v521_solution_request_preferences"
    request_id: Mapped[str] = mapped_column(ForeignKey("solution_requests.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    contact_date: Mapped[date] = mapped_column(Date, nullable=False)
    contact_time: Mapped[str] = mapped_column(String(20), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailConnectionEvent(Base):
    __tablename__ = "v521_email_connection_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    connection_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(60), default="test")
    status: Mapped[str] = mapped_column(String(40), default="complete")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
