from datetime import datetime, timezone
from sqlalchemy import text
from .db import engine
from . import cb1_models
MIGRATION_ID="005.002.000-commercial-correction-build-1"

def apply():
    cb1_models.Base.metadata.create_all(bind=engine, tables=[c.__table__ for c in (
      cb1_models.CB1SchemaMigration,cb1_models.CB1AuditEvent,cb1_models.CB1ClientAdminInvite,cb1_models.CB1CommercialProfile,
      cb1_models.CB1OrderForm,cb1_models.CB1Entitlement,cb1_models.CB1CustodyAuthority,cb1_models.CB1MFAFactor,
      cb1_models.CB1StepUpSession,cb1_models.CB1CustodySession,cb1_models.CB1ExportJob,cb1_models.CB1OffboardingCase,
      cb1_models.CB1ProviderConnection,cb1_models.CB1Campaign,cb1_models.CB1Message,cb1_models.CB1MessageVersion,
      cb1_models.CB1Suppression,cb1_models.CB1DripStep,cb1_models.CB1DripJob,cb1_models.CB1WorkerState,
      cb1_models.CB1SalesTask,cb1_models.CB1SocialContent)])
    with engine.begin() as conn:
        exists=conn.execute(text("SELECT migration_id FROM cb1_schema_migrations WHERE migration_id=:m"),{'m':MIGRATION_ID}).first()
        if not exists:
            conn.execute(text("INSERT INTO cb1_schema_migrations (migration_id, applied_at) VALUES (:m,:a)"),{'m':MIGRATION_ID,'a':datetime.now(timezone.utc)})
    return MIGRATION_ID
if __name__=='__main__': print(apply())
