from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import utcnow, uuid4_str


DISCOVERY_RUN_STATES = (
    "queued",
    "running",
    "retry_wait",
    "completed",
    "partial",
    "failed",
    "cancelled",
)

RESEARCH_RUN_STATES = (
    "awaiting_confirmation",
    "expired",
    "queued",
    "running",
    "retry_wait",
    "completed",
    "no_evidence",
    "partial",
    "failed",
    "cancelled",
)


class PiqDiscoveryRun(Base):
    __tablename__ = "piq_discovery_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_piq_discovery_tenant_idempotency"),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','completed','partial','failed','cancelled')",
            name="ck_piq_discovery_run_status",
        ),
        Index("ix_piq_discovery_tenant_status_due", "tenant_id", "status", "next_attempt_at"),
        Index("ix_piq_discovery_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    target_profile_id: Mapped[str] = mapped_column(ForeignKey("piq_target_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    managed_session_id: Mapped[str | None] = mapped_column(ForeignKey("managed_tenant_sessions.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(80), default="demonstration", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PiqProfileMatch(Base):
    __tablename__ = "piq_profile_matches"
    __table_args__ = (
        UniqueConstraint("discovery_run_id", "opportunity_id", name="uq_piq_match_run_opportunity"),
        CheckConstraint("base_match_score IS NULL OR (base_match_score >= 0 AND base_match_score <= 100)", name="ck_piq_match_base_score"),
        CheckConstraint("confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)", name="ck_piq_match_confidence"),
        CheckConstraint(
            "evidence_completeness_pct IS NULL OR (evidence_completeness_pct >= 0 AND evidence_completeness_pct <= 100)",
            name="ck_piq_match_evidence_pct",
        ),
        Index("ix_piq_match_tenant_profile_score", "tenant_id", "target_profile_id", "base_match_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    discovery_run_id: Mapped[str] = mapped_column(ForeignKey("piq_discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("piq_opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_profile_id: Mapped[str | None] = mapped_column(ForeignKey("piq_target_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    scoring_version: Mapped[str] = mapped_column(String(80), default="unscored", nullable=False)
    base_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_completeness_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    criteria_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PiqResearchRun(Base):
    __tablename__ = "piq_research_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_piq_research_tenant_idempotency"),
        CheckConstraint(
            "status IN ('awaiting_confirmation','expired','queued','running','retry_wait','completed','no_evidence','partial','failed','cancelled')",
            name="ck_piq_research_run_status",
        ),
        Index("ix_piq_research_tenant_status_due", "tenant_id", "status", "next_attempt_at"),
        Index("ix_piq_research_status_lease", "status", "lease_expires_at"),
        Index("ix_piq_research_tenant_opportunity", "tenant_id", "opportunity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("piq_opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    managed_session_id: Mapped[str | None] = mapped_column(ForeignKey("managed_tenant_sessions.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(80), default="demonstration", nullable=False)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_confirmation", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    estimated_cost_microusd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximum_cost_microusd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_microusd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    adaptive_score_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmation_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
