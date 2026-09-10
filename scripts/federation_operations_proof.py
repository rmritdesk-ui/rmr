"""Phase 4 disposable PG16/TLS proof. Never uses an installed database or real provider."""
import json, os, secrets, sys
from uuid import uuid4
from federation_workflow_proof import ROOT, initialize, run_rmr
from sqlalchemy import create_engine, text
URL="postgresql+psycopg://phase41_test:phase1-disposable-only@phase41-postgres:5432/phase41_test"
SCHEMA="rmr_operations_proof"
DB=URL+"?options=-csearch_path%3D"+SCHEMA
def public_fixture():
    # PIQ/worker/provider get only their credentials and public verification material.
    # RMR signing key and RMR browser credentials stay outside this mounted subdirectory.
    source=json.loads((ROOT/"fixture.json").read_text())
    public=ROOT/"piq";public.mkdir(exist_ok=True)
    (public/"fixture.json").write_text(json.dumps({k:v for k,v in source.items() if k not in {"rmr_secret","password"}}))
    for name in ["verification.pem","tls.crt","phase3-browser-result.json"]:
        if (ROOT/name).exists():(public/name).write_bytes((ROOT/name).read_bytes())
    print("PIQ-only fixture prepared; no private signing key or RMR browser credential")
action=sys.argv[1]
if action=="init":
    initialize()
    f=json.loads((ROOT/"fixture.json").read_text())
    f.update(crm_secret=secrets.token_hex(32),publicA=str(uuid4()),publicB=str(uuid4()))
    (ROOT/"fixture.json").write_text(json.dumps(f))
    path=ROOT/"nginx.conf"
    path.write_text(path.read_text().replace("phase2","phase4"))
    public_fixture()
elif action=="public":public_fixture()
elif action=="rmr":
    f=json.loads((ROOT/"fixture.json").read_text())
    control=create_engine(URL)
    with control.begin() as db:
        exists=db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"),{"schema":SCHEMA})
        if not exists:db.execute(text("CREATE SCHEMA "+SCHEMA))
    control.dispose()
    os.environ["RMR_PROSPECTIQ_CRM_KEYS_JSON"]=json.dumps({"crm-proof":f["crm_secret"]})
    run_rmr(database_url=DB,seed=not exists)
elif action in ("inspect","downgrade","restore","suspend","activate"):
    f=json.loads((ROOT/"fixture.json").read_text())
    engine=create_engine(DB)
    with engine.begin() as db:
        if action in ("downgrade","restore"):
            db.execute(text("UPDATE users SET tenant_role=:role WHERE id=:id"),
                {"role":"SALES_REP" if action=="downgrade" else "CLIENT_ADMIN","id":f["user"]})
        elif action in ("suspend","activate"):
            db.execute(text("UPDATE prospectiq_client_mappings SET status=:status WHERE id=:id"),
                {"status":"suspended" if action=="suspend" else "active","id":f["mapping"]})
        else:
            tables=["leads","accounts","contacts","opportunities","prospectiq_crm_receipts","prospectiq_crm_events"]
            counts={table:db.scalar(text("SELECT COUNT(*) FROM "+table)) for table in tables}
            assert counts==dict(zip(tables,[1,0,0,0,1,1])),counts
            assert tuple(db.execute(text("SELECT tenant_id,source,assigned_user_id FROM leads")).one())==(f["tenant"],"ProspectIQ",f["user"])
            indexes=set(db.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname=:schema"),{"schema":SCHEMA}))
            assert {"ix_bridge_grant_absolute","ix_bridge_browser_logout"}<=indexes
            print(json.dumps({"result":"PASS","durable_counts":counts,"tenant_actor_correct":True}))
    engine.dispose()
else:raise SystemExit("Unknown isolated Phase 4 action")
