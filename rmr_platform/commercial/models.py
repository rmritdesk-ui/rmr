
from __future__ import annotations
import datetime as dt, uuid
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
CommercialBase=declarative_base()
def uid(): return str(uuid.uuid4())
def now(): return dt.datetime.now(dt.timezone.utc)
class ProviderConnection(CommercialBase):
    __tablename__='commercial_provider_connections'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True)
    provider=Column(String(32),nullable=False); account_email=Column(String(320)); display_name=Column(String(255))
    encrypted_credentials=Column(Text); scopes=Column(Text,default='[]'); status=Column(String(32),default='PENDING')
    last_tested_at=Column(DateTime(timezone=True)); last_sync_at=Column(DateTime(timezone=True)); error=Column(Text)
    created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now); updated_at=Column(DateTime(timezone=True),default=now,onupdate=now)
class Entitlement(CommercialBase):
    __tablename__='commercial_entitlements'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True)
    module=Column(String(64),nullable=False); status=Column(String(32),default='ACTIVE'); source_order=Column(String(128))
    effective_at=Column(DateTime(timezone=True),default=now); expires_at=Column(DateTime(timezone=True)); created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('tenant_id','module',name='uq_commercial_entitlement'),)
class OrderRecord(CommercialBase):
    __tablename__='commercial_order_records'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True)
    order_number=Column(String(128),nullable=False); effective_date=Column(String(32)); modules_json=Column(Text,default='[]')
    pricing_json=Column(Text,default='{}'); status=Column(String(32),default='ACTIVE'); approved_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now)
class Campaign(CommercialBase):
    __tablename__='commercial_campaigns'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True)
    name=Column(String(255),nullable=False); purpose=Column(Text); status=Column(String(32),default='DRAFT')
    provider_connection_id=Column(String(64)); sequence_json=Column(Text,default='[]'); approval_required=Column(Boolean,default=True)
    created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now); updated_at=Column(DateTime(timezone=True),default=now,onupdate=now)
class Message(CommercialBase):
    __tablename__='commercial_messages'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True); campaign_id=Column(String(64),index=True)
    crm_record_type=Column(String(64)); crm_record_id=Column(String(64)); piq_record_id=Column(String(64)); recipient_name=Column(String(255)); recipient_email=Column(String(320),index=True)
    subject=Column(Text); body=Column(Text); status=Column(String(32),default='DRAFT'); step_number=Column(Integer,default=1)
    scheduled_at=Column(DateTime(timezone=True)); approved_at=Column(DateTime(timezone=True)); approved_by=Column(String(64)); sent_at=Column(DateTime(timezone=True))
    provider_message_id=Column(String(255)); reply_received_at=Column(DateTime(timezone=True)); stopped_reason=Column(String(128)); generated_context_json=Column(Text,default='{}')
    created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now); updated_at=Column(DateTime(timezone=True),default=now,onupdate=now)
class ActivityEvent(CommercialBase):
    __tablename__='commercial_activity_events'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True); event_type=Column(String(64),nullable=False,index=True)
    actor_user_id=Column(String(64)); entity_type=Column(String(64)); entity_id=Column(String(64)); campaign_id=Column(String(64)); message_id=Column(String(64)); crm_record_id=Column(String(64)); piq_record_id=Column(String(64))
    data_json=Column(Text,default='{}'); occurred_at=Column(DateTime(timezone=True),default=now,index=True)
class Suppression(CommercialBase):
    __tablename__='commercial_suppressions'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True); email=Column(String(320),nullable=False,index=True)
    reason=Column(String(128),nullable=False); source=Column(String(64)); active=Column(Boolean,default=True); created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('tenant_id','email',name='uq_commercial_suppression'),)
class SocialDraft(CommercialBase):
    __tablename__='commercial_social_drafts'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True); campaign_name=Column(String(255)); topic=Column(Text)
    facebook_text=Column(Text); instagram_text=Column(Text); linkedin_text=Column(Text); x_text=Column(Text); hashtags=Column(Text)
    status=Column(String(32),default='DRAFT'); marked_published_at=Column(DateTime(timezone=True)); created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now); updated_at=Column(DateTime(timezone=True),default=now,onupdate=now)
class SecureAccessSession(CommercialBase):
    __tablename__='commercial_secure_access_sessions'
    id=Column(String(64),primary_key=True,default=uid); token_hash=Column(String(128),nullable=False,unique=True); owner_user_id=Column(String(64),nullable=False,index=True); tenant_id=Column(String(64),nullable=False,index=True)
    reason=Column(Text,nullable=False); mode=Column(String(32),default='READ_ONLY'); ip_address=Column(String(128)); user_agent=Column(Text); started_at=Column(DateTime(timezone=True),default=now); expires_at=Column(DateTime(timezone=True)); ended_at=Column(DateTime(timezone=True))
class MFAState(CommercialBase):
    __tablename__='commercial_mfa_state'
    id=Column(String(64),primary_key=True,default=uid); user_id=Column(String(64),nullable=False,unique=True,index=True); encrypted_secret=Column(Text,nullable=False); enabled=Column(Boolean,default=False); verified_at=Column(DateTime(timezone=True)); updated_at=Column(DateTime(timezone=True),default=now,onupdate=now)
class ExportJob(CommercialBase):
    __tablename__='commercial_export_jobs'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),nullable=False,index=True); requested_by=Column(String(64)); reason=Column(Text); status=Column(String(32),default='PENDING'); file_path=Column(Text); manifest_json=Column(Text,default='{}'); created_at=Column(DateTime(timezone=True),default=now); completed_at=Column(DateTime(timezone=True))
class CostEntry(CommercialBase):
    __tablename__='commercial_cost_entries'
    id=Column(String(64),primary_key=True,default=uid); tenant_id=Column(String(64),index=True); category=Column(String(64),nullable=False); amount=Column(Float,nullable=False); period=Column(String(32)); allocation_method=Column(String(64),default='DIRECT'); policy_status=Column(String(32),default='APPROVED'); notes=Column(Text); created_by=Column(String(64)); created_at=Column(DateTime(timezone=True),default=now)
