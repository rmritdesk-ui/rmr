from __future__ import annotations
from datetime import datetime, timezone
import uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
try:
    from .db import Base
except Exception:
    from .models import Base

def uid(): return str(uuid.uuid4())
def utcnow(): return datetime.now(timezone.utc)

class CB1SchemaMigration(Base):
    __tablename__ = "cb1_schema_migrations"
    migration_id = Column(String(160), primary_key=True)
    applied_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

class CB1AuditEvent(Base):
    __tablename__ = "cb1_audit_events"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=True)
    user_id=Column(String(64),index=True,nullable=True); event_type=Column(String(120),index=True,nullable=False)
    object_type=Column(String(80),nullable=True); object_id=Column(String(64),nullable=True)
    detail_json=Column(Text,nullable=False,default="{}"); ip_address=Column(String(128)); user_agent=Column(Text)
    created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow)

class CB1ClientAdminInvite(Base):
    __tablename__="cb1_client_admin_invites"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    email=Column(String(320),index=True,nullable=False); full_name=Column(String(240),nullable=False)
    status=Column(String(40),index=True,nullable=False,default="PENDING")
    token_hash=Column(String(128),unique=True,index=True,nullable=False); expires_at=Column(DateTime(timezone=True),nullable=False)
    activated_user_id=Column(String(64),nullable=True); created_by=Column(String(64),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow); last_sent_at=Column(DateTime(timezone=True),nullable=False,default=utcnow)
    activated_at=Column(DateTime(timezone=True)); revoked_at=Column(DateTime(timezone=True))

class CB1CommercialProfile(Base):
    __tablename__="cb1_commercial_profiles"
    tenant_id=Column(String(64),primary_key=True); managed_no_login=Column(Boolean,nullable=False,default=False)
    managed_reason=Column(Text); updated_by=Column(String(64)); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1OrderForm(Base):
    __tablename__="cb1_order_forms"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    reference=Column(String(160),nullable=False); status=Column(String(40),nullable=False,default="ACTIVE")
    effective_date=Column(String(32)); signed_at=Column(DateTime(timezone=True)); notes=Column(Text)
    created_by=Column(String(64),nullable=False); created_at=Column(DateTime(timezone=True),nullable=False,default=utcnow)
    __table_args__=(UniqueConstraint('tenant_id','reference',name='uq_cb1_order_tenant_ref'),)

class CB1Entitlement(Base):
    __tablename__="cb1_entitlements"
    id=Column(String(64),primary_key=True,default=uid); order_form_id=Column(String(64),index=True,nullable=False)
    tenant_id=Column(String(64),index=True,nullable=False); module_key=Column(String(80),index=True,nullable=False)
    enabled=Column(Boolean,nullable=False,default=True); quantity=Column(Integer); usage_limit=Column(Integer)
    starts_at=Column(DateTime(timezone=True)); ends_at=Column(DateTime(timezone=True)); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint('tenant_id','module_key','order_form_id',name='uq_cb1_entitlement'),)

class CB1CustodyAuthority(Base):
    __tablename__="cb1_custody_authority"
    id=Column(Integer,primary_key=True,default=1); user_id=Column(String(64),unique=True,nullable=False)
    claimed_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1MFAFactor(Base):
    __tablename__="cb1_mfa_factors"
    user_id=Column(String(64),primary_key=True); secret_encrypted=Column(Text,nullable=False)
    verified=Column(Boolean,nullable=False,default=False); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    verified_at=Column(DateTime(timezone=True))

class CB1StepUpSession(Base):
    __tablename__="cb1_stepup_sessions"
    id=Column(String(64),primary_key=True,default=uid); token_hash=Column(String(128),unique=True,index=True,nullable=False)
    user_id=Column(String(64),index=True,nullable=False); expires_at=Column(DateTime(timezone=True),nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1CustodySession(Base):
    __tablename__="cb1_custody_sessions"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    user_id=Column(String(64),index=True,nullable=False); reason=Column(Text,nullable=False); status=Column(String(32),default="ACTIVE",nullable=False)
    read_only=Column(Boolean,default=True,nullable=False); elevated_until=Column(DateTime(timezone=True)); expires_at=Column(DateTime(timezone=True),nullable=False)
    ip_address=Column(String(128)); user_agent=Column(Text); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); ended_at=Column(DateTime(timezone=True))

class CB1ExportJob(Base):
    __tablename__="cb1_export_jobs"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    requested_by=Column(String(64),nullable=False); purpose=Column(String(120),nullable=False); status=Column(String(40),default="PENDING",nullable=False)
    file_path=Column(Text); manifest_json=Column(Text,default="{}"); sha256=Column(String(128)); error=Column(Text)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); completed_at=Column(DateTime(timezone=True))

class CB1OffboardingCase(Base):
    __tablename__="cb1_offboarding_cases"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    status=Column(String(40),default="OPEN",nullable=False); export_deadline=Column(DateTime(timezone=True)); integrations_revoked=Column(Boolean,default=False,nullable=False)
    retention_status=Column(String(80),default="ACTIVE"); notes=Column(Text); created_by=Column(String(64),nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); closed_at=Column(DateTime(timezone=True))

class CB1ProviderConnection(Base):
    __tablename__="cb1_provider_connections"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    provider=Column(String(40),index=True,nullable=False); sender_email=Column(String(320),nullable=False); sender_name=Column(String(240))
    physical_address=Column(Text,nullable=False); status=Column(String(50),default="CONFIGURATION_REQUIRED",nullable=False)
    token_encrypted=Column(Text); refresh_token_encrypted=Column(Text); credential_encrypted=Column(Text); config_json=Column(Text,default="{}")
    expires_at=Column(DateTime(timezone=True)); last_sync_at=Column(DateTime(timezone=True)); created_by=Column(String(64),nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1Campaign(Base):
    __tablename__="cb1_campaigns"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    name=Column(String(240),nullable=False); status=Column(String(40),default="DRAFT",nullable=False)
    provider_connection_id=Column(String(64)); frequency_hours=Column(Integer,default=24,nullable=False)
    created_by=Column(String(64),nullable=False); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1Message(Base):
    __tablename__="cb1_messages"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    campaign_id=Column(String(64),index=True); crm_record_id=Column(String(64),index=True); piq_record_id=Column(String(64),index=True)
    recipient_email=Column(String(320),index=True,nullable=False); subject=Column(Text,nullable=False); body_draft=Column(Text,nullable=False)
    body_approved=Column(Text); approved_hash=Column(String(128)); status=Column(String(40),index=True,default="DRAFT",nullable=False)
    approved_by=Column(String(64)); approved_at=Column(DateTime(timezone=True)); scheduled_at=Column(DateTime(timezone=True)); sent_at=Column(DateTime(timezone=True))
    provider_message_id=Column(String(320)); replied_at=Column(DateTime(timezone=True)); bounced_at=Column(DateTime(timezone=True)); unsubscribed_at=Column(DateTime(timezone=True))
    stop_reason=Column(String(120)); idempotency_key=Column(String(128),unique=True,index=True,nullable=False); cost_micros=Column(Integer,default=0,nullable=False)
    supported_facts_json=Column(Text,default="[]",nullable=False); created_by=Column(String(64),nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1MessageVersion(Base):
    __tablename__="cb1_message_versions"
    id=Column(String(64),primary_key=True,default=uid); message_id=Column(String(64),index=True,nullable=False)
    version_number=Column(Integer,nullable=False); subject=Column(Text,nullable=False); body=Column(Text,nullable=False)
    body_hash=Column(String(128),nullable=False); created_by=Column(String(64),nullable=False); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint('message_id','version_number',name='uq_cb1_message_version'),)

class CB1Suppression(Base):
    __tablename__="cb1_suppressions"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    email=Column(String(320),index=True,nullable=False); reason=Column(String(80),nullable=False); source_message_id=Column(String(64))
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint('tenant_id','email',name='uq_cb1_suppression'),)

class CB1DripStep(Base):
    __tablename__="cb1_drip_steps"
    id=Column(String(64),primary_key=True,default=uid); campaign_id=Column(String(64),index=True,nullable=False)
    step_number=Column(Integer,nullable=False); delay_hours=Column(Integer,nullable=False,default=0); subject_template=Column(Text); body_template=Column(Text)
    active=Column(Boolean,default=True,nullable=False); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint('campaign_id','step_number',name='uq_cb1_drip_step'),)

class CB1DripJob(Base):
    __tablename__="cb1_drip_jobs"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    campaign_id=Column(String(64),index=True,nullable=False); message_id=Column(String(64),index=True,nullable=False)
    status=Column(String(40),index=True,default="QUEUED",nullable=False); due_at=Column(DateTime(timezone=True),index=True,nullable=False)
    lease_until=Column(DateTime(timezone=True)); attempts=Column(Integer,default=0,nullable=False); last_error=Column(Text)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1WorkerState(Base):
    __tablename__="cb1_worker_state"
    worker_name=Column(String(80),primary_key=True); status=Column(String(40),nullable=False); heartbeat_at=Column(DateTime(timezone=True),nullable=False)
    detail_json=Column(Text,default="{}",nullable=False)

class CB1SalesTask(Base):
    __tablename__="cb1_sales_tasks"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    crm_record_id=Column(String(64),index=True); message_id=Column(String(64)); task_type=Column(String(80),nullable=False)
    status=Column(String(40),default="OPEN",nullable=False); detail=Column(Text); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

class CB1SocialContent(Base):
    __tablename__="cb1_social_content"
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True,nullable=False)
    platform=Column(String(40),nullable=False); title=Column(String(240)); post_text=Column(Text,nullable=False); hashtags=Column(Text,default="")
    status=Column(String(40),default="DRAFT",nullable=False); published_url=Column(Text); published_at=Column(DateTime(timezone=True))
    created_by=Column(String(64),nullable=False); created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
